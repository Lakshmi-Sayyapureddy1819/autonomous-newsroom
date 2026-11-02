# Token Usage Audit — Autonomous Newsroom

**Scope:** Hermes Agent (editor, copydesk) and OpenClaw (reporter, factcheck).
**Method:** read-only inspection of the local runtime databases, CLI help and `hermes insights`.
**Not done:** no agent was run, no model call was made, nothing was modified. Databases were opened with SQLite `mode=ro`.
**Machine time zone:** India Standard Time (IST). Dates below are local IST unless marked UTC.

**Evidence labels used in this document**

| Label | Meaning |
|---|---|
| **Runtime-reported** | Counts stored by Hermes or OpenClaw in its own session store. Provider-reported counts passed through by the runtime. |
| **Provider-reported** | Token counts the model API returned in its response. Both runtimes appear to store these. I did not capture raw API responses, so I label them runtime-reported. |
| **Estimated** | Written by an agent or by a pricing table. Not measured. |
| **Unavailable** | Not stored anywhere I found. |
| ✅ Verified | I ran or read it myself. |
| 💡 Proposed | My design suggestion. Not implemented. |

---

## 1. Executive summary

1. **The token report in the repo is incomplete and does not match the runtime records.**
   - `docs/token-report.md` has only a few thousand estimated tokens, copied from agent handoff comments.
   - Both runtimes actually stored **per-call token counts**, in the millions.
   - The repo's report was built from agent self-estimates. The dispatcher never captured the runtimes' own counters.
2. **Most of the missing data can still be recovered**, because both runtimes keep it locally.
   - **Hermes** keeps per-session and per-model counts in `state.db` (input, output, cache-read, cache-write, reasoning tokens, and an estimated cost).
   - **OpenClaw** keeps a `usage` object on every assistant message in its transcripts (`input`, `output`, `cacheRead`, `cacheWrite`, `totalTokens`, `cost`).
3. **Linking usage to tickets works for some runs and not others.**
   - OpenClaw dispatcher runs are named `newsroom-reporter-<issue>-<epoch>`. That epoch matches the dispatcher log file name, so those runs tie directly to Issue #12 and #14.
   - Hermes copydesk/editor sessions tie to tickets through the session title and first prompt.
   - Long-running default sessions (`agent:reporter:main`, Hermes interactive sessions) mix many tickets and cannot be split by ticket without time correlation.
4. **Some usage genuinely cannot be recovered.**
   - Hermes calls that failed with HTTP 429 before any response recorded **0 tokens**.
   - The earliest ticket-creation and review work (T0–T2 editor/copydesk, T2/T3 factcheck) has **no matching session** in the databases I inspected.
   - Three OpenClaw reporter sessions were deleted, but archived copies survive in the database (see §6).
5. **One label in the repo is contradicted by the runtime records.** Commit trailers and `docs/token-report.md` name `qwen-2.5-coder-32b` for the reporter. That model does **not** appear in any OpenClaw per-message record or Hermes session I inspected.
6. **Best honest statement for the interview:** "The report in the repo is estimates from handoff comments. I later found the runtimes had stored real usage. I have audited it, but I have not yet replaced the report with a verified, per-ticket export."

---

## 2. The token-reporting gap

### 2.1 What the protocol asked for
`agents/PROTOCOL.md` ("Token tracking") says: after each invocation persist usage (`OpenClaw /usage` or OTel `openclaw.tokens`; Hermes `hermes insights`), put numbers on the handoff comment, and export a per-agent / per-model split into `DELIVERY.md` or `docs/token-report.md`. Handoff comments say `Tokens: prompt=<n> completion=<n> model=<id> (estimate OK, say so)`.

### 2.2 What actually happened (✅ verified in the repo)
- `agents/dispatcher/dispatch.py` builds the agent commands without any usage capture:
  - OpenClaw: `openclaw agent --agent <name> --message ... --timeout ...`. It does **not** pass `--json`.
  - Hermes: `hermes -p <agent> chat -q ... --oneshot --max-turns ...`. It does **not** pass `--usage-file`.
- So no usage was saved at the moment each run finished.
- The numbers in handoff comments were written by the agents themselves. They often cannot see their own usage, so many say "estimate" or give nothing (`DELIVERY.md`, `docs/token-report.md`).
- `docs/token-report.md` therefore holds only the handful of numbers that agents typed.

### 2.3 Why the gap matters for grading
The assignment asks for "tokens per agent and per model, split into planning, coding, review/test and retries, and in plain words where the tokens went" (15 points for models, tokens and observability). The repo's report cannot answer that. The runtime data can, once cleaned up.

### 2.4 Mismatch between the repo's estimates and the runtime records

