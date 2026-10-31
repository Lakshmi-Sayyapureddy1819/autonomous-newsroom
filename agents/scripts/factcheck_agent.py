"""Run independent lint and test checks for a GitHub pull request."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile


def run_command(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run an argument-vector command without invoking a shell."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
    if result.returncode != 0:
        print(f"Command failed ({result.returncode}): {cmd!r}", file=sys.stderr)
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
    elif result.stdout:
        print(result.stdout, end="")
    return result


def get_pr_details(pr_number: int) -> dict | None:
    """Fetch PR metadata and the exact head revision through gh."""
    result = run_command(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,title,body,labels,headRefName,headRefOid,baseRefName,statusCheckRollup",
        ]
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        print(f"Could not parse gh PR response: {error}", file=sys.stderr)
        return None


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
                [
                    uv,
                    "run",
                    "--project",
                    "app",
                    "--extra",
                    "dev",
                    "pytest",
                    "app/tests/",
                ],
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


def main(pr_number: int) -> None:
    print(f"Factcheck Agent: Validating PR #{pr_number}")

    pr = get_pr_details(pr_number)
    if not pr:
        print(f"Error: Could not retrieve PR #{pr_number} details.", file=sys.stderr)
        sys.exit(1)

    review_approved = any(
        label.get("name") == "review:approved" for label in pr.get("labels", [])
    )
    ci_passed = any(
        check.get("name") == "ci" and check.get("conclusion") == "SUCCESS"
        for check in pr.get("statusCheckRollup", [])
    )
    if not review_approved or not ci_passed:
        print(
            "Factcheck Agent: PR is not eligible for testing (Copydesk approval and green CI are required); "
            "no verdict or labels were changed.",
            file=sys.stderr,
        )
        sys.exit(2)

    expected_head = pr.get("headRefOid")
    if not expected_head:
        result, detail = None, "Could not get the PR head SHA; no local checks were run."
    else:
        result, detail = run_local_tests(pr_number, expected_head)

    if result is None:
        comment_body = f"Factcheck Agent: PR #{pr_number} could not be independently tested. {detail} No test verdict was applied."
        run_command(["gh", "pr", "comment", str(pr_number), "--body", comment_body])
        sys.exit(2)

    if result:
        test_status = "test:passed"
        comment_body = (
            f"Factcheck Agent: PR #{pr_number} ({expected_head}) validated. {detail} "
            f"Applying '{test_status}' label."
        )
        next_status = "status:ready-to-merge"
        next_owner = None
    else:
        test_status = "test:failed"
        comment_body = (
            f"Factcheck Agent: PR #{pr_number} ({expected_head}) failed independent checks. {detail} "
            f"Applying '{test_status}' label."
        )
        next_status = "status:ready"
        next_owner = "agent:editor"

    labels_to_add = [test_status, next_status]
    if next_owner:
        labels_to_add.append(next_owner)
    labels_to_remove = ["agent:factcheck", "status:in-test"]

    edit_cmd = ["gh", "pr", "edit", str(pr_number)]
    for label in labels_to_add:
        edit_cmd.extend(["--add-label", label])
    for label in labels_to_remove:
        edit_cmd.extend(["--remove-label", label])

    if run_command(edit_cmd).returncode != 0:
        print("Factcheck Agent: Failed to update PR labels.", file=sys.stderr)
        sys.exit(1)
    if run_command(["gh", "pr", "comment", str(pr_number), "--body", comment_body]).returncode != 0:
        print("Factcheck Agent: Failed to post the verification comment.", file=sys.stderr)
        sys.exit(1)

    print(f"Factcheck Agent: Finished processing PR #{pr_number}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python factcheck_agent.py <PR_NUMBER>")
        sys.exit(1)
    main(int(sys.argv[1]))
