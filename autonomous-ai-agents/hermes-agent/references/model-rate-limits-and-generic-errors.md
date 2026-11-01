# LLM Rate Limits and Generic Agent Errors

This document outlines strategies and pitfalls related to persistent rate limiting and generic agent failures encountered with free-tier LLM providers.

## Pitfall: Persistent Rate Limiting (HTTP 429, "needs a short break")

**Rule:** Free-tier LLM providers frequently impose strict rate limits (e.g., "HTTP 429: Rate limit exceeded", "The AI service needs a short break"). These limits can persist even after switching models or making multiple retry attempts within a short period.

**Why:** Providers implement these limits to manage resource allocation on free tiers. The exact reset times and allowable request volumes are often undocumented or dynamic.

**Mitigation Strategies:**

1.  **Increase Dispatcher Backoff (`NEWSROOM_RETRY_BACKOFF`):**
    *   **Procedure:** Temporarily increase the `NEWSROOM_RETRY_BACKOFF` environment variable in the dispatcher's configuration (e.g., to `300` seconds / 5 minutes or more). This provides longer intervals between agent invocation retries, giving the model's rate limit more time to reset.
    *   **Command (example):** `export NEWSROOM_RETRY_BACKOFF=300`

2.  **Switch LLM Models/Providers:**
    *   **Procedure:** Configure Hermes and OpenClaw agents to use different models or providers, especially if one provider consistently hits rate limits. This can be done via environment variables (`NEWSROOM_HERMES_EXTRA_ARGS`, `NEWSROOM_OPENCLAW_EXTRA_ARGS`) or agent-specific configuration.
    *   **Command (example for Hermes):** `export NEWSROOM_HERMES_EXTRA_ARGS="--model gemini-1.5-pro --provider gemini"`
    *   **Pitfall:** Even after switching, new models/providers may also have their own rate limits or temporary unavailability. Monitor agent logs closely.

3.  **Manual Intervention (Escalation):**
    *   **Procedure:** If rate limits persist after multiple attempts and backoff, the dispatcher's escalation mechanism (setting `status:blocked`, `agent:editor`) will flag the ticket for human review. The human must then manually clear the `rate_limited` flag in the dispatcher's state file or wait for the rate limit to naturally expire.
    *   **Pitfall:** Avoid manually setting `review:approved` or `test:passed` labels to bypass rate limits, as this circumvents genuine agent validation.

## Pitfall: Generic Agent Failures ("couldn't generate a response")

**Rule:** Generic agent errors (e.g., "Agent couldn't generate a response" from Hermes, "OpenClaw couldn't finish this reply" from OpenClaw) provide limited debugging information and often indicate internal model issues or prompt complexity that the agent cannot resolve.

**Why:** These messages are high-level summaries from the agent runtime when the underlying LLM call or internal agent process fails without a specific, actionable error code.

**Mitigation Strategies:**

1.  **Inspect Detailed Agent Logs:**
    *   **Procedure:** Always inspect the specific agent's detailed logs (e.g., in `C:\Users\Yasaswini\.local\state\newsroom-dispatch\logs/`) for more context. Look for any underlying LLM API errors, Python tracebacks, or specific agent tool failures.
    *   **Command (example):** `ls -t C:/Users/Yasaswini/.local/state/newsroom-dispatch/logs/reporter-12-*.log | head -n 1` followed by `read_file <log_path>`.

2.  **Simplify Agent Task (if possible):**
    *   **Procedure:** If a task consistently triggers generic failures, consider whether the prompt can be simplified or broken down into smaller sub-tasks.

3.  **Rely on Dispatcher Escalation:**
    *   **Procedure:** Allow the dispatcher's retry and escalation mechanisms to handle repeated generic failures. A ticket will eventually be marked `status:blocked`, `agent:editor`, signaling a need for human intervention.
    *   **Pitfall:** Do not repeatedly force agent re-runs if failures persist, as this consumes tokens without making progress.
