#!/usr/bin/env python3
"""GitHub Issue dispatcher (ordinary code, no LLM). See agents/PROTOCOL.md.

Each tick:
1. Poll open Issues (plus the verdict labels of their linked PRs) via `gh`.
2. Run the deterministic editor duties (editor_lifecycle.py): re-route rejected work,
   escalate after 3 attempts, promote the next ready ticket.
3. Wake ONLY the agent named by each ticket's single agent:* label, one invocation per
   agent at a time (lock file), then check whether the labels moved.
4. An invocation that fails, or exits without moving the labels, counts as a failed
   attempt. State survives restarts. After 3 failures the ticket is set to
   status:blocked + agent:editor with a comment for the human.

Environment (all optional):
  GITHUB_REPOSITORY, NEWSROOM_DISPATCH_STATE_DIR, NEWSROOM_REPO_DIR,
  NEWSROOM_CMD_<AGENT> (shell-style template with {issue} and {prompt}),
  NEWSROOM_REVIEW_MODE=deterministic (copydesk/factcheck run agents/scripts/*_agent.py, no LLM;
  default is the LLM agents), NEWSROOM_AGENT_TIMEOUT (s, default 900), NEWSROOM_MAX_TURNS (default 40),
  NEWSROOM_RETRY_BACKOFF (s, default 60), NEWSROOM_STALE_MINUTES (default 45).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import editor_lifecycle as lifecycle  # noqa: E402

MAX_FAILURES = 3
WAKE = {  # (status, agent) -> wake. in-progress is only woken when stale.
    ("status:ready", "agent:reporter"): "reporter",
    ("status:in-progress", "agent:reporter"): "reporter",
    ("status:in-review", "agent:copydesk"): "copydesk",
    ("status:in-test", "agent:factcheck"): "factcheck",
}
DETERMINISTIC = {"copydesk": "copydesk_agent.py", "factcheck": "factcheck_agent.py"}
SECRET = re.compile(r"(ghp_|github_pat_|sk-|AIza)[A-Za-z0-9_\-]{8,}")


def sanitize(text: str, limit: int = 400) -> str:
    return SECRET.sub("[redacted]", text.strip())[-limit:]


class Config:
    def __init__(self, env=os.environ):
        root = Path(__file__).resolve().parents[2]
        self.repo = env.get("GITHUB_REPOSITORY", "Lakshmi-Sayyapureddy1819/autonomous-newsroom")
        self.root = Path(env.get("NEWSROOM_REPO_DIR", root))
        default_state = Path(env.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self.state_dir = Path(
            env.get("NEWSROOM_DISPATCH_STATE_DIR", default_state / "newsroom-dispatch")
        )
        self.timeout = int(env.get("NEWSROOM_AGENT_TIMEOUT", "900"))
        self.max_turns = int(env.get("NEWSROOM_MAX_TURNS", "40"))
        self.backoff = int(env.get("NEWSROOM_RETRY_BACKOFF", "60"))
        self.stale = int(env.get("NEWSROOM_STALE_MINUTES", "45")) * 60
        self.deterministic = env.get("NEWSROOM_REVIEW_MODE", "").lower() == "deterministic"
        self.env = env

    def needs_pr(self, agent: str) -> bool:
        """True when this agent's command takes a PR number ({pr}) instead of an Issue."""
        override = self.env.get(f"NEWSROOM_CMD_{agent.upper()}")
        if override:
            return "{pr}" in override
        return self.deterministic and agent in DETERMINISTIC

    def command(self, agent: str, issue: str, prompt: str, pr: str = "") -> list[str]:
        override = self.env.get(f"NEWSROOM_CMD_{agent.upper()}")
        if override:
            argv = [a.replace("{issue}", issue).replace("{pr}", pr).replace("{prompt}", prompt)
                    for a in shlex.split(override)]
        elif self.deterministic and agent in DETERMINISTIC:
            argv = [sys.executable, str(self.root / "agents" / "scripts" / DETERMINISTIC[agent]),
                    pr]
        elif agent in ("reporter", "factcheck"):  # OpenClaw
            argv = ["openclaw", "agent", "--agent", agent, "--message", prompt,
                    "--timeout", str(self.timeout)]
        else:  # Hermes: copydesk, editor
            argv = ["hermes", "-p", agent, "chat", "-q", prompt, "--oneshot",
                    "--max-turns", str(self.max_turns)]
        argv[0] = shutil.which(argv[0]) or argv[0]
        return argv


