# Demo commands (copy and paste, top to bottom)

Run everything in **Git Bash** from `nr-repair`. Long version: `docs/DEMO_RUNBOOK.md`.
Paste only the code, never the text around it.

## A. Before the interview (safe, creates nothing on GitHub)

```bash
# Step 1: Go to the demo repo
cd /c/Users/Yasaswini/nr-repair

# Step 2: Run every check + preflight (no Issue, no PR)
bash agents/demo/final_demo.sh --check-only
```

## B. Live demo

```bash
# Step 1: Go to the demo repo
cd /c/Users/Yasaswini/nr-repair

# Step 2: Set your task here (only change this line, keep the single quotes)
TASK='In app/newsroom/templates/runs.html change the h1 text "Run log" to "Pipeline run log". Add app/tests/test_runs_heading.py with exactly one test that uses TestClient(app) from newsroom.main to GET "/runs" and asserts "Pipeline run log" is in response.text. Edit only these two files. Do not read, list or modify any other files, and do not run anything except pytest on the new test.'

# Step 3: Pull latest main
git pull --rebase

# Step 4: Show the services are up
openclaw gateway status
openclaw gateway health
hermes gateway status
hermes profile list
openclaw agents list

# Step 5: Run checks, then the autonomous flow (type CREATE when asked)
bash agents/demo/final_demo.sh --task "$TASK"
```

Flow it runs: Editor -> Dispatcher -> Reporter -> Copydesk -> Factcheck -> Gate. It stops at "READY FOR HUMAN MERGE".

## C. Watch it (optional, second terminal)

```bash
# Step 1: See the Issue and PR
gh issue list ; gh pr list

# Step 2: See the labels move
gh issue view <N> --json labels --jq '[.labels[].name]|join(",")'
```

## D. If it stops or fails

```bash
# Step 1: Resume (never start a new task)
cd /c/Users/Yasaswini/nr-repair
bash agents/demo/run_local_demo.sh --issue <N> --poll 5
```

## E. Review and merge (you do this)

```bash
# Step 1: Find the PR number
gh pr list

# Step 2: Only the files from your task must be listed
gh pr diff <PR> --name-only

# Step 3: ci and gate must be green
gh pr checks <PR>

# Step 4: Open it and click Merge in the browser
gh pr view <PR> --web
```

## F. Show the merged change

```bash
# Step 1: Pull the merged code
cd /c/Users/Yasaswini/nr-repair
git pull --rebase

# Step 2: Start the app on port 8001
cd app
NEWSROOM_DB=C:/Users/Yasaswini/nr-demo-copy.sqlite3 uv run --with-editable . uvicorn newsroom.main:app --port 8001

# Step 3: Open http://localhost:8001/runs  (Ctrl+C to stop)
```

## G. Tokens (optional)

```bash
# Step 1: Hermes tokens and cost
hermes -p editor insights
hermes -p copydesk insights

# Step 2: OpenClaw tokens per session
openclaw sessions --all-agents

# Step 3: Hermes + OpenClaw lifetime totals
uv run python agents/demo/token_total.py
```

## H. Quick fixes

```bash
# Gateway stuck: restart, then wait for OK
openclaw gateway restart
openclaw gateway health

# Hermes gateway stuck
hermes gateway restart

# "no tracking information" on git pull
git branch --set-upstream-to=origin/main main

# Behind origin/main
git pull --rebase

# DNS / network down: switch to the phone hotspot, then check
nslookup github.com

# Port busy: use another port (8002) in step F
# Open PR or Issue blocking the preflight
gh pr list ; gh issue list
```

## I. Deploy to the server (run on the VM, not on your laptop)

```bash
# Step 1: Enter the existing repository
cd ~/autonomous-newsroom

# Step 2: Check for unexpected local modifications
git status --short

# Step 3: Download the latest committed code from main
git pull --ff-only origin main

# Step 4: Deploy the updated application
sudo bash ./deploy/install.sh

# Step 5: Confirm the application is running
sudo systemctl status newsroom-web.service --no-pager

# Step 6: Test the local application
curl -I http://127.0.0.1:8000/

# Step 7: Test the public application
curl -I https://34.10.175.17.sslip.io/
```

## Rules

- Never merge a red gate. Never relabel by hand.
- One task per run. Name the exact files. End with "Edit only these files."
- Run section A the day before and again 30 minutes before.
