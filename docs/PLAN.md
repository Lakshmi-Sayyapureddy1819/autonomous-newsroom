# Autonomous Newsroom — Plan

Source brief: `Confer_Autonomous_Newsroom_Assignment.pdf` (Confer Inc. AI/ML take-home).
GitHub repo: [Lakshmi-Sayyapureddy1819/autonomous-newsroom](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom) (public).
**Git author identity (only):** `Lakshmi Sayyapureddy` `<142775745+Lakshmi-Sayyapureddy1819@users.noreply.github.com>`

Scoring is 70/100 on agent team design, delivery evidence, and models/tokens; 15 on Terraform/reproducibility; **10 on "it runs"**; 5 on an honest write-up. Favour a clean, inspectable agent trail over product features.

**Rules we must not break**

- Agents write all product code (`app/`, `deploy/`). Humans (with AI help) write only bootstrap: `infra/`, `agents/`, `.github/`, this plan, and later `DELIVERY.md`.
- The **editor** (orchestrator) writes GitHub Issues from the brief. Section 6 is the quality bar for those Issues — **do not paste it into GitHub and do not pre-create product tickets.**
- Free stack only. No secrets, keys, tfstate, or personal data in git.
- Every git commit uses Lakshmi's GitHub identity as **Author**. Prove which agent acted with `Co-authored-by` plus `Agent` / `Runtime` / `Model` / `Ticket` trailers (the brief allows this). Do not invent extra GitHub users.
- Ollama Cloud free plan = 1 concurrent request. Do not run two Ollama calls at once (including product summarizer vs an agent).

---

## 1. Architecture

```
                     ┌──────────── Oracle A1 VM (2 OCPU / 12 GB, Ubuntu 24.04 arm64) — Terraform ────────────┐
                     │                                                                                        │
  PRODUCT            │  systemd timer (~every 3h) ──► collector ──► summarizer ──► SQLite                    │
                     │                                 │             │ primary free model, fallback on 402/429 │
                     │                     Google News RSS                                                    │
                     │                                               ▼                                        │
  Internet ──► Caddy :80/:443 ──► FastAPI (127.0.0.1:8000) ── reads SQLite                                    │
                     │                                                                                        │
  AGENT TEAM         │  Hermes: editor, copydesk          OpenClaw: reporter, factcheck                       │
                     │  dashboards: localhost only, opened via SSH tunnel from your laptop                    │
                     │        ▲                                      ▲                                        │
                     │        └──── dispatcher (systemd timer, shell, no LLM) ────┘                           │
                     │                         polls GitHub labels, wakes the owning agent                    │
                     └─────────────────────────┼──────────────────────────────────────────────────────────────┘
                                               ▼
                         GitHub: Issues · PRs · labels (state) · Actions (ci + gate)
```

- **SQLite** — allowed; saves RAM for OpenClaw + Hermes on 12 GB.
- **Product refresh is ordinary code on a systemd timer** — required core. Running the collector as a Hermes/OpenClaw cron job is a plus only if the core trail is already solid.
- **Server-rendered HTML** — no JS build for agents to break.
- **Public URL: Caddy + `<public-ip>.sslip.io`**. If HTTPS or ports fight you, **cloudflared Quick Tunnel** is an allowed fallback (URL may change on restart; say so in `DELIVERY.md`).
- **Local vs VM split** — Ticket 0 smoke test runs locally using existing local Hermes and OpenClaw installations to validate the agent orchestration loop, git trailers, and GitHub CI gates. Product implementation (T1–T5) and final serving live on the OCI VM provisioned via Terraform.

Two systems, do not mix them: the **agent team** ships the product through GitHub; the **product** may call free models from plain code.

## 2. Agent roster

Keep four roles on two runtimes so every handoff crosses OpenClaw ↔ Hermes and therefore **must** go through GitHub.

| Agent | Runtime | Role | Model (confirm on Day 1; stay configurable) | Tools |
|---|---|---|---|---|
| **editor** | Hermes profile | Orchestrator | Strongest available (planning; low volume) | `gh` issues, comments, labels. No `app/` edits, no merge. |
| **reporter** | OpenClaw (`agents add`) | Builder | Coding model (Qwen3-Coder class or similar) via OpenRouter `:free` or Ollama | git + `gh` in one worktree, shell, files. No merge. |
| **copydesk** | Hermes profile | Reviewer | Different family from builder (e.g. Gemini Flash free) | `gh pr diff`, comments, labels. No push, no merge. |
| **factcheck** | OpenClaw | Tester | Cheap/fast (e.g. Groq) | Checkout PR branch; pytest, curl, sqlite3. Comment + labels. No push, no merge. |
| **human** (Lakshmi) | — | Merge + unblock | — | Merge, `status:blocked`, secrets, Terraform apply. |

Why this split:

- Inspectable handoffs (the 30-point orchestration score).
- Different builder vs reviewer model families.
- Token attribution: OpenClaw `/usage` + `openclaw.tokens`, Hermes `hermes insights` / Analytics, Ollama usage page. Optional: separate OpenRouter keys if you already have them — **not required**.
- Product summarizer uses env-configured primary/fallback so it does not steal the single Ollama slot from daytime agent work.

