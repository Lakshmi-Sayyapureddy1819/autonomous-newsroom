#!/usr/bin/env bash
# Idempotent installer for the Autonomous Newsroom on Ubuntu 24.04 (arm64 or amd64).
#
#   sudo ./deploy/install.sh                       # auto-detect <public-ip>.sslip.io
#   sudo NEWSROOM_DOMAIN=news.example.com ./deploy/install.sh
#   sudo NEWSROOM_DOMAIN=:80 ./deploy/install.sh   # plain HTTP, no certificate
#
# Re-running is safe: packages, user, venv, units and firewall rules are only changed
# when needed, and /etc/newsroom.env (the only place for secrets) is never overwritten.
set -euo pipefail

APP_USER=newsroom
APP_DIR=/opt/newsroom
DATA_DIR=/var/lib/newsroom
ENV_FILE=/etc/newsroom.env
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '==> %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

log "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip rsync curl caddy \
  iptables iptables-persistent

log "Creating service user and directories"
id -u "$APP_USER" >/dev/null 2>&1 ||
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$DATA_DIR"
install -d -m 0755 "$APP_DIR"

log "Syncing application code to $APP_DIR/app"
rsync -a --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.ruff_cache' --exclude '*.egg-info' --exclude '*.sqlite3*' \
  "$REPO_DIR/app/" "$APP_DIR/app/"

log "Installing Python environment"
[[ -x "$APP_DIR/venv/bin/python" ]] || python3 -m venv "$APP_DIR/venv"
# Editable install: templates are loaded relative to the source files.
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -e "$APP_DIR/app"

log "Ensuring $ENV_FILE exists (secrets live only here)"
if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  cat >"$ENV_FILE" <<ENV
# Autonomous Newsroom runtime configuration. Readable by root and the newsroom service
# only; never commit this file.
NEWSROOM_DB=$DATA_DIR/newsroom.sqlite3
# NEWSROOM_FEED_URL=
# NEWSROOM_SUMMARIZE_LIMIT=20

# Primary summarizer model (OpenAI-compatible).
# NEWSROOM_LLM_BASE_URL=https://openrouter.ai/api/v1
# NEWSROOM_LLM_MODEL=openrouter/free
NEWSROOM_LLM_API_KEY=

# Fallback model, used on HTTP 402/429 from the primary.
# NEWSROOM_FALLBACK_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# NEWSROOM_FALLBACK_MODEL=gemini-2.5-flash
NEWSROOM_FALLBACK_API_KEY=
ENV
fi
chown root:"$APP_USER" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

log "Initializing database"
runuser -u "$APP_USER" -- env "$(grep -E '^NEWSROOM_DB=' "$ENV_FILE")" \
  "$APP_DIR/venv/bin/python" -m newsroom.db init

log "Installing systemd units"
for unit in newsroom-web.service newsroom-refresh.service newsroom-refresh.timer; do
  install -m 0644 "$REPO_DIR/deploy/systemd/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable newsroom-web.service newsroom-refresh.timer >/dev/null
systemctl restart newsroom-web.service
# Start the timer (it fires once shortly after boot, then every 3h after each run).
systemctl start newsroom-refresh.timer

log "Configuring Caddy"
SITE="${NEWSROOM_DOMAIN:-}"
if [[ -z "$SITE" ]]; then
  PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
  if [[ "$PUBLIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SITE="${PUBLIC_IP}.sslip.io"
  else
    SITE=":80"
    echo "Could not detect a public IP; serving plain HTTP on :80." >&2
  fi
fi
sed "s|__SITE__|$SITE|" "$REPO_DIR/deploy/Caddyfile" >/etc/caddy/Caddyfile
systemctl enable caddy >/dev/null
systemctl reload-or-restart caddy

log "Opening ports 80/443 in the image firewall"
# Ubuntu images on Oracle Cloud ship an INPUT REJECT rule; insert ACCEPTs before it.
for port in 80 443; do
  iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null ||
    iptables -I INPUT -p tcp --dport "$port" -j ACCEPT
done
netfilter-persistent save >/dev/null

log "Done. Site: $SITE"
echo "Set API keys in $ENV_FILE, then: sudo systemctl start newsroom-refresh.service"
echo "Remember to also open ports 80/443 in the cloud provider's security list."
