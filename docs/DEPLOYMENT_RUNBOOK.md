# Deployment runbook

Everything here is derived from the files in this repository (`infra/`, `deploy/`, `agents/`, `app/`). Nothing in this document has been run against a real OCI VM yet: commands marked **(unverified on a VM)** have only been checked by reading the scripts.

## 0. What is deployed

| Piece | Name | Details |
|---|---|---|
| Web app | `newsroom-web.service` | One FastAPI process (`uvicorn newsroom.main:app`) on `127.0.0.1:8000`. It serves the pages **and** the RSS feed; there is no separate frontend or backend service. |
| Reverse proxy | `caddy.service` | Ports 80/443 to `127.0.0.1:8000`. HTTPS for `<public-ip>.sslip.io` is automatic. |
| Refresh job | `newsroom-refresh.service` + `.timer` | Runs `newsroom.collector`, then `newsroom.summarizer`. First run 2 min after boot, then every 3 h. |
| Dispatcher | `dispatcher.service` + `.timer` | Runs `agents/dispatcher/dispatch.sh` every 5 min as user `newsroom-agent`. |
| Agents | Hermes (editor, copydesk), OpenClaw (reporter, factcheck) | Installed by `agents/bootstrap.sh`; credentials are manual. |

Routes (from `app/newsroom/main.py`): `GET /` (homepage, optional `?tag=&q=&page=`), `GET /rss.xml` (XML, or a styled page when the `Accept` header contains `text/html`; `?format=xml` forces XML), `GET /runs` (run log). Unknown paths return a JSON 404. **There is no `/health` endpoint**; use `/` for liveness.

Paths on the VM: app code `/opt/newsroom/app`, venv `/opt/newsroom/venv`, database `/var/lib/newsroom/newsroom.sqlite3`, secrets `/etc/newsroom.env`, agent checkout `/opt/newsroom-agent/repo`, dispatcher state `/var/lib/newsroom-agent/dispatcher`, optional dispatcher overrides `/etc/newsroom-agent.env`.

`infra/cloud-init.yaml` only installs base packages and enables SSH. **It does not install or start the app or the dispatcher.** Sections 4 to 7 are manual.

## 1. Prerequisites and credentials

You must supply these. Never commit them (`*.tfvars`, `.env`, `*.tfstate*` are gitignored).

- **OCI:** tenancy OCID, user OCID, API key fingerprint, private key file, home region, compartment OCID, and the OCID of a Canonical Ubuntu 24.04 **aarch64** image in that region.
- **SSH:** a keypair (`ssh-keygen -t ed25519`) and your public IP as a `/32` for `ssh_allowed_cidr`.
- **Model keys:** `NEWSROOM_LLM_API_KEY` and `NEWSROOM_FALLBACK_API_KEY` for the summarizer, plus provider keys for the Hermes/OpenClaw agents.
- **GitHub:** a fine-grained PAT scoped to this repository (Issues, Pull requests, Contents) for the agent user on the VM.
- **Local tools:** Terraform 1.6+ (or Docker), an SSH client, `uv` or Python 3.12 for tests.

## 2. Local checks before deploying

```bash
# From the repo root. Expect: all pass.
python -m pytest -q app/tests
python -m pytest -q agents/dispatcher/tests
ruff check app/                       # CI runs exactly this; expect "All checks passed!"
bash -n deploy/install.sh && bash -n agents/bootstrap.sh && bash -n agents/dispatcher/dispatch.sh
```

With `uv` (no global install): `uv run --project app --extra dev python -m pytest -q app/tests` and `uv run --project app --extra dev ruff check app/`.

Failure means: code or environment problem. Run the failing test alone with `-x -vv`.

## 3. Terraform and OCI provisioning

