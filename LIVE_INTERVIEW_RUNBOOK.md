# Live Interview Runbook: "Agents make a small change live"

The interviewer said: *"We'll go through your agent setup together and have your agents make a small change live, so keep your environment running."*

This file is the plan for that call. Commands are for **Git Bash** at the repo root (`/c/Users/Yasaswini/autonomous-newsroom`). Background reading: `agents/demo/DEMO_GUIDE.md`, `agents/PROTOCOL.md`, `INTERVIEW_PREPARATION_GUIDE.md`.

---

## 1. What will happen on the call (expect this order)

1. **Walkthrough (about 10 min):** the team, runtimes, hand-off protocol, dispatcher.
2. **Live change (about 15-25 min):** you give one small task, the agents deliver it as a PR, you merge it.
3. **Q&A:** failures, trade-offs, what you would change.

The live change is the same path as `agents/demo/run_local_demo.sh`:

```
task -> Editor (Hermes) writes Issue -> Reporter (OpenClaw) opens PR
     -> Copydesk (Hermes) reviews -> Factcheck (OpenClaw) tests exact head SHA
     -> gate green -> YOU click Merge
```

---

## 2. Tonight: get the environment ready

Do all of this tonight, so tomorrow only needs a quick re-check.

- [ ] **Laptop:** plugged in, sleep disabled (Settings > Power > Screen and sleep = Never), Windows updates paused.
- [ ] **Internet:** stable. Have a phone hotspot ready as a backup.
- [ ] **Git Bash works:** open it and run `cd /c/Users/Yasaswini/autonomous-newsroom`.
- [ ] **Tools present:** `gh --version`, `git --version`, `uv --version`, `python --version`, `openclaw --version`, `hermes --version`.
- [ ] **GitHub login:** `gh auth status` (must be logged in as the repo owner). If not, run `gh auth login`.
- [ ] **Secrets present:** `.env` and the OpenClaw/Hermes configs hold the model API keys (Gemini). Do not open them on screen during the call.
- [ ] **Clean tree:** `git status`. Right now `docs/gap-tickets.md` is untracked and you are on `fix/close-delivery-gaps`. Either commit or stash those, or leave them. The demo script uses a clean `origin/main` worktree, so they will not leak into the agents' PR.
- [ ] **Repo up to date:** `git fetch origin && git log origin/main --oneline -3`.
- [ ] **Free-tier quota:** check your Gemini quota is not exhausted. 429 errors are the most likely failure (see `agents/traces/t4-dispatcher-429.md`).
- [ ] **Offline tests pass:**
  ```bash
  uv run --project app --extra dev pytest app/tests agents/dispatcher/tests -q
  bash .github/scripts/test_gate_decide.sh
  ```
- [ ] **Dry run of preflight (no GitHub writes):**
  ```bash
  bash agents/demo/run_local_demo.sh --preflight-only
  ```
  It must print all checks OK.
- [ ] **Optional full rehearsal tonight:** run the whole demo once with a trivial task so you see the real timing. It creates a real Issue and PR, so merge or close them afterwards.
  ```bash
  bash agents/demo/run_local_demo.sh
  ```
  Type `CREATE` when asked. Do not press merge unless you want it.

## 3. Tomorrow, 30 minutes before the call

- [ ] Restart nothing new. Just confirm: `gh auth status`, `bash agents/demo/run_local_demo.sh --preflight-only`.
- [ ] Close heavy apps. Keep open: **Git Bash**, **browser tab on the repo's Issues/PRs page**, **VS Code** (with `agents/dispatcher/dispatch.py`, `agents/PROTOCOL.md`).
- [ ] Check no stale state: `gh issue list --state open` and `gh pr list`. Close leftovers or be ready to explain them.
- [ ] Remove stale lock if a previous run crashed: `ls ~/.local/state/newsroom-demo/` and delete `demo.lock`. Also check `~/.local/state/newsroom-dispatch/` for old lock files.
- [ ] Put the task text in a notepad so you can paste it (see section 5).

---

## 4. Walkthrough script (what to say, in order)

**1. The team (README roster)**

