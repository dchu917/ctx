Experimental integration for deleting ctx sessions in Cursor.

Treat any extra text after `/ctx-delete` as the argument string for `ctx delete`.

Run:

```bash
ctx delete <arguments>
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py delete <arguments>
```

This is destructive. Be explicit about what will be deleted.
