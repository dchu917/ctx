ContextFun
===========

Capture, organize, and resume coding context across agents (Claude, Codex, etc.) using a tiny local CLI backed by SQLite. ContextFun introduces Workstreams so you can group sessions by goal and instantly “resume” from any agent with a single slash-style command.

Features
--------

- Workstreams: Stable slugs to group sessions by project/goal.
- Sessions: Create, list, show, and auto-link to a workstream.
- Entries: Add notes, decisions, todos, files, links (stdin and snapshots supported).
- Resume packs: Compact text/Markdown packs for pasting into any agent.
- Slash flow: One-liner shim to support `/ctx --new`, `/ctx`, and `/ctx list` in chats.
- Local-first: Pure stdlib, SQLite; no cloud or API keys. Global DB supported.

Install (1-liner)
-----------------

Run once locally to install a shared DB and `ctx` shim in `~/.contextfun`:

```
sh -lc 'mkdir -p ~/.contextfun/{bin,lib} && cp -R contextfun ~/.contextfun/lib/ && install -m 0755 scripts/ctx_cmd.py ~/.contextfun/bin/ctx && echo "export CONTEXTFUN_DB=$HOME/.contextfun/context.db" >> ~/.zshrc && echo "export PATH=$HOME/.contextfun/bin:\$PATH" >> ~/.zshrc && python3 -m contextfun --db "$HOME/.contextfun/context.db" init && echo "Installed ctx; restart your shell to use it."'
```

Agent bootstrap (1-liner)
-------------------------

Paste this in Claude Code or Codex terminals at the start of a workspace to sync with your local DB/path:

```
sh -lc 'export CONTEXTFUN_DB="$HOME/.contextfun/context.db"; export PATH="$HOME/.contextfun/bin:$PATH"; echo "ctx ready"'
```

Basic Usage
-----------

- Initialize (optional, auto-initializes on first command):
  - `python -m contextfun init`

- Create a workstream:
  - `python -m contextfun workstream-new proj-auth-refactor "Auth Module Refactor" --tags auth,refactor --workspace $PWD --description "Reduce duplication; add tests"`
  - Prints the new workstream id (e.g., `1`).

- Set and view the current workstream (for convenience):
  - `python -m contextfun workstream-set-current --slug proj-auth-refactor`
  - `python -m contextfun workstream-current`

- Create a new session (linked to a workstream):
  - `python -m contextfun session-new "Investigate flaky tests" --agent codex --workstream-slug proj-auth-refactor`
  - Prints the new session id (e.g., `3`).
  - If a current workstream is set, `session-new` will auto-link to it.

- List sessions (filters optional):
  - `python -m contextfun session-list`
  - `python -m contextfun session-list --agent claude`
  - `python -m contextfun session-list --tag auth --query Refactor`
  - `python -m contextfun session-list --workstream-slug proj-auth-refactor`

- Show a session (entries and metadata):
  - `python -m contextfun session-show 3`

- Show a workstream and recent sessions:
  - `python -m contextfun workstream-show --slug proj-auth-refactor`

- Add an entry (note):
  - `python -m contextfun add 3 --type note --text "Drafted new API surface; pending tests."`
  - Or pipe from stdin: `git diff | python -m contextfun add 3 --type note --text -`
  - New entry types include: `decision` and `todo`.

- Add an entry to the latest session in a workstream (or current):
  - `python -m contextfun add-latest --type decision --text "Adopt pytest-xdist; cap workers at 4."`
  - Or specify explicitly: `python -m contextfun add-latest --workstream-slug proj-auth-refactor --type todo --text "Refactor fixtures into conftest."`

- Add an entry from a file and snapshot the file contents:
  - `python -m contextfun add 3 --type file --from-file README.md --snapshot README.md`
  - Snapshots are stored under `~/.contextfun/attachments/<session>/<entry>/` and linked in entry extras.

- Search across titles and entry content:
  - `python -m contextfun search "auth token"`

- Export to JSON (single session or all):
  - `python -m contextfun export --session-id 3 --out session3.json`
  - `python -m contextfun export > all-sessions.json`

- Import from JSON:
  - `python -m contextfun import --file session3.json`
  - Or: `cat all-sessions.json | python -m contextfun import`

- Produce a copy-paste pack to resume a workstream with any agent:
  - `python -m contextfun pack --workstream-slug proj-auth-refactor --max-sessions 5 --max-entries 40`
  - Focus on decisions/todos only: `python -m contextfun pack --workstream-slug proj-auth-refactor --focus decision,todo`
  - Markdown output: `python -m contextfun pack --workstream-slug proj-auth-refactor --format markdown`
  - Brief header only: `python -m contextfun pack --workstream-slug proj-auth-refactor --brief`
  - Or use the convenience wrapper with preamble: `python -m contextfun resume --workstream-slug proj-auth-refactor --format markdown`

Slash Flow in Chats
-------------------

You can type these in Claude/Codex chats if you use a text expander (Espanso/Keyboard Maestro/Raycast) to execute and paste results:

