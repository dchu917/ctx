ContextFun
===========

Capture, organize, and resume coding context across agents (Claude, Codex, etc.) using a tiny local CLI backed by SQLite. ContextFun introduces Workstreams so you can group sessions by goal and resume from either Claude Code or Codex with the command style each client actually supports.

Features
--------

- Workstreams: Stable slugs to group sessions by project/goal.
- Sessions: Create, list, show, and auto-link to a workstream.
- Entries: Add notes, decisions, todos, files, links (stdin and snapshots supported).
- Resume packs: Compact text/Markdown packs for pasting into any agent.
- Stable transcript binding: A workstream can bind to the exact Claude and/or Codex conversation id it was started from, so later pulls do not drift to a newer chat.
- Branching: Seed a new workstream from an existing workstream snapshot without sharing future transcript pulls.
- Agent commands: Claude Code skills plus `ctx`, `ctx-list`, `ctx-start`, `ctx-resume`, `ctx-delete`, and `ctx-branch` executables for Codex.
- Local-first: Pure stdlib, SQLite; no cloud or API keys. Global DB supported.

Install (1-liner)
-----------------

Run once locally to install a shared DB and `ctx` shim in `~/.contextfun` (no git needed):

`curl -fsSL https://raw.githubusercontent.com/dchu917/ctx/main/scripts/install.sh | bash`

Agent bootstrap (1-liner)
-------------------------

Paste this in Claude Code or Codex terminals to sync with your local DB/path:

Two options depending on where you want the files:

- Global (shared across all workspaces):
  - `source <(curl -fsSL https://raw.githubusercontent.com/dchu917/ctx/main/scripts/agent_bootstrap.sh)`

- Project-local (download into ./ctx so it’s easy to package/export with the repo):
  - `source <(curl -fsSL https://raw.githubusercontent.com/dchu917/ctx/main/scripts/agent_setup_local_ctx.sh)`

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

Quickstart
----------

After cloning this repo, run:

- `./setup.sh`

That local setup does all of the following:

- Creates `./.contextfun/context.db`
- Writes `./ctx.env`
- Installs repo-backed `ctx`, `ctx-list`, `ctx-start`, `ctx-resume`, `ctx-delete`, and `ctx-branch` shims into `~/.contextfun/bin`
- Links local skill folders into `~/.claude/skills` and `~/.codex/skills`

Other setup modes:

- Local explicit: `bash scripts/quickstart.sh`
- Global install: `./setup.sh --global`

Agent Commands
--------------

Claude Code:

- Restart Claude Code after running quickstart.
- Use `/ctx` to see the current workstream
- Use `/ctx list` to see workstreams with one-line goal/latest-task summaries
- Use `/ctx start my-workstream --pull`
- Use `/ctx resume my-workstream`
- Use `/ctx delete my-workstream`
- Use `/ctx branch source-workstream target-workstream`
- Use `/branch source-workstream target-workstream` as a dedicated branch shortcut

Codex:

- Restart Codex after running quickstart.
- Use `ctx` to see the current workstream
- Use `ctx-list` to see workstreams with one-line goal/latest-task summaries
- Use `ctx-start my-workstream`
- Use `ctx-start --pull my-workstream`
- Use `ctx-resume my-workstream`
- Use `ctx-delete my-workstream`
- Use `ctx-branch source-workstream target-workstream`

Codex note:

- Codex does not currently expose repo-defined custom slash commands like `/ctx-list`.
- The supported Codex path is installed `ctx` / `ctx-*` executables plus the repo `AGENTS.md`.

How Transcript Linking Works
---------------------------

- `ctx` stores its own SQLite entities:
  - `workstream`
  - `session`
  - `entry`
- Transcript identity is tracked at the workstream level, not by guessing on every pull.
- The first time a workstream pulls from Claude or Codex, `ctx` records:
  - source: `claude` or `codex`
  - exact external session id from the transcript file
  - transcript path
  - how many messages were already ingested
- Later `start`, `resume`, and `pull` calls for that workstream reuse the exact same external conversation instead of switching to whichever transcript file is newest.
- New messages are ingested incrementally from the linked transcript. Old messages are not re-ingested into every new ctx session.
- A workstream can be linked to both one Claude conversation and one Codex conversation at the same time.

