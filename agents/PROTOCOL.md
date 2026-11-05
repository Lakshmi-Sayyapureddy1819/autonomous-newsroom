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
- No LLM. The editor's mechanical duties (re-route a rejected ticket with `attempt+1`, block after 3 attempts, promote the next ready ticket once its `Depends on` tickets are closed) run as code in `agents/dispatcher/editor_lifecycle.py`. The Hermes editor is woken only to author tickets from `docs/brief.md`. A ticket waiting on dependencies carries `agent:editor` and no `status:*`.
- After every invocation the dispatcher **re-reads GitHub and validates the hand-off**; it never trusts the exit code or a bare "labels changed". Valid means: exactly one open PR closes the Issue; the Issue carries exactly the expected pair (reporter → `status:in-review` + `agent:copydesk`; copydesk approve → `status:in-test` + `agent:factcheck`; factcheck pass → `status:ready-to-merge`); the verdict label (`review:*` / `test:*`) is on the **PR**; the PR has no `status:*`/`agent:*`; a reviewer's PR head did not move during its run; and a handoff comment or review was posted. Only obsolete leftovers (a stale `status:ready`, hand-off labels on the PR) are removed, and each repair is logged and commented; a missing hand-off is never fabricated. A valid hand-off wins over a non-zero exit (so a dropped gateway after finished work is not re-run), and a timed-out agent's lock is kept so no duplicate invocation starts.
- **A hand-off must prove it belongs to this task** (`agents/dispatcher/handoff.py`). A new comment is not enough: at least one new comment must start with the protocol header naming this Issue *and* this PR (`Ticket: #<issue> · PR: #<pr> · Attempt: <n>`), and any new comment whose header names a different Ticket/PR rejects the whole hand-off (this is how a stale Issue #41 / PR #42 review was once accepted on Issue #48). A Copydesk review must also cite the current PR head SHA, give one PASS/FAIL line per acceptance criterion and per out-of-scope restriction, and agree with its verdict label (`review:approved` allows no FAIL line, `review:changes-requested` needs one). A Factcheck report must cite the exact head SHA and show `ruff` and `pytest` output. A Reporter retry (attempt ≥ 2) must push a new commit to the existing PR. An invalid hand-off is undone (verdict labels dropped from the PR, Issue labels restored to the agent's previous owner) and counts as a failure; no second PR is ever opened.
- **Every invocation starts a fresh conversation** and receives the complete task in its prompt (repository, Issue number/title/body verbatim, attempt, PR number/branch/head SHA, and the latest hand-off or review *of this task*): OpenClaw runs with a unique `--session-id` (otherwise it resumes the agent's main session and replies "still waiting for review" from history), Hermes runs `--oneshot --source tool` (never `--resume`/`-c`) with the prompt passed by `--query-file`, and each run gets its own empty scratch directory under the dispatcher state dir (a reused `review_comment.md` once published another task's review). Optional extra isolation: `NEWSROOM_EXTRA_ARGS_COPYDESK="--ignore-rules"` also skips Hermes memory/`SOUL.md` injection.
- Credential or quota errors (`401/403`, "unauthorized", "quota", `RESOURCE_EXHAUSTED`, "insufficient credit") escalate immediately instead of consuming the remaining retries; a plain 429 is retried with a long back-off. An uncertain outcome (timeout, lost Hermes gateway) is awaited, never re-run.
- A failed or invalid invocation is retried; after 3 (or 9 wakes overall) the ticket becomes `status:blocked`, `agent:editor`. Inconsistent labels (two `status:*`, an owner without a status, ...) that persist past `NEWSROOM_MALFORMED_GRACE` (120 s) are escalated the same way, never skipped silently.
- Agents run only in a clean checkout (`NEWSROOM_REPO_DIR`); the dispatcher refuses to start the Reporter in a dirty one.
- Tasks enter through `agents/dispatcher/submit_task.py`, which has the Hermes Editor write the Issue and then verifies it (one Issue, exact labels, ticket sections, task identifiers intact, no PR).
- Do not start a second invocation if that agent is already running (per-agent lock).
- Do not wake anyone for `status:ready-to-merge` or `status:blocked`.

## Token tracking

After each invocation, persist usage (OpenClaw `/usage` or OTel `openclaw.tokens`; Hermes `hermes insights`). Put numbers on the handoff comment. Human exports a per-agent / per-model split (planning, coding, review/test, retries) into `DELIVERY.md` or `docs/token-report.md`.

## Limits

- Max 3 build attempts per ticket, then `status:blocked`.
- Max turns per invocation (runtime config).
- One in-progress ticket for reporter.
- Stop on 402/429; do not hammer a failing model.
- No secrets in Issues, PRs, logs, or commits. Configs in git are `*.example` only.