| Source | Reporter figure |
|---|---|
| `docs/token-report.md` (agent estimates) | 3,920 prompt + 1,870 completion, model `qwen-2.5-coder-32b`, T0–T3 |
| OpenClaw runtime records (this audit) | One reporter session for Issue #12 alone: 243,164 input + 19,074 output (plus cache reads). Model `google/gemini-2.5-flash` |

The estimates are roughly two orders of magnitude too low. The model name in the repo's report is also not backed by runtime records. Do not defend those numbers in the interview.

---

## 3. Hermes investigation

### 3.1 Version and layout (✅ verified)
- `hermes --version`: **Hermes Agent v0.22.5 (2026.9.24)**. Install under `AppData\Local\hermes`.
- There are **three** session databases, because each profile has its own home:
  - `hermes/state.db` (default profile): 11 sessions.
  - `hermes/profiles/editor/state.db`: 1 session.
  - `hermes/profiles/copydesk/state.db`: 12 sessions.
- `hermes insights` reads only the default `state.db` (it reported 11 sessions). **It does not include the editor or copydesk profile databases.** A single `hermes insights` figure therefore under-reports the roster agents.

### 3.2 Which commands exist (✅ verified from `hermes --help` / `hermes insights --help`)

| Command | Exists? | What it gives | Notes |
|---|---|---|---|
| `hermes insights [--days N] [--source S]` | ✅ ran it | Session history analytics: tokens, cost, models | Default profile only. Total tokens appears to include cache reads. I did not verify its exact formula |
| `hermes --usage-file PATH` (one-shot mode) | ✅ in help; **not run** (it needs a model call) | JSON report with estimated cost, token counts, model, api_calls, written even on failure | This is the right capture hook for the dispatcher |
| `hermes sessions list/export/...` | ✅ listed in help; not run | Session history management | Not used for the numbers below |
| `hermes usage` | ✅ in help | **Account rate-limit windows**, not token counts | Do not use it as token evidence |

### 3.3 What the Hermes database stores (✅ verified, schema read)
- `sessions` table: `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`, `api_call_count`, `billing_provider`, `estimated_cost_usd`, `actual_cost_usd`, `cost_status`, `cwd`, `title`, `started_at`, `ended_at`.
- `session_model_usage` table: the same counters split by `(session, model, provider, task)`, where `task` is empty for the main work or one of `title_generation`, `background_review`, `approval`.
- **Important:** the `sessions` totals equal only the main-work rows (task empty). I checked the arithmetic on session `e2a75ca8`. The auxiliary task rows (`title_generation`, `background_review`, `approval`) are extra and are not in the session total or in `hermes insights`.
- `actual_cost_usd` is empty for every session. `estimated_cost_usd` comes from Hermes's pricing table, so it is an **estimate, not a bill**.

### 3.4 Answers to the investigation questions

| Question | Answer (evidence) |
|---|---|
| Which model/provider did Hermes use? | Recorded per session: `gemini-2.5-flash` (provider `gemini`), `google/gemini-3.8-flash` and `google/gemini-3.7-flash` (provider `openrouter`), `gemini-3.7-flash` (provider `gemini`), `nvidia/nemotron-3-ultra-550b-a55b:free` (openrouter), and `google/gemma-4-31b-it:free` (sessions with zero tokens) |
| Is usage exposed through session history/CLI/logs? | Yes: `state.db`, `hermes insights`, and `--usage-file` (not run) |
| Input, output, cached, total available? | Input, output, cache-read, cache-write, reasoning: yes. A "total" is not a stored column; `insights` computes one |
| Per run, task, or session? | Per session, and per (session, model, task). Each dispatcher invocation creates its own `oneshot` session, so per-run is possible for the roster agents |
| Linkable to a GitHub issue? | Partly. Roster sessions carry the issue in the title/first prompt (for example "You are copydesk. Work ONLY on Issue #14…"). The database has no ticket column. `cwd` and `git_branch` are recorded, but `git_branch` is empty everywhere |
| Retrievable retroactively? | Yes for sessions still in the database, which is all those listed in §5. Failed 429 calls have no recorded tokens |

---

## 4. OpenClaw investigation

### 4.1 Version and layout (✅ verified)
- `openclaw --version`: **OpenClaw 2026.10.8 (dc2523e)**.
- State lives in `~/.openclaw`. Each agent has its own `agents/<name>/agent/openclaw-agent.sqlite`: `reporter`, `factcheck`, and a default `main` agent (not in the roster).
- Configured models (read from `openclaw.json`, secrets not printed):
  - `reporter`: `google/gemini-2.5-flash`.
  - `factcheck`: `openrouter/nvidia/nemotron-3.5-lightning:free`.
  - `main` (default/system agent): `google/gemini-2.5-flash`.
  - The config has **no `diagnostics` section**, so the OpenTelemetry `openclaw.tokens` metric that `PROTOCOL.md` mentions does not appear to be configured. I did not test an OTel exporter.

