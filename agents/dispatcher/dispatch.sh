#!/usr/bin/env bash
# Thin entry point for the systemd timer / manual runs. All logic is in dispatch.py
# (no LLM, no assignment decisions). Pass --dry-run to see what would happen.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for candidate in "${PYTHON:-}" python3 python; do
  [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1 && exec "$candidate" "$here/dispatch.py" "$@"
done
echo "Python 3 not found" >&2
exit 1