| Agent | Runtime | Role | Never does |
|---|---|---|---|
| editor | Hermes | Orchestrator: writes Issues, re-routes, escalates | edits code, merges |
| reporter | OpenClaw | Builder: branch, commits, opens PR | merges |
| copydesk | Hermes | Reviewer: checks diff against acceptance criteria | pushes code, merges |
| factcheck | OpenClaw | Tester: runs ruff and pytest on the PR head | pushes code, merges |
| human (you) | n/a | Merges PRs, owns secrets and infra | n/a |

**2. Hand-offs happen only through GitHub** (`agents/PROTOCOL.md`): Issues, PRs, and labels (`status:*`, `agent:*`, `review:approved`, `test:passed`). No agent talks to another directly.

**3. The dispatcher** (`agents/dispatcher/dispatch.py`) is plain Python with no LLM. Each tick it polls Issues with `gh`, wakes only the agent named by the single `agent:*` label, with one invocation per agent at a time (lock file), then re-reads GitHub and validates the hand-off. Three failures sets `status:blocked` + `agent:editor` for the human.

**4. The gate** (`.github/workflows/gate.yml`) blocks merges unless the PR has both `review:approved` and `test:passed`. Only the human merges.

**5. Authorship:** commits carry trailers (`Agent`, `Runtime`, `Model`, and so on) via `agents/scripts/agent_commit.sh`. Be honest that all commits share one git identity and the trailers are self-declared.

