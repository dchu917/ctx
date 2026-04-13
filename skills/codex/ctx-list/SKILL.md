---
name: ctx-list
description: Compatibility alias for listing available ContextFun workstreams
---

Usage
- Prefer `ctx list`
- `ctx-list` is a compatibility alias that prints workstreams with a one-line summary

What it runs
- `bash ./scripts/skills/ctx_cli_skill.sh`
- Falls back to `ctx list` or `python3 scripts/ctx_cmd.py list`
