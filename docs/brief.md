# Autonomous Newsroom: Product Brief

## Need

Build a small public newsroom page that gathers recent public AI/ML news, summarizes each story once, and refreshes itself on a schedule. The page should make it easy to open the original source and quickly scan the summary and topic.

## Requirements

- Read stories from one configurable public RSS feed. The default feed may be a Google News RSS search for artificial intelligence.
- Save each story's title, source, URL, publication time, summary, topic tag, and the model used for the summary in SQLite.
- Use the story URL to avoid duplicate rows.
- Summarize only stories with no saved summary. Keep summaries to one sentence and 160 characters or less. Use one tag from `LLMs`, `Research`, `Industry`, `Policy`, `Tools`, or `Other`.
- Configure the primary and fallback summarizer through environment variables. Try the fallback when the primary returns HTTP 402 or 429. Leave an article retryable when both providers fail.
- Record collection and summarization runs, including timestamps, status, counts, and a sanitized error when a run fails or is partial.
- Serve a public page showing recent stories, source links, summaries or a pending message, topic tags, and the time since the last successful refresh. Show a useful empty state before the first stories arrive.
- Refresh automatically every few hours and once shortly after boot. No button press should be needed to collect or summarize stories.
- Keep secrets outside the repository. Keep user data synthetic or public.

## Out of scope for the core

Search, tag filters, multiple feeds, a run-history dashboard, and agent-managed product refresh jobs are optional enhancements. Prioritize a working core and a clear GitHub delivery trail.