### 4.2 Commands (✅ help text verified; none run)

| Command | What it does | Token use |
|---|---|---|
| `openclaw agent ... --json` | Returns the run result as JSON | Dispatcher does not pass `--json`. I did not run it, so I cannot say whether it includes a usage block |
| `openclaw sessions --agent <id> --json` | Lists stored sessions | Not run. I do not know if it includes token fields |
| `openclaw status --usage` | **Provider usage/quota snapshots** | This is quota, not per-run tokens |
| `openclaw audit` | Activity records | Not inspected |
| `/usage` (in chat) | Named in `PROTOCOL.md` | Not verified against this version |

### 4.3 What the OpenClaw database stores (✅ verified)
- `transcript_events` holds every message event. For assistant messages the event JSON has a `usage` object with `input`, `output`, `cacheRead`, `cacheWrite`, `totalTokens`, a `cost` object, and in some messages `reasoningTokens` and `contextUsage`.
- Each message has its own `model` field, so a session that changes model mid-way (there are `model_change` events) has to be split by message, not by session.
- Some assistant messages are synthetic (`delivery-mirror`, `gateway-injected`) and have zero usage.
- `session_windows` has the session key, provider, model, start/end times and status. Dispatcher invocations are named `newsroom-<agent>-<issue>-<epoch>`, and the epoch equals the dispatcher log file name (for example `reporter-12-1793506530.log`).
- `cost` is `0` for nearly everything (free models or no price table). Treat it as **unpriced, not free-of-charge proof**.
- `totalTokens` equals `input + output + cacheRead` (checked on several sessions). **Cache reads are re-read context, counted on every call**, so they grow very large and are not unique new text.

### 4.4 Answers to the investigation questions

| Question | Answer |
|---|---|
| Which model did OpenClaw use per run? | Recorded per message and in `session_windows`. Mostly `gemini-2.5-flash`; some free OpenRouter models appear (§5) |
| Usage in logs/status/API? | In per-message `usage` objects inside the session database. `status --usage` is quota only |
| Input/output/cached? | Yes: input, output, cacheRead, cacheWrite, totalTokens, sometimes reasoning |
| Per session or per call? | **Per call** (each assistant message), so any grouping is possible |
| Tied to ticket/PR/task? | Dispatcher-launched sessions: yes through the key (issue number + epoch). Default `agent:<name>:main` sessions: no |
| Retroactive recovery? | Yes for what is stored. Three reporter transcripts were "deleted" but archived inside the database and are readable (§6) |

---

## 5. Evidence table

All numbers are **runtime-reported** unless noted. Cost fields are estimates or `0` and are not billing records. "Cached" = cache-read tokens. "Total" = `input + output + cached` as the runtime defines it for OpenClaw; for Hermes I give input + output only, because Hermes does not store a total and I did not verify how `insights` builds one.

### 5.1 Assignment task runs that can be tied to a ticket

| Runtime | Session / task | Model | Input | Output | Cached | Total | Evidence source | Confidence |
|---|---|---|---:|---:|---:|---:|---|---|
| OpenClaw | reporter, Issue #12 (4 dispatcher runs, 3 marked `failed` and 1 `done` in OpenClaw's session status; keys `newsroom-reporter-12-*`) | `gemini-2.5-flash` (one run also has `gemini-3.7-flash` messages) | 392,419 | 24,744 | 3,383,882 | 3,801,045 | `~/.openclaw/agents/reporter/agent/openclaw-agent.sqlite`, `session_windows` + `transcript_events` | High for sums; **medium for the model split** (mixed models in one session) |
| OpenClaw | reporter, Issue #14 (5 dispatcher runs, keys `newsroom-reporter-14-*`) | `gemini-2.5-flash` | 436,908 | 28,671 | 3,300,036 | 3,765,615 | same | High |
| OpenClaw | reporter, PR #25 cleanup (`cleanup-pr25-*`, `final-cleanup-*`; 2 explicit runs, Issue #14) | `gemini-2.5-flash` | 39,037 | 2,295 | 188,113 | 229,445 | same | High for sums. Which run was the "failed" attempt is **not verified** |
| OpenClaw | factcheck, Issue #12 (`newsroom-factcheck-12-1793508553`, status failed) | `nvidia/nemotron-3.5-lightning:free` | 38,220 | 3,041 | 234,752 | 276,013 | `agents/factcheck/agent/openclaw-agent.sqlite` | High |
| Hermes | copydesk, Issue #12 (session `0942a805`, "Fix RSS channel link") | `gemini-2.5-flash` (gemini) | 79,485 | 7,534 | 237,381 | Not stored (input + output = 87,019) | `hermes/profiles/copydesk/state.db`, `sessions` + `session_model_usage`. Reasoning 2,790. Estimated cost $0.0200 (estimate) | High. The session has no end time; it was resumed (matches the 429/gateway-loss story), so it could still grow |
| Hermes | copydesk, Issue #7 attempt 2 review (session `88991d2e`) | `gemini-2.5-flash` (gemini) | 126,692 | 9,191 | 180,435 | Not stored (input + output = 135,883) | `hermes/state.db` (default profile). Reasoning 7,171. Estimated cost $0.0272 (estimate). Title-generation call (509 in / 13 out) is extra | High |
| Hermes | editor, UI-polish tickets (session `c1be526c`, "Create UI polish issues from product brief") | `nvidia/nemotron-3-ultra-550b-a55b:free` (openrouter) | 442,006 | 8,792 | 1,563,840 | Not stored (input + output = 450,798) | `hermes/profiles/editor/state.db`. Reasoning 2,742. Cost status `unknown` | High for the session. The link to Issues #14–#18 comes from the prompt text, not from a ticket column |
| Hermes | copydesk, Issue #12 (4 sessions) and Issue #14 (4 sessions) | `google/gemma-4-31b-it:free` | **0** | **0** | **0** | **0** | `hermes/profiles/copydesk/state.db`: `api_call_count` is 0 for all eight | High that the database recorded zero. **Not** proof that no tokens were used. These calls failed (HTTP 429, per `agents/traces/t4-dispatcher-429.md`) before a response came back |

