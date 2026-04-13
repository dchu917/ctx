---
description: Experimental ctx dispatcher for OpenCode
---

Experimental integration for `ctx` in OpenCode.

- If no extra arguments were supplied, run `ctx`.
- If extra arguments were supplied, run `ctx $ARGUMENTS`.
- If `ctx` is unavailable, fall back to `python3 scripts/ctx_cmd.py $ARGUMENTS`.

Behavior notes:

- `ctx start <name>` creates a new workstream. If the name already exists, ctx creates `name (1)`, `name (2)`, and so on.
- `ctx resume <name>` continues an existing workstream. If it does not exist, tell the user to use `ctx start <name>`.
- Treat `--pull` strictly as a flag, never as part of the workstream name.
- If the command loads a ctx pack, summarize the workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.
- Do not paste the full ctx pack back unless the user explicitly asks for it.
