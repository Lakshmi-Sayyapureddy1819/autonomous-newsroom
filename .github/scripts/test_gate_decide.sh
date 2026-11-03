#!/usr/bin/env bash
# Truth-table test for gate_decide.sh. Run: bash .github/scripts/test_gate_decide.sh
d="$(dirname "$0")"; fail=0
t() { exp=$1; shift; bash "$d/gate_decide.sh" "$@" >/dev/null; got=$?
  [ "$got" = "$exp" ] && echo "ok   exit=$got args: $*" || { echo "FAIL want=$exp got=$got args: $*"; fail=1; }; }
t 0 0 false false   # maintenance, no labels
t 0 0 true  true    # maintenance, labels irrelevant
t 1 1 false false   # newsroom, no labels
t 1 1 true  false   # newsroom, only review
t 1 1 false true    # newsroom, only test
t 0 1 true  true    # newsroom, both
t 1 2 false false   # multiple linked still enforced
t 1 ""  true true   # lookup failed -> fail closed
t 1 abc true true   # garbage -> fail closed
t 1 1 true  true  true   # both verdicts but a stale rejection label too -> blocked
t 0 1 true  true  false  # explicit no conflict -> pass
t 0 0 true  true  true   # maintenance PR ignores verdict labels entirely
exit $fail
