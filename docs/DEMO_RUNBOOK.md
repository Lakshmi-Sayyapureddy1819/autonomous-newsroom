# Demo Runbook: Autonomous Newsroom (live change)

All commands are for **Git Bash**. Canonical checkout: `/c/Users/Yasaswini/nr-repair` (branch `main`).
Flow: task -> Hermes Editor (Issue) -> Dispatcher -> OpenClaw Reporter (PR) -> Hermes Copydesk (review)
-> OpenClaw Factcheck (tests exact head SHA) -> GitHub Gate -> **you merge**.

---

## 0. Before the call (day before / 30 min before)

```bash
cd /c/Users/Yasaswini/nr-repair
git fetch origin
git switch main
git pull --rebase                      # must say "Already up to date" or rebase cleanly
git status -sb                          # expect: "## main...origin/main" and nothing else
git log --oneline -3
```

Network and auth:

```bash
nslookup github.com                     # must return an address
gh auth status                          # must say "Logged in"
gh pr list --state open                 # must be EMPTY (the demo needs a quiet pipeline)
gh issue list --state open              # no leftover agent:/status: tickets
```

If you are on flaky Wi-Fi, switch to the phone hotspot NOW. A DNS drop mid-run causes false
"label missing" / "open PRs exist (?)" preflight failures.

---

## 1. Start / check the services

### 1a. OpenClaw Gateway (needed by Reporter and Factcheck)

It can take **75-110 s to cold start**. "Registered" is not "listening".

```bash
openclaw gateway status                 # service state + connectivity
openclaw gateway health                 # healthy = OK
openclaw gateway probe                  # reachability check

# If it is not running:
openclaw gateway start
# If it is running but unhealthy / stuck:
openclaw gateway restart
# Last resort (stop, wait, start):
openclaw gateway stop
sleep 5
openclaw gateway start
```

Wait until the port answers (up to ~4 min), then confirm:

```bash
for i in $(seq 1 48); do
  (echo > /dev/tcp/127.0.0.1/18789) 2>/dev/null && { echo "Gateway listening on 18789"; break; }
  sleep 5
done
```

(The demo script and dispatcher also start the Gateway once automatically if nothing listens.
Disable that with `NEWSROOM_GATEWAY_AUTOSTART=0`. Change the wait with `NEWSROOM_GATEWAY_WAIT=240`.)

If the port is in use by something else: `NEWSROOM_GATEWAY_PORT=<port>`.

### 1b. Hermes (Editor and Copydesk)

Use the user-level launcher, not any blocked internal executable:

```bash
type -a hermes                          # expect /c/Users/Yasaswini/AppData/Local/hermes/bin/hermes
hermes profile list                     # must show: editor, copydesk (and default)
hermes gateway status                   # Scheduled Task "Hermes_Gateway", process running
hermes gateway list                     # every profile's gateway status

# If the Hermes gateway is down:
hermes gateway restart
# or: hermes gateway stop ; hermes gateway start
```

The Editor and Copydesk are invoked per task (`hermes -p editor chat ...`), so a quick live check is:

```bash
hermes -p editor   chat -q "Reply with the single word OK"
hermes -p copydesk chat -q "Reply with the single word OK"
```

### 1c. OpenClaw agents

```bash
openclaw agents list                    # expect reporter (google/gemini-2.5-flash) and factcheck
```

---

## 2. Safe preflight (writes nothing to GitHub, starts no agents)

```bash
cd /c/Users/Yasaswini/nr-repair
bash agents/demo/run_local_demo.sh --preflight-only
```

Every line must say `ok`. Expected tail:

```
ok    OpenClaw Gateway listening on 127.0.0.1:18789
ok    openclaw agent 'factcheck' registered
ok    fetched origin
ok    this checkout contains origin/main (<sha>)
ok    no other open PRs
ok    no other active ticket in the pipeline
preflight only: done.
```

### Preflight failures and what to do

| Preflight line | Fix |
|---|---|
| `this checkout is behind origin/main` | `git pull --rebase` |
| `git fetch failed` / `Could not resolve host` / `repo label missing` / `open PRs exist (?)` | Network or DNS dropped. Fix the connection (hotspot), re-run. Do NOT create labels by hand. |
| `OpenClaw Gateway still not listening` | Section 1a: `openclaw gateway restart`, wait, re-run. |
| `hermes has no '<x>' profile` / `hermes not on PATH` | Section 1b, `hermes profile list`. |
| `gh authenticated` fails | `gh auth login` |
| `open PRs exist` (real) | Merge or close the leftover PR, or resume it (section 5). |
| `other active ticket in the pipeline` | Finish it or resume it with `--issue N`. |

