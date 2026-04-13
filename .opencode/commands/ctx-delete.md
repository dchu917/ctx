---
description: Experimental OpenCode command to delete a ctx session
---

Experimental integration for deleting ctx sessions in OpenCode.

Run:

```bash
ctx delete $ARGUMENTS
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py delete $ARGUMENTS
```

This is destructive. Be explicit about what will be deleted.
