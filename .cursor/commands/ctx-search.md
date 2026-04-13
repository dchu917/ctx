Experimental integration for searching ctx workstreams in Cursor.

Treat any extra text after `/ctx-search` as the search query.

Run:

```bash
ctx search <query>
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py search <query>
```

Return the grouped search results directly.
