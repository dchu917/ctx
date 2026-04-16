---
name: ctx start
description: Create a new ContextFun workstream and its first session, then print a markdown pack.
---

Usage
- In chat:
  - `/ctx start <workstream>` — creates a new workstream and its first session, then prints the pack
  - `/ctx start --pull <workstream>` — also ingests the current visible chat into that first session
  - `--pull` can appear before or after the workstream name

What it runs
- `bash ./scripts/ctx_start.sh`
- Falls back to `ctx start` or `python3 scripts/ctx_cmd.py start`

Notes
- If the requested workstream name already exists, ctx automatically creates `name (1)`, `name (2)`, and so on.
- Use `/ctx resume <workstream>` to continue an existing workstream.
- Uses local transcript storage (default `~/.claude/projects`, `~/.codex/sessions`).
- Initialize ContextFun with `scripts/quickstart.sh`.
