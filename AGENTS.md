# ContextFun Agent Guide

Use the installed ContextFun commands directly when the user types them as a message.

Supported chat-style commands in this repo:

- `ctx`
  - Run `ctx`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py`.
  - Return stdout directly.

- `ctx list`
  - Run `ctx list`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py list`.
  - Return stdout directly.
  - If the user typed the plain `ctx list` form, do not describe it as `ctx-list` or say you are using the alias skill. Prefer the exact command the user typed.

- `ctx search <query>`
  - Run `ctx search <query>`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py search <query>`.
  - Return the grouped search results directly.
  - Prefer using this when the user asks to find the relevant workstream or recall prior context.

- `ctx start [--pull] <workstream>`
  - Treat `--pull` strictly as a flag, never as part of the workstream name.
  - Run `ctx start [--pull] <workstream>`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py start [--pull] <workstream> --format markdown`.
  - `start` means create a new workstream. If that name already exists, ctx automatically creates `<workstream> (1)`, `<workstream> (2)`, and so on.
  - Do not paste the full ctx pack back unless the user asks for it.
  - Summarize the loaded workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.
  - Make it explicit that in Codex the user can inspect the full command output with `ctrl-t`, and in Claude they can expand the tool output block.

- `ctx resume <workstream>`
  - Run `ctx resume <workstream>`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py resume <workstream> --format markdown`.
  - `resume` means continue an existing workstream. If the workstream does not exist, tell the user to use `ctx start <workstream>` instead.
  - Do not paste the full ctx pack back unless the user asks for it.
  - Summarize the loaded workstream briefly, mention the latest relevant activity, and ask how the user wants to proceed.
  - Make it explicit that in Codex the user can inspect the full command output with `ctrl-t`, and in Claude they can expand the tool output block.

- `ctx rename <new-name>` or `ctx rename <new-name> --from <existing-workstream>`
  - Run `ctx rename ...`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py rename ...`.
  - If the requested new name already exists, ctx auto-suffixes the rename result the same way as `start`.

- `ctx delete <workstream>` or `ctx delete --session-id <id>`
  - Run `ctx delete ...`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py delete ...`.
  - This is destructive: it deletes the latest session in the named workstream, or the explicit session id.

- `ctx branch <source-workstream> <target-workstream>`
  - Run `ctx branch <source-workstream> <target-workstream>`.
  - If that is unavailable, run `python3 scripts/ctx_cmd.py branch <source-workstream> <target-workstream> --format markdown`.
  - This creates a new workstream seeded from the source workstream snapshot, but future transcript pulls stay independent.
  - Do not paste the full ctx pack back unless the user asks for it.
  - Summarize the new branch briefly, mention the latest inherited context, and ask how the user wants to proceed.
  - Make it explicit that in Codex the user can inspect the full command output with `ctrl-t`, and in Claude they can expand the tool output block.

- Compatibility aliases:
  - `ctx-list`, `ctx-search`, `ctx-start`, `ctx-resume`, `ctx-delete`, `ctx-branch`
  - These should behave the same as the `ctx <subcommand>` forms above.
  - Treat these as compatibility aliases only. Prefer the plain `ctx <subcommand>` wording whenever the user typed that form.

Behavior notes:

- Claude Code supports local skill folders under `~/.claude/skills`.
- Codex does not currently support repo-defined custom slash commands like `/ctx-list`.
- In Codex, prefer plain `ctx`, `ctx list`, `ctx search`, `ctx start`, `ctx resume`, `ctx delete`, and `ctx branch` messages or run the same commands in the terminal.
- If `CTX_AGENT_WORKSTREAM` is set, it is the default workstream when the command omits a name.
