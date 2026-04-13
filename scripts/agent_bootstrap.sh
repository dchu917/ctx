#!/usr/bin/env bash
# ContextFun agent bootstrap (Claude Code / Codex terminals)
# Usage:
#   source <(curl -fsSL https://raw.githubusercontent.com/dchu917/ctx/main/scripts/agent_bootstrap.sh)

set -euo pipefail

PREFIX="$HOME/.contextfun"
BIN_DIR="$PREFIX/bin"
DB_PATH="$PREFIX/context.db"

export CONTEXTFUN_DB="$DB_PATH"
export PATH="$BIN_DIR:$PATH"

echo "ContextFun agent bootstrap complete. Using DB: $CONTEXTFUN_DB"
command -v ctx >/dev/null 2>&1 && echo "ctx available" || echo "ctx not found; run local installer first."