### 5.2 Sessions that are project-related but not tied to one ticket (report separately)

| Runtime | Session | Model(s) | Input | Output | Cached | Why it is not a ticket run |
|---|---|---|---:|---:|---:|---|
| Hermes | `e2a75ca8` "Review Autonomous Newsroom Day 1 setup" (default profile, 375 calls, still open) | `google/gemini-3.8-flash` (openrouter) 2,263,127 in / 115,819 out; `google/gemini-3.7-flash` (openrouter) 436,718 / 252; `gemini-3.7-flash` (gemini) 5,943,620 / 59,560 | 8,643,465 | 175,631 | 70,136,311 | Planning/setup. Estimated cost $12.76 (an estimate). This is the only place `gemini-3.8-flash` / `3.7-flash` appear with large usage |
| Hermes | `89a9980b` "Investigate failing gate check on PR #10" (350 calls) | `gemini-2.5-flash` | 1,983,734 | 185,757 | 80,946,060 | Interactive debugging linked to Issue #9/PR #10. Not a roster-agent run |
| Hermes | `e9f8f517` "Continue previous conversation" (277 calls, still open) | `gemini-2.5-flash` | 1,485,216 | 80,388 | 30,788,999 | Interactive session. The ticket scope is not recorded |
| Hermes | `34fcd131` "Implement Copydesk fixes for Issue 7" | `google/gemini-3.8-flash` | 0 (title generation only: 528 in / 14 out) | 0 | 0 | The model made no recorded main-work calls |
| OpenClaw | reporter default session `agent:reporter:main` (`80170e13`; 2026-10-30 13:04 → 2026-11-01 00:18, 784 assistant messages) | per message: `gemini-2.5-flash`, `cohere/north-mini-code:free`, `poolside/laguna-s-2.1:free`, `gemini-3.7-flash` (and zero-usage `gemini-3.8-flash`) | 10,455,480 | 383,300 | 311,597,678 | Covers the T2–T4 era, but mixes tickets. Could be split by message timestamp, which I did **not** do |
| OpenClaw | reporter default session `agent:reporter:main` (`11cc8e39`; 2026-11-01 → 2026-11-02, 67 messages) | `gemini-2.5-flash` | 333,505 | 39,201 | 3,220,844 | Mixed. Window overlaps the Issue #14 / PR #25 work, but the link is not recorded |
| OpenClaw | reporter sessions with UUID keys (5 sessions on 2026-11-01), not named by ticket | `gemini-2.5-flash` | 230,585 (combined) | 22,594 | 1,976,966 | Ticket unknown |
| OpenClaw | factcheck default session `agent:factcheck:main` (`9231c508`; 18 messages) | `gemini-2.5-flash` | 115,180 | 1,915 | 158,166 | Ticket unknown |
| OpenClaw | 3 archived reporter sessions (deleted 2026-11-01) | `gemini-2.5-flash` and others (not split) | 65,468 + 316,198 + 587,427 | 3,492 + 9,637 + 76,314 | 276,195 + 1,548,082 + 9,292,541 | Recoverable from the archive in the database. Ticket unknown (§6) |

### 5.3 Excluded on purpose (diagnostics, probes and unrelated work)