---

## 3. Model fallbacks (only if needed)

OpenRouter's free quota (Factcheck default model) can run out, or Hermes can return 429. Set these
**before** the run, in the same shell:

```bash
export NEWSROOM_EXTRA_ARGS_EDITOR="-m gemini-2.5-flash --provider gemini"
export NEWSROOM_EXTRA_ARGS_COPYDESK="-m gemini-2.5-flash --provider gemini"
export NEWSROOM_EXTRA_ARGS_FACTCHECK="--model google/gemini-2.5-flash"
```

Undo with `unset NEWSROOM_EXTRA_ARGS_EDITOR NEWSROOM_EXTRA_ARGS_COPYDESK NEWSROOM_EXTRA_ARGS_FACTCHECK`.

---

## 4. The live change

Give ONE small task. Suggested (a small endpoint plus one test, same shape as PR #42):

```bash
cd /c/Users/Yasaswini/nr-repair
bash agents/demo/run_local_demo.sh --task "Add a GET /health endpoint to the FastAPI app in app/newsroom/main.py that returns JSON {\"status\": \"ok\"}, and add one test in app/tests/test_health_endpoint.py that checks the status code is 200 and the body is {\"status\": \"ok\"}. Do not change any other files."
```

- It asks you to confirm creating ONE live GitHub Issue. Answer `y` (or add `--yes` to skip the prompt).
- Useful flags: `--yes`, `--timeout MIN` (default 45), `--poll SEC` (default 20),
  `--deterministic-review` (scripted review instead of Hermes), `--issue N` (resume).
- A full run takes about 10-25 minutes.

### Watch the flow (second terminal)

```bash
gh issue list --state open
gh pr list --state open
gh issue view <N> --json labels,comments --jq '.labels[].name'
gh pr view <PR> --json labels --jq '.labels[].name'
gh pr checks <PR>
```

Expected label progression:

| Stage | Issue labels | PR labels |
|---|---|---|
| Editor created it | `status:ready`, `agent:reporter`, `attempt:1` | |
| Reporter opened PR | `status:in-review`, `agent:copydesk` | |
| Copydesk reviewed | `agent:factcheck` | `review:approved` |
| Factcheck tested | `status:ready-to-merge` | `test:passed` |

Verdict labels (`review:*`, `test:*`) live on the **PR** only, not on the Issue.

---

## 5. If something goes wrong

**Resume, do not start over** (this reuses the existing Editor-created Issue):

```bash
bash agents/demo/run_local_demo.sh --issue <N>
```

| Symptom | Action |
|---|---|
| 429 / quota error | Wait one retry (dispatcher backs off). Then section 3 overrides and `--issue <N>`. |
| `Gateway disconnected` / `turn outcome is unknown` | Do not resend work. `openclaw gateway restart`, wait for port 18789, then `--issue <N>`. |
| Hermes agent hangs | `hermes gateway restart`, then `--issue <N>`. Per-agent timeout is `NEWSROOM_AGENT_TIMEOUT` (900 s). |
| Ticket `status:blocked` | Designed escalation after 3 failed attempts. Show the dispatcher's comment for the human. |
| `malformed labels; skipped` | The dispatcher stops rather than guesses. Show the labels and explain. Fix by hand only openly. |
| Stale lock | `rm -rf ~/.local/state/newsroom-demo/demo.lock` and check `~/.local/state/newsroom-dispatch/` |
| Network drops | Switch to hotspot, confirm `nslookup github.com`, then `--issue <N>`. |
| Whole live run fails | Show the offline proof (below) and a past merged PR. Say honestly that the live run did not complete. |

Offline proof (no network, no agents):

```bash
cd /c/Users/Yasaswini/nr-repair
uv run --with pytest python -m pytest agents/dispatcher/tests -q        # expect 105+ passed
cd app && uv run --with pytest --with ruff --with-editable . python -m pytest tests -q   # expect 80+ passed
uv run --with ruff ruff check .                                         # All checks passed
```

---

## 6. Review and merge (you, manually)

```bash
gh pr list --state open
gh pr view <PR> --web                    # check: only the 2 expected files changed
gh pr diff <PR> --name-only              # expect exactly: app/newsroom/main.py, app/tests/test_health_endpoint.py
gh pr checks <PR>                        # CI + Gate must be green
gh pr view <PR> --json labels --jq '.labels[].name'   # must include review:approved and test:passed
```

Merge only when the Gate is green (click **Merge** in the browser, or):

```bash
gh pr merge <PR> --merge
```

Never merge a PR whose gate is red, and never relabel secretly.

---

## 7. After the demo

```bash
cd /c/Users/Yasaswini/nr-repair
git switch main
git pull --rebase
git log --oneline -3                     # shows the merged PR
git status -sb                           # clean, on main
gh issue list --state open               # the Issue should be closed by the merge
```

---

## 8. Demo test cases (pick ONE per run)

Rules: one task per run, tiny, name the exact files, end with "Do not change any other files."
Run only one at a time (the pipeline must be quiet). Each task goes in the same command:

```bash
bash agents/demo/run_local_demo.sh --task "<task text>"
```

Verify every result the same way before merging:

```bash
gh pr diff <PR> --name-only          # only the files named in the task
gh pr checks <PR>                    # ci + gate green
```

Existing routes: `/`, `/runs`, `/rss.xml`, `/version`, `/build-info`, `/agent-demo`.
Existing UI files: `app/newsroom/templates/{base,index,runs,feed,errors}.html`, `app/newsroom/static/styles.css`.
Existing tests: `app/tests/test_main.py`, `test_responsive.py`, `test_version_endpoint.py` (copy this style).

### A. Backend (smallest, safest)

| # | Task text | Files expected | How to verify |
|---|---|---|---|
| A1 | Add a GET /health endpoint to the FastAPI app in app/newsroom/main.py that returns JSON {"status": "ok"}, and add one test in app/tests/test_health_endpoint.py that checks the status code is 200 and the body is {"status": "ok"}. Do not change any other files. | `main.py`, `test_health_endpoint.py` | `curl localhost:8000/health` |
| A2 | Add a GET /ping endpoint in app/newsroom/main.py that returns the plain text "pong" with status 200, and add one test in app/tests/test_ping_endpoint.py. Do not change any other files. | `main.py`, `test_ping_endpoint.py` | `curl localhost:8000/ping` |
| A3 | Add a GET /uptime endpoint in app/newsroom/main.py returning JSON {"started_at": <ISO timestamp recorded when the app module loads>}, and add one test in app/tests/test_uptime_endpoint.py checking the key exists. Do not change any other files. | `main.py`, `test_uptime_endpoint.py` | `curl localhost:8000/uptime` |

(If PR #58 `/health` is not merged yet, use A2 or A3 so the Reporter does not collide with it.)

### B. UI changes (each touches a template and one test)

| # | Task text | Files expected | How to verify |
|---|---|---|---|
| B1 | Add an "About" link to the main navigation in app/newsroom/templates/base.html that points to /version, placed after the "Runs" link, and add one test in app/tests/test_nav_about.py that fetches "/" and asserts the response contains `href="/version"`. Do not change any other files. | `base.html`, `test_nav_about.py` | Open `/`: nav shows Home, Runs, About, RSS |
| B2 | Change the heading on the Runs page in app/newsroom/templates/runs.html from "Run log" to "Pipeline run log", and add one test in app/tests/test_runs_heading.py that fetches "/runs" and asserts the page contains "Pipeline run log". Do not change any other files. | `runs.html`, `test_runs_heading.py` | Open `/runs` |
| B3 | Add a "Version" link to the site footer in app/newsroom/templates/base.html next to "Subscribe via RSS", pointing to /version, and add one test in app/tests/test_footer_version.py that fetches "/" and asserts the footer contains `href="/version"`. Do not change any other files. | `base.html`, `test_footer_version.py` | Scroll to footer on `/` |
| B4 | Add a "Skip to content" accessibility link as the first element inside the body in app/newsroom/templates/base.html (href="#main"), make sure the main content element has id="main", and add one test in app/tests/test_skip_link.py asserting the page contains `href="#main"` and `id="main"`. Do not change any other files. | `base.html`, `test_skip_link.py` | Press Tab on `/`: the link appears |
| B5 | Add a meta description tag to the head in app/newsroom/templates/base.html with the content "AI news, collected and summarized by an agent team", and add one test in app/tests/test_meta_description.py that fetches "/" and asserts that text is in the HTML. Do not change any other files. | `base.html`, `test_meta_description.py` | View page source on `/` |
| B6 | Change the empty-state message on the home page in app/newsroom/templates/index.html from "The newsroom is empty right now." to "No stories yet. Check back soon.", and update or add a test in app/tests/test_empty_state_message.py that checks the new text appears when there are no stories. Do not change any other files. | `index.html`, test file | Needs an empty DB; rely on the test |
| B7 | Add a CSS rule in app/newsroom/static/styles.css that underlines navigation links on hover (`.nav a:hover { text-decoration: underline; }`), and add one test in app/tests/test_nav_hover_css.py that reads the stylesheet and asserts that rule exists. Do not change any other files. | `styles.css`, `test_nav_hover_css.py` | Hover a nav link |

Good first UI pick for the interview: **B1** (visible in the browser, 2 files, easy to review) or **B2** (one-word change).

### C. Show the failure loop (optional, only if asked)

These deliberately stress the loop. Run only if you are comfortable the demo may end `status:blocked`.

| # | Task text | What it demonstrates |
|---|---|---|
| C1 | Add a test in app/tests/test_failing_demo.py that asserts 1 == 2. Do not change any other files. | Factcheck/CI fails -> `test:failed`, never reaches `status:ready-to-merge`, retries, then escalates |
| C2 | Add a GET /health endpoint in app/newsroom/main.py and also rewrite the whole README.md. | Out-of-scope change: Copydesk should request changes (`review:changes-requested`), ticket goes back to the Reporter with `attempt:2` |

Be honest in the interview if the live outcome differs from the offline tests. The dispatcher tests already prove these paths:
`uv run --with pytest python -m pytest agents/dispatcher/tests -q -k "reroute or escalat or rejection or factcheck_failure"`

### D. See the result in the browser after merge

```bash
cd /c/Users/Yasaswini/nr-repair && git pull --rebase
cd app && uv run --with-editable . uvicorn newsroom.main:app --port 8000
# then open http://localhost:8000/  and  http://localhost:8000/runs
```

---

## 9. How failures loop (what the dispatcher does)

Routing is plain code in `agents/dispatcher/editor_lifecycle.py` (no LLM, no tokens).

| Event | What happens next |
|---|---|
| Copydesk finds a problem | `review:changes-requested` on the PR; ticket goes straight back to the Reporter, `attempt:2` |
| Factcheck tests fail | `test:failed` on the PR; ticket goes straight back to the Reporter, `attempt:2` |
| Reporter fixes it | Same branch, same PR (no new PR); old verdict labels cleared |
| After the fix | Whole chain again: CI, Copydesk, Factcheck, Gate |
| Third failure | `status:blocked` plus an escalation comment for a human; no agent is woken |

Note: a Factcheck failure does NOT go through Copydesk first; it goes to the Reporter, and Copydesk
re-reviews the next attempt. Verdict labels (`review:*`, `test:*`) live on the PR, Issue labels
(`status:*`, `agent:*`, `attempt:*`) on the Issue.

Interview one-liner: "On any failure the dispatcher sends the ticket back to the Reporter on the same
PR, bumps the attempt, and the fix goes through Copydesk and Factcheck again. After three attempts it
escalates to a human."

Offline proof of these paths (37 tests, no network):

```bash
uv run --with pytest python -m pytest agents/dispatcher/tests -q -k "reroute or escalat or block or stale or retry or e2e or resilien or invalid or malformed or attempt"
```

---

## 10. Token usage (see it directly)

`sqlite3` is not installed on Windows and plain `python` is not on PATH. Use `uv run python`.

### Built-in views

```bash
# Hermes: tokens, models, estimated cost per profile
hermes -p editor   insights
hermes -p copydesk insights
hermes insights                     # default profile

# OpenClaw: per-session tokens (context size, not lifetime)
openclaw sessions --agent reporter
openclaw sessions --agent factcheck
openclaw sessions --all-agents
openclaw sessions --all-agents --json
```

### Lifetime totals, Hermes + OpenClaw together

```bash
cd /c/Users/Yasaswini/nr-repair
LOCALAPPDATA=$(cygpath -w ~/AppData/Local) uv run python agents/demo/token_total.py
```

PowerShell:

```powershell
uv run python C:\Users\Yasaswini\nr-repair\agents\demo\token_total.py
```

Sources it reads (read-only): Hermes `%LOCALAPPDATA%\hermes\[profiles\<p>\]state.db`
(table `session_model_usage`); OpenClaw `~\.openclaw\agents\<agent>\agent\openclaw-agent.sqlite`
(`usage` object inside `transcript_events`, plain or zstd-compressed; needs Python 3.14, which `uv run` uses).

Reference output (2026-11-06, lifetime, all sessions on this machine):

| Source | input | output | cache_read |
|---|---|---|---|
| HERMES total | 21,818,675 | 1,153,272 | 283,324,312 |
| OPENCLAW total | 18,649,372 | 624,783 | 383,289,624 |
| GRAND TOTAL | 40,468,047 | 1,778,055 | 666,613,936 |

Input + output (excluding cache) = about 42.2M. `hermes/default` and `openclaw/main` include non-demo work;
for the four-agent flow use editor, copydesk, reporter and factcheck only.

### Cost of ONE demo

1. Run `token_total.py` before the demo and save the output.
2. Run it again after the demo.
3. Subtract.

Single Hermes call: `hermes -z "<prompt>" --usage-file usage.json` writes a JSON usage report (untested).

### Honest caveats

- Counts are runtime-reported, not provider billing. Authoritative: Google AI Studio usage and the
  OpenRouter activity page. Hermes costs are estimates (some sessions have no pricing data).
- `cache_read` is the same context re-read each turn. Quote input + output; do not add cache to it.
- OpenClaw totals sum every event with a `usage` field. Not checked for duplicate events from
  session branching or compaction.
- Hermes and OpenClaw were assumed not to overlap.
- Say: "About 42M input+output tokens by runtime-reported counters across both runtimes, lifetime,
  mostly the Reporter. Runtime counts, not provider billing."

---

## 11. Quick error fixes (errors seen in real rehearsals)

### Habit that avoids most problems (run before every attempt)

```bash
cd /c/Users/Yasaswini/nr-repair
git pull --rebase
bash agents/demo/run_local_demo.sh --preflight-only
```

Continue only if every line says `ok`. Read any FAIL line: it usually names the fix.

### 1. Pasting mistakes

| What you see | Cause | Fix |
|---|---|---|
| `bash: Step: command not found`, `bash: Every: command not found` | Explanation text was pasted with the commands | Paste ONLY the code block, never the lines around it |
| Output repeated several times | Same pasted text ran more than once | Open a fresh terminal, paste the block once |
| A command does nothing | A `#` comment or stray line broke it | Run one block at a time |

### 2. Git state

| What you see | Cause | Fix |
|---|---|---|
| `FAIL this checkout is behind origin/main; run: git pull` | `origin/main` moved (for example after a merge) | `cd /c/Users/Yasaswini/nr-repair && git pull --rebase`, re-run preflight |
| `There is no tracking information for the current branch` | Local `main` not linked to `origin/main` | `git branch --set-upstream-to=origin/main main` |
| `git pull --ff-only` fails | Local commits make `main` ahead | Use `git pull --rebase` |
| Prompt shows `(972c592...)` / not on `main` | In the old detached checkout | `cd /c/Users/Yasaswini/nr-repair && git switch main`. Always work from this folder |
| `open PRs exist` (real) | A PR from an earlier run is still open | `gh pr list`, merge or close it by hand |

### 3. Network and services

| What you see | Cause | Fix |
|---|---|---|
| `Could not resolve host: github.com`, `git fetch failed`, `repo label missing`, `open PRs exist (?)` | DNS/Wi-Fi dropped mid-run. The label and PR lines are false alarms | `nslookup github.com`; switch to phone hotspot; re-run preflight. Do NOT create labels by hand |
| `OpenClaw Gateway still not listening` | Gateway down or cold-starting | `openclaw gateway restart`, wait up to 4 min, `openclaw gateway health` |
| `hermes has no 'editor' profile` / `hermes not on PATH` | Wrong shell or PATH | `type -a hermes` (expect `AppData/Local/hermes/bin/hermes`), then `hermes profile list` |
| `gh authenticated` fails | Login expired | `gh auth login` |

### 4. During the run

| What you see | Fix |
|---|---|
| Script stops or terminal closes mid-run | Do not start over: `bash agents/demo/run_local_demo.sh --issue <N>` (Issue number it printed) |
| 429 / quota error | Wait for one automatic retry. If it persists set the three `NEWSROOM_EXTRA_ARGS_*` exports (section 3), then resume |
| `Gateway disconnected` / `turn outcome is unknown` | `openclaw gateway restart`, wait for port 18789, then resume. The dispatcher will not resend work |
| Ticket becomes `status:blocked` | Designed escalation after 3 failures. Show its comment and say so |

Never relabel secretly, merge a red gate, or fake a pass to get past an error. Showing how the
system recovers or escalates scores better than a hidden manual fix.

---

## 12. Resume a stopped or interrupted run

Use this when the script was stopped (Ctrl+C, closed terminal, network drop) or the agents paused
part-way. Never start a new `--task`: that would create a second Issue and PR.

### Step 1: find the ticket and see where it stopped

```bash
cd /c/Users/Yasaswini/nr-repair
gh issue list --state open                      # the active ticket number N
gh pr list --state open                         # its PR number
gh issue view <N> --json labels --jq '[.labels[].name]|join(",")'
gh pr view <PR> --json labels,statusCheckRollup --jq '"labels: \([.labels[].name]|join(",")) | checks: \([.statusCheckRollup[]?|"\(.name)=\(.conclusion // .status)"]|join(" "))"'
```

### Step 2: make sure nothing else is running and the services are up

```bash
tasklist | grep -i "bash.exe"                   # no other run_local_demo still running
openclaw gateway health                         # expect OK
```

If the Gateway is down: `openclaw gateway restart`, wait for port 18789, check health again.

### Step 3: resume (the only command you need)

```bash
cd /c/Users/Yasaswini/nr-repair
bash agents/demo/run_local_demo.sh --issue <N> --poll 5
```

- No new Issue or PR is created. The Editor is skipped, since the ticket already exists.
- The preflight runs in resume mode: the ticket's own PR is allowed; any OTHER open PR blocks it.
- The dispatcher reads the labels and wakes whichever agent is next.
- It stops at "READY FOR HUMAN MERGE" and never merges. You merge in the browser.
- It is safe to run this command again if it stops again.

### Where each stop point resumes

| Issue labels | PR labels | Next agent woken |
|---|---|---|
| `status:ready, agent:reporter` | none | Reporter builds the PR |
| `status:in-review, agent:copydesk` | none, CI green | Copydesk reviews |
| `status:in-review, agent:copydesk` | `review:changes-requested` | Dispatcher re-routes to the Reporter, `attempt:2`, same PR |
| `status:in-test, agent:factcheck` | `review:approved` | Factcheck tests the exact head |
| `status:in-test, agent:factcheck` | `test:failed` | Dispatcher re-routes to the Reporter, `attempt:2`, same PR |
| `status:ready-to-merge` | `review:approved, test:passed` | Nobody. Review and merge by hand |
| `status:blocked` | any | Nobody (3 failed attempts). Human decision needed |

### Real example (Issue #59)

The run was stopped after Copydesk wrote `review:changes-requested` on PR #60 (the Reporter had edited
`app/newsroom/main.py` and added a second test, which broke "do not change any other files"). The Issue
still showed `status:in-review, agent:copydesk`. Resuming with `--issue 59` lets the dispatcher route it
back to the Reporter on the same PR. This is the designed failure loop (section 9).

### Before merging a resumed run

```bash
gh pr diff <PR> --name-only          # must list ONLY the files named in the task
gh pr checks <PR>                    # ci and gate green
gh pr view <PR> --json labels --jq '.[]|.[].name'   # review:approved and test:passed
```

If an out-of-scope file is still listed, do not merge.

### If resume does not help

| Symptom | Fix |
|---|---|
| `open PRs exist` for a PR that is not the ticket's | Close or merge the other PR, then resume |
| `other tickets already active` | Finish or close the other ticket first (one active ticket at a time) |
| `malformed labels; skipped` | Show the labels, say the dispatcher stops rather than guesses; fix by hand only openly |
| `status:blocked` | Designed escalation. Show the dispatcher comment; do not relabel secretly |
| Stale lock | `rm -rf ~/.local/state/newsroom-demo/demo.lock` and check `~/.local/state/newsroom-dispatch/locks` |

---

## 13. One-screen cheat sheet

```bash
cd /c/Users/Yasaswini/nr-repair && git pull --rebase && git status -sb
nslookup github.com
openclaw gateway status ; openclaw gateway health
hermes gateway status ; hermes profile list
bash agents/demo/run_local_demo.sh --preflight-only
bash agents/demo/run_local_demo.sh --task "<one-sentence task>"
bash agents/demo/run_local_demo.sh --issue <N>        # resume after any failure
openclaw gateway restart                              # gateway stuck
hermes gateway restart                                # hermes gateway stuck
gh pr list ; gh pr checks <PR> ; gh pr view <PR> --web
hermes -p editor insights ; hermes -p copydesk insights          # Hermes tokens + est. cost
openclaw sessions --all-agents                                    # OpenClaw per-session tokens
uv run python agents/demo/token_total.py                          # Hermes + OpenClaw lifetime totals
```



uv run python C:\Users\Yasaswini\nr-tools\token_total.py