What `--pull` Means
-------------------

- `--pull` is separate from transcript binding.
- `ctx start my-workstream --pull` means:
  - create a new ctx session
  - copy the visible frontmost chat via Cmd+A / Cmd+C on macOS
  - ingest that clipboard text into the new ctx session
- `--pull` does not create or change the stable Claude/Codex transcript binding by itself.

Branching
---------

- `ctx-branch source-workstream target-workstream`
- Claude shortcuts:
  - `/ctx branch source-workstream target-workstream`
  - `/branch source-workstream target-workstream`
- Branching creates a new target workstream and seeds it with a snapshot pack from the source workstream.
- The target does not inherit the source workstream's Claude/Codex transcript binding.
- After branching, future transcript pulls and new ctx sessions in the target are independent from the source.

Agent Setup Tips
----------------

- Optional global store across apps:
  - `export CONTEXTFUN_DB="$HOME/.contextfun/context.db"`
- For quick capture during coding:
  - `git diff | ctx add-latest --type note --text -`
- For per-agent defaults:
  - `export CTX_AGENT_WORKSTREAM="my-workstream"`

Security Model
--------------

- `ctx` is a context/memory layer, not a sandbox.
- Installing `ctx` does not reduce the shell permissions of Claude Code or Codex by itself.
- The actual security boundary still comes from the agent runtime:
  - Codex/Claude approval mode
  - Codex/Claude filesystem sandbox settings
  - the OS user account and file permissions
  - Accessibility permissions for `--pull`
- Recommended setup if you want tight controls:
  - keep approvals enabled in the agent
  - use workspace-scoped sandboxes where available
  - only grant Accessibility permission if you need `--pull`
  - use a dedicated repo or dedicated machine/user for sensitive work
  - treat `ctx` transcript imports as local data access to `~/.claude/projects` and `~/.codex/sessions`
- `ctx` does help reduce accidental context mixups by binding each workstream to exact Claude/Codex conversation ids after first pull.
- See [SECURITY.md](SECURITY.md) for a short threat-model summary and recommended controls.

Automation Helpers
------------------

The Python helpers under `scripts/skills/` are for clipboard and automation workflows such as Raycast or Keyboard Maestro. They are not the primary Claude/Codex skill entrypoints.

- `python3 scripts/skills/ctx_resume_skill.py --name "my-workstream" --paste`
- `python3 scripts/skills/ctx_start_skill.py --name "my-workstream" --agent codex --pull --paste`

Delete Sessions
---------------

- Core CLI:
  - `python3 scripts/ctx_cmd.py delete my-workstream`
  - `python3 scripts/ctx_cmd.py delete --session-id 123`
- Claude Code:
  - `/ctx delete my-workstream`
  - `/ctx delete --session-id 123`
- Codex:
  - `ctx-delete my-workstream`
  - `ctx-delete --session-id 123`

Branch Workstreams
------------------

- Core CLI:
  - `python3 scripts/ctx_cmd.py branch source-workstream target-workstream --format markdown`
- Claude Code:
  - `/ctx branch source-workstream target-workstream`
  - `/branch source-workstream target-workstream`
- Codex:
  - `ctx-branch source-workstream target-workstream`

Notes:

- Deleting by workstream deletes the latest session in that workstream.
- Deleting by `--session-id` deletes exactly that session.
- This is destructive.

Install skills into Codex/Claude
--------------------------------

- Local symlink install:
  - `bash scripts/install_skills.sh`
- Official Codex install path:
  - Install the repo-backed Codex skills into `~/.codex/skills` from GitHub using the `skill-installer` helper, or symlink them locally with `scripts/install_skills.sh`.
- If your apps use non-default skill directories, override with:
  - `CODEX_SKILLS_DIR=/custom/codex/skills CLAUDE_SKILLS_DIR=/custom/claude/skills bash scripts/install_skills.sh`


Pull transcripts from Codex / Claude
------------------------------------

