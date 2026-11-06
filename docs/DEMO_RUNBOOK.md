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

## 9. One-screen cheat sheet

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
```
