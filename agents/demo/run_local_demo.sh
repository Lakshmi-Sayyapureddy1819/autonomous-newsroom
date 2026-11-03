#!/usr/bin/env bash
# Local four-agent demo: a task goes to the Hermes EDITOR, which writes the Issue; then
#   dispatcher -> OpenClaw REPORTER (PR) -> dispatcher -> Hermes COPYDESK (review)
#   -> dispatcher -> OpenClaw FACTCHECK (tests the exact head) -> gate green -> STOP.
# A human merges. This script NEVER merges and never edits labels or verdicts itself: every
# transition is made by an agent or by the dispatcher, and every hand-off is validated against
# GitHub (see agents/dispatcher/dispatch.py). All four agents are the REAL LLM agents; the
# deterministic scripts are used only with --deterministic-review.
#
#   bash agents/demo/run_local_demo.sh [--yes] [--task TEXT] [--issue N] [--timeout MIN]
#                                      [--poll SEC] [--preflight-only] [--deterministic-review]
#     --yes             run without the interactive confirmation
#     --task TEXT       the task for the Editor (default: add app/tests/test_demo_true.py)
#     --issue N         resume an existing Editor-created ticket instead of submitting a task
#     --timeout MIN     overall deadline (default 45)
#     --preflight-only  run checks only; no GitHub writes, no agents
set -uo pipefail

REPO="${GITHUB_REPOSITORY:-Lakshmi-Sayyapureddy1819/autonomous-newsroom}"
TIMEOUT_MIN=45; POLL=20; YES=0; ISSUE=""; PREFLIGHT_ONLY=0; DETERMINISTIC=0
TASK="Add a new test file app/tests/test_demo_true.py containing a single test named test_true_is_true that asserts True is True. Do not modify any existing files."
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --issue) ISSUE="${2:?--issue needs a number}"; shift ;;
    --timeout) TIMEOUT_MIN="${2:?}"; shift ;;
    --poll) POLL="${2:?}"; shift ;;
    --preflight-only) PREFLIGHT_ONLY=1 ;;
    --task) TASK="${2:?--task needs text}"; shift ;;
    --deterministic-review) DETERMINISTIC=1 ;;
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
  shift
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
STATE_ROOT="$HOME/.local/state/newsroom-demo"
RUN="$STATE_ROOT/run-$(date +%Y%m%d-%H%M%S)"
LOCK="$STATE_ROOT/demo.lock"
DEADLINE=$((SECONDS + TIMEOUT_MIN * 60))
WT=""; PR=""; TICK_N=0; IDLE=0; NET_FAILS=0

# Never print tokens: mask anything that looks like a credential in all output we relay.
redact() { sed -E 's/(ghp_|github_pat_|sk-|AIza|gho_)[A-Za-z0-9_-]{8,}/[redacted]/g'; }
say()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
gh_()  { gh "$@" --repo "$REPO"; }

cleanup() {
  [ -n "$WT" ] && git -C "$MAIN_REPO" worktree remove --force "$WT" >/dev/null 2>&1
  rm -rf "$LOCK"
}
trap cleanup EXIT

issue_labels() { gh_ issue view "$ISSUE" --json labels --jq '[.labels[].name]|join(",")' 2>/dev/null; }
issue_state()  { gh_ issue view "$ISSUE" --json state --jq .state 2>/dev/null; }
# prints: "<pr>|<labels>|<ci>" for the one open PR that closes the issue, or "none"
pr_info() {
  gh_ pr list --state open --limit 100 --json number,labels,closingIssuesReferences,statusCheckRollup \
    --jq '[.[]|select(any(.closingIssuesReferences[]?; .number=='"$ISSUE"'))] | if length==0 then "none" else .[0] |
      ([.statusCheckRollup[]?|select(.name=="ci")]) as $c |
      (if ($c|length)==0 then "missing" elif any($c[]; .status!="COMPLETED") then "pending"
       elif all($c[]; .conclusion=="SUCCESS") then "success" else "failure" end) as $ci |
      "\(.number)|\([.labels[].name]|join(","))|\($ci)" end' 2>/dev/null
}
has() { case ",$1," in *",$2,"*) return 0 ;; *) return 1 ;; esac; }

