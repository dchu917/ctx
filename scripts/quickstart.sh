#!/usr/bin/env bash
set -euo pipefail

# ContextFun Quickstart (run after cloning this repo)
# - Initializes a local DB in ./.contextfun
# - Creates a project env file with handy aliases
# - Installs repo-backed shims and local skill links for Claude/Codex
# - Prints the exact commands that work in each agent

usage() {
  cat <<EOF
Usage: $0 [--global]

Without flags, sets up a project-local ContextFun store under ./.contextfun, writes ./ctx.env,
installs repo-backed ctx-* shims, and links skills into ~/.claude/skills and ~/.codex/skills.
Use --global to install a shared CLI into ~/.contextfun (requires PATH update; see output).
EOF
}

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
DB_LOCAL="$ROOT_DIR/.contextfun/context.db"

GLOBAL=false
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage; exit 0
fi
if [[ "${1:-}" == "--global" ]]; then
  GLOBAL=true
fi

echo "==> ContextFun Quickstart"

if $GLOBAL; then
  echo "[1/3] Installing global CLI to ~/.contextfun (ctx on PATH)"
  bash "$ROOT_DIR/scripts/install.sh"
  echo "[2/3] Verifying installation"
  if command -v ctx >/dev/null 2>&1; then
    echo "  - Found 'ctx' in PATH"
  else
    echo "  - 'ctx' not yet in PATH. Open a new shell or add: export PATH=\"$HOME/.contextfun/bin:\$PATH\""
  fi
  echo "[3/3] Initializing global DB at \"$HOME/.contextfun/context.db\""
  PYTHONPATH="$HOME/.contextfun/lib" python3 -m contextfun --db "$HOME/.contextfun/context.db" init >/dev/null || true
  echo "\nDone. You can now run: ctx list"
else
  echo "[1/5] Initializing project-local DB at $DB_LOCAL"
  mkdir -p "$(dirname "$DB_LOCAL")"
  python3 -m contextfun --db "$DB_LOCAL" init >/dev/null || true

  ENV_FILE="$ROOT_DIR/ctx.env"
  echo "[2/5] Writing project env to $ENV_FILE"
  cat > "$ENV_FILE" <<EOF
# ContextFun project environment
export CONTEXTFUN_DB="$DB_LOCAL"
alias ctx-local='python3 "$ROOT_DIR/scripts/ctx_cmd.py"'
EOF

  echo "[3/5] Installing repo-backed ctx-* shims into ~/.contextfun/bin"
  bash "$ROOT_DIR/scripts/install_shims.sh"

  echo "[4/5] Linking local skills into ~/.claude/skills and ~/.codex/skills"
  bash "$ROOT_DIR/scripts/install_skills.sh"

  echo "[5/5] Smoke test (list workstreams)"
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  python3 "$ROOT_DIR/scripts/ctx_cmd.py" list || true

  echo "Next steps"
  cat <<'NEXT'
- Activate this project env in new shells: source ./ctx.env
- Claude Code:
  - Restart Claude Code, then use `/ctx`, `/ctx list`, `/ctx start my-stream --pull`, `/ctx resume my-stream`, `/ctx delete my-stream`, `/ctx branch source-stream target-stream`
  - Shortcut: `/branch source-stream target-stream`
- Codex:
  - Restart Codex, then use `ctx`, `ctx list`, `ctx start my-stream --pull`, `ctx resume my-stream`, `ctx delete my-stream`, `ctx branch source-stream target-stream`
  - Compatibility aliases: `ctx-list`, `ctx-start`, `ctx-resume`, `ctx-delete`, `ctx-branch`
  - Codex does not currently support custom repo-defined slash commands like `/ctx-list`.
- Optional automation helpers for paste/status workflows:
  - `python3 scripts/skills/ctx_resume_skill.py --name "my-stream" --paste`
  - `python3 scripts/skills/ctx_start_skill.py --name "my-stream" --agent codex --pull --paste`

Tip: For a global setup across projects, rerun this script with --global and use 'ctx'.
NEXT
fi

echo "\nQuickstart complete."