Install Terraform 1.6+ (https://developer.hashicorp.com/terraform/install), or use Docker:

```bash
terraform version
# Docker alternative (validation only, copy infra to a scratch dir first):
docker run --rm -v "$PWD/infra:/w" -w /w hashicorp/terraform:1.9 validate
```

Configure and validate:

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars     # edit every REPLACE_ME value
terraform -chdir=infra init
terraform -chdir=infra validate        # expect: Success! The configuration is valid.
terraform -chdir=infra fmt -check      # expect: no output
terraform -chdir=infra plan -out=tf.plan
```

Review the plan: it should create a VCN, internet gateway, route table, security list (22 from your CIDR only, 80/443 from anywhere), subnet and one `VM.Standard.A1.Flex` instance. Then:

```bash
terraform -chdir=infra apply tf.plan
terraform -chdir=infra output public_ip
terraform -chdir=infra output ssh_command
```

| Failure | Meaning | Next step |
|---|---|---|
| `401 NotAuthenticated` | Wrong user/tenancy OCID, fingerprint or key path | Re-check `terraform.tfvars` and the key file |
| `Out of host capacity` | No free A1 capacity | Retry later or review another availability domain |
| `shape/limit` errors | Requested size exceeds the Always Free allowance | Lower `instance_ocpus`, `instance_memory_gbs` or `instance_boot_volume_gbs` |

State is local (`infra/terraform.tfstate`); keep it, it is the only record of what to destroy.

## 4. Connect and install the app

```bash
ssh ubuntu@<public_ip>
cloud-init status --wait                 # expect: status: done
git clone https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom.git
cd autonomous-newsroom
sudo ./deploy/install.sh                 # auto-detects <ip>.sslip.io; or: sudo NEWSROOM_DOMAIN=:80 ./deploy/install.sh
```

Expected last line: `==> Done. Site: <something>`. The script is idempotent; re-run it to deploy a newer checkout. If it fails: `sudo bash -x ./deploy/install.sh 2>&1 | tail -40`.

Set secrets (the file is created root-owned, group `newsroom`, mode 0640; never overwritten by the installer):

```bash
sudoedit /etc/newsroom.env
```

Fill in `NEWSROOM_LLM_API_KEY=` and `NEWSROOM_FALLBACK_API_KEY=`. Optional settings (all appear commented in the file): `NEWSROOM_FEED_URL`, `NEWSROOM_SUMMARIZE_LIMIT`, `NEWSROOM_LLM_BASE_URL`, `NEWSROOM_LLM_MODEL`, `NEWSROOM_FALLBACK_BASE_URL`, `NEWSROOM_FALLBACK_MODEL`. Then:

```bash
sudo systemctl restart newsroom-web
sudo systemctl start newsroom-refresh.service      # collect and summarize now
```

Also confirm ports 80/443 are open in the OCI security list (Terraform does this) and in the image firewall (`install.sh` does this).

## 5. Install Hermes, OpenClaw and the agents

```bash
sudo ./agents/bootstrap.sh
sudo -iu newsroom-agent
gh auth login --with-token               # paste the PAT, then Ctrl-D
gh auth status                           # expect: Logged in to github.com
openclaw onboard                          # then register workspaces, see agents/openclaw/README.md
openclaw agents add ...                   # reporter and factcheck
hermes -p editor setup
hermes -p copydesk setup
exit
```

Credentials live in the agent user's home (`~/.openclaw`, `~/.hermes`), never in the repo. See `agents/openclaw/README.md`, `agents/hermes/README.md` and `agents/PROTOCOL.md`. **(unverified on a VM, including the OpenClaw/Hermes installer URLs)**

## 6. Install and enable the dispatcher

```bash
sudo install -m 0644 agents/dispatcher/dispatcher.service /etc/systemd/system/dispatcher.service
sudo install -m 0644 agents/dispatcher/dispatcher.timer   /etc/systemd/system/dispatcher.timer
sudo systemctl daemon-reload
sudo systemctl enable --now dispatcher.timer
sudo -u newsroom-agent bash /opt/newsroom-agent/repo/agents/dispatcher/dispatch.sh --dry-run
```

Expected: the dry run lists what it would do and exits 0, and `list-timers` (section 8) shows a next run. Optional tuning goes in `/etc/newsroom-agent.env`: `NEWSROOM_RETRY_BACKOFF`, `NEWSROOM_AGENT_TIMEOUT`, `NEWSROOM_STALE_MINUTES`, `NEWSROOM_MAX_TURNS`, `NEWSROOM_CMD_<AGENT>`, `NEWSROOM_HERMES_EXTRA_ARGS`, `NEWSROOM_OPENCLAW_EXTRA_ARGS`.

## 7. Start, stop and restart

```bash
sudo systemctl restart newsroom-web          # app
sudo systemctl reload-or-restart caddy       # proxy
sudo systemctl start newsroom-refresh.service  # run a refresh now
sudo systemctl stop newsroom-refresh.timer dispatcher.timer   # pause schedules (running jobs finish)
sudo systemctl start newsroom-refresh.timer dispatcher.timer  # resume
```

Stop in this order for maintenance: timers, then `newsroom-web`, then `caddy`. Start in reverse.

## 8. Status and logs

```bash
systemctl status newsroom-web caddy --no-pager
systemctl status newsroom-refresh.service dispatcher.service --no-pager
systemctl list-timers newsroom-refresh.timer dispatcher.timer     # expect a NEXT time for each
journalctl -u newsroom-web -n 100 --no-pager
journalctl -u newsroom-refresh -n 100 --no-pager
journalctl -u caddy -n 100 --no-pager
journalctl -u dispatcher -n 100 --no-pager
journalctl -u dispatcher -f                                       # follow
```

## 9. Website, frontend, backend and RSS

Replace `<site>` with the host printed by `install.sh` (for example `1.2.3.4.sslip.io`).

| What | Command | Expected | If it fails |
|---|---|---|---|
| App direct (on the VM) | `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/` | `200` | `journalctl -u newsroom-web -n 50`; check `/etc/newsroom.env` and DB permissions |
| Public URL | `curl -sI https://<site>/ \| head -1` | `HTTP/2 200` | `journalctl -u caddy -n 50`; check OCI security list and `sudo iptables -L INPUT -n \| grep -E '80\|443'` |
| Homepage content | `curl -s https://<site>/ \| grep -c '<article'` | A number above 0 once stories exist; before that an empty-state page with status 200 | Check `/runs` for failed refreshes |
| RSS XML | `curl -s 'https://<site>/rss.xml?format=xml' \| head -8` | `<rss version="2.0">` and a channel `<link>` with the **public** host, not localhost | Check the Caddy proxy headers and `rss.xml` base URL |
| RSS content type | `curl -sI https://<site>/rss.xml \| grep -i content-type` | `application/xml; charset=utf-8` | |
| Run log page | `curl -s -o /dev/null -w '%{http_code}\n' https://<site>/runs` | `200` | |
| Error handling | `curl -s -o /dev/null -w '%{http_code}\n' https://<site>/nope` | `404` | |

Visual check: open `https://<site>/` on a desktop and a phone. The page should render with styling, with no console errors. Do not edit templates to fix a visual issue found here; report it instead.

## 10. Database, collector and summarizer

```bash
journalctl -u newsroom-refresh -n 50 --no-pager      # collector then summarizer; look for errors/HTTP 402/429
sudo -u newsroom /opt/newsroom/venv/bin/python - <<'PY'
import os, sqlite3
c = sqlite3.connect("/var/lib/newsroom/newsroom.sqlite3")
print("articles:", c.execute("select count(*), sum(summary is not null) from articles").fetchone())
for r in c.execute("select started_at, status, fetched, inserted, summarized, error from runs order by id desc limit 5"):
    print(r)
PY
```

Expected after the first refresh: `articles` count above 0, and the latest runs show `success`. Summaries stay pending if the API keys are blank or both providers fail (the articles remain retryable). If runs fail, read the sanitized `error` column and the journal.

## 11. Dispatcher and agent workflow

```bash
systemctl list-timers dispatcher.timer
journalctl -u dispatcher -n 50 --no-pager
sudo -u newsroom-agent bash /opt/newsroom-agent/repo/agents/dispatcher/dispatch.sh --dry-run
sudo -u newsroom-agent gh issue list --repo Lakshmi-Sayyapureddy1819/autonomous-newsroom --state open
ls /var/lib/newsroom-agent/dispatcher                 # per-ticket JSON state, per-agent locks, logs
```

The workflow is verified only when an Issue with `status:ready` + `agent:reporter` moves through reporter, copydesk and factcheck via labels and PR comments. Until that has happened on the VM, do not claim the live loop works. Backing off on HTTP 429 is expected on free tiers (see `agents/traces/t4-dispatcher-429.md` once committed).

## 12. Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| `newsroom-web` crash loops | Missing venv or env file, DB not writable | `journalctl -u newsroom-web -n 50`; re-run `sudo ./deploy/install.sh` |
| Site down but app up | Caddy or firewall | `systemctl status caddy`; open 80/443 in OCI and iptables |
| No HTTPS certificate | Port 80/443 blocked or DNS not resolving | `journalctl -u caddy`; use `NEWSROOM_DOMAIN=:80` for plain HTTP |
| Stories but no summaries | Empty keys or quota exhausted | Edit `/etc/newsroom.env`, restart, run refresh; check for 402/429 |
| Dispatcher does nothing | `gh` not authenticated as `newsroom-agent`, or no actionable labels | `sudo -u newsroom-agent gh auth status`; run with `--dry-run` |
| Dispatcher backing off | 3-strike retry or 429 | Read the per-ticket JSON in the state dir; raise `NEWSROOM_RETRY_BACKOFF` or change model args |
| Agent command not found | Installer not completed | `sudo -u newsroom-agent bash -lc 'command -v hermes openclaw'` |

## 13. Rollback and recovery

```bash
# Back up the database first.
sudo systemctl stop newsroom-web
sudo cp /var/lib/newsroom/newsroom.sqlite3 /var/lib/newsroom/newsroom.sqlite3.bak
# Roll the code back to a known-good commit and redeploy.
cd ~/autonomous-newsroom && git checkout <good-sha> && sudo ./deploy/install.sh
sudo systemctl start newsroom-web
```

`/etc/newsroom.env` and the database are preserved by `install.sh`. To pause the agents without losing state: `sudo systemctl disable --now dispatcher.timer` (move, do not delete, `/var/lib/newsroom-agent/dispatcher`).

## 14. Cleanup

```bash
sudo systemctl disable --now newsroom-refresh.timer dispatcher.timer newsroom-web
terraform -chdir=infra plan -destroy        # review
terraform -chdir=infra destroy
```

Revoke the GitHub PAT, rotate model keys, and delete the OCI API key if it was created only for this project.
