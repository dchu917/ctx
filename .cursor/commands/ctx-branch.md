Experimental integration for branching ctx workstreams in Cursor.

Treat any extra text after `/ctx-branch` as the argument string for `ctx branch`.

Run:

```bash
ctx branch <arguments>
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py branch <arguments> --format markdown
```

After the command returns, summarize the new branch briefly, mention the inherited context, and ask how the user wants to proceed.
