---
name: ctx-resume
description: Resume a ContextFun workstream, auto-pull latest Codex/Claude transcript, copy a resume pack, and print a status line.
---

What it does
- Ensures/selects a workstream.
- Imports the newest transcript from Codex/Claude (local storage).
- Generates a compact pack (markdown) and copies it to the clipboard.
- Emits a status line: "Context for [slug] ingested. Last: <type> — <preview>".

How to trigger
- Run the helper script from your repo clone:
  - `python3 scripts/skills/ctx_resume_skill.py --name "<workstream>"`
  - Add `--paste` on macOS to paste into the frontmost app.

Requirements
- Python 3.9+
- Local transcripts in `~/.codex/sessions` or `~/.claude/projects` (override via `CODEX_HOME`/`CLAUDE_HOME`).
- ContextFun DB (local or global). Use `scripts/quickstart.sh` to initialize.
