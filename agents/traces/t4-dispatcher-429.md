# Dispatcher wakes Copydesk on Issue #12 and backs off on HTTP 429

Real excerpt from the dispatcher's per-invocation log (`copydesk-12-<epoch>.log`, 31 Oct 2026, about 23:35 local). Nothing was invented; session ids and the agent's prose were dropped.

```
Query: You are copydesk. Work ONLY on Issue #12 (Fix: RSS channel link points to localhost). Read agents/PROTOCOL.md first. ...
Attempt 1/3 failed: HTTP 429: Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day
Rate limited. Resets in ~5h 55m. Waiting 2.7s (attempt 2/3)...
Attempt 2/3 failed: HTTP 429: Rate limit exceeded: free-models-per-day. ...
Attempt 3/3 failed: HTTP 429: Rate limit exceeded: free-models-per-day. ...
Rate limited after 3 retries - HTTP 429 ... (resets in ~5h 55m)
```

Dispatcher state written for the ticket (`issue-12.json`): signature `agent:copydesk|status:in-review`, `failures: 1`, `rate_limited: true`. The next dispatcher tick printed `issue-12: backing off after 1 failure(s)` instead of waking the agent again, which is the PROTOCOL rule "stop on 402/429; do not hammer a failing model". No label or comment was changed on the Issue.

What this shows: the dispatcher woke only the agent named by the labels, detected the failed invocation, kept the retry count in persistent state, and did not retry inside the rate-limit window. After three failed attempts it would set `status:blocked` + `agent:editor` and comment for the human.

## Re-run on Gemini: a real review rejection (PR #13)

After the free-tier quota stalled Copydesk, the dispatcher was re-run with `NEWSROOM_HERMES_EXTRA_ARGS="-m gemini-2.5-flash --provider gemini"`. The Hermes `copydesk` agent reviewed PR #13, set `review:changes-requested` on the PR and `agent:editor` on Issue #12, then lost its gateway before commenting (the dispatcher logged `failure 1/3`). Resuming the same session posted the review. Excerpt from the posted comment (31 Oct 2026, 18:48 UTC):

> "### Handoff  copydesk → editor ... Acceptance criteria ... PASS: app/newsroom/main.py:112-113 ... Changes Requested: In `app/tests/test_main.py`, revert the change in `test_rss_feed_empty_state` (line 119) from `client.get("/")` back to `client.get("/rss.xml")`."

Token numbers in that comment are literally `estimate` (the agent supplied no figures), so none are counted in `docs/token-report.md`.
