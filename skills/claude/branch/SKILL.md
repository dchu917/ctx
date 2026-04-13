---
name: branch
description: Branch one workstream into a new workstream with a frozen starting snapshot.
---

Usage
- `/branch <source-workstream> <target-workstream>`

Backing script
- `scripts/skills/branch.sh`

Notes
- The target workstream must not already exist.
- The branch gets a snapshot of the source workstream's current context, but it does not inherit the source's external Claude/Codex transcript bindings.
