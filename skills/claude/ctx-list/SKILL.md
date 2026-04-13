---
name: ctx list
description: List available ContextFun workstreams
---

Usage
- /ctx list — prints workstreams with a one-line goal/latest-task summary

What it runs
- `bash ./scripts/skills/ctx_cli_skill.sh`
- Falls back to `ctx list` or `python3 scripts/ctx_cmd.py list`
