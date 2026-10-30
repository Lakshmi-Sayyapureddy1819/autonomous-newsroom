# Autonomous Newsroom

A self-updating autonomous newsroom delivered by a multi-agent team running on OpenClaw and Hermes Agent.

## Agent Team Roster

The delivery team consists of four specialized roles operating across two runtimes. All agent coordination and handoffs flow exclusively through GitHub Issues, Pull Requests, and label transitions.

- **editor**
  - Runtime: Hermes Agent
  - Role: Orchestrator
  - Responsibilities: Breaks the brief into checkable GitHub Issues, assigns work, re-routes retries, and escalates blockers to human oversight. Does not edit product code or merge PRs.

- **reporter**
  - Runtime: OpenClaw
  - Role: Builder
  - Responsibilities: Claims tickets, implements product features in isolated git branches, writes commits with agent trailers, and opens pull requests. Does not merge PRs.

- **copydesk**
  - Runtime: Hermes Agent
  - Role: Reviewer
  - Responsibilities: Inspects pull request diffs against ticket acceptance criteria, leaves itemized review comments, and applies review approval or changes-requested labels. Does not push code or merge PRs.

- **factcheck**
  - Runtime: OpenClaw
  - Role: Tester
  - Responsibilities: Checks out pull request branches, executes tests, commands, and runtime checks, reports evidence, and applies test passed or failed labels. Does not push code or merge PRs.

- **human** (Lakshmi Sayyapureddy)
  - Role: Human-in-the-loop
  - Responsibilities: Merges PRs via GitHub web UI after review and test gates pass; manages infrastructure, secrets, and repository protection.