| Item | Why excluded |
|---|---|
| OpenClaw `diag-*` and `probe-*` sessions (4 `diag-*` sessions and 1 `probe-*` session, 2026-11-01 and 11-02) | Setup diagnostics, not assignment tasks. **`DELIVERY.md`'s one measured figure (32,423 input / 1,266 output / 73,637 cache-read) is exactly session `diag-720865046`.** I verified it matches. It is a diagnostic and must not be reported as task usage |
| Hermes ping/health sessions (`22899731`, `e515909b`, `4fdd4187`, `1b2c5e2f`, `302f7316`, `ea033e8b`, `2b60d8cc`) | "Reply with exactly…" pings and status checks |
| Hermes `ae527f00` "Review second resume draft" | **Unrelated to this assignment** (a resume review). It is in the same database, so it **is** counted by `hermes insights`. Exclude it from any project total |
| OpenClaw default `main` agent sessions | Not a roster agent. Likely setup, but I did not verify what it was used for |

---

## 6. What can and cannot be recovered

### Recoverable now (with a script over the existing databases)
- Per-run tokens for every dispatcher-launched OpenClaw run, tied to a ticket and a dispatcher log file.
- Per-message model attribution for OpenClaw, so mixed-model sessions can be split.
- Per-session and per-model tokens for Hermes roster sessions that got a response.
- Cache-read and reasoning tokens for both runtimes.
- The three deleted OpenClaw reporter sessions. They are stored compressed in the `session_transcript_archives` table (I decompressed them in memory). Their period was 2026-11-01 06:47–09:41 UTC. Their per-ticket link is **not** recorded.
- Splitting the long default reporter session by time, by matching message timestamps to PR/commit times. Possible but not done and not verified.

### Not recoverable (or not recoverable from the evidence I have)
| Missing item | Why |
|---|---|
| Hermes calls that hit HTTP 429 | No response came back, so the runtime stored 0. Any tokens the provider counted before rejecting are unknown |
| Editor and copydesk work for T0–T2 | I found no matching session in the three Hermes databases. Earliest relevant Hermes sessions are setup/planning (Oct 29) and the Issue #7 review (Oct 31). I do not know where the T2 copydesk review ran |
| Factcheck runs for T2 and T3 (the "40 passed" result) | The factcheck database holds only 2 sessions. I cannot tie either to those runs |
| Ticket for the default-session work | Not recorded by either runtime |
| Real cost in money | `actual_cost_usd` is empty in Hermes and OpenClaw `cost` is 0 or unpriced. Only Hermes's estimated cost exists, and it is not a provider bill. Provider consoles (OpenRouter, Google AI Studio) would be the billing source. I did not check them |
| Token numbers for the product's own summarizer | `summarizer.py` stores the model name but **not** token counts. Provider dashboards are the only possible source |
| Whether `qwen-2.5-coder-32b` was ever used | Appears in 6 commit trailers and `docs/token-report.md`, but in **no** runtime record I read. Treat the trailer as unsupported until someone shows evidence |

### Alternative evidence if a number is missing
- Dispatcher logs in `~/.local/state/newsroom-dispatch/logs/` and `.dispatcher-validation/logs/` (I only searched for the words "token/usage"; they contain agent prose, not a structured usage block).
- Provider dashboards (OpenRouter activity, Google AI Studio usage).
- Retry counts and timestamps in the dispatcher state JSON files.

---

## 7. Correct token-tracking architecture

**Status:** 💡 **Proposed implementation.** None of this exists in the repo. The *capabilities it relies on* are marked.

### 7.1 When to collect
**At the end of every invocation, in the dispatcher** (`agents/dispatcher/dispatch.py::_run_subprocess`), including failed and timed-out runs. Do not rely on agents typing numbers in comments.

### 7.2 Where to collect from
| Runtime | Source | Status |
|---|---|---|
| Hermes | `--usage-file PATH` on the one-shot command: JSON with estimated cost, token counts, model, api_calls, written even on failure | ✅ exists in `hermes --help`. **Not run** and its exact JSON fields are unverified |
| Hermes (fallback) | `session_model_usage` rows for the session id | ✅ schema verified |
| OpenClaw | Per-message `usage` in the agent's `transcript_events`, selected by session key `newsroom-<agent>-<issue>-<epoch>` | ✅ verified. Reading another program's SQLite file is an internal detail and could change between versions |
| OpenClaw (alternative) | `openclaw agent --json` | ⚠️ flag exists. Whether it contains usage is **unverified** |
| Provider dashboards | Billing cross-check | Not checked |

### 7.3 How to save it
One append-only file in git or a small SQLite table, `usage_events`, one row per **model call group** (see schema in §8). Never edit rows; add correction rows.

### 7.4 How to associate it
Give the dispatcher the identifiers it already has: `agent`, `runtime`, `issue`, `pr`, `attempt` (from the `attempt:n` label), `dispatch_key` (`issue-<n>`), the runtime session id, and the model per message. The OpenClaw session key and Hermes session title already carry the issue number, so the dispatcher can pass an explicit session name instead of relying on title parsing.

