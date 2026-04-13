---
name: ctx-delete
description: Delete the latest session in a ContextFun workstream, or delete a specific session id.
---

Usage
- In Codex:
  - `ctx-delete <workstream>` — deletes the latest session in that workstream
  - `ctx-delete --session-id <id>` — deletes that specific session

What it runs
- `bash ./scripts/skills/ctx_delete.sh`
- Falls back to `ctx delete` or `python3 scripts/ctx_cmd.py delete`

Notes
- This is destructive.
- Workstream deletion targets the latest session in the named workstream.

