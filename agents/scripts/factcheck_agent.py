"""Deterministic Factcheck: lint + test the exact head SHA of one pull request (no LLM).

Usage: factcheck_agent.py <PR_NUMBER>   (the dispatcher resolves Issue -> PR for you)

Only writes a test:* verdict from a real ruff/pytest run on the PR head commit. If the checks
cannot run (no uv, fetch failed, head moved) it writes NO verdict, comments, and exits 2 so the
dispatcher counts a failed attempt. Requires review:approved, a green `ci` and one linked Issue.
"""

from __future__ import annotations

import shutil
import sys
import tempfile

import ghlib

run_command = ghlib.run


def run_local_tests(pr_number: int, expected_head: str) -> tuple[bool | None, str]:
    """Test the exact PR head in a temporary worktree, preserving the current checkout."""
    uv = shutil.which("uv")
    if not uv:
        return None, "uv was not found; no local checks were run."

    repo_result = run_command(["git", "rev-parse", "--show-toplevel"])
    if repo_result.returncode != 0:
        return None, "Could not locate the repository root; no local checks were run."
    repo_root = repo_result.stdout.strip()

    print(f"Factcheck Agent: Fetching PR #{pr_number} head {expected_head}")
    fetch_result = run_command(
        ["git", "-C", repo_root, "fetch", "origin", f"refs/pull/{pr_number}/head"]
    )
    if fetch_result.returncode != 0:
        return None, "Could not fetch the PR head; no local checks were run."

    fetched_head = run_command(["git", "-C", repo_root, "rev-parse", "FETCH_HEAD"])
    if fetched_head.returncode != 0:
        return None, "Could not resolve the fetched PR head; no local checks were run."
    if fetched_head.stdout.strip() != expected_head:
        return None, "The PR head changed while preparing the checkout; no local checks were run."

    with tempfile.TemporaryDirectory(prefix="newsroom-factcheck-") as worktree:
        add_result = run_command(
            ["git", "-C", repo_root, "worktree", "add", "--detach", worktree, expected_head]
        )
        if add_result.returncode != 0:
            return None, "Could not create an isolated PR worktree; no local checks were run."

        check_result: bool | None = None
        detail = ""
        try:
            print("Factcheck Agent: Running Ruff on the PR head.")
            lint = run_command(
                [uv, "run", "--project", "app", "--extra", "dev", "ruff", "check", "app/"],
                cwd=worktree,
            )
            if lint.returncode != 0:
                return False, "Ruff check failed on the PR head."

            print("Factcheck Agent: Running pytest on the PR head.")
            tests = run_command(
                [uv, "run", "--project", "app", "--extra", "dev", "pytest", "app/tests/"],
                cwd=worktree,
            )
            if tests.returncode != 0:
                return False, "Pytest failed on the PR head."

            check_result = True
            detail = "Ruff and pytest passed on the exact PR head."
        except OSError as error:
            check_result = None
            detail = f"Could not run local checks ({error}); no test verdict was produced."
        finally:
            remove_result = run_command(
                ["git", "-C", repo_root, "worktree", "remove", "--force", worktree]
            )
            if remove_result.returncode != 0:
                print("Warning: could not remove the temporary Factcheck worktree.", file=sys.stderr)

        return check_result, detail


def main(pr_number: int) -> int:
    print(f"Factcheck Agent: Validating PR #{pr_number}")
    pr = ghlib.pr_details(pr_number)
    if not pr:
        print(f"Could not retrieve PR #{pr_number}.", file=sys.stderr)
        return 1
    issue = ghlib.linked_issue(pr)
    if (
        "review:approved" not in ghlib.label_names(pr)
        or ghlib.ci_state(pr) != "success"
        or issue is None
    ):
        print("Factcheck Agent: PR not eligible (needs review:approved, green ci and one "
              "linked Issue); no verdict written.", file=sys.stderr)
        return 2

    sha = pr.get("headRefOid")
    if sha:
        result, detail = run_local_tests(pr_number, sha)
    else:
        result, detail = None, "Could not get the PR head SHA; no local checks were run."
    if result is not None:  # the head must not have moved while we were testing
        now = ghlib.pr_details(pr_number)
        if not now or now.get("headRefOid") != sha:
            result, detail = None, "PR head changed during testing; result discarded."
    if result is None:
        note = (f"Factcheck Agent: PR #{pr_number} could not be independently tested. "
                f"{detail} No test verdict was applied.")
        ghlib.run(["gh", "pr", "comment", str(pr_number), "--body", note])
        return 2

    if result:
        label, gone, verb = "test:passed", "test:failed", "validated"
        issue_add, issue_remove = ["status:ready-to-merge"], ["status:in-test", "agent:factcheck"]
        target = "human"
    else:
        label, gone, verb = "test:failed", "test:passed", "FAILED independent checks"
        # No status label: editor_lifecycle re-routes (attempt+1) on the verdict label.
        issue_add, issue_remove = ["agent:editor"], ["status:in-test", "agent:factcheck"]
        target = "editor"
    body = f"### Handoff  factcheck -> {target}\nPR #{pr_number} @ {sha} {verb}. {detail}"
    if not ghlib.record(pr_number, issue, pr_add=[label], pr_remove=[gone],
                        issue_add=issue_add, issue_remove=issue_remove, comment=body):
        print("Factcheck Agent: failed to record the verdict on GitHub.", file=sys.stderr)
        return 1
    print(f"Factcheck Agent: PR #{pr_number} -> {label}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Usage: python factcheck_agent.py <PR_NUMBER>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(int(sys.argv[1])))
