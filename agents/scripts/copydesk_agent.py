
import os
import sys
import json
import subprocess
import time

def run_command(cmd):
    """Helper to run shell commands."""
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True, check=False)
    if result.returncode != 0:
        print(f"Command failed: {cmd}\n{result.stderr}", file=sys.stderr)
    else:
        print(result.stdout)
    return result

def get_pr_details(pr_number):
    """Fetch PR details using gh CLI."""
    cmd = f"gh pr view {pr_number} --json number,title,body,labels,headRefName,baseRefName,statusCheckRollup"
    result = run_command(cmd)
    if result.returncode == 0:
        return json.loads(result.stdout)
    return None

def main(pr_number):
    print(f"Copydesk Agent: Reviewing PR #{pr_number}")

    pr = get_pr_details(pr_number)
    if not pr:
        print(f"Error: Could not retrieve PR #{pr_number} details.")
        sys.exit(1)

    # Basic review logic: check if CI passed
    ci_passed = False
    for check in pr.get('statusCheckRollup', []):
        if check.get('name') == 'ci' and check.get('conclusion') == 'SUCCESS':
            ci_passed = True
            break

    if ci_passed:
        review_status = "review:approved"
        comment_body = f"Copydesk Agent: PR #{pr_number} reviewed and CI passed. Applying '{review_status}' label."
        print(comment_body)
    else:
        review_status = "review:changes-requested"
        comment_body = f"Copydesk Agent: PR #{pr_number} review failed. CI is not green. Applying '{review_status}' label."
        print(comment_body)

    # Apply review label and update status
    labels_to_add = [review_status]
    labels_to_remove = ["agent:copydesk", "status:in-review"]

    if review_status == "review:approved":
        labels_to_add.append("status:in-test")
        labels_to_add.append("agent:factcheck")
    else:
        labels_to_add.append("status:ready")
        labels_to_add.append("agent:reporter")


    edit_cmd = ["gh", "pr", "edit", str(pr_number)]
    for label in labels_to_add:
        edit_cmd.extend(["--add-label", label])
    for label in labels_to_remove:
        edit_cmd.extend(["--remove-label", label])
    
    run_command(edit_cmd)
    run_command(["gh", "pr", "comment", str(pr_number), "--body", comment_body])

    print(f"Copydesk Agent: Finished processing PR #{pr_number}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python copydesk_agent.py <PR_NUMBER>")
        sys.exit(1)
    pr_number = int(sys.argv[1])
    main(pr_number)
