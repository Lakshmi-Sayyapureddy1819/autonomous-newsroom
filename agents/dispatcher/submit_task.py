#!/usr/bin/env python3
"""Give a small task to the Hermes Editor and VERIFY the Issue it created.

    python agents/dispatcher/submit_task.py "Add a test file ..."   (or --task-file FILE)

The Editor (Hermes profile `editor`, one-shot, non-interactive) turns the task into exactly one
GitHub Issue labelled status:ready + agent:reporter + attempt:1, which is what the dispatcher
polls. This script never writes to GitHub itself. After the Editor exits (or times out, or the
gateway drops) it re-reads GitHub and checks the outcome, because the exit code alone proves
nothing:

* exactly one new Issue, not zero and not two (an unknown outcome is never blindly resent: it is
  reported, and a possible duplicate of an open ticket is refused unless --allow-duplicate);
* exactly {status:ready, agent:reporter, attempt:1} as its status/agent/attempt labels;
* the Ticket-format sections (Goal, Acceptance criteria, Out of scope, Depends on);
* every file path / identifier named in the task survives into the body (a shell that ate the
  backticks, as it did for Issue #33, is caught here);
* the Editor opened no PR and left the checkout clean.

Exit 0 and a final `ISSUE=<n>` line on success; non-zero otherwise.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch  # noqa: E402

WANT_LABELS = {"status:ready", "agent:reporter", "attempt:1"}
SECTIONS = ("goal", "acceptance criteria", "out of scope", "depends on")
PATHLIKE = re.compile(r"[\w][\w./\\-]*\.\w{1,5}\b")
SNAKE = re.compile(r"\b[A-Za-z]+(?:_[A-Za-z0-9]+)+\b")


def critical_tokens(task: str) -> list[str]:
    """File paths and snake_case identifiers in the task that the Issue must repeat verbatim."""
    found = PATHLIKE.findall(task) + SNAKE.findall(task)
    return sorted({t.rstrip(".") for t in found if len(t) > 3})


def validate_issue(issue: dict, task: str) -> list[str]:
    """Problems with an Editor-created Issue (empty list = valid)."""
    problems = []
    names = {label["name"] for label in issue["labels"]}
    handoff = {n for n in names if n.startswith(("status:", "agent:", "attempt:"))}
    if handoff != WANT_LABELS:
        problems.append(f"labels {sorted(handoff)} != {sorted(WANT_LABELS)}")
    body = issue.get("body") or ""
    low = body.lower()
    missing = [s for s in SECTIONS if s not in low]
    if missing:
        problems.append(f"body lacks section(s): {missing}")
    lost = [t for t in critical_tokens(task) if t not in body and t not in issue["title"]]
    if lost:
        problems.append(f"task text missing from the Issue (shell quoting?): {lost}")
    if "- [ ]" not in body and "* [ ]" not in body:
        problems.append("acceptance criteria are not a checklist")
    return problems


def editor_prompt(task: str, repo: str) -> str:
    return f"""You are the editor. Read agents/PROTOCOL.md first. The human gave you this task, \
verbatim between the markers:

<<<TASK
{task.strip()}
TASK>>>

Create EXACTLY ONE GitHub Issue for it in {repo}: not zero, not two. Do not create branches, \
commits or PRs, do not edit any file in the repository, never merge.

Issue format (PROTOCOL "Ticket format"): sections `## Goal`, `## Acceptance criteria` (a `- [ ]` \
checklist, every item checkable by running or reading something), `## Out of scope`, \
`## Depends on` (write `none`). Copy every file path, function name and quoted literal from the \
task EXACTLY into the criteria.

Labels, applied in the SAME create command: status:ready, agent:reporter, attempt:1. That is \
exactly one status:* and one agent:*; add no other status:* or agent:* label.

Shell safety: write the Issue body to a temporary file in the OS temp directory with your \
file-writing tool, then run: gh issue create --repo {repo} --title "<title>" --body-file <file> \
--label status:ready --label agent:reporter --label attempt:1 . Never inline the body in a shell \
string (backticks and $ are eaten by the shell).

