# Hermes profiles

Hermes runs the `editor` and `copydesk` roles as separate profiles. The role identities are in `profiles/editor/SOUL.md` and `profiles/copydesk/SOUL.md`. Create the profiles after installing Hermes, then copy the matching `SOUL.md` into each profile home. Configure each profile's provider credentials locally; do not commit its `.env` or runtime state.

```bash
hermes profile create editor --description "Turns product requirements into GitHub Issues and routes retries."
hermes profile create copydesk --description "Reviews each product PR against its Issue acceptance criteria."
```

Copy the matching `SOUL.md` from this repository into the new profile home. The bootstrap script does this for newly created profiles and preserves existing profiles. Start Hermes from `/opt/newsroom-agent/workspaces/<role>/repo` with its matching profile so it can read `agents/PROTOCOL.md` and the Issue/PR context. Hermes profiles are separate homes; never point both roles at one profile. GitHub is the only channel between the roles and OpenClaw.
