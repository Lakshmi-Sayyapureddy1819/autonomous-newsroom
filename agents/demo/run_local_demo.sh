#!/bin/bash
set -euo pipefail

# Ensure gh CLI is available
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) not found. Please install it."
    exit 1
fi

# Ensure Python is available
if [ ! -f "C:/Users/Yasaswini/autonomous-newsroom/.venv/Scripts/python.exe" ]; then
    echo "Error: python3 not found. Please ensure it's in your PATH."
    exit 1
fi

REPO_ROOT=$(git rev-parse --show-toplevel)
DISPATCH_STATE_DIR="$REPO_ROOT/.local/newsroom-dispatch-state"
LOG_FILE="$DISPATCH_STATE_DIR/dispatcher.log"

mkdir -p "$DISPATCH_STATE_DIR/locks"
mkdir -p "$DISPATCH_STATE_DIR/logs"

echo "Dispatcher state directory: $DISPATCH_STATE_DIR"
echo "Logging dispatcher output to: $LOG_FILE"
echo "Starting dispatcher in a loop. Press Ctrl+C to stop."
echo "----------------------------------------------------"

export NEWSROOM_DISPATCH_STATE_DIR="$DISPATCH_STATE_DIR"
export NEWSROOM_REPO_DIR="$REPO_ROOT"
# Use deterministic review agents for local demo to simplify debugging
export NEWSROOM_REVIEW_MODE="deterministic"
export NEWSROOM_AGENT_TIMEOUT="180" # Shorter timeout for faster feedback

while true; do
    echo "$(date): Running dispatcher tick..." >> "$LOG_FILE"
    "C:/Users/Yasaswini/autonomous-newsroom/.venv/Scripts/python.exe" "$REPO_ROOT/agents/dispatcher/dispatch.py" >> "$LOG_FILE" 2>&1
    sleep 10 # Poll every 10 seconds
done
