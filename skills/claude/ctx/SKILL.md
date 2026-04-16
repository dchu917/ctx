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
- `/ctx rename <new-name>` or `/ctx rename <new-name> --from <existing-workstream>`
- `/ctx delete <workstream>` or `/ctx delete --session-id <id>`
- `/ctx branch <source-workstream> <target-workstream>`

Backing script
- `scripts/ctx.sh`

Notes
- This skill dispatches to the installed `ctx` command or the repo fallback.
- `start` is for creating a new workstream. If that name already exists, ctx automatically creates `name (1)`, `name (2)`, and so on.
- `resume` is for continuing an existing workstream.
- `branch` copies the current context snapshot from one workstream into a new workstream without sharing future transcript pulls.