When the Issue exists, post ONE comment on it: "### Handoff  editor -> reporter" with Did / How \
to verify / Known gaps / Tokens lines. Then stop."""


def run_editor(cfg: dispatch.Config, task: str, timeout: int) -> tuple[int, str]:
    """One-shot Hermes editor via --query-file (no command-line quoting or length limits)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(editor_prompt(task, cfg.repo))
    argv = [shutil.which("hermes") or "hermes", "-p", "editor", "chat", "--query-file", fh.name,
            "--oneshot", "--max-turns", str(cfg.max_turns)]
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    try:
        proc = subprocess.Popen(argv, cwd=cfg.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                encoding="utf-8", errors="replace", **group)
        try:
            out, err = proc.communicate(timeout=timeout)
            return proc.returncode, (out or "") + (err or "")
        except subprocess.TimeoutExpired:
            dispatch.Dispatcher._kill_tree(proc)
            return 124, "editor timed out; outcome uncertain"
    except OSError as exc:
        return 127, f"could not start hermes: {exc}"
    finally:
        Path(fh.name).unlink(missing_ok=True)


def submit(gh, task: str, editor, *, allow_duplicate: bool = False, log=print) -> tuple[int, int]:
    """Run the editor once and judge GitHub's state. Returns (exit_code, issue_number)."""
    before_issues = gh.issues("open") + gh.issues("closed")
    baseline = max((i["number"] for i in before_issues), default=0)
    before_prs = {p["number"] for p in gh.open_prs()}
    tokens = critical_tokens(task)
    if not allow_duplicate and tokens:
        dupes = [i["number"] for i in gh.issues("open")
                 if all(t in (i.get("body") or "") + i["title"] for t in tokens)]
        if dupes:
            log(f"REFUSED: open Issue(s) {dupes} already contain this task's file/identifier "
                "names. Inspect them first (--allow-duplicate overrides).")
            return 3, dupes[0]

    code, output = editor(task)
    log(f"editor exited {code}; re-reading GitHub (the exit code is not trusted)")
    new = [i for i in gh.issues("open") + gh.issues("closed") if i["number"] > baseline]
    if len(new) != 1:
        log(f"FAILED: the Editor created {len(new)} new Issue(s) {[i['number'] for i in new]}; "
            "expected exactly 1. Nothing was resent. Inspect GitHub and the Hermes session "
            "before retrying.")
        log(dispatch.sanitize(output, 600))
        return 1, 0
    issue = new[0]
    problems = validate_issue(issue, task)
    prs = {p["number"] for p in gh.open_prs()} - before_prs
    if prs:
        problems.append(f"the Editor opened PR(s) {sorted(prs)}; the Reporter must do that")
    if problems:
        log(f"FAILED: Issue #{issue['number']} is not a valid hand-off:")
        for p in problems:
            log(f"  - {p}")
        return 1, issue["number"]
    if code:
        log(f"note: editor exited {code} but the Issue is valid; accepting it (not re-running)")
    log(f"Editor created Issue #{issue['number']}: {issue['title']}")
    return 0, issue["number"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("task", nargs="?", help="the task text")
    ap.add_argument("--task-file", help="read the task from a file instead")
    ap.add_argument("--timeout", type=int, default=600, help="editor timeout in seconds")
    ap.add_argument("--allow-duplicate", action="store_true")
    ap.add_argument("--print-prompt", action="store_true", help="show the editor prompt and stop")
    args = ap.parse_args(argv)
    task = Path(args.task_file).read_text(encoding="utf-8") if args.task_file else args.task
    if not task or not task.strip():
        ap.error("give the task as an argument or with --task-file")
    cfg = dispatch.Config()
    if args.print_prompt:
        print(editor_prompt(task, cfg.repo))
        return 0
    dirty = dispatch.Dispatcher._dirty(cfg.root)
    if dirty:
        print(f"REFUSED: checkout {cfg.root} is not clean: {dirty}", file=sys.stderr)
        return 2
    gh = dispatch.GitHub(cfg.repo)
    code, number = submit(gh, task, lambda t: run_editor(cfg, t, args.timeout),
                          allow_duplicate=args.allow_duplicate)
    if code == 0:
        print(f"ISSUE={number}")
    return code


if __name__ == "__main__":
    sys.exit(main())