### 7.5 Retries and multiple model calls
- Keep **one row per runtime session and model**, and a separate `attempt` field. A retry is a new session, so it is a new row. Do not overwrite earlier attempts.
- Report "tokens spent on retries" as the sum of rows where `attempt > 1` or `outcome = failed`.
- Multiple LLM calls in one run are already summed by the runtime per session and model. Keep `api_calls` to show the count.

### 7.6 Avoiding double-counting
- Use the runtime session id plus model as a unique key. Re-importing the same session replaces nothing and inserts nothing.
- Never add a session total **and** its per-model rows.
- Never add Hermes auxiliary tasks (`title_generation`, `background_review`, `approval`) into the session total silently. Store them as separate rows with their `task` value.
- Do **not** sum OpenClaw `cacheRead` with `input` as if it were new text. Report `cache_read` as its own column, and label totals "including cache reads" or "excluding cache reads".
- Exclude diagnostic, probe and ping sessions by tagging them `purpose: diagnostic`.
- A session that is still open (Hermes `ended_at` empty) must be marked `open` and re-read later.

### 7.7 Missing usage metadata
Write the row anyway with `input_tokens: null`, `status: "unavailable"` and a reason (`rate_limited`, `runtime_not_recorded`, `session_not_found`). Never fill a missing value with an estimate in the measured columns. If an estimate is useful, put it in a separate `estimated_*` field with a method note.

### 7.8 Totals across agents
Sum measured columns only, grouped by `agent`, `model`, `ticket` and `stage`. Show three separate lines: **measured**, **estimated**, **unavailable (count of runs)**. Do not add cost across providers unless every row has a price.

### 7.9 Model/provider and cost
Store `provider` and `model` per row. Compute cost only where a price is known: `cost = input×p_in + output×p_out + cache_read×p_cache`, with `pricing_version` and date. Mark free-tier models `cost_basis: "free_tier"` rather than 0. Hermes already stores `estimated_cost_usd`, `cost_status` and `pricing_version`. Treat them as estimates.

### 7.10 Do not confuse
- **Context window** is the maximum the model can read. **Tokens consumed** are what a call actually used. They are different numbers.
- **Tokens** are a quantity. **Cost** is tokens times a price, and free tiers have a zero price but still have tokens and rate limits.

---

## 8. Example schema and report

### 8.1 JSON schema (💡 proposed)

```json
{
  "schema_version": 1,
  "generated_at": "2026-11-02T00:00:00Z",
  "usage_events": [
    {
      "event_id": "hermes:local-0942a8053c60414f:gemini-2.5-flash:gemini:",
      "runtime": "hermes",
      "agent": "copydesk",
      "issue": 12,
      "pr": 13,
      "attempt": 1,
      "purpose": "task",
      "stage": "review_test",
      "provider": "gemini",
      "model": "gemini-2.5-flash",
      "session_id": "local-0942a8053c60414f",
      "task": "",
      "api_calls": 16,
      "input_tokens": 79485,
      "output_tokens": 7534,
      "cache_read_tokens": 237381,
      "cache_write_tokens": 0,
      "reasoning_tokens": 2790,
      "usage_source": "runtime_reported",
      "usage_status": "measured",
      "cost_usd": 0.0200,
      "cost_basis": "runtime_estimate",
      "session_open": true,
      "evidence": "hermes/profiles/copydesk/state.db#session_model_usage"
    },
    {
      "event_id": "hermes:local-24306bc4475ba685:google/gemma-4-31b-it:free",
      "runtime": "hermes",
      "agent": "copydesk",
      "issue": 12,
      "attempt": 1,
      "purpose": "task",
      "stage": "review_test",
      "provider": null,
      "model": "google/gemma-4-31b-it:free",
      "api_calls": 0,
      "input_tokens": null,
      "output_tokens": null,
      "usage_source": "runtime_reported",
      "usage_status": "unavailable",
      "unavailable_reason": "rate_limited_http_429_no_response_recorded"
    }
  ]
}
```

(The first row uses values I read from the Hermes database. The second row shows how an unavailable value should be written. In the actual database those eight copydesk sessions show 0, not null. The schema stores unknown as `null` and keeps `0` for a measured zero.)

### 8.2 Markdown report template (💡 proposed)

```markdown
## Token report (measured unless marked)

| Ticket | Agent | Runtime | Model | Attempt | Calls | Input | Output | Cache read | Status |
|---|---|---|---|---|---:|---:|---:|---:|---|
| #12 | copydesk | Hermes | gemini-2.5-flash | 1 | 16 | 79,485 | 7,534 | 237,381 | measured |
| #12 | reporter | OpenClaw | gemini-2.5-flash | 1-4 | 124 | 392,419 | 24,744 | 3,383,882 | measured, mixed-model sessions |
| #12 | copydesk | Hermes | gemma-4-31b-it:free | 1-3 | 0 | - | - | - | unavailable (429, no response) |

Totals: measured X · estimated Y · unavailable N runs
Notes: totals exclude diagnostics; cache-read shown separately; costs are estimates.
```

