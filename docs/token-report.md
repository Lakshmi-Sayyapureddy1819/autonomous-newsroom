# Token and Model Report

*Companion to [DELIVERY.md](../DELIVERY.md). Figures re-derived read-only from the local Hermes and OpenClaw stores on November 2, 2026. All times are UTC.*

**Contents**
[1. Executive summary](#1-executive-summary) · [2. Usage by agent and model](#2-token-usage-by-agent-and-model) · [3. Usage by activity](#3-usage-by-activity) · [4. Per-agent breakdown](#4-per-agent-breakdown) · [5. Retries and failed runs](#5-retry-and-failed-run-usage) · [6. Totals and estimates](#6-totals-and-estimates) · [7. Scope and exclusions](#7-scope-and-exclusions)

---

## 1. Executive summary

**What this covers.** Token usage of the Hermes and OpenClaw agents (editor, reporter, copydesk, factcheck) and of the owner's interactive Hermes/OpenClaw sessions for this project, from **October 29 to November 2, 2026**. The ticket-linked roster runs fall between **October 31 and November 2**.

**Source.** The dispatcher did not record usage when runs finished, and agents' own handoff-comment estimates were far too low (the earlier report quoted about 3.9k prompt and 1.9k completion tokens for the reporter; the runtime stores show hundreds of thousands). The numbers here were recovered afterwards, read-only, from the runtimes' own stores and recomputed from raw records:

| Runtime | Version | Store | What it holds |
|---|---|---|---|
| Hermes | v0.22.5 | `state.db` in the default, `editor` and `copydesk` profile homes (`sessions`, `session_model_usage`) | Per-session and per-model input, output, cache-read and reasoning tokens |
| OpenClaw | 2026.10.8 | Per-agent `openclaw-agent.sqlite` (`transcript_events`, `session_windows`) | A `usage` object on every assistant message; each message names its model. Dispatcher runs are keyed `newsroom-<agent>-<issue>-<epoch>`, and the epoch matches the dispatcher log file name |

**Headline figures (runtime-reported).**

| Scope | Input | Output | Cache-read | Input + output |
|---|---:|---:|---:|---:|
| Roster-agent runs tied to a ticket | 1,554,767 | 84,268 | 9,088,439 | 1,639,035 |
| Interactive and unattributed project sessions | 24,528,257 | 983,413 | 510,101,682 | 25,511,670 |
| **All included usage** | **26,083,024** | **1,067,681** | **519,190,121** | **27,150,705** |

**Important limitations.**

- **These are runtime-reported counts, not provider billing.** No provider invoice or dashboard was checked, so **no dollar cost is claimed.** Most models used were free-tier; OpenClaw's cost field is 0/unpriced, and Hermes's cost field is its own pricing-table estimate (not reproduced here).
- **Cache-read tokens are context re-read on every call of a long conversation, not new text.** They dominate the volume and are always shown separately.
- Some usage is **unavailable**: Hermes calls that failed with HTTP 429 recorded zero; the earliest ticket work (T0–T2 editor and copydesk, T2/T3 factcheck) has no recorded session; the product's own summarizer stores no token counts.
- The activity split in section 3 is derived from session titles, ticket keys and runtime run status, not from a recorded category. Where that was not possible, usage is shown as unclassified.

---

## 2. Token usage by agent and model

### 2.1 Roster-agent runs tied to a ticket (verified)

"Calls" are assistant messages (OpenClaw) or API calls (Hermes). **Total** = input + output; cache-read is shown separately.

| Agent | Runtime | Model | Tickets / runs | Input | Output | Cache-read | Total (in + out) | Status |
|---|---|---|---|---:|---:|---:|---:|---|
| editor | Hermes | `nvidia/nemotron-3-ultra-550b-a55b:free` | UI-polish tickets #14–#18, 1 session, 30 calls | 442,006 | 8,792 | 1,563,840 | 450,798 | Verified. Ticket link comes from the prompt text |
| reporter | OpenClaw | `google/gemini-2.5-flash` | #12 (4 runs), #14 (5 runs), PR #25 cleanup (2 runs) | 677,243 | 37,924 | 4,532,534 | 715,167 | Verified. See 2.3 for the per-ticket rows |
| reporter | OpenClaw | `google/gemini-3.7-flash` | #12, inside one run | 191,121 | 17,786 | 2,339,497 | 208,907 | Verified (per-message model) |
| copydesk | Hermes | `gemini-2.5-flash` (Gemini API) | #12 review (16 calls), #7 attempt-2 review (10 calls) | 206,177 | 16,725 | 417,816 | 222,902 | Verified. Both sessions have no end time and could still grow |
| copydesk | Hermes | `google/gemma-4-31b-it:free` | 7 task sessions (3 for #12, 4 for #14) | not available | not available | not available | not available | Runtime recorded 0 calls; HTTP 429 before any response |
| factcheck | OpenClaw | `nvidia/nemotron-3.5-lightning:free` | #12, 1 run (16 calls), marked `failed` | 38,220 | 3,041 | 234,752 | 41,261 | Verified |
| copydesk, factcheck | scripts | none (no LLM) | PR #25, deterministic mode | 0 | 0 | 0 | 0 | By design: `copydesk_agent.py` / `factcheck_agent.py` make no model call |
| | | **Subtotal** | | **1,554,767** | **84,268** | **9,088,439** | **1,639,035** | |

### 2.2 Interactive and unattributed project sessions (verified sums, ticket unknown)

These are real usage but are not tied to a ticket or a roster run, so they are **not** added into the per-ticket rows above.

| Runtime | Session | Model(s) | Input | Output | Cache-read | Total (in + out) | Note |
|---|---|---|---:|---:|---:|---:|---|
| Hermes (default profile) | Day-1 setup planning, Oct 29–31, 375 calls | `google/gemini-3.8-flash` 2,263,127 in / 115,819 out; `google/gemini-3.7-flash` (OpenRouter) 436,718 / 252; `gemini-3.7-flash` (Gemini API) 5,943,620 / 59,560 | 8,643,465 | 175,631 | 70,136,311 | 8,819,096 | Owner-driven planning; session still open |
| Hermes (default) | "Hermes working with Nemotron free", Oct 29, 20 calls | `nvidia/nemotron-3-ultra-550b-a55b:free` | 311,999 | 5,184 | 159,840 | 317,183 | Starts as a one-line ping, then continues the assignment in an editor/orchestrator role. Classified as planning from its first prompts. Not listed in earlier drafts of this report |
| Hermes (default) | "Investigate failing gate check on PR #10", Oct 31, 350 calls | `gemini-2.5-flash` | 1,983,734 | 185,757 | 80,946,060 | 2,169,491 | Interactive debugging |
| Hermes (default) | "Continue previous conversation", Oct 31, 277 calls | `gemini-2.5-flash` | 1,485,216 | 80,388 | 30,788,999 | 1,565,604 | Ticket not recorded; session still open |
| OpenClaw | reporter default session, Oct 30–Nov 1 (784 messages) | `gemini-2.5-flash` 9,774,388 in / 349,003 out; `cohere/north-mini-code:free` 402,300 / 2,800; `poolside/laguna-s-2.1:free` 278,792 / 31,497 | 10,455,480 | 383,300 | 311,597,678 | 10,838,780 | Covers the T2–T4 era; mixes tickets |
| OpenClaw | reporter default session, Nov 1–2 (66 messages) | `google/gemini-2.5-flash` | 333,505 | 39,201 | 3,220,844 | 372,706 | Time-correlated with PR #25 work (see 5.3) |
| OpenClaw | 5 reporter dashboard sessions, Nov 1 | `google/gemini-2.5-flash` | 230,585 | 22,594 | 1,976,966 | 253,179 | Ticket not recorded |
| OpenClaw | 3 reporter sessions deleted Nov 1, recovered from the in-database archive | mixed, not split | 969,093 | 89,443 | 11,116,818 | 1,058,536 | Ticket not recorded |
| OpenClaw | factcheck default session (17 calls) | `google/gemini-2.5-flash` | 115,180 | 1,915 | 158,166 | 117,095 | Ticket not recorded |
| | | **Subtotal** | **24,528,257** | **983,413** | **510,101,682** | **25,511,670** | |

### 2.3 Reporter usage by ticket (inside the OpenClaw rows above)

| Ticket | Runs | Model(s) | Input | Output | Cache-read | Note |
|---|---|---|---:|---:|---:|---|
| #12 | 4 (3 marked `failed`) | Gemini 2.5 Flash 201,298 in / 6,958 out / 1,044,385 cache; Gemini 3.7 Flash 191,121 / 17,786 / 2,339,497 | 392,419 | 24,744 | 3,383,882 | 123 assistant messages with usage |
| #14 | 5 (1 marked `failed`) | Gemini 2.5 Flash | 436,908 | 28,671 | 3,300,036 | Dispatcher runs launched Nov 1, 04:36–05:18 UTC |
| #14, PR #25 cleanup | 2 explicit sessions | Gemini 2.5 Flash | 39,037 | 2,295 | 188,113 | Which session was which dispatcher attempt is **not verified** |

### 2.4 Totals per model (all included usage)

Provider spelling differs by runtime (`gemini-2.5-flash` in Hermes, `google/gemini-2.5-flash` in OpenClaw); they are treated as the same model and merged here.

| Model | Input | Output | Cache-read | Total (in + out) |
|---|---:|---:|---:|---:|
| Gemini 2.5 Flash | 14,806,028 | 733,507 | 426,854,039 | 15,539,535 |
| Gemini 3.7 Flash | 6,571,459 | 77,598 | 53,496,503 | 6,649,057 |
| `google/gemini-3.8-flash` | 2,263,127 | 115,819 | 18,979,305 | 2,378,946 |
| Mixed / not split (archived reporter sessions) | 969,093 | 89,443 | 11,116,818 | 1,058,536 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 754,005 | 13,976 | 1,723,680 | 767,981 |
| `cohere/north-mini-code:free` | 402,300 | 2,800 | 0 | 405,100 |
| `poolside/laguna-s-2.1:free` | 278,792 | 31,497 | 6,785,024 | 310,289 |
| `nvidia/nemotron-3.5-lightning:free` | 38,220 | 3,041 | 234,752 | 41,261 |
| **All models** | **26,083,024** | **1,067,681** | **519,190,121** | **27,150,705** |

---

## 3. Usage by activity

The split follows the assignment's categories. A session is placed by what it did (its title, ticket key and the runtime's own run status); nothing is estimated. **Retries/failures** holds only OpenClaw reporter runs that the runtime itself marked `failed`; those runs are removed from Coding so nothing is counted twice.

### 3.1 Roster-agent runs

| Activity | Agent (runtime) / model | Input | Output | Cache-read | Total (in + out) |
|---|---|---:|---:|---:|---:|
| **Planning / orchestration** | editor (Hermes), nemotron-3-ultra free | 442,006 | 8,792 | 1,563,840 | 450,798 |
| **Coding / implementation** | reporter (OpenClaw): #12 successful run (Gemini 2.5 Flash 52,043 in / 1,288 out; Gemini 3.7 Flash 191,121 / 17,786) | 243,164 | 19,074 | 2,673,547 | 262,238 |
| | reporter: #14 four runs not marked failed (Gemini 2.5 Flash) | 370,880 | 23,340 | 2,743,468 | 394,220 |
| | reporter: PR #25 cleanup (Gemini 2.5 Flash) | 39,037 | 2,295 | 188,113 | 41,332 |
| | *Coding subtotal* | *653,081* | *44,709* | *5,605,128* | *697,790* |
| **Review / testing** | copydesk (Hermes), Gemini 2.5 Flash: #12 and #7 | 206,177 | 16,725 | 417,816 | 222,902 |
| | factcheck (OpenClaw), nemotron-3.5 free: #12 | 38,220 | 3,041 | 234,752 | 41,261 |
| | copydesk/factcheck for PR #25 (scripts) | 0 | 0 | 0 | 0 |
| | *Review/testing subtotal* | *244,397* | *19,766* | *652,568* | *264,163* |
| **Retries / failures** | reporter: 3 runs for #12 and 1 for #14 marked `failed` (Gemini 2.5 Flash) | 215,283 | 11,001 | 1,266,903 | 226,284 |
| | copydesk gemma-4 free: 7 rate-limited sessions | not available | not available | not available | not available |
| **Roster total** | | **1,554,767** | **84,268** | **9,088,439** | **1,639,035** |

### 3.2 Interactive and unattributed sessions

| Activity | Sessions | Input | Output | Cache-read | Total (in + out) |
|---|---|---:|---:|---:|---:|
| Planning / setup (Hermes, owner-driven) | Day-1 planning, Nemotron setup trial | 8,955,464 | 180,815 | 70,296,151 | 9,136,279 |
| Not classifiable | Hermes PR #10 debugging, Hermes "continue" session, all unattributed OpenClaw reporter/factcheck sessions, archived sessions | 15,572,793 | 802,598 | 439,805,531 | 16,375,391 |
| **Total** | | **24,528,257** | **983,413** | **510,101,682** | **25,511,670** |

**What cannot be derived.** The long default reporter sessions (about 10.8M input over three days) mix several tickets and are not split by ticket or activity. Splitting them by message timestamp against commit and PR times is possible but was not done, so they appear as unclassified rather than being forced into Coding.

---

## 4. Per-agent breakdown

- **Editor (Hermes).** One recorded task session, 442k input tokens across 30 calls to write the UI-polish tickets from `docs/brief-ui-polish.md`. The earlier T0–T4 Issues were written by the editor too, but **no matching session exists in the stores**, so that planning usage is unavailable. Retry routing, blocking and promotion are dispatcher code and use no tokens. The largest planning cost was the owner's interactive Day-1 Hermes session (8.6M input on Gemini 3.x models, plus 70M cache-read tokens), which is not a roster run.
- **Reporter (OpenClaw).** The biggest roster consumer: about 868k input, 56k output and 6.9M cache-read tokens across 11 dispatcher-launched sessions, spent on coding and retries. The cost is dominated by repeated context, not by output. Issue #12 (a one-line link fix) took four runs because of tool and configuration trouble (DELIVERY.md, section 6); Issue #14 and the PR #25 cleanup took seven more.
- **Copydesk (Hermes).** Two LLM reviews that got a response used 80k–127k input tokens each. Seven rate-limited attempts on the free Gemma model produced nothing and recorded no tokens. PR #25's review ran as a script and cost no LLM tokens.
- **Factcheck (OpenClaw).** One recorded LLM run (Issue #12, free Nemotron model, 38k input, marked `failed`). Its T2/T3 runs, and PR #25's scripted run, have no token data.
- **Interactive sessions.** The owner's Hermes and OpenClaw default sessions account for about 94% of all input tokens. They are separate from the team's ticket work and are reported for completeness.

**In plain words.** Almost all token volume is cache-read context: the same conversation re-read on every call. New text (input plus output) for the ticket work was about 1.6M tokens, and for the whole project about 27M. Coding (the reporter) and its retries dominate the team's spend; review and testing were small because the free models were rate-limited and PR #25 used scripts. The single largest block is the owner's interactive planning and debugging in Hermes.

---

## 5. Retry and failed-run usage

### 5.1 What the records support

| Run                                             | Runtime status | Input       | Output     | Cache-read    |
| ----------------------------------------------- | -------------- | ----------: | ---------: | ------------: |
| Reporter #12, `newsroom-reporter-12-1793506530` | failed         | 73,039      | 1,682      | 215,641       |
| Reporter #12, `newsroom-reporter-12-1793506714` | failed         | 39,819      | 2,052      | 335,517       |
| Reporter #12, `newsroom-reporter-12-1793508803` | failed         | 36,397      | 1,936      | 159,177       |
| Reporter #14, `newsroom-reporter-14-1793509000` | failed         | 66,028      | 5,331      | 556,568       |
| **Subtotal (marked** `failed`**)**              |                | **215,283** | **11,001** | **1,266,903** |

Also verified as wasted: the **seven Copydesk task sessions** (Issues #12 and #14) that failed with HTTP 429 and recorded zero. The real count is unknown. Dispatcher state for Issue #14 shows a rate-limited Copydesk failure and two infrastructure failures.

### 5.2 What the records do not support

- A run's `done` status does not mean it was not a retry. The dispatcher counts a run that exits 0 without moving labels as a failed attempt; the PR #25 cleanup had two such attempts, and the runtime stored them as normal sessions. Their tokens are in **Coding**, not Retries.
- Attempt numbers (`attempt:n`) are not stored in either runtime, so usage **cannot be attributed to a specific attempt**. Retry usage above is "runtime-marked failed", not "everything beyond attempt 1".
- Factcheck's run for #12 is also marked `failed`; it is counted once, under Review/testing.

### 5.3 Time-correlated candidates (not verified, not added to any ticket row)

The default reporter session of Nov 1–2 contains activity that lines up with the PR #25 work: 34 assistant messages in the 14:00–14:59 UTC hour on Nov 1 (126,583 input / 34,685 output / 2,535,170 cache-read), against a dispatcher log for the reporter's PR #25 run started at 14:48:50, and 3 messages in the 06:00 hour on Nov 2 (106,453 / 381 / 206,791). These are plausibly the PR #25 reporter run and the first cleanup attempts, but the runtime does not name them, so they remain in the unclassified total.

---

## 6. Totals and estimates

- **Measured (runtime-reported):** everything in the tables above, with input, output and cache-read kept separate. Totals are input + output unless labelled. If cache-read is included, the all-usage figure is 546,340,826 tokens (roster runs 10,727,474; interactive and unattributed 535,613,352), the way OpenClaw itself defines `totalTokens`.
- **Estimated:** nothing in the tables is an estimate. Agents' handoff-comment figures are not used. Hermes also stores estimated dollar costs from its own pricing table; they are not used here.
- **Unavailable:** seven Copydesk 429 sessions (0 recorded, true usage unknown); T0–T2 editor and copydesk; T2/T3 factcheck; product summarizer tokens; cost in money.
- **Not independently verified:** that Hermes's `gemini-2.5-flash` and OpenClaw's `google/gemini-2.5-flash` are the same model version; provider-side counts (cross-check against the OpenRouter and Google AI Studio usage pages was not done).
- **Not a billed cost.** Runtime token counts are not billing evidence. No dollar figure is claimed. Because most models were free-tier, billed cost is probably near zero, but that is not verified.
- **Consistency checks run:** OpenClaw `totalTokens = input + output + cache-read` on sampled sessions; Hermes session totals equal the main-work rows of `session_model_usage`; the per-ticket sums above were recomputed from raw message events, including events stored compressed, and match the figures in this report.

**Corrections to earlier reports.**

- The earlier estimate-only ledger (about 3,920 prompt / 1,870 completion tokens, model `qwen-2.5-coder-32b`) is superseded. **No runtime record shows** `qwen-2.5-coder-32b` **being used**, although six early commit trailers name it; treat that model as unsupported.
- A single "measured" figure of 32,423 input / 1,266 output / 73,637 cache-read quoted in an earlier `DELIVERY.md` was a diagnostic session (`diag-720865046`), not task usage. It is excluded.

---

## 7. Scope and exclusions

**Included.**

- Hermes sessions for the default, `editor` and `copydesk` profiles that were project work (planning, debugging, roster runs).
- OpenClaw sessions for the `reporter` and `factcheck` agents, including dispatcher runs, default and dashboard sessions, and three archived sessions.

**Excluded on purpose.**

- **Diagnostics and probes:** four OpenClaw `diag-`* reporter sessions (133,951 input in total) and one `probe-*` session (13,345 input); six Hermes ping or status sessions ("Reply with exactly…" style).
- **Unrelated work:** one Hermes session reviewing a personal document (271,557 input), which is in the same database and counted by `hermes insights`, but has nothing to do with this assignment.
- **Hermes auxiliary calls** (`title_generation`, `approval`, `background_review`): Hermes keeps them outside the session totals. For the Day-1 planning session alone they add about 0.95M input and 15.7M cache-read tokens. They are excluded here, so Hermes figures are slightly understated.
- Empty sessions with zero usage, and the OpenClaw default `main` system agent.

**Data-quality notes.** Two Hermes copydesk sessions and two interactive sessions have no end time and could grow after this export. OpenClaw's mixed-model sessions are split by message model; Hermes mixed-model sessions are split by `session_model_usage`. Reading another program's SQLite store is an internal detail that may change between versions.
