#!/usr/bin/env bash
# Pure gate decision. Usage: gate_decide.sh <linked_issue_count> <has_review> <has_test> [has_conflict]
#   linked_issue_count: number of Issues the PR closes ("Closes #N"); must be an integer.
#   has_review / has_test: "true" if review:approved / test:passed is on the PR.
# Newsroom PR (>=1 linked Issue): both labels required.
#   has_conflict: "true" if review:changes-requested or test:failed is ALSO on the PR (a
#   stale rejection next to an approval); it blocks a newsroom PR. Optional, default "false".
# Maintenance PR (0 linked Issues): verdict labels not applicable.
# Anything unparseable fails closed.
set -u
linked="${1:-}"; has_review="${2:-}"; has_test="${3:-}"; has_conflict="${4:-false}"

case "$linked" in
  ''|*[!0-9]*) echo "GATE BLOCKED: could not determine linked Issues (got '${linked}')."; exit 1 ;;
esac

if [ "$linked" -eq 0 ]; then
  echo "GATE PASSED: maintenance PR (closes no Issue); verdict labels not required."
  exit 0
fi

echo "Newsroom PR (closes ${linked} Issue(s)); verdict labels required."
if [ "$has_conflict" = "true" ]; then
  echo "GATE BLOCKED: review:changes-requested and/or test:failed is still on the PR."
  exit 1
fi
if [ "$has_review" = "true" ] && [ "$has_test" = "true" ]; then
  echo "GATE PASSED: Both review:approved and test:passed labels are present on PR."
  exit 0
fi
echo "GATE BLOCKED: Missing required verdict labels."
[ "$has_review" = "true" ] || echo "  - Missing: review:approved (must be set by Copydesk)"
[ "$has_test" = "true" ] || echo "  - Missing: test:passed (must be set by Factcheck)"
exit 1
