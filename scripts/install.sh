#!/usr/bin/env bash
set -euo pipefail

# ContextFun one-line installer
# Installs to ~/.contextfun and sets PATH + CONTEXTFUN_DB

REPO_URL="https://github.com/dchu917/contextfun"
ARCHIVE_URL="$REPO_URL/archive/refs/heads/main.tar.gz"

PREFIX="${HOME}/.contextfun"
BIN_DIR="$PREFIX/bin"
LIB_DIR="$PREFIX/lib"
DB_PATH="$PREFIX/context.db"

echo "Installing ContextFun to $PREFIX"
mkdir -p "$BIN_DIR" "$LIB_DIR"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "Downloading latest from $REPO_URL ..."
curl -fsSL "$ARCHIVE_URL" | tar xz -C "$TMPDIR"
SRC_DIR=$(find "$TMPDIR" -maxdepth 1 -type d -name 'contextfun-*' | head -n1)

if [[ ! -d "$SRC_DIR/contextfun" ]]; then
  echo "Error: could not find package in archive." >&2
  exit 1
fi

echo "Copying files ..."
rsync -a "$SRC_DIR/contextfun/" "$LIB_DIR/contextfun/"
install -m 0755 "$SRC_DIR/scripts/ctx_cmd.py" "$BIN_DIR/ctx"

# Also install convenience shims so Codex/Claude can call dashed commands directly
cat > "$BIN_DIR/ctx-list" <<EOF_SH
#!/usr/bin/env bash
exec "$BIN_DIR/ctx" list
EOF_SH
cat > "$BIN_DIR/ctx-resume" <<EOF_SH
#!/usr/bin/env bash
exec "$BIN_DIR/ctx" go "$@"
EOF_SH
cat > "$BIN_DIR/ctx-start" <<EOF_SH
#!/usr/bin/env bash
exec "$BIN_DIR/ctx" start "$@"
EOF_SH
cat > "$BIN_DIR/ctx-delete" <<EOF_SH
#!/usr/bin/env bash
exec "$BIN_DIR/ctx" delete "$@"
EOF_SH
chmod +x "$BIN_DIR/ctx-list" "$BIN_DIR/ctx-resume" "$BIN_DIR/ctx-start" "$BIN_DIR/ctx-delete"

SHELL_RC=""
if [[ -n "${ZSH_VERSION:-}" ]]; then SHELL_RC="$HOME/.zshrc"; fi
if [[ -n "${BASH_VERSION:-}" ]]; then SHELL_RC="$HOME/.bashrc"; fi
if [[ -z "$SHELL_RC" ]]; then SHELL_RC="$HOME/.profile"; fi

echo "Writing environment to $SHELL_RC"
grep -q 'CONTEXTFUN_DB' "$SHELL_RC" 2>/dev/null || echo "export CONTEXTFUN_DB=\"$DB_PATH\"" >> "$SHELL_RC"
grep -q "$BIN_DIR" "$SHELL_RC" 2>/dev/null || echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$SHELL_RC"

echo "Initializing database at $DB_PATH"
PYTHONPATH="$LIB_DIR" python3 -m contextfun --db "$DB_PATH" init >/dev/null || true

cat <<EOF

ContextFun installed.

Open a new shell or run:
  export CONTEXTFUN_DB="$DB_PATH"
  export PATH="$BIN_DIR:\$PATH"

Try:
  ctx list
  ctx-list
  ctx-start my-workstream
  ctx-start --pull my-workstream
  ctx-resume my-workstream
  ctx-delete my-workstream
  python3 -m contextfun --help

For Claude/Codex terminals, use the agent bootstrap one-liner from README.
EOF
