# ContextFun Agent Guide

Use the installed ContextFun commands directly when the user types them as a message.

Supported chat-style commands in this repo:

- `ctx`
  - Run `ctx`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py`.
  - Return stdout directly.

- `ctx-list`
  - Run `ctx-list`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py list`.
  - Return stdout directly.

- `ctx-start [--pull] <workstream>`
  - Treat `--pull` strictly as a flag, never as part of the workstream name.
  - Run `ctx-start [--pull] <workstream>`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py start [--pull] <workstream> --format markdown`.
  - Return the emitted markdown pack directly.

- `ctx-resume <workstream>`
  - Run `ctx-resume <workstream>`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py resume <workstream> --format markdown`.
  - Return the emitted markdown pack directly.

- `ctx-delete <workstream>` or `ctx-delete --session-id <id>`
  - Run `ctx-delete ...`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py delete ...`.
  - This is destructive: it deletes the latest session in the named workstream, or the explicit session id.

- `ctx-branch <source-workstream> <target-workstream>`
  - Run `ctx-branch <source-workstream> <target-workstream>`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py branch <source-workstream> <target-workstream> --format markdown`.
  - This creates a new workstream seeded from the source workstream snapshot, but future transcript pulls stay independent.

Behavior notes:

- Claude Code supports local skill folders under `~/.claude/skills`.
- Codex does not currently support repo-defined custom slash commands like `/ctx-list`.
- In Codex, prefer plain `ctx-list`, `ctx-start`, `ctx-resume`, and `ctx-delete` messages or run the same commands in the terminal.
- If `CTX_AGENT_WORKSTREAM` is set, it is the default workstream when the command omits a name.