report_failure() {
  local why="$1"
  echo; echo "################ DEMO FAILED: $why ################"
  echo "Issue : #${ISSUE:-none}  state=$(issue_state)  labels=[$(issue_labels)]"
  local info; info="$(pr_info)"
  echo "PR    : ${info:-unknown}   (format: number|labels|ci)"
  local last; last="$(ls -t "$RUN"/tick-*.log 2>/dev/null | head -1)"
  [ -n "$last" ] && { echo "--- latest dispatcher tick log: $last"; tail -n 30 "$last" | redact; }
  local alog; alog="$(ls -t "$RUN"/state/logs/*.log 2>/dev/null | head -1)"
  [ -n "$alog" ] && { echo "--- latest agent log: $alog"; tail -n 30 "$alog" | redact; }
  [ -n "$ISSUE" ] && [ -f "$RUN/state/issue-$ISSUE.json" ] && {
    echo "--- dispatcher state for issue-$ISSUE:"; redact < "$RUN/state/issue-$ISSUE.json"; }
  echo "Error : $why"
  echo "Run dir: $RUN   (resume with: bash agents/demo/run_local_demo.sh --issue ${ISSUE:-N})"
  exit 1
}

# ---------------------------------------------------------------- 1. preflight
step "1/5 Preflight"
fail=0
ok()   { say "ok    $*"; }
bad()  { say "FAIL  $*"; fail=1; }
[ -n "${BASH_VERSION:-}" ] && ok "bash ${BASH_VERSION%%(*} (Git Bash)" || bad "not running under bash"
command -v git >/dev/null && ok "git" || bad "git missing"
command -v uv >/dev/null && ok "uv $(uv --version | cut -d' ' -f2)" || bad "uv missing"
PY="${NEWSROOM_PYTHON:-uv run --no-project python}"
$PY -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1 \
  && ok "python via uv ($($PY -c 'import platform;print(platform.python_version())'))" \
  || bad "python 3.10+ not runnable through uv"
gh auth status >/dev/null 2>&1 && ok "gh authenticated" || bad "gh not authenticated (run: gh auth login)"
if command -v openclaw >/dev/null; then
  oc="$(openclaw agents list 2>&1)"
  echo "$oc" | grep -q '^- reporter' && ok "openclaw agent 'reporter' registered" || bad "openclaw has no 'reporter' agent"
  model="$(echo "$oc" | awk '/^- reporter/{f=1;next} /^- /{f=0} f&&/Model:/{sub(/.*Model: */,"");print;exit}')"
  [ -n "$model" ] && [ "$model" != "(none)" ] && ok "reporter model: $model" || bad "reporter has no model configured"
else
  bad "openclaw not on PATH"
fi
if command -v hermes >/dev/null; then
  hp="$(hermes profile list 2>&1)"
  for prof in editor copydesk; do
    echo "$hp" | grep -Eq "^[^A-Za-z]*$prof[[:space:]]" && ok "hermes profile '$prof' exists" || bad "hermes has no '$prof' profile"
  done
else
  bad "hermes not on PATH"
fi
command -v openclaw >/dev/null && { echo "$oc" | grep -q '^- factcheck' && ok "openclaw agent 'factcheck' registered" || bad "openclaw has no 'factcheck' agent"; }
for l in status:ready agent:reporter attempt:1 status:ready-to-merge review:approved test:passed; do
  gh_ label list --limit 100 --json name --jq '.[].name' 2>/dev/null | grep -qx "$l" || bad "repo label missing: $l"
done
git -C "$MAIN_REPO" fetch origin --quiet && ok "fetched origin" || bad "git fetch failed"
git -C "$MAIN_REPO" merge-base --is-ancestor origin/main HEAD \
  && ok "this checkout contains origin/main ($(git -C "$MAIN_REPO" rev-parse --short origin/main))" \
  || bad "this checkout is behind origin/main; run: git pull"
open_prs="$(gh_ pr list --state open --json number --jq 'length' 2>/dev/null)"
[ "${open_prs:-x}" = "0" ] && ok "no other open PRs" || bad "open PRs exist (${open_prs:-?}); the demo needs a quiet pipeline"
active="$(gh_ issue list --state open --json number,labels --jq '[.[]|select(any(.labels[].name; test("^status:(ready|in-progress|in-review|in-test)$")))]|map("#\(.number)")|join(" ")' 2>/dev/null)"
if [ -n "$ISSUE" ]; then ok "resuming ticket #$ISSUE"; elif [ -z "$active" ]; then ok "no other active ticket in the pipeline"; else bad "other tickets already active: $active"; fi
[ "$fail" -eq 0 ] || { echo "Preflight failed; nothing was created or started."; exit 1; }
[ "$PREFLIGHT_ONLY" -eq 1 ] && { say "preflight only: done."; exit 0; }

mkdir -p "$STATE_ROOT"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another demo run holds $LOCK. If none is running: rm -rf '$LOCK'" >&2; trap - EXIT; exit 1
fi
mkdir -p "$RUN/state"

