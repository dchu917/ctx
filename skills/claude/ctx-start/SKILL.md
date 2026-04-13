---
name: ctx start
description: Start a new session in a ContextFun workstream, auto-pull latest transcript, copy a pack, and print a status line.
---

Usage
- In chat:
  - /ctx start <workstream> — creates a new session
  - /ctx start <workstream> --pull — also ingests the current chat (selects all, copies, and stores it)
- Backing command: `scripts/skills/ctx_start_skill.py`
  - `./scripts/skills/ctx_start_skill.py --name "<workstream>" --agent claude`
  - Add `--pull` to ingest the current chat; add `--paste` to paste the pack

Notes
- Uses local transcript storage (default `~/.claude/projects`, `~/.codex/sessions`).
- Initialize ContextFun with `scripts/quickstart.sh`.
