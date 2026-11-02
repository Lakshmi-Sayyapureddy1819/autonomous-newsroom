# Autonomous Newsroom delivery

**Status as of November 2, 2026:** T0-T4 and the RSS-link fix (Issue #12 / PR #13) are merged. The UI-polish tickets #14-#18 are still open; PR #25 (Issue #14) is open and awaiting the human review and merge (not merged by the agents). Its scope was widened by the owner after the agent cleanup to also carry the brand assets, docs, traces and infra changes listed under "PR #25 scope update"; `ci`/`gate` results quoted below were for the earlier 3-file head `7f74fd7` and must be re-checked on the final head. Terraform in `infra/` has created only networking resources (the local state has no compute instance), so **no VM exists and there is no public URL**. **Public deployment is postponed**: neither the Oracle VM nor the Cloudflare Quick Tunnel fallback has been done, and `cloudflared` is not installed on this machine. The product runs locally; the live-refresh evidence on a public host is outstanding.

## Handoff

- **Repository:** [Lakshmi-Sayyapureddy1819/autonomous-newsroom](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom)
- **Local preview:** `http://localhost:8000/` was open in the local browser when this handoff was prepared. This is not the required public URL.
- **Public URL:** Not available. Deployment is postponed (owner decision, Nov 2, 2026). Fill this only after a public smoke test succeeds (HTTP 200, article list, summaries, source links, updated timestamp).
- **Hosting method:** None yet. Planned: Oracle VM via Terraform + Caddy; the assignment-permitted fallback is a Cloudflare Quick Tunnel to `localhost:8000`, which only works while the tunnel process and this computer stay running. Neither has been run.
- **Deployment status:** Not verified on OCI or via a tunnel. Do not describe the Terraform plan as an applied VM or the local preview as a public deployment.

## Agent roster and split

| Agent | Runtime | Role | Models evidenced in the repo history | Tools / boundary |
|---|---|---|---|---|
| editor | Hermes | Creates Issues, assigns work, routes retries, escalates blockers | `google/gemini-3.8-flash`, `google/gemini-3.7-flash` appear in handoff estimates | `gh` Issues/comments/labels; no product edits or merges |
| reporter | OpenClaw | Implements one assigned Issue and opens/updates its PR | `qwen-2.5-coder-32b`, `google/gemini-2.5-flash` appear in commit trailers | Git, `gh`, shell, files; no merge |
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
- **UI polish (open):** Issue #14 / PR #25 moves CSS to `static/styles.css` (about 760 lines out of `base.html`, plus 4 lines in `main.py` to serve static files). Issues #15-#18 have not started. See "PR #25 cleanup and re-review" below.

## How the gates actually ran (read this before trusting the labels)

Free-tier models hit HTTP 429 repeatedly (see `agents/traces/t4-dispatcher-429.md`). For later PRs the dispatcher was run with `NEWSROOM_REVIEW_MODE=deterministic`, so **PR #25's Copydesk and Factcheck verdicts came from scripts (`agents/scripts/copydesk_agent.py`, `factcheck_agent.py`), not from an LLM reading the acceptance criteria**. Copydesk checks only: one linked Issue, not a draft, no conflicts, `ci` green. Factcheck runs ruff and pytest on the exact PR head. The LLM-driven review/test that rejected T2 and T3 (and PR #13) ran earlier, on Hermes and OpenClaw. Issue #14 also reached `status:blocked` once after three failed Copydesk invocations (rate limits) before a human re-routed it.

Known problems in PR #25 (original commit `3f57733`): it added unrelated files (`pr19/20/21_diff_vs_main.txt`, `.dispatcher-validation/locks/reporter.lock`, brand assets, runbook, Hermes reference notes); those were removed by the reporter's cleanup commit `7f74fd7` (below). **Still true:** `3f57733` carries `Co-authored-by: Lakshmi <Lakshmi_Sayyapureddy1819@users.noreply.github.com>` instead of the protocol's `reporter (openclaw) <reporter@newsroom.agents>`. It stays because the protocol forbids amending or force-pushing pushed commits; `ci` trailer-check still passes. Main also carries `jq.exe` and `desktop.ini`.

## PR #25 scope update (November 2, 2026, owner decision)

After the agent cleanup below, the owner restored the intentionally authored, non-generated files to PR #25 (the cleanup had removed them with the stray files; `b7d183f` reverted it on the remote). The final PR keeps: the CSS extraction (`app/newsroom/static/styles.css`, `base.html`, `main.py`), brand assets (`docs/brand/*`), `docs/brief-ui-polish.md`, `docs/DEPLOYMENT_RUNBOOK.md`, agent evidence (`agents/traces/t2-attempt2.md`, `t4-dispatcher-429.md`), this file, and the Terraform `fault_domain` option plus `infra/.terraform.lock.hcl`. It deliberately drops `pr19/20/21_diff_vs_main.txt`, `.dispatcher-validation/locks/reporter.lock`, and the `autonomous-ai-agents/` note files. The statements below about "3 intended files" describe head `7f74fd7` only and are kept as history.

## PR #25 cleanup and re-review (November 2, 2026)

**Facts verified on GitHub/git in this session**

- **Cleanup commit:** `7f74fd7` ("chore(pr25): remove unrelated and generated files from PR scope") deletes 16 files (11,658 lines), changes no app file, and carries the protocol trailers (`Agent: reporter`, `Runtime: openclaw`, `Model: google/gemini-2.5-flash`, `Ticket: #14`, `Co-authored-by: reporter (openclaw)`). PR #25 now lists exactly `app/newsroom/main.py`, `app/newsroom/static/styles.css`, `app/newsroom/templates/base.html`.
- **LLM agent work:** the reporter (OpenClaw, `google/gemini-2.5-flash`) made that commit and wrote its handoff comments. It took **three dispatcher attempts**: attempts 1 and 2 exited 0 but changed nothing (attempt 1 claimed the work was already done from stale session memory; attempt 2 asked for the file list because it could not read the Issue). Attempt 3 (cleanup file list inline in the prompt) succeeded.
- **Root cause of the failures (OpenClaw working-directory bug):** `~/.openclaw/openclaw.json` set the reporter's `cwd` to `C:UsersYasaswiniautonomous-newsroom-t4` (backslashes stripped, and pointing at an old worktree). Every `exec` call failed with `workdir unavailable`, so the agent could not run `git`, `gh` or a shell. A first diagnostic run falsely reported PASS for all checks; a stricter rerun exposed the failures. **Fix:** the one `cwd` line was changed to `C:/Users/Yasaswini/nr-pr25-clean` (config backed up first, outside the repo). A rerun diagnostic then showed real output (`gh` authenticated, git 2.53.0, HEAD `3f57733`, Issue comment readable). **Caveat:** that `cwd` now points at a temporary clean clone and must be repointed for future tickets.
- **Scripted (non-LLM) review and test:** `NEWSROOM_REVIEW_MODE=deterministic`, so `review:approved` came from `copydesk_agent.py` (one linked Issue, not a draft, no conflicts, `ci` green) and `test:passed` came from `factcheck_agent.py` (ruff and pytest on the exact head `7f74fd7`). These are **not** LLM Copydesk/Factcheck reviews against the acceptance criteria. The LLM Hermes copydesk could not be used because of OpenRouter rate limits.
- **Two false test failures first:** the first two factcheck runs wrote `test:failed` (`Ruff check failed on the PR head.`). `uv run ruff check app/` passes on that commit when run by hand; the failures came from running the dispatcher with a virtualenv's Python, which made `uv`'s build subprocess load the wrong standard library (`SRE module mismatch`). Re-running the dispatcher with the plain `py` interpreter produced a genuine `test:passed`. The failed-verdict comments remain on the PR as record.
- **Manual label actions (human-authorized, done by the Claude Code session, not by an agent):** stale `review:approved`/`test:passed` were removed from PR #25 before cleanup; Issue #14 was relabeled `status:ready` + `agent:reporter` (from `status:ready-to-merge`) to wake the reporter; and `test:failed` plus the editor re-route were reset twice for the factcheck reruns.
- **Final state:** PR #25 head `7f74fd7`: `ci` pass, `gate` pass, labels `review:approved` + `test:passed`, mergeable and clean, **open, not merged**. Issue #14 shows `status:ready-to-merge`.
- **Local test evidence (clean clone, same app files as the PR head):** `ruff check app/` clean; `pytest app/tests` 67 passed, 1 skipped; `pytest agents/dispatcher/tests` 46 passed. The dispatcher tests use fake GitHub and fake agents, so they test the dispatcher logic, not the live agents.

**Not done / not claimed:** the live-agent handoff for the final cleanup attempt has no token figures ("estimate not available"); the skipped test was not investigated; no public URL exists.

## Real review/retry evidence

- [Copydesk's T3 blocking review on Issue #7](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6516849264) found that empty or malformed summaries could be stored as successful output.
- [Editor routed T3 attempt 2 on the existing PR](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6516885679). The comment records estimated editor usage; it does not claim an exact provider measurement.
- [Factcheck's T3 result](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6540142986) records 40 passing tests, clean Ruff, and the exact PR head checked.
- A separate real retry is recorded for [the T2 collector on Issue #5](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/5), where review found missing malformed-feed/timestamp handling before the second attempt passed.

The short excerpts in [agents/traces/t3-attempt2.md](agents/traces/t3-attempt2.md) point to the original comments. No rejection or test result was invented for this handoff.

## Models and tokens

**Measured (runtime-reported):** one OpenClaw reporter diagnostic run on `google/gemini-2.5-flash` (Nov 2, 2026, after the `cwd` fix) reported 32,423 input / 1,266 output / 73,637 cache-read tokens (107,326 total, cost 0). This is that single diagnostic run only. **Not recorded:** token usage of the three reporter dispatcher attempts for the PR #25 cleanup (their handoff says "estimate not available"). The scripted copydesk/factcheck runs use no LLM tokens.

**Estimates:** the available handoff estimates are summarized in [docs/token-report.md](docs/token-report.md). They cover only some T0-T3 comments. Copydesk and Factcheck numeric totals, T3 attempt-2 Reporter usage, T4 totals, and provider billing exports are not recorded in the inspected evidence. Replace the partial report with runtime exports if available; keep all estimates labeled.

## Reproduce locally (works today)

From the repository root, with Python 3.12+ and `uv`:

1. Lint and test exactly as CI does: `uv run --project app --extra dev ruff check app/` and `uv run --project app --extra dev pytest app/tests/` (67 passed, 1 skipped when last run). Dispatcher tests: `python -m pytest agents/dispatcher/tests -q` (46 passed; needs `pytest`).
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

Terraform was not applied for this handoff. The deployment scripts and cloud-init configuration are source artifacts, not proof of a running VM.

## Runtime dashboards

Bind each runtime dashboard to loopback on the VM. After checking the actual configured ports with the runtime status commands, create an SSH tunnel from your workstation:

```bash
ssh -L <local-port>:127.0.0.1:<runtime-port> ubuntu@<public-ip>
```

Open `http://127.0.0.1:<local-port>` locally. Keep dashboard ports closed to public ingress.

## What I would improve

- Capture every agent's usage from the runtime at the end of each turn and export a complete, model-by-stage report.
- Keep sanitized trace excerpts in the repository alongside the original GitHub links.
- Verify the product on the VM after provisioning, including the actual HTTPS URL, timer state, and persisted SQLite data.
- Dedupe is URL-only (`articles.url UNIQUE`); near-identical stories from different outlets are not merged.
- Give Copydesk a real criteria-reading review that still works when the free model is rate limited, rather than a mechanical fallback.
- Keep stray files out of agent PRs (a path allowlist in `ci`).
