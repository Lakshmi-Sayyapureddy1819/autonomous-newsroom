"""Deterministic Copydesk review of one pull request (no LLM).

Usage: copydesk_agent.py <PR_NUMBER>   (the dispatcher resolves Issue -> PR for you)

Review criteria (mechanical only; this does NOT read acceptance criteria prose):
  1. the PR closes exactly one Issue
  2. the PR is not a draft
  3. the PR has no merge conflicts
  4. the `ci` check completed successfully
If `ci` is still pending or missing no verdict is written and the script exits 2, so the
dispatcher counts a failed attempt and retries later. Any other failed criterion yields
review:changes-requested. Approval is never written unless all four pass.
"""

from __future__ import annotations

import sys

import ghlib


def evaluate(pr: dict) -> tuple[str, list[str]]:
    """Return ('approved'|'changes'|'wait', reasons)."""
    ci = ghlib.ci_state(pr)
    if ci in ("pending", "missing"):
        return "wait", [f"ci check is {ci}"]
    problems = []
    if ghlib.linked_issue(pr) is None:
        problems.append("PR must close exactly one Issue ('Closes #N')")
    if pr.get("isDraft"):
        problems.append("PR is a draft")
    if pr.get("mergeable") == "CONFLICTING":
        problems.append("PR has merge conflicts with main")
    if ci != "success":
        problems.append("ci check failed")
    return ("changes" if problems else "approved"), problems


def main(pr_number: int) -> int:
    print(f"Copydesk Agent: Reviewing PR #{pr_number}")
    pr = ghlib.pr_details(pr_number)
    if not pr:
        print(f"Could not retrieve PR #{pr_number}.", file=sys.stderr)
        return 1
    verdict, reasons = evaluate(pr)
    if verdict == "wait":
        print(f"Copydesk Agent: not reviewable yet ({reasons[0]}); no verdict written.",
              file=sys.stderr)
        return 2
    issue = ghlib.linked_issue(pr)
    if issue is None:  # cannot hand off without an Issue; never write a verdict
        print("Copydesk Agent: " + "; ".join(reasons), file=sys.stderr)
        return 2
    sha = pr.get("headRefOid", "unknown")
    if verdict == "approved":
        label, gone = "review:approved", "review:changes-requested"
        body = (f"### Handoff  copydesk → factcheck\nPR #{pr_number} @ {sha}: mechanical review "
                "passed (single linked Issue, not draft, no conflicts, ci green). "
                "Acceptance criteria are verified by Factcheck/human.")
        issue_add, issue_remove = (["status:in-test", "agent:factcheck"],
                                   ["status:in-review", "agent:copydesk"])
    else:
        label, gone = "review:changes-requested", "review:approved"
        body = (f"### Handoff  copydesk → editor\nPR #{pr_number} @ {sha}: changes requested.\n"
                + "\n".join(f"- {r}" for r in reasons))
        # No status label: editor_lifecycle re-routes (attempt+1) on the verdict label.
        issue_add, issue_remove = ["agent:editor"], ["status:in-review", "agent:copydesk"]
    if not ghlib.record(pr_number, issue, pr_add=[label], pr_remove=[gone],
                        issue_add=issue_add, issue_remove=issue_remove, comment=body):
        print("Copydesk Agent: failed to record the verdict on GitHub.", file=sys.stderr)
        return 1
    print(f"Copydesk Agent: PR #{pr_number} -> {label}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Usage: python copydesk_agent.py <PR_NUMBER>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(int(sys.argv[1])))
