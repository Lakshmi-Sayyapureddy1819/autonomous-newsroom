#!/usr/bin/env python3
"""GitHub Issue dispatcher (ordinary code, no LLM). See agents/PROTOCOL.md.

Each tick:
1. Poll open Issues (plus the verdict labels of their linked PRs) via `gh`.
2. Run the deterministic editor duties (editor_lifecycle.py): re-route rejected work,
   escalate after 3 attempts, promote the next ready ticket.
3. Wake ONLY the agent named by each ticket's single agent:* label, one invocation per
   agent at a time (lock file), then RE-READ GitHub and validate the hand-off (see
   `Dispatcher._evaluate`): exactly one linked PR, the expected Issue labels, the verdict
   label on the PR, no status:*/agent:* on the PR, an unmoved PR head, a new comment.
4. An invocation that fails or leaves an invalid hand-off counts as a failed attempt. A
   valid hand-off wins over a non-zero exit (the outcome is read from GitHub, never guessed),
   and a timed-out agent is never re-woken while its lock is held. State survives restarts.
   After 3 failures (or too many wakes overall) the ticket is set to status:blocked +
   agent:editor with a comment for the human. Conflicting labels that persist are escalated
   the same way instead of being skipped silently.

Environment (all optional):
  GITHUB_REPOSITORY, NEWSROOM_DISPATCH_STATE_DIR, NEWSROOM_REPO_DIR,
  NEWSROOM_CMD_<AGENT> (shell-style template with {issue}, {pr} and {prompt}),
  NEWSROOM_REVIEW_MODE=deterministic (copydesk/factcheck run agents/scripts/*_agent.py, no LLM;
  default is the LLM agents), NEWSROOM_AGENT_TIMEOUT (s, default 900), NEWSROOM_MAX_TURNS (default 40),
  NEWSROOM_RETRY_BACKOFF (s, default 60), NEWSROOM_STALE_MINUTES (default 45),
  NEWSROOM_MALFORMED_GRACE (s, default 120), NEWSROOM_MAX_WAKES (default 9),
  NEWSROOM_EXTRA_ARGS_<AGENT> (shell-style args appended to that agent's command, e.g. a
  per-run model override: NEWSROOM_EXTRA_ARGS_COPYDESK="-m gemini-2.5-flash --provider gemini";
  OpenClaw: NEWSROOM_EXTRA_ARGS_FACTCHECK="--model google/gemini-2.5-flash"). Off by default.
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
PR_AGENTS = ("reporter", "copydesk", "factcheck")  # work on exactly one linked PR
NEEDS_PR_ARG = ("copydesk", "factcheck")           # woken with the resolved PR number
HANDOFF_PREFIXES = ("status:", "agent:")
TERMINAL_STATUS = ("status:ready-to-merge", "status:blocked")
OWNERS = ("agent:reporter", "agent:copydesk", "agent:factcheck")
# Success hand-offs: agent -> the only (status, agent) pair its Issue may carry afterwards.
HANDOFF_TO = {
    "reporter": ("status:in-review", "agent:copydesk"),
    "copydesk": ("status:in-test", "agent:factcheck"),
}
SECRET = re.compile(r"(ghp_|gho_|github_pat_|sk-|AIza)[A-Za-z0-9_\-]{8,}")


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
        self.malformed_grace = int(env.get("NEWSROOM_MALFORMED_GRACE", "120"))
        self.max_wakes = int(env.get("NEWSROOM_MAX_WAKES", "9"))
        self.env = env

    def needs_pr(self, agent: str) -> bool:
        """True when the agent is woken with its linked PR (reviewers always are)."""
        override = self.env.get(f"NEWSROOM_CMD_{agent.upper()}")
        if override and "{pr}" in override:
            return True
        return agent in NEEDS_PR_ARG

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
        if not override:
            argv += shlex.split(self.env.get(f"NEWSROOM_EXTRA_ARGS_{agent.upper()}", ""))
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
                                   "number,labels,closingIssuesReferences,headRefOid"))

    def activity(self, issue: int, pr: int | None) -> int:
        """Comments on the Issue plus comments and reviews on the PR (a hand-off must add one)."""
        data = json.loads(self._gh("issue", "view", str(issue), "--json", "comments"))
        count = len(data["comments"])
        if pr:
            data = json.loads(self._gh("pr", "view", str(pr), "--json", "comments,reviews"))
            count += len(data["comments"]) + len(data["reviews"])
        return count

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

    def clear(self, key: str) -> None:
        (self.dir / f"{key}.json").unlink(missing_ok=True)


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

    def keep(self, seconds: int) -> None:
        """Leave the lock in place (refreshed for `seconds`): the agent's outcome is uncertain,
        so nobody may start a second invocation until it has certainly stopped."""
        if self.held:
            os.utime(self.path, (time.time() + seconds - self.ttl,) * 2)
            self.held = False


def parse_ticket(issue: dict, pr_labels: set[str]) -> lifecycle.Ticket:
    return lifecycle.Ticket(
        number=issue["number"], title=issue["title"], body=issue.get("body") or "",
        labels={label["name"] for label in issue["labels"]}, pr_labels=pr_labels,
    )


def signature(t: lifecycle.Ticket) -> str:
    return "|".join(t.with_prefix("agent:") + t.with_prefix("status:") + t.with_prefix("attempt:"))


def label_problem(t: lifecycle.Ticket) -> str:
    """Why this Issue's status:*/agent:* labels cannot be dispatched ('' if they are fine).

    Terminal and queue states are fine: ready-to-merge / blocked (any owner), and
    `agent:editor` with no status (a ticket waiting on its dependencies).
    """
    status, agent = t.with_prefix("status:"), t.with_prefix("agent:")
    if len(status) > 1:
        return f"multiple status labels {status}"
    if len(agent) > 1:
        return f"multiple agent labels {agent}"
    if status and status[0] in TERMINAL_STATUS:
        return ""
    if status and not agent:
        return f"{status[0]} without an agent:* owner"
    if agent and not status:
        return "" if agent[0] == "agent:editor" else f"{agent[0]} without a status:* label"
    if status and agent and (status[0], agent[0]) not in WAKE:
        return f"inconsistent pair {status[0]} + {agent[0]}"
    return ""


ROLE_RULES = {
    "reporter": (
        "Work ONLY in the checkout named above. If a branch or open PR for this Issue already "
        "exists, continue on it; never open a second PR. Change only what the Issue asks and "
        "run `git status` before committing so nothing else is staged. The PR body must contain "
        "'Closes #{n}'. Never put status:* or agent:* labels on the PR. When done, on the "
        "ISSUE: add status:in-review and agent:copydesk, remove status:ready, status:in-progress "
        "and agent:reporter; then post the handoff comment on the Issue and on the PR."
    ),
    "copydesk": (
        "Review PR #{pr} at its CURRENT head against EVERY acceptance criterion and the Out "
        "of scope section of the Issue. Run `gh pr diff {pr} --name-only`: any file the Issue "
        "does not allow is a failed criterion. Post a review comment on the PR listing each "
        "criterion as pass/fail with file:line evidence. If all pass: add review:approved to the "
        "PR; on the ISSUE add status:in-test and agent:factcheck and remove status:in-review and "
        "agent:copydesk. If any fails: add review:changes-requested to the PR and leave the "
        "Issue labels alone (the dispatcher re-routes). Never put status:* or agent:* on the PR. "
        "Do not edit, commit or push."
    ),
    "factcheck": (
        "Test PR #{pr}. Fetch and check out its EXACT head SHA in the checkout named above "
        "(`gh pr checkout {pr} --detach` or `git fetch origin pull/{pr}/head`), record the SHA, "
        "run `ruff check app/` and the pytest suite, and verify each acceptance criterion by "
        "command. Post the commands, output and SHA as a PR comment. If everything passes and "
        "the PR head is still that SHA: add test:passed to the PR; on the ISSUE add "
        "status:ready-to-merge and remove status:in-test and agent:factcheck. Otherwise add "
        "test:failed to the PR and leave the Issue labels alone. Never put status:* or agent:* "
        "on the PR. Do not edit, commit or push."
    ),
}


def prompt_for(agent: str, number: int, t: lifecycle.Ticket | None, root: Path | None = None,
               pr: str = "") -> str:
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
    where = (f" Your repository checkout is {root} (clean). Do ALL git and file work there and "
             "in no other checkout." if root else "")
    pr_note = f" The linked PR is #{pr}." if pr else ""
    rules = ROLE_RULES.get(agent, "").format(n=number, pr=pr or "?")
    return (
        f"You are {agent}. Work ONLY on Issue #{number} ({t.title if t else ''}).{pr_note}{where} "
        "Read agents/PROTOCOL.md first. Follow your role instructions, never merge, and finish by "
        "updating the labels and posting the handoff comment on the Issue (and PR) exactly as "
        f"the protocol specifies. GitHub is the only channel to other agents. {rules}"
    ).strip()


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
            if status == ["status:blocked"]:
                self.state.clear(f"issue-{t.number}-wakes")  # a human owns it now
            problem = label_problem(t)
            if problem:
                self._malformed(t, problem)
                continue
            self.state.clear(f"malformed-{t.number}")
            if len(status) != 1 or len(agent) != 1:
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

        wakes_key = f"{key}-wakes"
        wakes = self.state.load(wakes_key).get("count", 0)
        if t and wakes >= self.cfg.max_wakes:
            st["last_error"] = (f"{wakes} agent invocations without reaching ready-to-merge "
                                "(possible loop)")
            self._escalate(agent, key, number, st)
            return

        lock = AgentLock(self.state.dir, agent, self.cfg.timeout + 60)
        if not lock.acquire():
            self.log(f"{agent} is already running; not waking it for {key}")
            return
        try:
            self.log(f"Waking {agent} for {key} ({sig})")
            extra, code, output, pr = {}, None, "", None
            if self.cfg.needs_pr(agent):
                pr, why = self.resolve_pr(number)
                if pr is None:
                    code, output = 2, why  # counts as a failed attempt; agent not started
                else:
                    extra = {"pr": str(pr)}
            if code is None and agent == "reporter":
                dirty = self._dirty(self.cfg.root)
                if dirty:
                    code, output = 2, f"working checkout {self.cfg.root} is not clean: {dirty}"
            before = {}
            if code is None and t:
                before = self._snapshot(number, pr)
                before["labels"] = sorted(t.with_prefix("status:") + t.with_prefix("agent:"))
            if code is None:
                prompt = prompt_for(agent, number, t, self.cfg.root, extra.get("pr", ""))
                code, output = self.run_agent(agent, str(number), prompt, **extra)
                self.state.save(wakes_key, {"count": wakes + 1})
                if code == 124:  # uncertain: it may still be running somewhere
                    lock.keep(self.cfg.timeout)
            st["last_attempt"] = self.now()
            st["rate_limited"] = bool(re.search(r"\b(402|429)\b", output))
            never_started = not before and t and code is not None and code != 0
            if never_started:
                problem = output  # no PR / dirty checkout: the agent was not started
            elif t:
                problem = self._evaluate(agent, number, before)  # re-read GitHub; may repair
            else:  # editor bootstrap: judged by what exists on GitHub, not by the exit code
                problem = "" if self.gh.issues("open") else "editor created no ticket"
            if not problem:
                if code:
                    self.log(f"{key}: {agent} exited {code} but left a valid hand-off on "
                             "GitHub; accepting it (not re-running)")
                st = {"signature": sig, "failures": 0, "last_ok": self.now()}
                self.log(f"{key}: {agent} finished and the hand-off is valid")
            else:
                st["failures"] += 1
                detail = "" if never_started else f" (exit {code}: {output})" if code else ""
                st["last_error"] = sanitize(f"{problem}{detail}")
                self.log(f"{key}: failure {st['failures']}/{MAX_FAILURES} "
                         f"(exit {code}): {st['last_error'][:160]}")
            if st["failures"] >= MAX_FAILURES:
                self._escalate(agent, key, number, st)
            self.state.save(key, st)
        finally:
            lock.release()

    # ---- hand-off validation -------------------------------------------------------
    @staticmethod
    def _dirty(root: Path) -> str:
        """Uncommitted files in the checkout the Reporter will use ('' if clean/not a repo)."""
        if shutil.which("git") is None:
            return ""
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                             capture_output=True, text=True, check=False)
        return " ".join(out.stdout.split())[:200] if out.returncode == 0 else ""

    def _snapshot(self, number: int, pr: int | None) -> dict:
        head = next((p.get("headRefOid") for p in self.gh.open_prs() if p["number"] == pr), None)
        return {"head": head, "activity": self.gh.activity(number, pr)}

    def _evaluate(self, agent: str, number: int, before: dict) -> str:
        """Re-read GitHub after an invocation. '' if the agent left a valid hand-off, else why
        not. Only leftovers that the expected hand-off makes obsolete are repaired (stale
        status:*/agent:* on the Issue, status:*/agent:* on the PR) and every repair is logged
        and commented. A hand-off that did not happen is never fabricated."""
        issue = next((i for i in self.gh.issues("open") if i["number"] == number), None)
        if issue is None:
            return ""  # closed meanwhile; nothing left to validate
        labels = {x["name"] for x in issue["labels"]}
        prs = [p for p in self.gh.open_prs()
               if any(r["number"] == number for r in p.get("closingIssuesReferences") or [])]
        if agent in PR_AGENTS and len(prs) != 1:
            return f"expected exactly one open PR closing #{number}, found {len(prs)}"
        pr = prs[0] if prs else None
        pr_labels = {x["name"] for x in pr["labels"]} if pr else set()
        notes: list[str] = []

        stray = sorted(label for label in pr_labels if label.startswith(HANDOFF_PREFIXES))
        if pr and stray:
            notes.append(f"removed {stray} from PR #{pr['number']} (hand-off labels belong on "
                         "the Issue only)")
            if not self.dry:
                self.gh.edit_labels("pr", pr["number"], remove=stray)
            pr_labels -= set(stray)

        problem = self._check_agent(agent, number, labels, pr_labels, notes)
        if not problem and pr and agent in NEEDS_PR_ARG:
            head = pr.get("headRefOid")
            if before.get("head") and head and head != before["head"]:
                problem = (f"PR head moved {before['head'][:8]} -> {head[:8]} during the run; the "
                           "verdict is stale")
                self._rollback(number, pr["number"], before, pr_labels, notes)
        if not problem and self.gh.activity(number, pr["number"] if pr else None) <= before.get(
                "activity", -1):
            problem = "no handoff comment or review was posted"
        if notes:
            self.log(f"#{number}: dispatcher normalised after {agent}: " + "; ".join(notes))
            if not self.dry:
                self.gh.comment("issue", number, "### Dispatcher note\nAfter the "
                                f"{agent} run the dispatcher: " + "; ".join(notes) + ".")
        return problem

    def _check_agent(self, agent: str, number: int, labels: set[str], pr_labels: set[str],
                     notes: list[str]) -> str:
        def handoff(want: tuple[str, ...]) -> str:
            have = {label for label in labels if label.startswith(HANDOFF_PREFIXES)}
            if not set(want) <= have:
                return f"{agent} left {sorted(have)}; expected {sorted(want)}"
            stale = sorted(have - set(want))
            if stale:
                notes.append(f"removed obsolete {stale} from Issue #{number}")
                if not self.dry:
                    self.gh.edit_labels("issue", number, remove=stale)
            return ""

        def unchanged_or_queued() -> str:
            have = sorted(label for label in labels if label.startswith(HANDOFF_PREFIXES))
            ok = [sorted(before_pair) for before_pair in (
                ("status:in-review", "agent:copydesk"), ("status:in-test", "agent:factcheck"),
                ("agent:editor",))]
            return "" if have in ok else f"{agent} rejected the PR but left {have}"

        if agent == "reporter":
            return handoff(HANDOFF_TO["reporter"])
        if agent == "copydesk":
            approved, rejected = "review:approved" in pr_labels, \
                "review:changes-requested" in pr_labels
            if approved == rejected:
                return ("conflicting review verdicts on the PR" if approved
                        else "no review:approved / review:changes-requested label on the PR")
            return handoff(HANDOFF_TO["copydesk"]) if approved else unchanged_or_queued()
        if agent == "factcheck":
            passed, failed = "test:passed" in pr_labels, "test:failed" in pr_labels
            if passed == failed:
                return ("conflicting test verdicts on the PR" if passed
                        else "no test:passed / test:failed label on the PR")
            if failed:
                return unchanged_or_queued()
            if "review:approved" not in pr_labels:
                return "test:passed without review:approved on the PR"
            status = sorted(label for label in labels if label.startswith(HANDOFF_PREFIXES))
            if "status:ready-to-merge" not in status:
                return f"factcheck passed the PR but left {status}; expected status:ready-to-merge"
            stale = [label for label in status if label != "status:ready-to-merge"]
            if stale:
                notes.append(f"removed obsolete {stale} from Issue #{number}")
                if not self.dry:
                    self.gh.edit_labels("issue", number, remove=stale)
            return ""
        return ""

    def _rollback(self, number: int, pr: int, before: dict, pr_labels: set[str],
                  notes: list[str]) -> None:
        """The PR head moved under a reviewer/tester: drop its verdict and restore the Issue's
        previous owner so the same agent runs again on the new head."""
        verdicts = sorted(pr_labels & {"review:approved", "test:passed"})
        issue = next((i for i in self.gh.issues("open") if i["number"] == number), None)
        now = {x["name"] for x in issue["labels"]
               if x["name"].startswith(HANDOFF_PREFIXES)} if issue else set()
        restore = set(before.get("labels", []))
        notes.append(f"dropped {verdicts} from PR #{pr} and restored {sorted(restore)}")
        if not self.dry:
            self.gh.edit_labels("pr", pr, remove=verdicts)
            self.gh.edit_labels("issue", number, sorted(restore - now), sorted(now - restore))

    def _malformed(self, t: lifecycle.Ticket, problem: str) -> None:
        """Conflicting labels are never skipped silently: log, give an agent/human mid-edit a
        grace period, then block the ticket for the human with an explanation."""
        key = f"malformed-{t.number}"
        st = self.state.load(key)
        first = st.get("first_seen") or self.now()
        if st.get("problem") != problem:
            first = self.now()
        self.state.save(key, {"first_seen": first, "problem": problem})
        age = self.now() - first
        self.log(f"#{t.number}: malformed labels: {problem}; not dispatched "
                 f"({int(age)}s of {self.cfg.malformed_grace}s grace)")
        if age < self.cfg.malformed_grace or self.dry:
            return
        old = t.with_prefix("status:") + t.with_prefix("agent:")
        self.log(f"#{t.number}: malformed labels persisted; escalating to the human")
        self.gh.edit_labels("issue", t.number, ["status:blocked", "agent:editor"], old)
        self.gh.comment("issue", t.number, (
            "### Escalation  dispatcher → human\nThe Issue's labels are inconsistent "
            f"({problem}) and stayed that way, so no agent can be woken safely. Set the ticket to "
            "status:blocked + agent:editor. Fix the labels (exactly one status:* and one agent:*) "
            "or decide how to proceed."))
        self.state.clear(key)

    def _escalate(self, agent: str, key: str, number: int, st: dict) -> None:
        self.log(f"{key}: {MAX_FAILURES} failed attempts; escalating to the human")
        body = (
            f"### Escalation  dispatcher → human\n{agent} could not complete this ticket "
            f"(after {st.get('failures', 0)} failed invocation(s), or too many wakes overall)."
            f"\nLast error: `{st.get('last_error', 'n/a')}`"
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
        group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                 else {"start_new_session": True})
        try:
            proc = subprocess.Popen(argv, cwd=self.cfg.root, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                                    **group)
            try:
                stdout, stderr = proc.communicate(timeout=self.cfg.timeout + 30)
                text, code = (stdout or "") + (stderr or ""), proc.returncode
            except subprocess.TimeoutExpired:
                self._kill_tree(proc)
                text, code = "timed out; outcome uncertain", 124
        except OSError as exc:
            text, code = f"could not start {argv[0]}: {exc}", 127
        log.write_text(sanitize(text, 20000), encoding="utf-8")
        return code, text

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """Stop the agent AND its children so a timed-out run cannot keep acting on GitHub."""
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, check=False)
            else:
                os.killpg(proc.pid, 9)
            proc.communicate(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()


def utf8_stdio() -> None:
    """Agent output is Unicode; a cp1252 Windows console must never crash the dispatcher."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    utf8_stdio()
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