# Run the dispatcher and agents from a clean throwaway checkout of origin/main so the Reporter's
# branch contains ONLY the ticket's change (never this demo script or local edits).
WT="$RUN/repo"
git -C "$MAIN_REPO" worktree add --detach "$WT" origin/main >/dev/null 2>&1 \
  && ok "clean checkout of origin/main at $WT" || report_failure "could not create worktree"

# ---------------------------------------------------------------- 2. Hermes Editor writes the ticket
step "2/5 Task -> Hermes Editor -> GitHub Issue"
export NEWSROOM_DISPATCH_STATE_DIR="$RUN/state"    # fresh retry budget, isolated from other runs
export NEWSROOM_REPO_DIR="$WT"                     # agents work ONLY in this clean checkout
export GITHUB_REPOSITORY="$REPO"
export PYTHONUNBUFFERED=1
[ "$DETERMINISTIC" -eq 1 ] && export NEWSROOM_REVIEW_MODE=deterministic || unset NEWSROOM_REVIEW_MODE
# The dispatcher code under test is THIS checkout; only the agents' work tree is origin/main.
DISPATCH="$MAIN_REPO/agents/dispatcher"
EDITOR_LOG="$RUN/editor.log"
if [ -z "$ISSUE" ]; then
  say "Task for the Editor: $TASK"
  say "The Hermes Editor will create ONE LIVE GitHub Issue in $REPO labelled"
  say "  status:ready, agent:reporter, attempt:1  (this is what wakes the Reporter)"
  if [ "$YES" -ne 1 ]; then
    read -r -p "Type CREATE to proceed: " ans </dev/tty
    [ "$ans" = "CREATE" ] || { echo "Aborted; nothing created."; exit 1; }
  fi
  $PY "$DISPATCH/submit_task.py" "$TASK" 2>&1 | redact | tee "$EDITOR_LOG"
  [ "${PIPESTATUS[0]}" -eq 0 ] || report_failure "the Editor did not produce a valid Issue (see above; nothing was resent)"
  ISSUE="$(sed -n 's/^ISSUE=//p' "$EDITOR_LOG" | tail -1)"
  say "Editor created Issue #$ISSUE"
fi
case "$ISSUE" in ''|*[!0-9]*) report_failure "bad issue number '$ISSUE'" ;; esac

# ---------------------------------------------------------------- 3. dispatcher loop
step "3/5 Dispatcher loop (timeout ${TIMEOUT_MIN} min, poll ${POLL}s)"
tick() {
  TICK_N=$((TICK_N + 1)); local out="$RUN/tick-$TICK_N.log"
  say ">>> dispatcher tick #$TICK_N"
  $PY "$DISPATCH/dispatch.py" 2>&1 | redact | tee "$out"
  local rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    # A transient GitHub/network error ("gh ... failed: ... timeout/EOF") is retried; anything else is fatal.
    if grep -Eqi "TLS handshake timeout|EOF|timeout|connection reset|no such host" "$out" && [ "$NET_FAILS" -lt 3 ]; then
      NET_FAILS=$((NET_FAILS + 1)); say "dispatcher could not reach GitHub (transient, $NET_FAILS/3); retrying"; sleep 15; return 0
    fi
    report_failure "dispatcher exited $rc (see tick log)"
  fi
  NET_FAILS=0
  grep -q "escalating" "$out" && report_failure "dispatcher escalated the ticket to the human"
  grep -q "malformed labels persisted" "$out" && report_failure "labels stayed inconsistent; the dispatcher blocked the ticket for the human"
  grep -q "failure [0-9]/3" "$out" && say "an invocation failed validation (the dispatcher retries up to 3 times, then escalates)"
  if grep -q "Nothing to dispatch" "$out"; then
    IDLE=$((IDLE + 1)); [ "$IDLE" -ge 3 ] && report_failure "3 consecutive ticks woke nobody although the ticket looked actionable"
  else IDLE=0; fi
  sleep 5
  return 0
}

