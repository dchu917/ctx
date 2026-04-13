---
name: ctx-resume
description: Resume a ContextFun workstream and print a markdown pack.
---

What it does
- Ensures/selects a workstream.
- Imports the newest transcript from Codex/Claude (local storage).
- Prints a compact markdown pack that can be pasted back into the chat.

How to trigger
- In Codex:
  - `ctx-resume <workstream>`
- Run from terminal:
  - `bash ./scripts/skills/ctx_resume.sh my-workstream`
  - `python3 scripts/ctx_cmd.py resume "<workstream>" --format markdown`

Requirements
- Python 3.9+
- Local transcripts in `~/.codex/sessions` or `~/.claude/projects` (override via `CODEX_HOME`/`CLAUDE_HOME`).
- ContextFun DB (local or global). Use `scripts/quickstart.sh` to initialize.
