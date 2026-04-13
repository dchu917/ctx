#!/usr/bin/env bash
set -euo pipefail

# Project-local agent setup: downloads ContextFun into ./ctx and wires env vars.
# Usage in Claude Code / Codex terminal:
#   source <(curl -fsSL https://raw.githubusercontent.com/dchu917/ctx/main/scripts/agent_setup_local_ctx.sh)

REPO_URL="https://github.com/dchu917/ctx"
ARCHIVE_URL="$REPO_URL/archive/refs/heads/main.tar.gz"

PREFIX="$PWD/ctx"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib"
DB_PATH="$PREFIX/context.db"

mkdir -p "$BIN_DIR" "$LIB_DIR"

if [[ ! -d "$LIB_DIR/contextfun" ]]; then
  TMPDIR=$(mktemp -d)
  trap 'rm -rf "$TMPDIR"' EXIT
  echo "Downloading ContextFun into ./ctx ..."
  curl -fsSL "$ARCHIVE_URL" | tar xz -C "$TMPDIR"
  SRC_DIR=$(find "$TMPDIR" -maxdepth 1 -type d -name 'contextfun-*' | head -n1)
  cp -R "$SRC_DIR/contextfun" "$LIB_DIR/"
  install -m 0755 "$SRC_DIR/scripts/ctx_cmd.py" "$BIN_DIR/ctx"
fi

# Initialize DB if missing
if [[ ! -f "$DB_PATH" ]]; then
  PYTHONPATH="$LIB_DIR" python3 -m contextfun --db "$DB_PATH" init >/dev/null || true
fi

# Export env vars for the current shell
export CONTEXTFUN_DB="$DB_PATH"
export PATH="$BIN_DIR:$PATH"

echo "ContextFun ready in ./ctx (DB: $DB_PATH). Commands available: ctx, python3 -m contextfun"