**6. Honest limits (say these first, before they ask):**
- Agents are free-tier LLMs. They can be slow or hit 429 rate limits. The dispatcher retries and escalates.
- The dispatcher checks the *shape* of a hand-off, not the quality of a review.
- Earlier live runs (#29, #31, #33) failed on malformed labels and were fixed with tests. See `agents/demo/DEMO_GUIDE.md`.
- The GCP Terraform and `deploy/update.sh` were written in a Claude Code session, not by the agents (`docs/gap-tickets.md`). Say so if asked.

---

## 5. The live change

### Choose a tiny task

Smaller is safer. The Reporter did best on narrow tickets. Good choices:

1. **Safest (default):** a one-test change.
   ```
   Add a new test file app/tests/test_demo_true.py containing a single test named test_true_is_true that asserts True is True. Do not modify any existing files.
   ```
2. **If the interviewer wants something visible:** a one-line text change.
   ```
   Change the page footer text in the newsroom app to include the line "Built by an autonomous agent team". Only touch the template file that holds the footer, and add no new dependencies.
   ```
   Check first that a footer exists: `grep -ri footer app/newsroom`. If it does not, use option 1 or adapt the wording.
3. **If they suggest their own change:** keep it to one file, state "Do not modify any other files" and "no new dependencies".

### Run it

```bash
cd /c/Users/Yasaswini/autonomous-newsroom
bash agents/demo/run_local_demo.sh --preflight-only            # safe check
bash agents/demo/run_local_demo.sh                              # default task
bash agents/demo/run_local_demo.sh --task "<your task text>"   # custom task
```

- Type `CREATE` when asked. That is the only manual step before the merge.
- Narrate each progress line, for example `issue #N [labels] | PR #M [labels] ci=...`:
  `status:ready/agent:reporter` -> `status:in-progress` -> `status:in-review/agent:copydesk` (PR opens, CI runs) -> `review:approved` + `status:in-test/agent:factcheck` -> `test:passed` + `status:ready-to-merge`.
- Show the PR in the browser: labels, the agents' handoff comments, the commit trailers, green `ci` and `gate`.
- **You click Merge** in the GitHub UI. The Issue auto-closes. The script never merges.
- If the app auto-refreshes on the VM, mention that the dispatcher manages the refresh job (`agents/dispatcher/refresh_job.py`). Do not claim a public URL exists unless you have verified it (see `DELIVERY.md`).

### While you wait (runs take 10-25 min)

Do not sit in silence. Use the time to show:
- `agents/PROTOCOL.md` (ticket format: Goal, Acceptance criteria, Out of scope, Depends on).
- `agents/dispatcher/dispatch.py`: the `WAKE` table, `HANDOFF_TO`, `_evaluate`.
- `agents/traces/` (real failure traces and how they were fixed).
- `docs/token-report.md` and `TOKEN_USAGE_AUDIT.md` for cost.

---

## 6. If something goes wrong

| Symptom | What to do |
|---|---|
| `gh` auth error | `gh auth login`, then re-run. |
| 429 or quota error from the model | Say "free-tier rate limit, the dispatcher backs off and retries". Wait one retry. If it persists, use the per-run model override: `NEWSROOM_EXTRA_ARGS_COPYDESK="-m gemini-2.5-flash --provider gemini"` and `NEWSROOM_EXTRA_ARGS_FACTCHECK="--model google/gemini-2.5-flash"`. |
| Script exits with an error midway | Resume instead of starting again: `bash agents/demo/run_local_demo.sh --issue <N>`. |
| "malformed labels; skipped" | Known failure mode (Issues #29/#31/#33). Show the Issue labels, explain the dispatcher stops rather than guesses, and that escalation goes to the human. Fix the labels by hand only if you say so openly. |
| Ticket becomes `status:blocked` | That is the designed escalation after 3 failures. Show the comment the dispatcher left for the human. |
| Agent is very slow | Explain the timeout (`NEWSROOM_AGENT_TIMEOUT`, 900 s default) and the lock that prevents a double wake. |
| Lock file left behind | `rm -rf ~/.local/state/newsroom-demo/demo.lock` and check `~/.local/state/newsroom-dispatch/`. |
| Whole live run fails | Fall back to showing the offline proof: `uv run --project app --extra dev pytest agents/dispatcher/tests -q` (includes `test_e2e_state_machine.py`), plus a past merged PR with its labels and comments. Be honest that the live run did not complete. |
| Network drops | Switch to the phone hotspot, then resume with `--issue <N>`. |

**Never** fake a pass, relabel secretly, or merge a PR whose gate is red. Being honest about a failure and showing how the system escalates scores better than a hidden manual fix.

---

## 7. Likely questions and short answers

- **Why a dispatcher instead of letting agents poll?** Deterministic scheduling, a single writer for state, locks, retry limits, and hand-off validation. The agents only do the work.
- **Why two runtimes?** The assignment requires OpenClaw and Hermes. Builder and tester run on OpenClaw, orchestrator and reviewer on Hermes.
- **How do you stop an agent from merging?** Instructions in each agent's profile, branch protection, and the gate requiring both verdict labels. The human is the only merger.
- **How do you know a review is real?** Copydesk comments itemise each acceptance criterion. The dispatcher only checks shape, so quality still needs the human. Say this plainly.
- **What happens on failure?** Up to 3 attempts, backoff, then `status:blocked` + `agent:editor` with a comment.
- **How do you control cost?** Free-tier models, `NEWSROOM_MAX_TURNS`, small tickets, and a deterministic review mode (`--deterministic-review`) that uses no LLM.
- **What would you improve?** Per-agent GitHub identities (G7), token capture per run (G4), a CI path allowlist for agent PRs (G5), and a public VM deployment.

---

## 8. Quick command cheat sheet

```bash
# status
gh auth status
gh issue list --state open
gh pr list
gh pr checks <PR>
gh issue view <N> --comments

# demo
bash agents/demo/run_local_demo.sh --preflight-only
bash agents/demo/run_local_demo.sh
bash agents/demo/run_local_demo.sh --issue <N>

# dispatcher by hand
bash agents/dispatcher/dispatch.sh --dry-run
bash agents/dispatcher/dispatch.sh

# tests
uv run --project app --extra dev pytest app/tests agents/dispatcher/tests -q
bash .github/scripts/test_gate_decide.sh
```

## 9. Final checklist (5 minutes before)

- [ ] Preflight passes.
- [ ] Browser on the repo's PR page, Git Bash open at repo root, VS Code open.
- [ ] Notifications off, no secrets visible on screen.
- [ ] Task text ready to paste.
- [ ] You know your three honest limits (no verified public URL, free-tier flakiness, shared git identity).
