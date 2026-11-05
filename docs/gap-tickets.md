# Gap tickets for the agent team (DRAFT, nothing submitted)

These are the remaining delivery gaps written as tickets in the PROTOCOL.md format
(Goal / Acceptance criteria / Out of scope / Depends on). Each one is meant to go through the
normal flow: Editor opens the Issue, Reporter builds a PR, Copydesk reviews, Factcheck tests,
the owner merges.

**How to submit one** (the Editor writes the Issue; do not create Issues by hand):

```bash
bash agents/demo/run_local_demo.sh --preflight-only
python agents/dispatcher/submit_task.py --task-file docs/gap-tickets/G1.txt   # or paste the one-liner
bash agents/dispatcher/dispatch.sh                                            # drive it
```

Use the **Task** line under each ticket as the one-sentence input; the Editor expands it into
the full ticket shown here. Submit one ticket at a time and merge before the next, as the
dependency column says. Keep them small: the Reporter did best on narrow tickets (#35, #37).

| # | Ticket | Depends on | Needs owner input |
|---|---|---|---|
| G1 | GCP Terraform for the VM that hosts the site | none | project id and SSH key at apply time |
| G2 | `deploy/update.sh` redeploy script | none | run it on the VM afterwards |
| G3 | Per-agent commit helper and PROTOCOL note | none | none |
| G4 | Dispatcher captures token usage per run | none | none |
| G5 | CI path allowlist for agent PRs | none | none |
| G6 | Dispatcher clears `agent:*` labels when a ticket closes | none | none |
| G7 | Per-agent GitHub identity (`GH_TOKEN` per agent) | G3 | one GitHub account or token per agent |

Note on the existing branch: `fix/close-delivery-gaps` (commit `e2bc514`) already contains
hand-made versions of G1, G2 and G3, written in a Claude Code session. If you want these
credited to the agents, do **not** merge those files; let the agents rebuild them from the
tickets below (the files can serve as a reference for review, not as the deliverable).

---

## G1: GCP Terraform for the site VM

**Task:** Add Terraform in `infra/gcp/` that creates the Ubuntu 24.04 VM, reserved IP and firewall rules for the newsroom site on Google Cloud, and a startup script that clones this repo and runs `deploy/install.sh`.

### Goal
Make the VM that actually serves the site reproducible with Terraform, since the Oracle config in `infra/` was never applied.

### Acceptance criteria
- [ ] `infra/gcp/` contains `versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`, a startup template and `terraform.tfvars.example`.
- [ ] `terraform -chdir=infra/gcp init -backend=false && terraform -chdir=infra/gcp validate` passes, and `terraform fmt -check -recursive infra/gcp` passes.
- [ ] Firewall allows 80/443 from anywhere and 22 only from a `ssh_allowed_cidr` variable (no default of `0.0.0.0/0`).
- [ ] No secret, key, project id or IP address is committed; `*.tfvars` and state stay git-ignored.
- [ ] Startup script is idempotent and passes `bash -n` after rendering; `.tftpl` files keep LF line endings.
- [ ] `infra/gcp/README.md` gives the apply steps and says it has not been applied.
- [ ] Commits carry the five trailers.

### Out of scope
Running `terraform apply`; changing the Oracle files in `infra/`; app or dispatcher code.

### Depends on
none

---

## G2: Redeploy script

**Task:** Add `deploy/update.sh` that fetches a git ref (default `main`) and re-runs the idempotent `deploy/install.sh`.

### Goal
Let the owner update the live VM to the latest `main` with one command.

### Acceptance criteria
- [ ] `deploy/update.sh` exists, is executable, uses `set -euo pipefail`, and defaults the ref to `main`.
- [ ] `bash -n deploy/update.sh` passes and the file has LF endings (covered by `.gitattributes`).
- [ ] The script does not overwrite `/etc/newsroom.env` (it only calls `install.sh`, which already preserves it).
- [ ] `docs/DEPLOYMENT_RUNBOOK.md` has a short "Updating the VM" section naming the script.

### Out of scope
Running it on the VM; changing `install.sh`.

### Depends on
none

---

## G3: Per-agent commit helper

**Task:** Add `agents/scripts/agent_commit.sh` that commits as a given agent (distinct git author per agent) and appends the five trailers, and document it in `agents/PROTOCOL.md`.

### Goal
Make `git log --format=%an` show which agent made each new commit.

### Acceptance criteria
- [ ] `agents/scripts/agent_commit.sh <agent> <runtime> <model> <ticket#> <subject> [body]` commits with author and committer `<agent> (<runtime>) <agent>@newsroom.agents`.
- [ ] Only `editor|reporter|copydesk|factcheck` are accepted; anything else exits non-zero without committing.
- [ ] It uses per-command environment variables and never runs `git config`.
- [ ] The commit body ends with `Co-authored-by`, `Agent`, `Runtime`, `Model` and `Ticket` trailers.
- [ ] A shell test in `agents/dispatcher/tests/` (or `.github/scripts/`) creates a temp repo, runs the helper and asserts the author and all five trailers.
- [ ] `agents/PROTOCOL.md` documents the helper and says existing history is not rewritten.

### Out of scope
Rewriting existing commits; changing the CI trailer check.

### Depends on
none

---

## G4: Token usage capture in the dispatcher

**Task:** Make the dispatcher record token usage for every agent run (agent, ticket, attempt, model, prompt and completion tokens) in a JSONL file.

### Goal
Close the "token report is partial" gap by capturing usage at run time instead of recovering it afterwards.

### Acceptance criteria
- [ ] After each Hermes or OpenClaw invocation, `dispatch.py` appends one JSON line to a usage file under its state directory with `agent`, `runtime`, `issue`, `attempt`, `model`, `prompt_tokens`, `completion_tokens`, `source` and `exit_code`.
- [ ] When the runtime reports no usage, the line is still written with null token counts and `source: "unavailable"` (never an invented estimate).
- [ ] A failed or timed-out run is still recorded.
- [ ] New tests in `agents/dispatcher/tests/` cover a run with usage, one without, and a failed run; the existing dispatcher tests still pass.
- [ ] `docs/token-report.md` gets a short section explaining the new file and its fields.

### Out of scope
Changing the agents' prompts or models; back-filling past runs.

### Depends on
none

---

## G5: CI path allowlist for agent PRs

**Task:** Add a CI step that fails a ticket PR if it changes files outside the paths the Issue's allowed-file list names, so stray or generated files cannot ride along.

### Goal
Stop the kind of scope creep seen in PR #25 (unrelated and generated files in an agent PR).

### Acceptance criteria
- [ ] A script under `.github/scripts/` compares the PR's changed files with an `Allowed files:` line in the linked Issue body and exits non-zero on any extra file.
- [ ] A PR that closes no Issue (maintenance PR) is skipped, matching the gate's behaviour.
- [ ] A shell test next to `test_gate_decide.sh` covers: all files allowed, one extra file, no `Allowed files:` line (treated as skipped with a warning), and no linked Issue.
- [ ] `ci.yml` runs the script and the existing jobs are unchanged.

### Out of scope
Changing `gate.yml`; editing Issue bodies for old tickets.

### Depends on
none

---

## G6: Clear agent labels when a ticket closes

**Task:** Make the dispatcher remove any remaining `agent:*` label from an Issue once it is closed.

### Goal
Closed tickets (#29, #31, #33, #35, #37) still carry stale `agent:*` and `status:*` labels; the dispatcher should tidy them.

### Acceptance criteria
- [ ] On each tick the dispatcher finds closed Issues that still have an `agent:*` label and removes only those labels (the `status:ready-to-merge` and `attempt:*` labels stay as history).
- [ ] It posts no comment and wakes no agent for closed Issues.
- [ ] `--dry-run` lists what it would change and changes nothing.
- [ ] Tests cover an open Issue (untouched), a closed Issue with a stale label (cleaned), and a `gh` failure (no crash, retried next tick).

### Out of scope
Reopening Issues; touching PR labels.

### Depends on
none

---

## G7: Per-agent GitHub identity

**Task:** Let the dispatcher run each agent with its own `GH_TOKEN` (for example `NEWSROOM_TOKEN_COPYDESK`) so that agent's comments and labels appear under its own GitHub account.

### Goal
Make Copydesk (and the other agents) show as distinct authors on GitHub instead of all appearing as the owner.

### Acceptance criteria
- [ ] Before waking an agent, the dispatcher sets `GH_TOKEN` from `NEWSROOM_TOKEN_<AGENT>` in that agent's environment only; if the variable is unset it falls back to the current behaviour and logs one line saying so.
- [ ] Tokens are never printed or written to logs, state files or comments (the existing sanitizer is applied to any logged environment).
- [ ] The dispatcher's own reads and label moves keep using the owner's token.
- [ ] Tests cover: token set, token unset (fallback), and that no token value appears in captured output.
- [ ] `agents/dispatcher/README.md` documents the variables.

### Out of scope
Creating GitHub accounts or tokens; changing branch protection.

### Depends on
G3

---

## Owner actions (not ticketable)

These need your accounts or your machine, so no agent can do them:

1. **G7 prerequisite:** create one GitHub account (or bot) per agent, invite each as a collaborator with Issues and Pull requests write access, and create a fine-grained token for each. Put them in `/etc/newsroom-agent.env` or your shell, never in git.
2. **Redeploy the VM** from `main` after G2 merges (`sudo bash deploy/update.sh`), then record `systemctl list-timers`, `/runs` and the "Synapse" page title.
3. **Run one unattended cycle** with the dispatcher timer installed, and keep the trace.
4. **Record the 3-5 minute video** following `agents/demo/DEMO_GUIDE.md`.
5. **Apply the GCP Terraform** (or import the existing VM) once G1 merges.