class GitHub:
    """Thin wrapper over the gh CLI."""

    def __init__(self, repo: str):
        self.repo = repo

    def _gh(self, *args: str, stdin: str | None = None) -> str:
        out = subprocess.run(["gh", *args, "--repo", self.repo], input=stdin, text=True,
                             capture_output=True, timeout=120)
        if out.returncode:
            raise RuntimeError(f"gh {' '.join(args[:2])} failed: {sanitize(out.stderr)}")
        return out.stdout

    def issues(self, state: str) -> list[dict]:
        return json.loads(self._gh("issue", "list", "--state", state, "--limit", "200",
                                   "--json", "number,title,body,labels,updatedAt"))

    def open_prs(self) -> list[dict]:
        return json.loads(self._gh("pr", "list", "--state", "open", "--limit", "100", "--json",
                                   "number,labels,closingIssuesReferences"))

    def edit_labels(self, kind: str, number: int, add=(), remove=()) -> None:
        args = [kind, "edit", str(number)]
        for label in add:
            args += ["--add-label", label]
        for label in remove:
            args += ["--remove-label", label]
        if add or remove:
            self._gh(*args)

    def comment(self, kind: str, number: int, body: str) -> None:
        self._gh(kind, "comment", str(number), "--body-file", "-", stdin=body)

    def create_issue(self, title: str, body: str, labels: list[str]) -> None:
        args = ["issue", "create", "--title", title, "--body", body]
        for label in labels:
            args += ["--label", label]
        self._gh(*args)


class State:
    """One JSON file per ticket under the state dir; written atomically."""

    def __init__(self, directory: Path):
        self.dir = directory
        (directory / "locks").mkdir(parents=True, exist_ok=True)
        (directory / "logs").mkdir(exist_ok=True)

    def load(self, key: str) -> dict:
        path = self.dir / f"{key}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def save(self, key: str, data: dict) -> None:
        path = self.dir / f"{key}.json"
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)


class AgentLock:
    """Per-agent exclusive lock (O_EXCL file). A lock older than ttl is treated as stale."""

    def __init__(self, directory: Path, agent: str, ttl: int):
        self.path = directory / "locks" / f"{agent}.lock"
        self.ttl = ttl
        self.held = False

    def acquire(self) -> bool:
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return True
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime < self.ttl:
                        return False
                    self.path.unlink()
                except FileNotFoundError:
                    pass
        return False

    def release(self) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)
            self.held = False


def parse_ticket(issue: dict, pr_labels: set[str]) -> lifecycle.Ticket:
    return lifecycle.Ticket(
        number=issue["number"], title=issue["title"], body=issue.get("body") or "",
        labels={label["name"] for label in issue["labels"]}, pr_labels=pr_labels,
    )


def signature(t: lifecycle.Ticket) -> str:
    return "|".join(t.with_prefix("agent:") + t.with_prefix("status:") + t.with_prefix("attempt:"))


def prompt_for(agent: str, number: int, t: lifecycle.Ticket | None) -> str:
    if agent == "editor":
        return (
            "You are the editor. Read agents/PROTOCOL.md and docs/brief.md. The repository has "
            "no product tickets yet. Create small outcome-based GitHub Issues (Goal, Acceptance "
            "criteria, Out of scope, Depends on). Create tickets in dependency order so 'Depends "
            "on: #n' uses real numbers. Label a ticket with no dependencies `status:ready`, "
            "`agent:reporter`, `attempt:1`. Label every dependent ticket `agent:editor` with NO "
            "status label; the dispatcher promotes it when its dependencies are merged. Do not "
            "edit app/ or deploy/. Finish with a handoff comment on the first ticket."
        )
    return (
        f"You are {agent}. Work ONLY on Issue #{number} ({t.title if t else ''}). Read "
        "agents/PROTOCOL.md first. Follow your role instructions, never merge, and finish by "
        "updating the labels and posting the handoff comment on the Issue (and PR) exactly as "
        "the protocol specifies. GitHub is the only channel to other agents."
    )


