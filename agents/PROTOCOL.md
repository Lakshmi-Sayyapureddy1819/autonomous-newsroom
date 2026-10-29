# Agent Team Protocol

Shared contract. **GitHub is the only channel between agents** — no in-process handoff (`delegate_task`, DMs, shared scratchpads).

GitHub + git identity is **only** Lakshmi's account:

- User: `Lakshmi-Sayyapureddy1819`
- Author name: `Lakshmi Sayyapureddy`
- Author email: `142775745+Lakshmi-Sayyapureddy1819@users.noreply.github.com`

Agents still prove authorship with trailers (below). Do not create bot users or change `git config --global`.

## Roster

| Agent | Runtime | Role |
|---|---|---|
| editor | Hermes | Orchestrator: writes Issues from the brief, assigns, re-routes, escalates |
| reporter | OpenClaw | Builder: implements one ticket, opens/updates the PR |
| copydesk | Hermes | Reviewer: PR vs acceptance criteria |
| factcheck | OpenClaw | Tester: runs the PR branch |
| human | Lakshmi | **Only the human merges.** Unblocks `status:blocked`. Owns secrets and Terraform. |

The editor writes every product ticket. Humans must not open T1–T5 (or any product Issue).

## Labels (state machine)

Create these on Day 1. Exactly one `status:*` and exactly one `agent:*` on an open Issue.

| Label | Meaning | Set by |
|---|---|---|
| `status:ready` | Ticket assigned, waiting to be claimed | editor |
| `status:in-progress` | Builder claimed it | reporter |
| `status:in-review` | PR open, waiting for review | reporter |
| `status:in-test` | Review passed, waiting for test | copydesk |
| `status:ready-to-merge` | Review and test passed | factcheck |
| `status:blocked` | Attempt cap hit or stuck | editor |
| `agent:editor` `agent:reporter` `agent:copydesk` `agent:factcheck` | Who owns the next step | editor, or the agent handing off |
| `review:approved` / `review:changes-requested` | Review verdict | copydesk |
| `test:passed` / `test:failed` | Test verdict | factcheck |
| `attempt:<n>` | Build attempts (`attempt:1` … `attempt:3`) | editor |

## Flow

```
 brief ─► editor opens Issue [status:ready, agent:reporter, attempt:1]
            │
            ▼
 reporter claims [status:in-progress] ─► branch t<N>-slug ─► commits ─► PR "Closes #N"
            │                                              [status:in-review, agent:copydesk]
            ▼
 copydesk vs each acceptance criterion ─┬─ fail ─► [review:changes-requested]
            │                           │          editor: attempt+1, status:ready, agent:reporter
            │                           └─ pass ─► [review:approved, status:in-test, agent:copydesk off, agent:factcheck]
            ▼
 factcheck on the PR branch ────────────┬─ fail ─► [test:failed] + log
            │                           │          editor: attempt+1, status:ready, agent:reporter
            │                           └─ pass ─► [test:passed, status:ready-to-merge], remove agent:* 
            ▼
 human merges ─► Issue auto-closes ─► editor starts the next ready ticket
 attempt > 3 ─► [status:blocked, agent:editor] ─► human
```

Same branch and PR on retry. Editor strips stale `review:*` and `test:*` when re-routing.

## Ticket format

Every Issue from the editor has:

- **Goal** — one or two sentences, outcome-level.
- **Acceptance criteria** — checklist; each item checkable by running or reading something.
- **Out of scope**
- **Depends on** — other Issue numbers, if any.

Do not paste `docs/PLAN.md` section 6 into the Issue. Turn the brief into small tickets.

## Handoff comment

End every turn with a comment on the Issue (and on the PR once it exists). GitHub will show Lakshmi as the user; the **body** names the agent.

```
### Handoff  <from> → <to>
Ticket: #<n> · PR: #<n> · Attempt: <n>
Did: …
How to verify: …
Known gaps: …
Tokens: prompt=<n> completion=<n> model=<id>  (estimate OK, say so)
```

Reviewer and tester also list **each acceptance criterion: pass/fail + evidence** (file:line for review; command + short output for test).

## Commits (Lakshmi author, agent trailers)

Every commit:

```
git -c user.name="Lakshmi Sayyapureddy" \
    -c user.email="142775745+Lakshmi-Sayyapureddy1819@users.noreply.github.com" \
    commit -m "… message …

Co-authored-by: <agent> (<runtime>) <agent>@newsroom.agents
Agent: <editor|reporter|copydesk|factcheck>
Runtime: <hermes|openclaw>
Model: <model-id>
Ticket: #<n>
"
```

Example Co-authored-by: `reporter (openclaw) <reporter@newsroom.agents>`.

- Product commits (`app/`, `deploy/`) come from **reporter**. Reviewer and tester do not push.
- CI `trailer-check` fails a PR that changes `app/` or `deploy/` if those trailers are missing. Human bootstrap commits outside those paths are exempt.
- Never `git commit --amend` of pushed commits, never force-push `main`, never merge.

## Gates

- Branch protection on `main`: PR required; required checks `ci` and `gate`; no bypass (including admins).
- `ci`: ruff + pytest + gitleaks + trailer-check (product paths).
- `gate`: fails unless the PR has **both** `review:approved` and `test:passed`.
- Agents use a limited PAT (Contents, Issues, Pull requests: read/write). Because GitHub's Pull requests: write permission includes API merge capability, merging is strictly forbidden in agent instructions, and branch protection on `main` prevents merging until checks pass. Human merges from the GitHub UI after `status:ready-to-merge`. Agents must never run `gh pr merge` or change protection.

## Dispatcher

`agents/dispatcher/dispatch.sh` polls GitHub via `gh` to find open Issues with `agent:*` + a `status:*` that means work, and wakes **only that agent** with the Issue number.

- Execution mode:
  - Day 1 Local T0: Run manually or via a simple shell polling loop in Git Bash (`bash agents/dispatcher/dispatch.sh`).
  - Production VM (T1–T5): Run every 5 minutes via a systemd timer (`dispatcher.timer`).
- No LLM, no assignment decisions (editor assigns).
- Do not start a second invocation if that agent is already running.
- Do not wake anyone for `status:ready-to-merge` or `status:blocked`.

## Token tracking

After each invocation, persist usage (OpenClaw `/usage` or OTel `openclaw.tokens`; Hermes `hermes insights`). Put numbers on the handoff comment. Human exports a per-agent / per-model split (planning, coding, review/test, retries) into `DELIVERY.md` or `docs/token-report.md`.

## Limits

- Max 3 build attempts per ticket, then `status:blocked`.
- Max turns per invocation (runtime config).
- One in-progress ticket for reporter.
- Stop on 402/429; do not hammer a failing model.
- No secrets in Issues, PRs, logs, or commits. Configs in git are `*.example` only.