- `/ctx --new My Workstream` → ensure/create workstream, set current, create session, paste pack
- `/ctx My Workstream` → ensure/create workstream, set current, paste pack
- `/ctx list` → list all workstreams

Agent Setup Tips
----------------

- Add shell aliases (optional):
  - `alias ctx='python -m contextfun'`
  - Common flows: `ctx workstream-set-current --slug <slug>`; `ctx session-new "..."`; `ctx add-latest --type note --text "..."`; `ctx pack --format markdown`.
- Optional global store across apps:
  - `export CONTEXTFUN_DB="$HOME/.contextfun/context.db"`
  - The `scripts/ctx_cmd.py` shim will pass `--db` automatically when this env var is set, so `/ctx` works everywhere with one DB.
- With Claude / Codex / others: Start a new chat by pasting the output of `ctx resume --workstream-slug <slug> --format markdown`.
- For quick capture during coding: pipe diffs or logs into the latest session in the current workstream:
  - `git diff | ctx add-latest --type note --text -`
- Consider a global store by setting `--db ~/.contextfun/context.db` in your aliases if you want cross-repo continuity.

Slash-like command in any chat (Espanso)
----------------------------------------

If you want to type `/workstreams <slug>` in any text box (Claude, etc.) and have it expand to your resume pack:

1) Install Espanso (open-source text expander): https://espanso.org
2) Create a match file, for example `~/.config/espanso/match/contextfun.yml` with:

   - trigger: "/ctx --new {{name}}"
     replace: "$(python3 /absolute/path/to/your/repo/scripts/ctx_cmd.py new \"{{name}}\")"
     vars:
       - name: name
         type: clipboard  # or 'prompt' if supported in your Espanso version

   - trigger: "/ctx list"
     replace: "$(python3 /absolute/path/to/your/repo/scripts/ctx_cmd.py list)"

   - trigger: "/ctx {{name}}"
     replace: "$(python3 /absolute/path/to/your/repo/scripts/ctx_cmd.py go \"{{name}}\")"
     vars:
       - name: name
         type: clipboard

3) Reload Espanso. Now typing `/workstreams proj-demo` in Claude will expand to your pack. You can use a dynamic script to list slugs too; see Espanso docs for `shell` variable types.

Alternative (Keyboard Maestro / Raycast)
----------------------------------------

- Keyboard Maestro: Create macros:
  - "ctx new": Trigger regex `/ctx\s+--new\s+(.+)` → Action: `python3 scripts/ctx_cmd.py new "$1" | pbcopy` → Paste.
  - "ctx go": Trigger regex `/ctx\s+(.+)` → Action: `python3 scripts/ctx_cmd.py go "$1" | pbcopy` → Paste.
  - "ctx list": Trigger regex `/ctx\s+list` → Action: `python3 scripts/ctx_cmd.py list | pbcopy` → Paste.
- Raycast: Add a Script Command (Bash or Python) that forwards to `scripts/ctx_cmd.py` with `new`, `go`, or `list` and pastes output.

Command Reference
-----------------

- Workstreams
  - `workstream-new <slug> <title> [--description --tags --workspace --summary]`
  - `workstream-ensure <name> [--slug --workspace --set-current --json]`
  - `workstream-list [--tag --query --format plain|slugs]`
  - `workstream-show (--slug <slug> | --id <id>)`
  - `workstream-set-current (--slug <slug> | --id <id>)`
  - `workstream-current`

- Sessions & entries
  - `session-new <title> [--agent --tags --workspace --summary --workstream-slug|--workstream-id]`
  - `session-list [--agent --tag --query --workstream-slug]`
  - `session-show <id>`
  - `add <session_id> [--type note|cmd|file|link|decision|todo --text -|<txt> --from-file <path> --snapshot <path>]`
  - `add-latest [--workstream-slug|--workstream-id] [--type ... --text ... --from-file ... --snapshot ...]`
  - `session-latest [--workstream-slug|--workstream-id]`

- Packs & search
  - `pack --workstream-slug <slug> [--max-sessions --max-entries --focus <types> --format text|markdown --brief]`
  - `resume [--workstream-slug|--workstream-id] [--focus --format text|markdown --brief]`
  - `search <query>`
  - `export [--session-id <id>] [--out <file|-]>`
  - `import [--file <file|-]>`

Design Notes
------------

- SQLite file: Defaults to `.contextfun/context.db` in CWD; override via `--db` or the `CONTEXTFUN_DB` env var (used by the `ctx` shim and one-liners).
- Attachments: Stored under `.contextfun/attachments/<session>/<entry>/`.
- Schema: `workstream` ↔ `session` (FK), `entry` linked to `session`.
- Migrations: Best-effort, additive migrations run on `init_db`.

Roadmap
-------

- Git capture helpers (branch, status, last commit) → entries.
- TUI for browsing and editing.
- Multi-attach per entry and per-entry tags.

FAQ
---

- Q: Do I need API keys or network?
  - A: No. Everything is local, pure Python stdlib.
- Q: Can multiple repos share the same context?
  - A: Yes. Set `CONTEXTFUN_DB` to a single global path and both Claude/Codex will use the same DB.

