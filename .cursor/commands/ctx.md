Experimental integration for `ctx` in Cursor.

- If the user invokes this command without extra text, run `ctx`.
- If the user adds extra text after `/ctx`, treat that text as the `ctx` argument string and run `ctx <that text>`.
- If `ctx` is unavailable, fall back to `python3 scripts/ctx_cmd.py <that text>`.

Behavior notes:

- `start` creates a new workstream. If the name already exists, ctx creates `name (1)`, `name (2)`, and so on.
- `resume` continues an existing workstream. If it does not exist, tell the user to use `ctx start <name>`.
- Treat `--pull` strictly as a flag, never as part of the workstream name.
- If the command loads a ctx pack, summarize the workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.
- Do not paste the full ctx pack back unless the user explicitly asks for it.