(Those example rows are values from §5. The "Calls 124" for the reporter is 16 + 17 + 78 + 13 assistant messages in the four Issue #12 runs, as computed from the OpenClaw database. It counts assistant messages, including a few zero-usage synthetic ones.)

---

## 9. Interview questions and answers

**1. How did you track token usage in Hermes and OpenClaw?**
- **Say:** "Honestly, not well at the time. The protocol told agents to put token numbers in their handoff comments, but the agents had to estimate, and my dispatcher didn't capture the runtimes' own counters. Afterwards I found both runtimes had stored real usage: Hermes in its session database and OpenClaw in per-message usage records. The repo's report is still the earlier estimates."
- **Deeper:** Hermes `state.db` has per-session and per-model counters. OpenClaw stores a `usage` object on every assistant message. Neither was read by my code.
- **Follow-up:** "So are your numbers wrong?" → "The estimates are far lower than the runtime records. I would not defend them. I have audited the runtime data, but I have not replaced the report yet."

**2. Why is the token report incomplete?**
- **Say:** "Because collection depended on the agents reporting their own usage. They can't reliably see it, and failed runs, especially the rate-limited ones, never posted a handoff at all."
- **Deeper:** A design flaw. Capture belongs in the dispatcher at the end of each invocation, not in an LLM comment.
- **Follow-up:** "Whose fault is that?" → "Mine. The design was mine, and I didn't test the capture path."

**3. Can you recover the missing usage now?**
- **Say:** "Most of it, yes. Dispatcher-launched OpenClaw runs are named by issue and timestamp, so I can total them per ticket. Hermes keeps per-session counts. What I can't recover is anything where the call failed before a response, and a few early sessions I couldn't find."
- **Deeper:** Recoverable: OpenClaw per-ticket runs, Hermes roster sessions, cache and reasoning tokens. Not: 429 calls, T0–T2 editor/copydesk, T2/T3 factcheck, real billing cost.
- **Follow-up:** "Did you recover it?" → "I audited it. I have a table, but I haven't yet updated `docs/token-report.md`."

**4. How would you implement token tracking in a production multi-agent system?**
- **Say:** "The orchestrator records usage when every run ends, from the runtime itself, with the agent, model, ticket, attempt and session id. Append-only, so it can be audited."
- **Deeper:** §7. Use `--usage-file` for Hermes and transcript or JSON output for OpenClaw. Also use a gateway or tracing layer (for example Langfuse) so you don't depend on each runtime's internal files.
- **Follow-up:** "Which would you pick?" → "A proxy or tracing layer in front of the model API, because it sees every call whatever the runtime. I haven't built one here."

**5. How do you measure cost per ticket?**
- **Say:** "Add up the tokens by ticket and multiply by each model's price. On this project the models were mostly free-tier, so the money cost is near zero. The meaningful cost number is tokens and retries, not dollars."
- **Deeper:** `cost = input×p_in + output×p_out + cache_read×p_cache`. Hermes has an estimated cost per session, which is not a bill.
- **Follow-up:** "What's the cost of Issue #12?" → "I can give measured tokens: the reporter used about 392k input and 25k output across four runs, plus about 3.4M cache-read tokens. I won't give a dollar figure because I have no verified price or billing record."

**6. How would you compare token efficiency of Hermes and OpenClaw?**
- **Say:** "I wouldn't from this data. They did different jobs on different tickets and models, so the comparison would be unfair. I'd run the same task on both with the same model and compare tokens per successful outcome."
- **Deeper:** Metrics: tokens per accepted PR, calls per task, cache hit ratio, retries per ticket.
- **Follow-up:** "Any early signal?" → "Only that cache reads dominate in both. I wouldn't draw a conclusion."

**7. How would you prevent retries from inflating totals?**
- **Say:** "Two separate numbers. A retry is real spend, so it counts, but I'd label it as retry spend. What I must prevent is counting the same session twice."
- **Deeper:** Unique key on `(session id, model, task)`. Attempt number stored per row. Retries reported as their own category.
- **Follow-up:** "Where did retries show up here?" → "Issue #12 had four reporter runs, three of them marked failed by OpenClaw, and Issue #14 had five. Their usage is real and in the totals above."

**8. How would you track tokens when an agent makes multiple LLM calls?**
- **Say:** "Record at the call level, or let the runtime sum it per session and model. OpenClaw stores usage on each message, and Hermes keeps per-model totals per session."
- **Deeper:** Keep `api_calls`. Include auxiliary calls (title generation, background review) as separate rows, because Hermes keeps them out of the session total.
- **Follow-up:** "Did that affect you?" → "Yes. `hermes insights` leaves out those auxiliary calls and also only reads the default profile, so it under-reports my editor and copydesk agents."

**9. What is the difference between input, output, cached and total tokens?**
- **Say:** "Input is what I send in, output is what the model writes, cached is input the provider already had cached so it is cheaper or free to re-read, and total is a sum, which is defined differently by each tool."
- **Deeper:** In OpenClaw here `totalTokens = input + output + cacheRead`. Cache reads repeat on every call of a long conversation, so they get very large and shouldn't be read as new content. Reasoning tokens are extra "thinking" tokens some models report. Context-window size is something else: a limit, not usage.
- **Follow-up:** "Which total do you quote?" → "I'd quote input and output separately, and cache reads on their own line."

**10. How would you prove the token report is accurate?**
- **Say:** "Reconcile it against two independent sources: the runtime's own records and the provider's billing or usage page. If they agree within a small margin, I'd call it accurate. I haven't done the provider check."
- **Deeper:** Spot-check a session by recomputing from raw events (I did that for OpenClaw: `totalTokens` equals input + output + cacheRead; and for Hermes: session totals equal the main-work rows). Add a CI check that every dispatcher run has a usage row.
- **Follow-up:** "So is your audit proven?" → "Internally consistent, yes. Not reconciled to a provider invoice."

**Bonus questions**

**11. What's the one thing you'd correct in your delivery docs?**
- **Say:** "Replace the estimated token table with the runtime-recorded one, label the qwen model as unverified, and say that the one measured figure in `DELIVERY.md` comes from a diagnostic session, not a task."

**12. A reviewer sees 3.8M tokens for one ticket and asks if that's wasteful.**
- **Say:** "Most of it, about 3.4M, is cache reads, meaning the same conversation context re-read on every call. New input was about 392k and output about 25k. But four runs for one small fix is still a lot, mostly from retries and the configuration problem."

---

## 10. Recommended next steps

Each item is **proposed** unless marked.

1. **Fix the report first (no code change to the product).** Replace `docs/token-report.md` with the §5.1 table. Label every row measured/estimated. Remove or flag the `qwen-2.5-coder-32b` entries as unsupported. Say clearly that `DELIVERY.md`'s measured figure is a diagnostic run.
2. **Write a small read-only script** (not in the product path) that exports §5 from both runtimes into the JSON schema. Re-run it before submission, because Hermes sessions marked open can still grow.
3. **Split the long default reporter session** by message timestamp against PR/commit times to attribute T2–T4 usage. Mark the result "time-correlated, medium confidence".
4. **Add capture to the dispatcher:** pass `--usage-file` for Hermes. For OpenClaw, read the session's usage after the run, or test whether `openclaw agent --json` includes usage. Verify against one real run before relying on it. This needs one model call, so it needs your approval.
5. **Verify the claims I could not:** `/usage` and OTel `openclaw.tokens` on this OpenClaw version, and the exact output of `hermes --usage-file`.
6. **Reconcile with provider dashboards** (OpenRouter and Google AI Studio) for a billing cross-check.
7. **Record usage for the product's own summarizer** (token counts per call), because it currently stores only the model name.
8. **Exclude** diagnostics, pings and the resume-review session from every total.

---

## 11. Summary of verification status

**Verified by me (read-only):**
- Hermes v0.22.5: three `state.db` files, their schemas, per-session and per-model token fields, and the `hermes insights` output.
- OpenClaw 2026.10.8: per-agent SQLite stores, per-message `usage` objects, session keys that match dispatcher log names, three archived transcripts, and the absence of a `diagnostics` config section.
- Dispatcher does not capture usage (read `dispatch.py`).
- `DELIVERY.md`'s measured figure equals the diagnostic session `diag-720865046`.
- Arithmetic checks: OpenClaw `totalTokens = input + output + cacheRead`; Hermes session totals = main-task rows (auxiliary tasks excluded).

**Read from help text only, not run:** `hermes --usage-file`, `hermes sessions`, `openclaw agent --json`, `openclaw sessions --json`, `openclaw status --usage`, `openclaw audit`.

**Not verified:** `/usage`, OTel `openclaw.tokens`, provider billing, how `hermes insights` computes its "total", which PR #25 cleanup run was which attempt, the cause of the missing T0–T2 sessions.

**Still missing:** a verified, per-ticket, per-stage token report in the repo; usage for 429-failed Hermes calls; early editor/copydesk/factcheck runs; real cost.

**How to explain it in the interview:** "Token tracking was a gap in my design. I relied on agents estimating their usage in comments. Afterwards I found both runtimes had recorded real usage, so I audited it and found my repo estimates were far too low and one model name was unsupported. I can recover most per-ticket usage, but a few runs, especially rate-limited ones, have no data. I haven't yet updated the report, and the fix is to capture usage in the dispatcher."
