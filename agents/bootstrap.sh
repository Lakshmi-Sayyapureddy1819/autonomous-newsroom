#!/usr/bin/env bash
set -euo pipefail

# Install the agent runtimes and stage the role prompts on an Ubuntu 24.04 VM.
# Provider credentials and GitHub authentication remain a separate, local setup step.
AGENT_USER="newsroom-agent"
AGENT_HOME="/home/$AGENT_USER"
INSTALL_ROOT="/opt/newsroom-agent"
REPOSITORY_URL="${NEWSROOM_REPOSITORY_URL:-https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom.git}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -f /etc/os-release ]] || ! . /etc/os-release || [[ "${ID:-}" != "ubuntu" ]]; then
  echo "This bootstrap currently supports Ubuntu only." >&2
  exit 1
fi

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  ca-certificates curl git jq tmux rsync util-linux

if ! id -u "$AGENT_USER" >/dev/null 2>&1; then
  useradd --create-home --home-dir "$AGENT_HOME" --shell /bin/bash "$AGENT_USER"
fi
install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 0750 \
  "$INSTALL_ROOT" \
  "$INSTALL_ROOT/workspaces/editor" \
  "$INSTALL_ROOT/workspaces/copydesk" \
  "$AGENT_HOME/.openclaw/workspaces/reporter" \
  "$AGENT_HOME/.openclaw/workspaces/factcheck" \
  "$AGENT_HOME/.local/state/newsroom-dispatch" \
  /var/lib/newsroom-agent/dispatcher

if [[ ! -d "$INSTALL_ROOT/repo/.git" ]]; then
  runuser -u "$AGENT_USER" -- git clone "$REPOSITORY_URL" "$INSTALL_ROOT/repo"
fi

stage_if_missing() {
  local source="$1" target="$2"
  if [[ ! -e "$target" ]]; then
    install -o "$AGENT_USER" -g "$AGENT_USER" -m 0640 "$source" "$target"
  else
    echo "Preserving existing local file: $target"
  fi
}

for role in editor copydesk; do
  if [[ ! -d "$INSTALL_ROOT/workspaces/$role/repo/.git" ]]; then
    runuser -u "$AGENT_USER" -- git clone "$INSTALL_ROOT/repo" \
      "$INSTALL_ROOT/workspaces/$role/repo"
  fi
done
for role in reporter factcheck; do
  if [[ ! -d "$AGENT_HOME/.openclaw/workspaces/$role/repo/.git" ]]; then
    runuser -u "$AGENT_USER" -- git clone "$INSTALL_ROOT/repo" \
      "$AGENT_HOME/.openclaw/workspaces/$role/repo"
  fi
done

stage_if_missing "$INSTALL_ROOT/repo/agents/openclaw/reporter/AGENTS.md" \
  "$AGENT_HOME/.openclaw/workspaces/reporter/AGENTS.md"
stage_if_missing "$INSTALL_ROOT/repo/agents/openclaw/factcheck/AGENTS.md" \
  "$AGENT_HOME/.openclaw/workspaces/factcheck/AGENTS.md"

if ! runuser -u "$AGENT_USER" -- env HOME="$AGENT_HOME" PATH="$AGENT_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" \
  bash -c 'command -v openclaw >/dev/null 2>&1'; then
  runuser -u "$AGENT_USER" -- env HOME="$AGENT_HOME" bash -c \
    'curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard'
fi

if ! runuser -u "$AGENT_USER" -- env HOME="$AGENT_HOME" PATH="$AGENT_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" \
  bash -c 'command -v hermes >/dev/null 2>&1'; then
  runuser -u "$AGENT_USER" -- env HOME="$AGENT_HOME" bash -c \
    'curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash'
fi

HERMES_BIN="$AGENT_HOME/.local/bin/hermes"
if [[ -x "$HERMES_BIN" ]]; then
  for role in editor copydesk; do
    if [[ ! -d "$AGENT_HOME/.hermes/profiles/$role" ]]; then
      runuser -u "$AGENT_USER" -- env HOME="$AGENT_HOME" HERMES_HOME="$AGENT_HOME/.hermes" \
        PATH="$AGENT_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" \
        "$HERMES_BIN" profile create "$role" --no-alias \
          --description "Autonomous Newsroom $role role; follow agents/PROTOCOL.md."
    fi
    stage_if_missing "$INSTALL_ROOT/repo/agents/hermes/profiles/$role/SOUL.md" \
      "$AGENT_HOME/.hermes/profiles/$role/SOUL.md"
  done
fi

for owned_path in "$INSTALL_ROOT" "$AGENT_HOME/.openclaw" "$AGENT_HOME/.hermes" /var/lib/newsroom-agent; do
  if [[ -e "$owned_path" ]]; then
    chown -R "$AGENT_USER:$AGENT_USER" "$owned_path"
  fi
done

cat <<'NEXT'
Agent runtimes are staged. Complete these account-specific steps as newsroom-agent:
  1. Authenticate `gh` for the repository using a limited-scope PAT; do not save it in this repo.
  2. Finish OpenClaw onboarding, set local model credentials, and register the reporter/factcheck workspaces with `openclaw agents add`.
  3. Run `hermes -p editor setup` and `hermes -p copydesk setup` to set each profile's model credentials.
  4. Start one tmux session for each configured agent using the role's supported CLI.
  5. Install dispatcher.service and dispatcher.timer into /etc/systemd/system, then enable the timer.
NEXT
