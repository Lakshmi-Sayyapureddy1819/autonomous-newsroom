# Autonomous Newsroom delivery

**Status as of October 31, 2026:** the core product code for T0-T4 is present and merged in the GitHub history. Deployment artifacts, Terraform, and setup materials are now present in this working tree. The VPS has not been provisioned or publicly verified from this workspace, so a live URL and live-refresh evidence are still outstanding.

## Handoff

- **Repository:** [Lakshmi-Sayyapureddy1819/autonomous-newsroom](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom)
- **Local preview:** `http://localhost:8000/` was open in the local browser when this handoff was prepared. This is not the required public URL.
- **Public URL:** Not available yet. Fill this after the VM is provisioned, Caddy is serving the app, and a public smoke test succeeds.
- **Deployment status:** Not verified on OCI. Do not describe the Terraform plan as an applied VM or the local preview as a public deployment.

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

The local working tree also contains newer page/test edits and deployment files that are not yet part of a merged GitHub commit. They should be handled through the repo's normal PR workflow before being presented as merged deliverables.

## Real review/retry evidence

- [Copydesk's T3 blocking review on Issue #7](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6516849264) found that empty or malformed summaries could be stored as successful output.
- [Editor routed T3 attempt 2 on the existing PR](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6516885679). The comment records estimated editor usage; it does not claim an exact provider measurement.
- [Factcheck's T3 result](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7#issuecomment-6540142986) records 40 passing tests, clean Ruff, and the exact PR head checked.
- A separate real retry is recorded for [the T2 collector on Issue #5](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/5), where review found missing malformed-feed/timestamp handling before the second attempt passed.

The short excerpts in [agents/traces/t3-attempt2.md](agents/traces/t3-attempt2.md) point to the original comments. No rejection or test result was invented for this handoff.

## Models and tokens

The available handoff estimates are summarized in [docs/token-report.md](docs/token-report.md). They cover only some T0-T3 comments. Copydesk and Factcheck numeric totals, T3 attempt-2 Reporter usage, T4 totals, and provider billing exports are not recorded in the inspected evidence. Replace the partial report with runtime exports if available; keep all estimates labeled.

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
- Fix the RSS channel's hard-coded `localhost` site link through the Reporter workflow before publishing the feed.
