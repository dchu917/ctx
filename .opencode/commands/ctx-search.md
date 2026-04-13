---
description: Experimental OpenCode command to search ctx workstreams
---

Experimental integration for searching ctx in OpenCode.

Run:

```bash
ctx search $ARGUMENTS
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py search $ARGUMENTS
```

Return the grouped search results directly.
