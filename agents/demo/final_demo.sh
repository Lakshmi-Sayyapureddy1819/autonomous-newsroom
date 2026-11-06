#!/usr/bin/env bash
# One command for the live demo: sync, check everything, warm up, preflight, then run ONE task.
#
#   bash agents/demo/final_demo.sh                 # checks + the default task (asks you to type CREATE)
#   bash agents/demo/final_demo.sh --check-only    # checks + preflight only; creates nothing on GitHub
#   bash agents/demo/final_demo.sh --task "..."    # your own task text
#   bash agents/demo/final_demo.sh --skip-warmup   # skip the Hermes test prompts + app tests (run --check-only earlier)
#
# It stops at the first failed check. It never merges. You merge the PR yourself.
set -uo pipefail

REPO_DIR="/c/Users/Yasaswini/nr-repair"
CHECK_ONLY=0
SKIP_WARMUP=0
TASK='In app/newsroom/templates/runs.html change the h1 text "Run log" to "Pipeline run log". Add app/tests/test_runs_heading.py with exactly one test that uses TestClient(app) from newsroom.main to GET "/runs" and asserts "Pipeline run log" is in response.text. Edit only these two files. Do not read, list or modify any other files, and do not run anything except pytest on the new test.'

while [ $# -gt 0 ]; do
  case "$1" in
    --check-only) CHECK_ONLY=1 ;;
    --skip-warmup) SKIP_WARMUP=1 ;;
    --task) TASK="${2:?--task needs text}"; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
  shift
done

step() { printf '\n== %s ==\n' "$*"; }
ok()   { printf '[%s] ok    %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '[%s] FAIL  %s\n' "$(date +%H:%M:%S)" "$*"; printf '\nStopped. Nothing was created. Fix the line above (see docs/DEMO_RUNBOOK.md section 11), then run this again.\n'; exit 1; }

# Make sure the OpenClaw Gateway is healthy; restart it once if not (cold start can take ~2-4 min).
ensure_gateway() {
  openclaw gateway health 2>&1 | grep -q "OK" && return 0
  echo "[$(date +%H:%M:%S)] Gateway not healthy; restarting (can take up to ~4 min)..."
  openclaw gateway restart >/dev/null 2>&1
  for _ in $(seq 1 48); do (echo > /dev/tcp/127.0.0.1/18789) 2>/dev/null && break; sleep 5; done
  for _ in 1 2 3 4 5 6; do openclaw gateway health 2>&1 | grep -q "OK" && return 0; sleep 5; done
  return 1
}

step "1/6 Repository"
cd "$REPO_DIR" || die "cannot cd to $REPO_DIR"
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || die "not on main (run: git switch main)"
git branch --set-upstream-to=origin/main main >/dev/null 2>&1
[ -z "$(git status --porcelain)" ] || die "working tree is not clean (commit or discard these first): $(git status --porcelain | head -3 | tr '\n' ' ')"
pulled=0; pull_out=""
for i in 1 2 3; do
  if pull_out="$(git pull --rebase 2>&1)"; then pulled=1; break; fi
  echo "[$(date +%H:%M:%S)] git pull try $i/3 failed; retrying in 5s"; sleep 5
done
[ "$pulled" -eq 1 ] || { echo "--- git said ---"; echo "$pull_out" | tail -5; die "git pull --rebase failed after 3 tries (network? see git message above)"; }
ok "on main, synced, clean: $(git log --oneline -1)"
git merge-base --is-ancestor origin/main HEAD || die "main does not contain origin/main"
ok "main contains origin/main ($(git rev-parse --short origin/main))"

step "2/6 Network and GitHub"
nslookup github.com >/dev/null 2>&1 || die "DNS: cannot resolve github.com (switch to the phone hotspot)"
ok "github.com resolves"
gh auth status >/dev/null 2>&1 || die "gh not logged in (run: gh auth login)"
ok "gh authenticated"
open_prs="$(gh pr list --state open --json number --jq 'length' 2>/dev/null)" || die "gh pr list failed (network?)"
[ "$open_prs" = "0" ] || die "$open_prs open PR(s); merge or close them first (gh pr list)"
ok "no open PRs"
open_issues="$(gh issue list --state open --json number --jq 'length' 2>/dev/null)" || die "gh issue list failed"
[ "$open_issues" = "0" ] || die "$open_issues open Issue(s); finish or close them first (gh issue list)"
ok "no open Issues"

step "3/6 Agents and services"
command -v hermes >/dev/null || die "hermes not on PATH"
case "$(command -v hermes)" in *AppData/Local/hermes/bin/hermes*) ok "hermes launcher: $(command -v hermes)";; *) die "unexpected hermes launcher: $(command -v hermes)";; esac
profiles="$(hermes profile list 2>&1)"
echo "$profiles" | grep -q "editor" && echo "$profiles" | grep -q "copydesk" || die "hermes profiles 'editor' and 'copydesk' not both present"
ok "hermes profiles: editor, copydesk"
agents="$(openclaw agents list 2>&1)"
echo "$agents" | grep -q "reporter" && echo "$agents" | grep -q "factcheck" || die "openclaw agents 'reporter' and 'factcheck' not both registered"
ok "openclaw agents: reporter, factcheck"
ensure_gateway || die "OpenClaw Gateway still unhealthy"
ok "OpenClaw Gateway healthy"
hermes gateway status >/dev/null 2>&1 && ok "hermes gateway running" || echo "note: 'hermes gateway status' reported a problem (one-shot agents may still work)"

