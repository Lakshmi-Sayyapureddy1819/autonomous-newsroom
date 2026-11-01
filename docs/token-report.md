# Token and model report

This is a partial ledger of estimates explicitly present in the GitHub handoff comments. These are not provider billing exports. Missing values are left missing; the report does not infer token totals from commit counts or test output.

## Recorded estimates

| Role | Model | Stage | Recorded prompt tokens | Recorded completion tokens | Coverage |
|---|---|---|---:|---:|---|
| Editor (Hermes) | `google/gemini-3.8-flash` | Planning / T0-T1 | 860 | 400 | Two ticket handoffs; estimates |
| Editor (Hermes) | `google/gemini-3.7-flash` | Planning / T2-T3 | 2,280 | 1,110 | Ticket creation, clarification, and T3 retry routing; estimates |
| Reporter (OpenClaw) | `qwen-2.5-coder-32b` | Coding / T0-T3 | 3,920 | 1,870 | Recorded T0/T1, T2 attempts 1-2, and T3 attempt 1; estimates |

The sums above include only numeric prompt/completion estimates found in the linked handoff comments. They exclude unreported T3 attempt-2 usage, T4 usage, other agent invocations, and any activity not represented in those comments.

## Not numerically reported

- Copydesk (Hermes): the T2 retry review says review usage was unavailable; other review handoffs do not provide complete numeric totals.
- Factcheck (OpenClaw): the T3 attempt-2 handoff says usage was estimated but does not give numbers.
- Reporter (OpenClaw) on T4: commit trailers identify `google/gemini-2.5-flash`, but no numeric token estimate is recorded in the inspected handoff.
- Product summarizer: no provider-level token export is included here.

## Evidence links

- [Issue #1: T0 handoffs](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/1)
- [Issue #3: T1 handoffs](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/3)
- [Issue #5: T2 handoffs, retry, and test result](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/5)
- [Issue #7: T3 handoffs, retry, and test result](https://github.com/Lakshmi-Sayyapureddy1819/autonomous-newsroom/issues/7)

Before final submission, export per-agent/per-model usage from the Hermes and OpenClaw runtimes and replace this partial ledger with measured totals where available. Keep estimates clearly labeled and split them into planning, coding, review/test, and retries.
