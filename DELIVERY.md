# Autonomous Newsroom delivery

**Status as of November 2, 2026 (12:27 UTC):** T0-T4 and the RSS-link fix (Issue #12 / PR #13) are merged. **PR #25 (Issue #14, CSS extraction) was merged by the owner at 11:49 UTC** (merge commit `b9cb077`, head `c892dd3`) and Issue #14 is closed. **PR #26 (Synapse branding) was merged at 12:25 UTC** (merge commit `93dce88`). PR #22, a broken duplicate UI-polish PR, was closed unmerged. Issues #15-#18 have not been worked through the agent workflow. The product is **deployed and publicly reachable at https://34.10.175.17.sslip.io/** (Google Cloud VM, owner-confirmed). That deployment has **not** been updated since these merges: a check at 12:27 UTC still showed the old title "Autonomous Newsroom" and no Synapse branding, so the mobile-nav fix (PR #25) and the Synapse branding (PR #26) are in `main` but not live. The Terraform in `infra/` targets Oracle Cloud and was **not** used for this deployment (its local state has networking resources only, no compute instance). Still outstanding: redeploying the VM from `main`, recorded evidence of the scheduled refresh running on the VM, and UI-polish tickets #15-#18.

## Handoff

- **Repository:** [Lakshmi-Sayyapureddy1819/autonomous-newsroom](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom)
- **Local preview:** `http://localhost:8000/` was open in the local browser when this handoff was prepared. This is not the required public URL.
- **Public URL:** https://34.10.175.17.sslip.io/ (HTTPS; `sslip.io` maps the VM's public IP `34.10.175.17` to a hostname so Caddy can obtain a Let's Encrypt certificate without a purchased domain).
- **Hosting method:** Google Cloud (GCP) VM, set up by the owner outside this repo's Terraform. The stack matches `deploy/`: Caddy (TLS and reverse proxy, `deploy/Caddyfile`) in front of uvicorn on `127.0.0.1:8000`, with the refresh job on a systemd timer (`deploy/systemd/`). The exact VM type, region and install steps were not recorded here; **owner to fill in**.
- **Smoke test (Nov 2, 2026, 11:16 UTC, run from this repo's Claude Code session):** `GET /` returned HTTP 200. `GET /rss.xml?format=xml` returned HTTP 200, `Content-Type: application/xml`, `Server: Caddy` / `uvicorn`, valid RSS with real articles and the channel link set to the public URL. The feed's `lastBuildDate` was Nov 2, 2026 10:04 UTC, about an hour earlier, which suggests the refresh is running. This session did **not** inspect the VM, so timer state, refresh interval and the boot-time refresh are unverified.
- **Re-check (Nov 2, 2026, 12:27 UTC, this session):** `GET /` returned HTTP 200 with 20 articles and "Updated 2 hours ago"; the title was still "Autonomous Newsroom — AI news, summarized" and the page contained no "Synapse". `GET /rss.xml` returned HTTP 200 with channel title "Autonomous Newsroom" and `lastBuildDate` still Mon, 02 Nov 2026 10:04:04 +0000, unchanged since the 11:16 UTC check. That is consistent with a refresh interval of several hours but is not proof of a working timer.
- **Deployment status:** Deployed on GCP and reachable. The earlier Oracle VM and Cloudflare Quick Tunnel plans were not used. **Known gap:** the live site runs an older build. The mobile-nav fix (in PR #25 head `c892dd3`) and the Synapse branding (PR #26) are in `main` but have not been redeployed; the redeploy steps for the VM are not recorded here.

## Agent roster and split

| Agent | Runtime | Role | Models evidenced in the repo history | Tools / boundary |
|---|---|---|---|---|
| editor | Hermes | Creates Issues, assigns work, routes retries, escalates blockers | `google/gemini-3.8-flash`, `google/gemini-3.7-flash` appear in handoff estimates | `gh` Issues/comments/labels; no product edits or merges |
| reporter | OpenClaw | Implements one assigned Issue and opens/updates its PR | `google/gemini-2.5-flash` (confirmed by runtime records); `qwen-2.5-coder-32b` appears in 6 commit trailers but in no runtime record | Git, `gh`, shell, files; no merge |
| copydesk | Hermes | Reviews every PR against its Issue criteria | `gemini-2.5-flash` appears in an Issue #7 review handoff | PR diff, comments, review labels; no push or merge |
| factcheck | OpenClaw | Independently tests the PR head and reports evidence | `gemini-2.5-flash` appears in an Issue #7 test handoff | Checkout, tests, lint, runtime commands, verdict labels; no push or merge |
| human (Lakshmi) | — | Owns credentials and infrastructure; merges after gates | — | Terraform apply, secrets, branch protection, final merge |

The split makes the work inspectable: OpenClaw builds and tests, Hermes plans and reviews, and GitHub Issues/PRs carry the handoffs and gate labels. Model names above are taken from commit trailers or comments; they are not a claim that every invocation used the same model.

## Ticket to merged code

```text
Need / brief
  → Editor writes a checkable Issue and assigns Reporter
  → Reporter claims it, branches, implements, tests, and opens a PR
  → Copydesk reviews each acceptance criterion and requests changes or approves
  → Factcheck checks out the PR head and reports independent evidence
  → Editor routes failures/retries on the same Issue and PR
  → GitHub CI + review/test labels gate the PR
  → Lakshmi merges; the Issue closes
```

## What the team delivered

- **T0, README roster:** Issue #1 / PR #2 documents the four roles and runtimes.
- **T1, app scaffold:** Issue #3 / PR #4 adds the installable Python package, SQLite schema, and test harness.
- **T2, RSS collector:** Issue #5 / PR #6 adds fixture-based collection and run tracking. Copydesk found malformed-feed and timestamp gaps, the editor routed attempt 2, and Factcheck recorded a passing result.
- **T3, summarizer:** Issue #7 / PR #8 adds structured summaries, tags, fallback, model attribution, and offline tests. Copydesk rejected attempt 1 for unsafe handling of empty/invalid summaries. Reporter fixed it on the same PR; Factcheck then recorded 40 passing tests and a clean Ruff run.
- **T4, public page:** Issue #9 / PR #10 adds the server-rendered list page and RSS endpoint. The PR body records 43 passing tests and a clean Ruff check.

- **RSS fix:** Issue #12 / PR #13 fixed the hard-coded `localhost` channel link. Copydesk requested a test revert first, which the Reporter applied.
- **UI polish:** Issue #14 / PR #25 (merged) moves CSS to `static/styles.css` (about 760 lines out of `base.html`, plus 4 lines in `main.py` to serve static files). Its final head also carries a mobile-nav CSS fix, brand assets, docs and infra changes (see "PR #25 scope update"). Issues #15-#18 have not started.
- **Synapse branding:** PR #26 (merged) renames the site to Synapse and serves the logo files from `app/newsroom/static/brand/` (see "PR #26" below).

## How the gates actually ran (read this before trusting the labels)

Free-tier models hit HTTP 429 repeatedly (see `agents/traces/t4-dispatcher-429.md`). For later PRs the dispatcher was run with `NEWSROOM_REVIEW_MODE=deterministic`, so **PR #25's Copydesk and Factcheck verdicts came from scripts (`agents/scripts/copydesk_agent.py`, `factcheck_agent.py`), not from an LLM reading the acceptance criteria**. Copydesk checks only: one linked Issue, not a draft, no conflicts, `ci` green. Factcheck runs ruff and pytest on the exact PR head. The LLM-driven review/test that rejected T2 and T3 (and PR #13) ran earlier, on Hermes and OpenClaw. Issue #14 also reached `status:blocked` once after three failed Copydesk invocations (rate limits) before a human re-routed it. **The merged head `c892dd3` has no recorded review or test run:** the last copydesk/factcheck comments on PR #25 are for `7f74fd7` and `b7d183f`, yet the PR carried `review:approved` and `test:passed` when it was merged, and `ci` and `gate` passed. This session did not set those labels on `c892dd3` and cannot show who or what did.

Known problems in PR #25 (original commit `3f57733`): it added unrelated files (`pr19/20/21_diff_vs_main.txt`, `.dispatcher-validation/locks/reporter.lock`, brand assets, runbook, Hermes reference notes); those were removed by the reporter's cleanup commit `7f74fd7` (below). **Still true:** `3f57733` carries `Co-authored-by: Lakshmi <Lakshmi_Sayyapureddy1819@users.noreply.github.com>` instead of the protocol's `reporter (openclaw) <reporter@newsroom.agents>`. It stays because the protocol forbids amending or force-pushing pushed commits; `ci` trailer-check still passes. Main also carries `jq.exe` and `desktop.ini`.

## PR #25 scope update (November 2, 2026, owner decision)

After the agent cleanup below, a human-directed revert (`b7d183f`, made in this Claude Code session at the owner's request) restored the intentionally authored files. A further commit, `c892dd3` ("feat(styling): complete T14 scope - mobile nav, delivery docs, infra fault_domain"), was then pushed to the PR branch. It carries agent trailers (`Agent: reporter`, `Model: google/gemini-2.5-flash`) but this session cannot verify who created it, and it was the head that got merged. What `main` contains as a result: the CSS extraction, a 6-line mobile-nav CSS fix, brand assets (`docs/brand/*`), `docs/brief-ui-polish.md`, `docs/DEPLOYMENT_RUNBOOK.md`, agent traces, an earlier `DELIVERY.md`, the Terraform `fault_domain` option and `infra/.terraform.lock.hcl`, and four dispatcher run-state files under `.dispatcher-validation/` (`issue-14.json` and three logs). `c892dd3` removed `pr19/20/21_diff_vs_main.txt` and `reporter.lock`. **The two `autonomous-ai-agents/` Hermes note files were not removed and are on `main`**, as are `jq.exe` and `desktop.ini`. The statements below about "3 intended files" describe head `7f74fd7` only and are kept as history.

## PR #25 cleanup and re-review (November 2, 2026)

**Facts verified on GitHub/git in this session**

- **Cleanup commit:** `7f74fd7` ("chore(pr25): remove unrelated and generated files from PR scope") deletes 16 files (11,658 lines), changes no app file, and carries the protocol trailers (`Agent: reporter`, `Runtime: openclaw`, `Model: google/gemini-2.5-flash`, `Ticket: #14`, `Co-authored-by: reporter (openclaw)`). PR #25 now lists exactly `app/newsroom/main.py`, `app/newsroom/static/styles.css`, `app/newsroom/templates/base.html`.
- **LLM agent work:** the reporter (OpenClaw, `google/gemini-2.5-flash`) made that commit and wrote its handoff comments. It took **three dispatcher attempts**: attempts 1 and 2 exited 0 but changed nothing (attempt 1 claimed the work was already done from stale session memory; attempt 2 asked for the file list because it could not read the Issue). Attempt 3 (cleanup file list inline in the prompt) succeeded.
- **Root cause of the failures (OpenClaw working-directory bug):** `~/.openclaw/openclaw.json` set the reporter's `cwd` to `C:UsersYasaswiniautonomous-newsroom-t4` (backslashes stripped, and pointing at an old worktree). Every `exec` call failed with `workdir unavailable`, so the agent could not run `git`, `gh` or a shell. A first diagnostic run falsely reported PASS for all checks; a stricter rerun exposed the failures. **Fix:** the one `cwd` line was changed to `C:/Users/Yasaswini/nr-pr25-clean` (config backed up first, outside the repo). A rerun diagnostic then showed real output (`gh` authenticated, git 2.53.0, HEAD `3f57733`, Issue comment readable). **Caveat:** that `cwd` now points at a temporary clean clone and must be repointed for future tickets.
- **Scripted (non-LLM) review and test:** `NEWSROOM_REVIEW_MODE=deterministic`, so `review:approved` came from `copydesk_agent.py` (one linked Issue, not a draft, no conflicts, `ci` green) and `test:passed` came from `factcheck_agent.py` (ruff and pytest on the exact head `7f74fd7`). These are **not** LLM Copydesk/Factcheck reviews against the acceptance criteria. The LLM Hermes copydesk could not be used because of OpenRouter rate limits.
- **Two false test failures first:** the first two factcheck runs wrote `test:failed` (`Ruff check failed on the PR head.`). `uv run ruff check app/` passes on that commit when run by hand; the failures came from running the dispatcher with a virtualenv's Python, which made `uv`'s build subprocess load the wrong standard library (`SRE module mismatch`). Re-running the dispatcher with the plain `py` interpreter produced a genuine `test:passed`. The failed-verdict comments remain on the PR as record.
- **Manual label actions (human-authorized, done by the Claude Code session, not by an agent):** stale `review:approved`/`test:passed` were removed from PR #25 before cleanup; Issue #14 was relabeled `status:ready` + `agent:reporter` (from `status:ready-to-merge`) to wake the reporter; and `test:failed` plus the editor re-route were reset twice for the factcheck reruns.
- **State at that head (`7f74fd7`, history):** `ci` pass, `gate` pass, labels `review:approved` + `test:passed`. This was superseded: `b7d183f` reverted the cleanup, the scripted copydesk approved `b7d183f`, the scripted factcheck run for `b7d183f` was interrupted by network errors and never produced a verdict, and the PR was merged at head `c892dd3` (see the scope update). Issue #14 is closed.
- **Local test evidence (clean clone, same app files as the PR head):** `ruff check app/` clean; `pytest app/tests` 67 passed, 1 skipped; `pytest agents/dispatcher/tests` 46 passed. The dispatcher tests use fake GitHub and fake agents, so they test the dispatcher logic, not the live agents.

**Not done / not claimed:** the live-agent handoff for the final cleanup attempt has no token figures ("estimate not available"); the skipped test was not investigated; the scheduled-refresh evidence on the GCP VM (timer status, run history) is not recorded here.

## PR #26: Synapse branding (November 2, 2026)

- **What:** PR #26 (head `4b4f629`, merged 12:25 UTC as `93dce88`, 14 files) adds `SITE_NAME = "Synapse"` and `SITE_TAGLINE = "Every AI story, in one line"` and uses them in page titles, meta/og tags, the RSS link, header, footer, the error/runs/feed pages, and the RSS channel title and description. The six logo and wordmark files are served from `app/newsroom/static/brand/` (header mark, favicon, light/dark footer wordmark). Three tests were added (brand name and tagline on all pages, RSS title, logo assets linked and served).
- **Origin of the change:** the branding parts were ported from a local-only branch, `validate/workflow-wip` (never pushed to GitHub; backed up as a git bundle outside the repo). Its unrelated parts (dispatcher, infra, docs, a JS refactor) were not ported. PR #22, which was meant to carry UI polish, contained no Synapse content and its files sat under a broken `UsersYasaswiniautonomous-newsroom-t4/` path (the same broken working-directory setting described above), so it was closed unmerged.
- **Not agent-authored:** this was a human-directed change made with Claude Code, not by the reporter. Its commit trailers say `Agent: human`, `Runtime: claude-code`, `Model: claude-sonnet-5-5`, `Ticket: none`. There was no Copydesk or Factcheck review.
- **Why the gate passed without verdict labels:** PR #26 closes no Issue, so the gate (`.github/scripts/gate_decide.sh`) treats it as a maintenance PR and does not require `review:approved` or `test:passed`. `ci` (secret scan, author/trailer check, ruff, pytest) and `gate` both passed.
- **Verified before merge:** `ruff check app/` clean; `pytest app/tests` 70 passed, 1 skipped. On a local copy of the database the page returned HTTP 200 with 20 articles, the title "Synapse — Every AI story, in one line", the logo, wordmark, CSS, RSS and runs URLs returned 200, and no "Autonomous Newsroom" text remained on the page.
- **Not verified / not done:** the visual appearance was not checked by the assistant (no browser view was available to it), and the live VM has not been redeployed with this change.

## Real review/retry evidence

- [Copydesk's T3 blocking review on Issue #7](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6516849264) found that empty or malformed summaries could be stored as successful output.
- [Editor routed T3 attempt 2 on the existing PR](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6516885679). The comment records estimated editor usage; it does not claim an exact provider measurement.
- [Factcheck's T3 result](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6540142986) records 40 passing tests, clean Ruff, and the exact PR head checked.
- A separate real retry is recorded for [the T2 collector on Issue #5](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/5), where review found missing malformed-feed/timestamp handling before the second attempt passed.

The short excerpts in [agents/traces/t3-attempt2.md](agents/traces/t3-attempt2.md) point to the original comments. No rejection or test result was invented for this handoff.

## Models and tokens

**Why this was incomplete.** The dispatcher did not capture usage when runs finished, and agents could only estimate their own usage in handoff comments. Those estimates were far too low. On Nov 2, 2026 the usage was recovered read-only from the runtimes' own stores (Hermes `state.db` per profile; OpenClaw per-agent session database with a usage object on each assistant message). The method and caveats are in [TOKEN_USAGE_AUDIT.md](TOKEN_USAGE_AUDIT.md), and the figures are in [docs/token-report.md](docs/token-report.md).

**Measured (runtime-reported, not provider billing):** examples, all in input / output / cache-read tokens:
- Reporter (OpenClaw, `google/gemini-2.5-flash`), Issue #12, 4 runs (3 marked failed): 392,419 / 24,744 / 3,383,882.
- Reporter, Issue #14, 5 runs: 436,908 / 28,671 / 3,300,036. PR #25 cleanup, 2 runs: 39,037 / 2,295 / 188,113.
- Copydesk (Hermes, `gemini-2.5-flash`), Issue #12 review: 79,485 / 7,534 / 237,381. Issue #7 attempt-2 review: 126,692 / 9,191 / 180,435.
- Editor (Hermes, `nvidia/nemotron-3-ultra-550b-a55b:free`), UI-polish tickets: 442,006 / 8,792 / 1,563,840.

Cache-read tokens are context re-read on every call, not new text. The scripted copydesk/factcheck runs use no LLM tokens. The earlier "measured" figure here (32,423 / 1,266 / 73,637) was a diagnostic session and is not task usage, so it is no longer used as such.

**Corrections and gaps.**
- The earlier estimate ledger named `qwen-2.5-coder-32b` for the reporter. No runtime record shows that model being used, so treat that trailer value as unsupported.
- Eight Hermes copydesk sessions (Issues #12 and #14) failed with HTTP 429 and recorded 0 tokens. The real count is unknown.
- No session was found for the early T0-T2 editor and copydesk work or the T2/T3 factcheck runs.
- No provider billing export was checked, so no dollar cost is claimed. Hermes stores an estimated cost only.
- Long default reporter sessions mix several tickets and are reported separately, not assigned to one ticket.

## Reproduce locally (works today)

From the repository root, with Python 3.12+ and `uv`:

1. Lint and test exactly as CI does: `uv run --project app --extra dev ruff check app/` and `uv run --project app --extra dev pytest app/tests/` (70 passed, 1 skipped on the PR #26 head). Dispatcher tests: `python -m pytest agents/dispatcher/tests -q` (46 passed; needs `pytest`).
2. Start the app: `uvicorn app.newsroom.main:app --port 8000` (from the handoff comment on Issue #14; this session did not re-verify the page contents).
3. Open `http://localhost:8000/`. This is a local check only, not a public deployment.

To reproduce the agent workflow: run `bash agents/dispatcher/dispatch.sh --dry-run`, then without `--dry-run`. For deterministic review/test set `NEWSROOM_REVIEW_MODE=deterministic`. On Windows, run the dispatcher with the plain system Python, not a virtualenv's Python (see the `SRE module mismatch` note above).

## Reproduce the repository setup

1. Configure OCI credentials locally and fill `infra/terraform.tfvars` from the ignored example. Select and pin an Ubuntu 24.04 aarch64 image OCID for the chosen region.
2. From the repository root, review and apply the plan: `terraform -chdir=infra init`, `terraform -chdir=infra validate`, `terraform -chdir=infra plan`, then `terraform -chdir=infra apply`.
3. SSH to the Ubuntu instance and run `sudo bash agents/bootstrap.sh`. Authenticate `gh` and configure provider credentials locally for the agent runtimes. The bootstrap script does not embed secrets.
4. Install `agents/dispatcher/dispatcher.service` and `dispatcher.timer`, start role-specific tmux sessions, and enable the timer.
5. Install the product from the repo using `sudo bash deploy/install.sh`. Put summarizer credentials only in `/etc/newsroom.env`; open 80/443 in the OCI security list and verify the refresh timer.
6. Visit the resulting public URL and confirm that several stories load and the page reports a recent refresh. Record that URL and the command/output in this document.

The steps above describe the Oracle/Terraform path, which was not applied. The product was instead deployed on a GCP VM (see Handoff); the `deploy/` scripts and the Caddy/systemd layout are the same.

## Runtime dashboards

Bind each runtime dashboard to loopback on the VM. After checking the actual configured ports with the runtime status commands, create an SSH tunnel from your workstation:

```bash
ssh -L <local-port>:127.0.0.1:<runtime-port> ubuntu@<public-ip>
```

Open `http://127.0.0.1:<local-port>` locally. Keep dashboard ports closed to public ingress.

## What I would improve

- Capture every agent's usage in the dispatcher at the end of each invocation (Hermes `--usage-file`; OpenClaw session usage), keyed by agent, ticket, attempt and model, instead of relying on agent estimates. Reconcile with provider dashboards.
- Keep sanitized trace excerpts in the repository alongside the original GitHub links.
- Verify the product on the VM after provisioning, including the actual HTTPS URL, timer state, and persisted SQLite data.
- Dedupe is by URL (`articles.url UNIQUE`) and by normalized headline (`title_key` in `collector.py`, against the latest 2,000 stored titles); paraphrased stories from different outlets are not merged.
- Give Copydesk a real criteria-reading review that still works when the free model is rate limited, rather than a mechanical fallback.
- Keep stray files out of agent PRs (a path allowlist in `ci`).
