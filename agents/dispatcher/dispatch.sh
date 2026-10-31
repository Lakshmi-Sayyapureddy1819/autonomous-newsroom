#!/usr/bin/env bash
set -euo pipefail

# Dispatch each issue/owner/status transition once to an already-running tmux agent.
# This script does not make assignments, write GitHub comments, or call an LLM.
REPOSITORY="${GITHUB_REPOSITORY:-Lakshmi-Sayyapureddy1819/autonomous-newsroom}"
STATE_DIR="${NEWSROOM_DISPATCH_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/newsroom-dispatch}"
LOCK_FILE="$STATE_DIR/dispatcher.lock"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

for command_name in gh jq flock; do
  require_command "$command_name"
done

mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another dispatcher run is active; exiting."
  exit 0
fi

session_for() {
  case "$1" in
    reporter) echo "reporter" ;;
    copydesk) echo "copydesk" ;;
    factcheck) echo "factcheck" ;;
    *) return 1 ;;
  esac
}

dispatchable_issues() {
  gh issue list --repo "$REPOSITORY" --state open --limit 100 --json number,labels |
    jq -r '
      .[]
      | . as $issue
      | ([.labels[].name]) as $labels
      | ([$labels[] | select(startswith("status:"))]) as $statuses
      | ([$labels[] | select(startswith("agent:"))]) as $agents
      | select(($statuses | length) == 1 and ($agents | length) == 1)
      | if (($labels | index("status:ready")) and ($labels | index("agent:reporter"))) then
          [$issue.number, "reporter", "status:ready"]
        elif (($labels | index("status:in-review")) and ($labels | index("agent:copydesk"))) then
          [$issue.number, "copydesk", "status:in-review"]
        elif (($labels | index("status:in-test")) and ($labels | index("agent:factcheck"))) then
          [$issue.number, "factcheck", "status:in-test"]
        else empty end
      | @tsv
    '
}

while IFS=$'\t' read -r issue_number agent status; do
  [[ -n "${issue_number:-}" ]] || continue
  session="$(session_for "$agent")"
  state_file="$STATE_DIR/issue-${issue_number}-${agent}.state"
  signature="$status"

  if [[ -f "$state_file" ]] && [[ "$(<"$state_file")" == "$signature" ]]; then
    continue
  fi

  # Invoke the agent script directly
  agent_script="agents/scripts/${agent}_agent.py"
  if [[ ! -f "$agent_script" ]]; then
    echo "Error: Agent script '$agent_script' not found for $agent."
    continue
  fi

  echo "Invoking $agent agent script: $agent_script for PR #$issue_number"
  python "$agent_script" "$issue_number" &
  agent_pid=$!
  echo "Started $agent agent (PID: $agent_pid) for PR #$issue_number."

  # Mark only after agent is dispatched
  # timer runs from sending the same transition at once.
  temp_file="$state_file.tmp.$$"
  printf '%s\n' "$signature" >"$temp_file"
  mv -f "$temp_file" "$state_file"
  echo "Dispatched issue #$issue_number to $agent ($status)."
done < <(dispatchable_issues)