Do **not** use Hermes `delegate_task` (or any in-process handoff) for builder / review / test. GitHub is the only channel between agents.

## 3. Ticket workflow

See [`agents/PROTOCOL.md`](../agents/PROTOCOL.md) for labels, handoff comments, Lakshmi-only commits, trailers, and the review/test **gate**.

## 4. Stack (all free)

| Layer | Choice |
|---|---|
| VM / IaC | OCI Always Free **2 OCPU / 12 GB** (`VM.Standard.A1.Flex`), Ubuntu 24.04 **aarch64**, home region. Terraform or OpenTofu, `oracle/oci`, **local state**. Start from Oracle `examples/always_free`, trim to **one instance, no load balancer, no DB**. `shape_config` required. Do not pin a fault domain. |
| Product | Python 3.12, FastAPI + Jinja2, `feedparser`, `httpx`, OpenAI-compatible client, pytest, ruff |
| Data | SQLite (WAL). `articles` + `runs` is enough. |
| Source | One public feed: Google News RSS (e.g. `q=artificial intelligence`). No paid key, no personal data. |
| Summarizer | Env: `*_BASE_URL`, `*_MODEL`, `*_API_KEY`. Summarize each article **once**, store it, fallback on HTTP 402/429. |
| Serving | Caddy on 80/443 (remember Ubuntu image iptables). Fallback: cloudflared Quick Tunnel. |
| Tickets / CI | GitHub Issues, labels, PRs, Actions. |
| Observability | OpenClaw `/usage` + OTel `openclaw.tokens`; `hermes insights`; Ollama usage page; token lines on every handoff comment. gitleaks in CI. Do **not** self-host Langfuse on the VM. |
| Agent Node | OpenClaw needs Node **24.16+ or 26.1+**. Hermes via its `install.sh`. Dashboards bound to localhost; you SSH-tunnel to them. |

Python because free coding models handle it more reliably. Node is on the VM for OpenClaw anyway.

**Capacity:** if "Out of host capacity", try another AD, drop to 1 OCPU / 6 GB, retry later. Plan B: AWS Free (`m7i-flex.large`). Emergency: this machine (8 GB+) + Quick Tunnel, explained in `DELIVERY.md`. A card is required for OCI identity; stay inside Always Free.

## 5. Repository structure (target)

```
autonomous-newsroom/
├── DELIVERY.md                  # human, end of week
├── README.md
├── app/                         # product: agents only
│   ├── newsroom/  tests/  pyproject.toml
├── deploy/                      # agents (deploy ticket)
│   ├── install.sh  Caddyfile  systemd/
├── infra/                       # human bootstrap
│   ├── main.tf variables.tf outputs.tf versions.tf cloud-init.yaml
│   └── terraform.tfvars.example     # never commit terraform.tfvars / *.tfstate
├── agents/
│   ├── PROTOCOL.md
│   ├── openclaw/  *.example.json  reporter/  factcheck/
│   ├── hermes/    profiles/editor/  profiles/copydesk/
│   ├── dispatcher/  dispatch.sh  dispatcher.timer
│   ├── bootstrap.sh
│   └── traces/                  # exported logs, secrets scrubbed
├── docs/  PLAN.md  brief.md  token-report.md
└── .github/  ISSUE_TEMPLATE/  pull_request_template.md  workflows/ci.yml  workflows/gate.yml
```

`.gitignore` must cover: `.tfstate*`, `*.tfvars` (keep `*.tfvars.example`), `.env`, API keys, agent runtime data, `node_modules/`.

Human Day-1 bootstrap may add `docs/brief.md`: **product requirements only** (page, summary, tag, source, schedule, DB, "updated X ago") — not a ticket list.

## 6. Quality bar for the editor's tickets (not to paste)

Editor turns `docs/brief.md` + the PDF into Issues with Goal, Acceptance criteria, Out of scope, Depends on. Aim for **five** small tickets matching the brief's examples. Outcome-level, checkable, not line-by-line code.

