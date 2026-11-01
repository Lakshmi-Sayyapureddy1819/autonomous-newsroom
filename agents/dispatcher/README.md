# GitHub issue dispatcher

`dispatch.sh` -> `dispatch.py` is ordinary code (stdlib Python, no LLM). Each tick it:

1. Polls open Issues and the verdict labels (`review:*`, `test:*`) of their linked PRs through `gh`.
2. Runs the deterministic editor duties in `editor_lifecycle.py`:
   - `review:changes-requested` / `test:failed` -> `attempt+1`, `status:ready`, `agent:reporter`, stale verdicts stripped (same branch and PR).
   - Third failed attempt -> `status:blocked`, `agent:editor`, escalation comment for the human.
   - A ticket waiting on dependencies (`agent:editor`, no `status:*`, `Depends on: #n` in the body) is promoted to `status:ready` + `agent:reporter` once every dependency is closed, and only while no other ticket is in the build/review/test pipeline.
3. Wakes only the agent named by the ticket's single `agent:*` label:

| Labels | Agent | Command (override with `NEWSROOM_CMD_<AGENT>`) |
|---|---|---|
| `status:ready`, `agent:reporter` | reporter | `openclaw agent --agent reporter --message ...` |
| `status:in-review`, `agent:copydesk` | copydesk | `hermes -p copydesk chat -q ... --oneshot` |
| `status:in-test`, `agent:factcheck` | factcheck | `openclaw agent --agent factcheck --message ...` |
| no tickets exist and `docs/brief.md` exists | editor | `hermes -p editor chat -q ... --oneshot` (writes the tickets) |

**Deterministic review/test mode (no LLM, for rate-limited models):** set `NEWSROOM_REVIEW_MODE=deterministic`. Copydesk and Factcheck then run `agents/scripts/copydesk_agent.py` / `factcheck_agent.py` with the **PR number**, which the dispatcher resolves from the single open PR whose `Closes #N` matches the ticket (none or several = a failed attempt, agent not started; same retry/escalation). Copydesk approves only if the PR closes one Issue, is not a draft, has no conflicts and `ci` is green (pending `ci` = no verdict, retried). Factcheck needs `review:approved` + green `ci`, runs ruff and pytest on the exact head SHA in a throwaway worktree, and writes `test:passed` / `test:failed` only from that result (nothing if it cannot run or the head moved). Verdict labels go on the PR; `status:*` / `agent:*` hand-off labels go on the Issue. The default (unset) still uses the Hermes/OpenClaw agents. `NEWSROOM_CMD_<AGENT>` may use `{pr}` as well as `{issue}`.

`status:in-progress` is woken only when untouched for `NEWSROOM_STALE_MINUTES` (default 45). `status:ready-to-merge`, `status:blocked` and malformed label sets are never dispatched.

- **No concurrent duplicates:** a per-agent lock file in the state dir; agents run in parallel with each other, never twice at once. A lock older than the agent timeout is treated as stale.
- **Retry state:** one JSON file per ticket in the state dir survives restarts. An invocation that exits non-zero, times out, or exits 0 without moving the labels counts as a failure. Retries back off (`NEWSROOM_RETRY_BACKOFF`, x30 on 402/429). After 3 failures the ticket becomes `status:blocked` + `agent:editor` with a comment, and the dispatcher stops. If the editor itself fails 3 times, it opens a blocked escalation Issue.
- Output is sanitized (token patterns redacted) before it reaches state, logs or GitHub comments.

```bash
bash agents/dispatcher/dispatch.sh --dry-run   # show what would happen, change nothing
bash agents/dispatcher/dispatch.sh             # real run
python -m pytest agents/dispatcher/tests -q    # offline tests (fake GitHub, fake agents)
```

Authenticate `gh` as the repository owner first. The dispatcher runs agent commands in the repo root (`NEWSROOM_REPO_DIR`); on the VM point it at the staged checkout. Install the timer after `agents/bootstrap.sh`:

```bash
sudo install -m 0644 agents/dispatcher/dispatcher.service /etc/systemd/system/dispatcher.service
sudo install -m 0644 agents/dispatcher/dispatcher.timer /etc/systemd/system/dispatcher.timer
sudo systemctl daemon-reload
sudo systemctl enable --now dispatcher.timer
```

State lives under `/var/lib/newsroom-agent/dispatcher`; optional overrides go in `/etc/newsroom-agent.env` (never put credentials in the repo).
