---
name: ctx start
description: Start a new ContextFun session in a workstream, auto-pull latest transcript, copy a pack, and print a status line.
---

What it does
- Ensures/selects a workstream and creates a new session.
- Imports the newest transcript from Codex/Claude (local storage).
- Generates a compact pack (markdown) and copies it to the clipboard.
- Emits a status line: "Context for [slug] ingested. S<id> created. Last: <type> — <preview>".

How to trigger
- In chat:
  - /ctx start <workstream>
  - /ctx start <workstream> --pull (also ingests current chat)
- Run from terminal:
  - `python3 scripts/skills/ctx_start_skill.py --name "<workstream>" --agent codex`
  - Add `--pull` to ingest, `--paste` to auto-paste pack (macOS)

Requirements
- Python 3.9+
- Local transcripts in `~/.codex/sessions` or `~/.claude/projects` (override via `CODEX_HOME`/`CLAUDE_HOME`).
- ContextFun DB (local or global). Use `scripts/quickstart.sh` to initialize.