- Auto-pull defaults to ON (set `CTX_AUTOPULL_DEFAULT=0` to disable). You can still force on/off per command with `--auto-pull` / `--no-auto-pull`.
- Manual pull into the latest session of the current workstream:
  - `python3 scripts/ctx_cmd.py pull --codex`
  - `python3 scripts/ctx_cmd.py pull --claude`
  - `python3 scripts/ctx_cmd.py pull --auto`
- Defaults and paths:
  - Codex: scans `CODEX_HOME/sessions` (default `~/.codex/sessions`) for the most recent `*.jsonl`/`*.json` transcript.
  - Claude Code: scans `CLAUDE_HOME/projects` (default `~/.claude/projects`) for the most recent `*.jsonl`/`*.json` transcript.
  - Parsed roles/content are heuristic and best-effort across common JSON/JSONL shapes.

Slash-like command in any chat (optional)
-----------------------------------------

If you want to type `/ctx ...` in any text box and have it expand to a ContextFun pack:

1) Install Espanso (open-source text expander): https://espanso.org
2) Create a match file, for example `~/.config/espanso/match/contextfun.yml` with:

   - trigger: "/ctx list"
     replace: "$(python3 /absolute/path/to/your/repo/scripts/ctx_cmd.py list)"

   - trigger: "/ctx start {{name}}"
     replace: "$(python3 /absolute/path/to/your/repo/scripts/ctx_cmd.py start \"{{name}}\" --format markdown)"
     vars:
       - name: name
         type: clipboard

   - trigger: "/ctx resume {{name}}"
     replace: "$(python3 /absolute/path/to/your/repo/scripts/ctx_cmd.py resume \"{{name}}\" --format markdown)"
     vars:
       - name: name
         type: clipboard

3) Reload Espanso. Now typing `/ctx start proj-demo` or `/ctx resume proj-demo` in any app will expand to your pack. You can use a dynamic script to list slugs too; see Espanso docs for `shell` variable types.

Alternative (Keyboard Maestro / Raycast)
----------------------------------------

- Keyboard Maestro: Create macros for `/ctx list`, `/ctx start <name>`, and `/ctx resume <name>` that call `scripts/ctx_cmd.py` and paste stdout.
- Raycast: Add Script Commands that forward to `scripts/ctx_cmd.py list|start|resume` and paste output.

Automatic Copy/Paste (macOS)
----------------------------

If you want to trigger copy/paste automatically from the frontmost app (Claude/Codex), use the macOS helper scripts. You must grant Accessibility permission to the app running these scripts (Terminal/iTerm/Raycast).

- Copy and ingest the entire chat:
  - `bash scripts/mac_copy_and_ingest.sh --format markdown --source claude`
  - This sends Cmd+A, Cmd+C to the frontmost app, then ingests clipboard into the current workstream’s latest session.

- Generate and paste a pack into the frontmost app:
  - `bash scripts/mac_paste_pack.sh "My Workstream" --format markdown --focus decision,todo`
  - Copies the pack to clipboard and sends Cmd+V to paste.

Tips:
- To truly “auto-capture” the chat, chain a keystroke copy before expansion (Keyboard Maestro) or run `mac_copy_and_ingest.sh` first, then expand `/ctx start ...`.
- Set `CTX_SOURCE_DEFAULT=claude` or `codex` to label captured entries.
- To pull from agent storage directly, set env vars if needed: `CODEX_HOME=~/.codex`, `CLAUDE_HOME=~/.claude` (defaults are used if unset). The importer looks under `~/.codex/sessions/` and `~/.claude/projects/` for the newest `*.jsonl` transcript.

Notes:
- Grant Accessibility: System Settings → Privacy & Security → Accessibility → enable for your terminal/launcher.
- Clipboard-only ingestion also works without Accessibility: `pbpaste | python3 -m contextfun ingest --file - --format markdown --source claude`.
- Linux: use `xdotool` + `xclip` equivalents; Windows: AutoHotkey.

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
  - `session-delete <id>`
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

- Agent wrapper commands
  - `ctx` — show the current workstream
  - `ctx list`
  - `ctx start <workstream> [--pull]`
  - `ctx resume <workstream>`
  - `ctx delete <workstream>` or `ctx delete --session-id <id>`
  - `ctx branch <source-workstream> <target-workstream>`

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
