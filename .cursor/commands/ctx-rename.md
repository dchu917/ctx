Experimental integration for renaming a ctx workstream in Cursor.

Treat any extra text after `/ctx-rename` as the argument string for `ctx rename`.

Run:

```bash
ctx rename <arguments>
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py rename <arguments>
```

If the requested new name already exists, ctx auto-suffixes the renamed workstream.
