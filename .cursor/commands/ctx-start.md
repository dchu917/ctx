Experimental integration for creating a new ctx workstream in Cursor.

Treat any extra text after `/ctx-start` as the argument string for `ctx start`.

Run:

```bash
ctx start <arguments>
```

If `ctx` is unavailable, fall back to:

```bash
python3 scripts/ctx_cmd.py start <arguments> --format markdown
```

Behavior notes:

- `start` creates a new workstream and its first session.
- If the requested workstream name already exists, ctx auto-creates a suffixed name such as `name (1)`.
- Treat `--pull` strictly as a flag, never as part of the workstream name.
- After the command returns, summarize the loaded workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.
- Do not paste the full ctx pack back unless the user explicitly asks for it.
