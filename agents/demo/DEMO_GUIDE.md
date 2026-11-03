# Interview demo guide: one ticket, fully automatic hand-offs

## Start (Git Bash, repo root, ~10–25 min live)
```bash
cd /c/Users/Yasaswini/autonomous-newsroom
git checkout main && git pull            # once the demo PR is merged; until then: git checkout demo/e2e-local-demo
bash agents/demo/run_local_demo.sh --preflight-only   # safe: no GitHub writes
bash agents/demo/run_local_demo.sh                    # asks you to type CREATE, then runs hands-off
```
Resume after a failure: `bash agents/demo/run_local_demo.sh --issue <N>`.
Second window (optional): `gh pr list` / `gh issue view <N>` or the Issues page in the browser.

## What to show
1. **Preflight** – tools, gh auth, OpenClaw `reporter` + model, clean checkout of `origin/main`.
2. **Ticket** – goal + checkable acceptance criteria; created with `status:ready agent:reporter attempt:1`. This is the *only* manual write.
3. **Progress lines** – every poll prints `issue #N [labels] | PR #M [labels] ci=…`. Narrate the labels moving:
   `status:ready/agent:reporter` → `status:in-progress` → `status:in-review/agent:copydesk` (PR opens, `ci` runs)
   → `review:approved` on the PR + `status:in-test/agent:factcheck` → `test:passed` + `status:ready-to-merge`.
4. **Gate** – script prints `gh pr checks`; `ci` and `gate` both green. Open the PR in the browser to show the labels and the agents' handoff comments.
5. **Stop** – script prints the PR URL and exits. **You click Merge** (the only human action; Issue auto-closes).

## Who does what
| Step | Who | How |
|---|---|---|
| Decide who is next | **Dispatcher** (plain Python, no LLM) | reads labels via `gh`, wakes only the agent named by `agent:*`, per-agent lock, 3 failures → `status:blocked` |
| Issue → PR mapping | Dispatcher | the one open PR whose `closingIssuesReferences` contains the Issue |
| Build + open PR | **Reporter** (OpenClaw LLM) | branch, commits with 5 trailers, `Closes #N`, hands off |
| Review | **Copydesk** (`copydesk_agent.py`, deterministic) | one linked Issue, not draft, no conflicts, `ci` green → `review:approved` |
| Test | **Factcheck** (`factcheck_agent.py`, deterministic) | ruff + pytest on the *exact PR head SHA* in a throwaway worktree → `test:passed` |
| Block unreviewed merges | **gate.yml** + `gate_decide.sh` | needs both verdict labels on a PR that closes an Issue |
| Merge | **Human only** | agents are forbidden; script contains no merge call |

**Dispatcher vs agent (one sentence):** the dispatcher is a deterministic scheduler/state machine that never decides *what* to build; agents do the work and only move the labels the protocol allows; GitHub is the sole channel between them.

## Why the script waits instead of ticking blindly
Copydesk counts a pending/missing `ci` as a failed attempt (3 → escalation), so the script only wakes Copydesk once `ci` is green. Reporter runs while the tick blocks; no second dispatcher is started (script lock + per-agent lock).

## Safety / evidence
- Offline proof (CI, no network): `uv run --project app --extra dev pytest agents/dispatcher/tests -q` (includes `test_e2e_state_machine.py`) and `bash .github/scripts/test_gate_decide.sh`.
- The script uses a clean `origin/main` worktree, so the Reporter's PR never includes demo tooling.
- Secrets are masked in all relayed output.

## Honest limits – say these out loud
- **Not validated:** OCI VM deployment and the systemd timer (`dispatcher.timer`); the demo runs ticks locally from the script.
- Reporter is an LLM (gemini-2.5-flash via OpenClaw): it can be slow or fail; the dispatcher retries/escalates, and the script then prints the Issue, PR, labels and latest logs.
- Copydesk/Factcheck run in deterministic mode (no LLM review of acceptance-criteria prose); Factcheck re-runs ruff/pytest, it does not verify each criterion semantically.
- The earlier Issue #14 / PR #25 cycle needed human relabeling and a cleanup request, so it is **not** evidence of a hands-off run.