**T0 — smoke the loop (editor's first Issue, tiny):** e.g. README paragraph naming the four agents. Proves claim → PR → review → test → human merge **before** real product work.

**T1 — Scaffold app, schema, CI:** installable Python package; `articles` and `runs` tables; idempotent DB init; `pytest` + `ruff` on the PR.

**T2 — RSS collector:** fetch the configured public feed; store title, url, source, published time; upsert by URL; write a `runs` row; errors recorded, no crash; tests use a saved fixture (no network in CI).

**T3 — Summarizer with fallback:** only rows with no summary; one-line summary + one tag; HTTP 402/429 → other free model; both fail → leave NULL, mark run partial; cap per run (e.g. 20); store which model answered; test mocks 429 and asserts fallback.

**T4 — Public list page:** `GET /` shows recent articles with source link, summary or "Summary pending", tag, and footer **"updated X ago"** from last successful run; empty state if no rows. Tester proves the page, not a health JSON.

**T5 — Schedule + deploy:** idempotent `deploy/install.sh` on Ubuntu 24.04 arm64; app on 127.0.0.1:8000; Caddy 80/443; open image iptables; timer every few hours + once at boot; secrets only in `/etc/newsroom.env`; gitleaks clean. Tester: public URL shows several articles and "updated … ago"; timer is active.

**Out of scope unless the core trail is already mergeable:** tag filters, search, extra sources, dedupe, runs page, Hermes-cron collector.

## 7. Schedule (start today)

| Day | Goal |
|---|---|
| **1 (today)** | **Phase 1 (Local T0 Smoke Test):** Set repo identity to Lakshmi; GitHub labels, PAT, `ci.yml` + `gate.yml`, branch protection; configure local Hermes & OpenClaw agents; run manual/shell dispatch; Editor writes **T0** (README update) and agents complete the full PR/review/test loop locally.<br>**Phase 2 (Cloud Infra):** Terraform OCI A1 VM (or AWS fallback); install runtimes via `bootstrap.sh`; set up systemd timers (dispatcher + refresh). Ready for product tickets on Day 2. |
| **2** | Editor writes T1–T5 from the brief (not from a pasted spec). Flow T1–T3. Export usage as you go. |
| **3** | T4–T5; public URL loads. |
| **4** | Only if the trail is clean: one stretch **or** fixes. Capture one real rejection/retry (do not fake it; T3 often produces one). |
| **5** | `DELIVERY.md`, token report, scrubbed traces, optional 3–5 min recording, rehearse a **small live change** for the call. Keep the URL up ~a week. |

## 8. What you hand over (must match the brief)

Reply with: **live URL** + **this repo** + **`DELIVERY.md`**.

`DELIVERY.md` must include:

- Roster: name, runtime, role, model, tools (and why this split).
- Diagram: ticket from idea → merged code (same as the protocol).
- What each agent actually did.
- One thing that broke and how review/test/you caught it.
- What you would change.
- **Token & model report** (here or `docs/token-report.md`): tokens per agent and per model, split into planning / coding / review-test / retries; plain-language where they went. Estimates OK if labelled as estimates.
- Trace excerpts: real log/comment lines for a handoff **and** a rejection or retry.
- Reproduce: `terraform apply` then `agents/bootstrap.sh` then `deploy/install.sh`.
- How to open agent dashboards (SSH tunnel to localhost).

Repo must contain: agent-written product, `infra/` Terraform, `agents/` configs/prompts/skills with secrets removed, and the GitHub ticket/PR trail.

Public repo is enough; inviting `Shrikanth-Confer` is optional.

## 9. Day-1 human bootstrap (no product tickets, no product code)

**Phase 1: Local Setup & Ticket 0 Smoke Test (validate agent loop before cloud infra)**
1. Confirm local `git` / `gh` act as **Lakshmi Sayyapureddy** (`142775745+Lakshmi-Sayyapureddy1819@users.noreply.github.com`).
2. Create a **fine-grained PAT** as Lakshmi scoped strictly to this repo: Contents (read/write), Issues (read/write), Pull requests (read/write). No Administration. Note: GitHub's Pull requests: write scope technically includes API merge capability; agents are forbidden by instruction from merging, and `main` is protected so only Lakshmi merges via the GitHub UI after checks pass.
3. Create GitHub labels from PROTOCOL. Add `.github/workflows/ci.yml` (trailer check, lint, tests) and `gate.yml` (requires `review:approved` and `test:passed`). Configure branch protection on `main`.
4. Configure local Hermes profiles (`editor`, `copydesk`) and OpenClaw agents (`reporter`, `factcheck`) referencing `agents/PROTOCOL.md`.
5. Execute **Ticket 0** locally: Editor writes Issue #1 (smoke test README update); Reporter claims, branches, commits with trailers, opens PR; CI passes; Copydesk reviews and approves; Factcheck tests and passes; Lakshmi merges via GitHub UI. Dispatched manually or via shell script.

**Phase 2: Cloud Infrastructure & VM Setup (target runtime for T1–T5)**
6. Provision OCI Always Free A1 VM with Terraform (`infra/main.tf`); keep state and `.tfvars` out of git. (Fallback to AWS Free Tier if capacity unavailable).
7. Run `agents/bootstrap.sh` on the VM to install OpenClaw and Hermes, copy configs and PROTOCOL.
8. Set up `agents/dispatcher/dispatcher.timer` systemd unit on the VM.
9. Write `docs/brief.md` (requirements only: page, summary, tag, source, schedule, DB, "updated X ago"). Then **stop**. Editor creates product Issues (T1–T5) on Day 2.

## 10. Risks

1. **Token burn** — retry cap 3, dispatcher wakes only the labelled agent and only if it is not already running, max turns per invocation.
2. **No A1 capacity** — provision immediately; AWS then laptop + tunnel.
3. **Same GitHub user for every comment** — expected. The inspectable trail is labels + handoff comments + trailers, not four GitHub accounts.
4. **Secrets in exports** — `*.example` only; gitleaks; scrub `agents/traces/`.
5. **Idle VM reclaimed after 7 days** — keep the refresh timer (and a light heartbeat) running.
6. **No rejection in the trail** — do not stage a fake one. If none happens, say so honestly in `DELIVERY.md`.
