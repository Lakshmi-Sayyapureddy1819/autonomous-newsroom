"""Shared gh helpers for the deterministic Copydesk and Factcheck agents.

Label ownership follows agents/PROTOCOL.md: the *Issue* carries status:* / agent:* (that is
what the dispatcher polls and compares), the *PR* carries the review:* / test:* verdicts
(that is what the `gate` workflow and editor_lifecycle read).
"""

from __future__ import annotations

import json
import subprocess
import sys

PR_FIELDS = ("number,title,labels,headRefName,headRefOid,isDraft,mergeable,"
             "closingIssuesReferences,statusCheckRollup")


def run(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run an argument vector (never a shell) and echo failures to stderr."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
    if result.returncode != 0:
        print(f"Command failed ({result.returncode}): {cmd!r}", file=sys.stderr)
        print((result.stdout or "") + (result.stderr or ""), file=sys.stderr, end="")
    elif result.stdout:
        print(result.stdout, end="")
    return result


def pr_details(pr_number: int) -> dict | None:
    result = run(["gh", "pr", "view", str(pr_number), "--json", PR_FIELDS])
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        print(f"Could not parse gh PR response: {error}", file=sys.stderr)
        return None


def label_names(pr: dict) -> set[str]:
    return {label.get("name") for label in pr.get("labels") or []}


def linked_issue(pr: dict) -> int | None:
    """The single Issue this PR closes, or None if there is not exactly one."""
    refs = {ref["number"] for ref in pr.get("closingIssuesReferences") or []}
    return refs.pop() if len(refs) == 1 else None


def ci_state(pr: dict) -> str:
    """'success' | 'failure' | 'pending' | 'missing' for the check named `ci`."""
    runs = [c for c in pr.get("statusCheckRollup") or [] if c.get("name") == "ci"]
    if not runs:
        return "missing"
    if any(c.get("status") != "COMPLETED" for c in runs):
        return "pending"
    return "success" if all(c.get("conclusion") == "SUCCESS" for c in runs) else "failure"


def _edit(kind: str, number: int, add: list[str], remove: list[str]) -> bool:
    cmd = ["gh", kind, "edit", str(number)]
    for label in add:
        cmd += ["--add-label", label]
    for label in remove:
        cmd += ["--remove-label", label]
    return run(cmd).returncode == 0


def record(pr_number: int, issue: int, *, pr_add: list[str], pr_remove: list[str],
           issue_add: list[str], issue_remove: list[str], comment: str) -> bool:
    """Write the verdict (PR), then the hand-off labels (Issue). False if any write failed."""
    return (
        _edit("pr", pr_number, pr_add, pr_remove)
        and run(["gh", "pr", "comment", str(pr_number), "--body", comment]).returncode == 0
        and _edit("issue", issue, issue_add, issue_remove)
    )
