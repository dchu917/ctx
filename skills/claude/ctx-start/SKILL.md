---
name: ctx start
description: Start a new session in a ContextFun workstream and print a markdown pack.
---

Usage
- In chat:
  - `/ctx start <workstream>` — creates a new session and prints the pack
  - `/ctx start --pull <workstream>` — also ingests the current visible chat into the new session
  - `--pull` can appear before or after the workstream name

What it runs
- `bash ./scripts/skills/ctx_start.sh`
- Falls back to `ctx start` or `python3 scripts/ctx_cmd.py start`

Notes
- Uses local transcript storage (default `~/.claude/projects`, `~/.codex/sessions`).
- Initialize ContextFun with `scripts/quickstart.sh`.
