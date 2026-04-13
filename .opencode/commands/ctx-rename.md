---
description: Experimental OpenCode command to rename a ctx workstream
---

Experimental integration for renaming a ctx workstream in OpenCode.

Run:

```bash
ctx rename $ARGUMENTS
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py rename $ARGUMENTS
```

If the requested new name already exists, ctx auto-suffixes the renamed workstream.