class Dispatcher:
    def __init__(self, cfg: Config, gh, dry_run: bool = False, runner=None, clock=time.time):
        self.cfg, self.gh, self.dry = cfg, gh, dry_run
        self.state = State(cfg.state_dir)
        self.run_agent = runner or self._run_subprocess
        self.now = clock
        self.log_lock = threading.Lock()

    def log(self, msg: str) -> None:
        with self.log_lock:
            print(msg, flush=True)

    # ---- polling -------------------------------------------------------------------
    def fetch(self) -> tuple[list[lifecycle.Ticket], dict[int, str], set[int], int]:
        issues_open = self.gh.issues("open")
        issues_closed = self.gh.issues("closed")
        pr_by_issue: dict[int, set[str]] = {}
        for pr in self.gh.open_prs():
            names = {label["name"] for label in pr["labels"]}
            for ref in pr.get("closingIssuesReferences") or []:
                pr_by_issue.setdefault(ref["number"], set()).update(names)
        tickets = [parse_ticket(i, pr_by_issue.get(i["number"], set())) for i in issues_open]
        updated = {i["number"]: i["updatedAt"] for i in issues_open}
        closed = {i["number"] for i in issues_closed}
        return tickets, updated, closed, len(issues_open) + len(issues_closed)

    # ---- editor duties -------------------------------------------------------------
    def apply(self, actions: list[dict]) -> bool:
        for a in actions:
            self.log(f"[editor] #{a['issue']}: +{a['add']} -{a['remove']}")
            if self.dry:
                continue
            self.gh.edit_labels("issue", a["issue"], a["add"], a["remove"])
            for pr in self._linked_prs(a["issue"]) if a["pr_remove"] else []:
                self.gh.edit_labels("pr", pr, remove=a["pr_remove"])
            self.gh.comment("issue", a["issue"], a["comment"])
        return bool(actions)

    def resolve_pr(self, issue: int) -> tuple[int | None, str]:
        """The one open PR that closes `issue`, or (None, reason)."""
        prs = self._linked_prs(issue)
        if len(prs) == 1:
            return prs[0], ""
        if not prs:
            return None, f"no open PR closes #{issue}"
        return None, f"ambiguous: open PRs {sorted(prs)} all close #{issue}"

    def _linked_prs(self, issue: int) -> list[int]:
        return [pr["number"] for pr in self.gh.open_prs()
                if any(r["number"] == issue for r in pr.get("closingIssuesReferences") or [])]

    # ---- one tick ------------------------------------------------------------------
    def tick(self) -> None:
        tickets, updated, closed, total_issues = self.fetch()
        if self.apply(lifecycle.plan_actions(tickets, closed)) and not self.dry:
            tickets, updated, closed, total_issues = self.fetch()

        jobs: dict[str, tuple[str, int, lifecycle.Ticket | None]] = {}
        for t in sorted(tickets, key=lambda x: x.number):
            status, agent = t.with_prefix("status:"), t.with_prefix("agent:")
            if len(status) != 1 or len(agent) != 1:
                if status or agent:
                    self.log(f"#{t.number}: malformed labels {status + agent}; skipped")
                continue
            who = WAKE.get((status[0], agent[0]))
            if not who or who in jobs:
                continue
            if status[0] == "status:in-progress" and not self._is_stale(updated[t.number]):
                continue
            jobs[who] = (f"issue-{t.number}", t.number, t)

        brief = self.cfg.root / "docs" / "brief.md"
        if "editor" not in jobs and total_issues == 0 and brief.exists():
            jobs["editor"] = ("editor-bootstrap", 0, None)

        threads = [threading.Thread(target=self._handle, args=(agent, *job))
                   for agent, job in jobs.items()]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        if not jobs:
            self.log("Nothing to dispatch.")

    def _is_stale(self, updated_at: str) -> bool:
        ts = time.mktime(time.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        return self.now() - ts > self.cfg.stale

    def _handle(self, agent: str, key: str, number: int, t: lifecycle.Ticket | None) -> None:
        st = self.state.load(key)
        sig = signature(t) if t else "bootstrap"
        if st.get("signature") != sig:
            st = {"signature": sig, "failures": 0}  # new transition: fresh retry budget
        if st.get("escalated"):
            return
        if st["failures"] >= MAX_FAILURES:
            self._escalate(agent, key, number, st)
            return
        wait = st["failures"] * self.cfg.backoff * (30 if st.get("rate_limited") else 1)
        if st["failures"] and self.now() < st.get("last_attempt", 0) + wait:
            self.log(f"{key}: backing off after {st['failures']} failure(s)")
            return
        if self.dry:
            self.log(f"[dry-run] would wake {agent} for {key}")
            return

        lock = AgentLock(self.state.dir, agent, self.cfg.timeout + 60)
        if not lock.acquire():
            self.log(f"{agent} is already running; not waking it for {key}")
            return
        try:
            self.log(f"Waking {agent} for {key} ({sig})")
            prompt, extra, code, output = prompt_for(agent, number, t), {}, None, ""
            if self.cfg.needs_pr(agent):
                pr, why = self.resolve_pr(number)
                if pr is None:
                    code, output = 2, why  # counts as a failed attempt; agent not started
                else:
                    extra = {"pr": str(pr)}
            if code is None:
                code, output = self.run_agent(agent, str(number), prompt, **extra)
            st["last_attempt"] = self.now()
            st["rate_limited"] = bool(re.search(r"\b(402|429)\b", output))
            moved = self._labels_moved(number, sig) if t else code == 0
            if code == 0 and moved:
                st = {"signature": sig, "failures": 0, "last_ok": self.now()}
                self.log(f"{key}: {agent} finished and labels moved")
            else:
                st["failures"] += 1
                st["last_error"] = sanitize(
                    output if code else "exited 0 but labels/tickets did not change"
                )
                self.log(f"{key}: failure {st['failures']}/{MAX_FAILURES} "
                         f"(exit {code}): {st['last_error'][:120]}")
            if st["failures"] >= MAX_FAILURES:
                self._escalate(agent, key, number, st)
            self.state.save(key, st)
        finally:
            lock.release()

    def _labels_moved(self, number: int, old_sig: str) -> bool:
        current = [i for i in self.gh.issues("open") if i["number"] == number]
        return not current or signature(parse_ticket(current[0], set())) != old_sig

    def _escalate(self, agent: str, key: str, number: int, st: dict) -> None:
        self.log(f"{key}: {MAX_FAILURES} failed attempts; escalating to the human")
        body = (
            f"### Escalation  dispatcher → human\n{agent} failed {MAX_FAILURES} consecutive "
            f"invocations without moving the ticket.\nLast error: `{st.get('last_error', 'n/a')}`"
            "\nThe dispatcher has stopped retrying. Fix the cause, then relabel the ticket."
        )
        if not self.dry:
            if number:
                current = [i for i in self.gh.issues("open") if i["number"] == number]
                old = [label["name"] for label in current[0]["labels"]
                       if label["name"].startswith(("status:", "agent:"))] if current else []
                self.gh.edit_labels("issue", number, ["status:blocked", "agent:editor"], old)
                self.gh.comment("issue", number, body)
            else:
                self.gh.create_issue("Escalation: editor could not create tickets from the brief",
                                     body, ["status:blocked", "agent:editor"])
        st["escalated"] = True
        self.state.save(key, st)

    def _run_subprocess(self, agent: str, issue: str, prompt: str,
                        pr: str = "") -> tuple[int, str]:
        argv = self.cfg.command(agent, issue, prompt, pr)
        log = self.state.dir / "logs" / f"{agent}-{issue}-{int(self.now())}.log"
        try:
            out = subprocess.run(argv, cwd=self.cfg.root, capture_output=True, text=True,
                                 timeout=self.cfg.timeout + 30)
            text, code = (out.stdout or "") + (out.stderr or ""), out.returncode
        except subprocess.TimeoutExpired:
            text, code = "timed out", 124
        except OSError as exc:
            text, code = f"could not start {argv[0]}: {exc}", 127
        log.write_text(sanitize(text, 20000))
        return code, text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="show actions, change nothing")
    args = ap.parse_args(argv)
    cfg = Config()
    if not args.dry_run and not shutil.which("gh"):
        print("Required command not found: gh", file=sys.stderr)
        return 1
    try:
        Dispatcher(cfg, GitHub(cfg.repo), dry_run=args.dry_run).tick()
    except RuntimeError as exc:
        print(f"dispatcher: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
