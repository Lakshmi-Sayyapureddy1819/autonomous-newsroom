# Interview demo guide: one ticket, fully automatic hand-offs

## Start (Git Bash, repo root, ~10–25 min live)
```bash
cd /c/Users/Yasaswini/autonomous-newsroom
git checkout main && git pull            # once the demo PR is merged; until then: git checkout demo/e2e-local-demo
bash agents/demo/run_local_demo.sh --preflight-only   # safe: no GitHub writes
bash agents/demo/run_local_demo.sh                    # asks you to type CREATE, then the Hermes Editor writes the Issue and the dispatcher runs hands-off
bash agents/demo/run_local_demo.sh --task "Add a new test file ..."   # your own small task for the Editor
```
Resume after a failure: `bash agents/demo/run_local_demo.sh --issue <N>`.
Second window (optional): `gh pr list` / `gh issue view <N>` or the Issues page in the browser.

## What to show
1. **Preflight** – tools, gh auth, OpenClaw `reporter` + model, clean checkout of `origin/main`.
2. **Task → Editor → Issue** – you give one sentence to the **Hermes Editor** (`submit_task.py`); it writes the Issue (Goal, checklist, Out of scope, Depends on) labelled `status:ready agent:reporter attempt:1`. The script then *verifies* it (exactly one Issue, exact labels, task identifiers intact, no PR). Typing `CREATE` is the only manual step before the final merge.
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
| Review | **Copydesk** (Hermes LLM; `copydesk_agent.py` only with `--deterministic-review`) | reviews the PR head against every criterion and the allowed file list, comments, `review:approved` on the PR + Issue → `status:in-test`/`agent:factcheck` |
| Test | **Factcheck** (OpenClaw LLM; script only with `--deterministic-review`) | ruff + pytest on the *exact PR head SHA*, evidence comment → `test:passed` + `status:ready-to-merge` |
| Validate every hand-off | **Dispatcher** | re-reads GitHub after each run: one PR, expected labels, verdict on the PR, no `status:*`/`agent:*` on the PR, head unmoved, comment posted |
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
- Copydesk and Factcheck are LLM agents on free-tier models; they can hit 429s or review shallowly. The dispatcher validates the *shape* of every hand-off, not the quality of the review.
- The earlier Issue #14 / PR #25 cycle needed human relabeling and a cleanup request, so it is **not** evidence of a hands-off run.

## Live-run history – none of these is a pass
Issues #29, #31 and #33 all ended the same way (below): the dispatcher counted the Reporter's conflicting labels as progress, then skipped the ticket as malformed, so Copydesk and Factcheck never ran. #33 also showed the Reporter committing unrelated local files from a dirty shared checkout and the Issue body losing its backticked text. These are fixed and covered by `test_handoff_validation.py` / `test_submit_task.py`; the fix is only proven live by a run that ends with the evidence lines printed by step 4.

### Live-run result (2026-11-03, Issue #29 / PR #30) – NOT a pass
The dispatcher woke Reporter, which opened PR #30 (ci green). Reporter then left Issue #29 with two `status:*` labels and put the hand-off labels on the PR instead of the Issue. The dispatcher refused to act on the malformed ticket ("malformed labels; skipped"), so Copydesk and Factcheck never ran. The full hands-off cycle is therefore **not validated live**; it is validated only offline (`test_e2e_state_machine.py`). The demo script now stops on malformed labels instead of looping.