last_line=""
while :; do
  [ "$SECONDS" -ge "$DEADLINE" ] && report_failure "timeout after ${TIMEOUT_MIN} minutes"
  L="$(issue_labels)"; INFO="$(pr_info)"
  [ -z "$L" ] && { sleep 5; L="$(issue_labels)"; [ -z "$L" ] && report_failure "cannot read labels of Issue #$ISSUE (gh/network?)"; }
  PRL=""; CI="-"; PR=""
  if [ -n "$INFO" ] && [ "$INFO" != "none" ]; then PR="${INFO%%|*}"; rest="${INFO#*|}"; PRL="${rest%|*}"; CI="${rest##*|}"; fi
  line="issue #$ISSUE [$L] | PR ${PR:+#$PR} [${PRL}] ci=$CI"
  [ "$line" != "$last_line" ] && say "$line"; last_line="$line"

  if has "$L" status:ready-to-merge; then break; fi
  if has "$L" status:blocked; then report_failure "ticket is status:blocked"; fi
  if [ "$(issue_state)" = "CLOSED" ]; then report_failure "Issue #$ISSUE was closed unexpectedly"; fi

  if has "$L" status:ready && has "$L" agent:reporter; then
    say "Reporter is eligible -> dispatcher wakes OpenClaw (this blocks while it builds the PR)"
    tick
  elif has "$L" status:in-progress; then
    say "Reporter has claimed the ticket and is working..."; sleep "$POLL"
  elif has "$L" status:in-review && has "$L" agent:copydesk; then
    # Copydesk treats a pending/missing ci as a FAILED attempt; never wake it until ci is decided.
    case "$CI" in
      success) say "PR #$PR ci is green -> dispatcher wakes Copydesk"; tick ;;
      failure) report_failure "ci failed on PR #$PR; fix it (or let Copydesk request changes) - stopping the demo" ;;
      *) say "waiting for the Reporter PR / ci (ci=$CI); not waking Copydesk yet"; sleep "$POLL" ;;
    esac
  elif has "$L" status:in-test && has "$L" agent:factcheck; then
    say "Copydesk approved -> dispatcher wakes Factcheck (tests the exact PR head)"
    tick
  elif has "$L" agent:editor && ! echo "$L" | grep -q 'status:'; then
    say "re-route pending -> dispatcher applies the deterministic editor duties"
    tick
  else
    say "no actionable state yet; waiting"; sleep "$POLL"
  fi
done

# ---------------------------------------------------------------- 4. verify terminal state + gate
step "4/5 Verify the terminal state and the gate"
L="$(issue_labels)"; INFO="$(pr_info)"
[ -n "$INFO" ] && [ "$INFO" != "none" ] || report_failure "ticket is ready-to-merge but no open PR was found"
PR="${INFO%%|*}"; rest="${INFO#*|}"; PRL="${rest%|*}"
has "$PRL" review:approved && has "$PRL" test:passed || report_failure "PR #$PR lacks review:approved and/or test:passed (labels: $PRL)"
say "Issue #$ISSUE labels: $L"
say "PR    #$PR labels: $PRL"
# Proof from the logs that every agent was actually invoked and left a VALID hand-off.
ALL_TICKS=("$STATE_ROOT"/run-*/tick-*.log); ALL_EDITOR=("$STATE_ROOT"/run-*/editor.log)
if grep -qh "^Editor created Issue #$ISSUE" "${ALL_EDITOR[@]}" 2>/dev/null; then
  say "evidence: Hermes Editor was invoked and created Issue #$ISSUE (validated by submit_task.py)"
else
  say "note: no Editor log for Issue #$ISSUE in this run (resumed with --issue?)"
fi
for ag in reporter copydesk factcheck; do
  if grep -qh "Waking $ag for issue-$ISSUE" "${ALL_TICKS[@]}" 2>/dev/null \
     && grep -qh "issue-$ISSUE: $ag finished and the hand-off is valid" "${ALL_TICKS[@]}" 2>/dev/null; then
    say "evidence: $ag was woken by the dispatcher and left a valid hand-off"
  else
    report_failure "no log evidence that $ag was invoked and handed off validly"
  fi
done
gate_deadline=$((SECONDS + 180)); gate=""
while [ "$SECONDS" -lt "$gate_deadline" ]; do
  gate="$(gh_ pr view "$PR" --json statusCheckRollup --jq '[.statusCheckRollup[]?|select(.name=="gate")|.conclusion]|last // "pending"' 2>/dev/null)"
  [ "$gate" = "SUCCESS" ] && break
  case "$gate" in FAILURE|CANCELLED|TIMED_OUT) break ;; esac
  say "waiting for the gate check (currently: ${gate:-unknown})"; sleep 10
done
echo; gh_ pr checks "$PR" 2>&1 | redact
[ "$gate" = "SUCCESS" ] || report_failure "gate check is '${gate:-unknown}' (expected SUCCESS)"

# ---------------------------------------------------------------- 5. stop for the human
step "5/5 READY FOR HUMAN MERGE"
url="$(gh_ pr view "$PR" --json url --jq .url)"
say "Issue #$ISSUE is status:ready-to-merge; PR #$PR has review:approved + test:passed; gate is green."
say "Head tested by Factcheck: $(gh_ pr view "$PR" --json headRefOid --jq .headRefOid)"
echo
echo "  >>> Merge it yourself in the browser: $url"
echo "  >>> This script never merges and has stopped."
exit 0
