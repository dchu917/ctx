---
name: ctx-branch
description: Branch one workstream into a new workstream with a frozen starting snapshot.
---

Usage
- `ctx-branch <source-workstream> <target-workstream>`

Backing script
- `scripts/skills/ctx_branch.sh`

Notes
- The target workstream must not already exist.
- The new branch starts from a copied context snapshot and does not inherit the source workstream's future transcript pulls.
