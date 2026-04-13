---
description: Experimental OpenCode command to continue an existing ctx workstream
---

Experimental integration for resuming an existing ctx workstream in OpenCode.

Run:

```bash
ctx resume $ARGUMENTS
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py resume $ARGUMENTS --format markdown
```

Behavior notes:

- `resume` continues an existing workstream. If the workstream does not exist, tell the user to use `ctx start <name>`.
- After the command returns, summarize the loaded workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.
- Do not paste the full ctx pack back unless the user explicitly asks for it.
