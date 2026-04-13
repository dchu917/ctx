---
name: ctx-start
description: Start a new ContextFun session in a workstream and print a markdown pack.
---

What it does
- Ensures/selects a workstream and creates a new session.
- Imports the newest transcript from Codex/Claude (local storage).
- Prints a compact markdown pack that can be pasted back into the chat.

How to trigger
- In Codex:
  - `ctx-start <workstream>`
  - `ctx-start --pull <workstream>` (also ingests current chat)
  - `--pull` can appear before or after the workstream name
- Run from terminal:
  - `bash ./scripts/skills/ctx_start.sh --pull my-workstream`
  - `ctx-start my-workstream`
  - `python3 scripts/ctx_cmd.py start my-workstream --format markdown`

Requirements
- Python 3.9+
- Local transcripts in `~/.codex/sessions` or `~/.claude/projects` (override via `CODEX_HOME`/`CLAUDE_HOME`).
- ContextFun DB (local or global). Use `scripts/quickstart.sh` to initialize.
