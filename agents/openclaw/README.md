# OpenClaw workers

OpenClaw runs `reporter` and `factcheck` as separate agents with separate workspaces. The role prompts live in this directory; copy the matching prompt to the root of that agent's workspace as `AGENTS.md`.

After OpenClaw has been installed and onboarded with the intended provider, register the agents with the supported CLI (preferred):

```bash
openclaw agents add reporter \
  --workspace "$HOME/.openclaw/workspaces/reporter" \
  --non-interactive

openclaw agents add factcheck \
  --workspace "$HOME/.openclaw/workspaces/factcheck" \
  --non-interactive
```

The bootstrap script stages `reporter/AGENTS.md` and `factcheck/AGENTS.md` into their respective workspace roots. Each workspace has a separate `repo/` checkout. Keep provider credentials in the OpenClaw credential store or local environment; never copy them into this repository.

`agents.example.json` is a credential-free configuration fragment for the per-agent workspaces. Do not replace the whole generated OpenClaw config with it; use the CLI or merge only the `agents.entries` values into the existing config.

Use the configured agent name when opening an agent session. Do not use OpenClaw subagents to hand code from reporter to reviewer or tester: GitHub Issues, PRs, labels, and comments remain the only handoff channel.
