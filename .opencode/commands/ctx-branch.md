---
description: Experimental OpenCode command to branch one ctx workstream into another
---

Experimental integration for branching ctx workstreams in OpenCode.

Run:

```bash
ctx branch $ARGUMENTS
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py branch $ARGUMENTS --format markdown
```

After the command returns, summarize the new branch briefly, mention the inherited context, and ask how the user wants to proceed.
