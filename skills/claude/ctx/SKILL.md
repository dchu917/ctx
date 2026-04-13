---
name: ctx
description: Show the current workstream, or dispatch ctx subcommands like list, start, resume, delete, and branch.
---

Usage
- `/ctx` — show the current workstream
- `/ctx list`
- `/ctx search <query>`
- `/ctx start <workstream> [--pull]`
- `/ctx resume <workstream>`
- `/ctx delete <workstream>` or `/ctx delete --session-id <id>`
- `/ctx branch <source-workstream> <target-workstream>`

Backing script
- `scripts/skills/ctx.sh`

Notes
- This skill dispatches to the installed `ctx` command or the repo fallback.
- `branch` copies the current context snapshot from one workstream into a new workstream without sharing future transcript pulls.