step "4/6 Warm-up (first model call is the slowest)"
# A single transient blip (rate limit, network) must not abort the demo: try up to 3 times.
warm() {
  local prof="$1" out="" i
  for i in 1 2 3; do
    out="$(hermes -p "$prof" chat -q "Reply with the single word OK" 2>&1)" && echo "$out" | grep -q "OK" && { ok "hermes $prof answers (try $i)"; return 0; }
    echo "[$(date +%H:%M:%S)] hermes $prof try $i/3 failed; retrying in 10s"; sleep 10
  done
  echo "--- last output from hermes $prof ---"; echo "$out" | sed 's/\x1b\[[0-9;]*m//g' | grep -v '^\s*$' | tail -8
  return 1
}
if [ "$SKIP_WARMUP" -eq 1 ]; then
  echo "[$(date +%H:%M:%S)] skipped (--skip-warmup): Hermes test prompts and app tests not run"
else
  warm editor   || die "hermes editor did not answer after 3 tries (see output above; try the NEWSROOM_EXTRA_ARGS_EDITOR fallback model in DEMO_RUNBOOK section 3)"
  warm copydesk || die "hermes copydesk did not answer after 3 tries (see output above)"
  ( cd app && uv run --with pytest --with-editable . python -m pytest tests -q >/dev/null 2>&1 ) && ok "app tests pass (uv cache warm)" || die "app tests fail on main"
fi

step "5/6 Demo preflight (writes nothing to GitHub)"
bash agents/demo/run_local_demo.sh --preflight-only || die "demo preflight failed"

if [ "$CHECK_ONLY" -eq 1 ]; then
  printf '\nAll checks passed. (--check-only: nothing was created.)\n'
  exit 0
fi

step "6/6 Live run: Editor -> Dispatcher -> Reporter -> Copydesk -> Factcheck -> Gate"
echo "Task: $TASK"
echo "Started: $(date +%H:%M:%S)  (type CREATE when asked; the run takes about 15-25 minutes)"
bash agents/demo/run_local_demo.sh --poll 5 --task "$TASK"
rc=$?

# Auto-recovery: if the run stopped (Gateway drop, agent error, network blip), fix the Gateway and
# RESUME the same Issue (never a new --task, so no duplicate Issue or PR). Up to 3 resumes.
tries=0
while [ "$rc" -ne 0 ] && [ "$tries" -lt 3 ]; do
  tries=$((tries + 1))
  ISSUE_N="$(gh issue list --state open --json number --jq '.[0].number' 2>/dev/null)"
  if [ -z "$ISSUE_N" ] || [ "$ISSUE_N" = "null" ]; then
    echo "No Issue was created (the Editor step failed). Not retrying automatically, to avoid duplicates."
    echo "Check 'gh issue list', fix the cause (see docs/DEMO_RUNBOOK.md section 11), then run this script again."
    exit "$rc"
  fi
  if gh issue view "$ISSUE_N" --json labels --jq '[.labels[].name]|join(",")' 2>/dev/null | grep -q "status:blocked"; then
    echo "Issue #$ISSUE_N is status:blocked (3 failed attempts): the designed escalation. Needs a human decision."
    exit "$rc"
  fi
  echo; echo "[$(date +%H:%M:%S)] Run stopped (exit $rc). Auto-recovery $tries/3: fixing Gateway, resuming Issue #$ISSUE_N"
  ensure_gateway || { echo "Gateway still unhealthy; stopping. Run: openclaw gateway restart, then: bash agents/demo/run_local_demo.sh --issue $ISSUE_N --poll 5"; exit 1; }
  bash agents/demo/run_local_demo.sh --issue "$ISSUE_N" --poll 5
  rc=$?
done
echo "Finished: $(date +%H:%M:%S)  (exit $rc)"
if [ "$rc" -ne 0 ]; then
  echo "Still not complete after 3 auto-resumes. Resume by hand: bash agents/demo/run_local_demo.sh --issue <N> --poll 5"
  exit "$rc"
fi
cat <<'EOF'

Next (you, by hand):
  gh pr list
  gh pr diff <PR> --name-only          # exactly: runs.html and test_runs_heading.py
  gh pr checks <PR>                    # ci and gate green
  Merge in the browser, then:
  cd /c/Users/Yasaswini/nr-repair && git pull --rebase
  cd app && NEWSROOM_DB=C:/Users/Yasaswini/nr-demo-copy.sqlite3 uv run --with-editable . uvicorn newsroom.main:app --port 8001
  open http://localhost:8001/runs      # heading should read "Pipeline run log"
EOF
