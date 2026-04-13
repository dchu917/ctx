#!/usr/bin/env bash
set -euo pipefail

PREFIX="${HOME}/.contextfun"
BIN_DIR="$PREFIX/bin"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"

mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/ctx" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="__ROOT_DIR__"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" "$@"
SH

cat > "$BIN_DIR/ctx-list" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx list
fi
ROOT_DIR="__ROOT_DIR__"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" list
SH

cat > "$BIN_DIR/ctx-search" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx search "$@"
fi
ROOT_DIR="__ROOT_DIR__"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" search "$@"
SH

cat > "$BIN_DIR/ctx-resume" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx resume "$@"
fi
ROOT_DIR="__ROOT_DIR__"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" resume "$@" --format markdown
SH

cat > "$BIN_DIR/ctx-start" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx start "$@"
fi
ROOT_DIR="__ROOT_DIR__"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" start "$@" --format markdown
SH

cat > "$BIN_DIR/ctx-delete" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx delete "$@"
fi
ROOT_DIR="__ROOT_DIR__"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" delete "$@"
SH

cat > "$BIN_DIR/ctx-branch" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx branch "$@"
fi
ROOT_DIR="__ROOT_DIR__"
exec python3 "$ROOT_DIR/scripts/ctx_cmd.py" branch "$@" --format markdown
SH

for shim in "$BIN_DIR/ctx" "$BIN_DIR/ctx-list" "$BIN_DIR/ctx-search" "$BIN_DIR/ctx-resume" "$BIN_DIR/ctx-start" "$BIN_DIR/ctx-delete" "$BIN_DIR/ctx-branch"; do
  perl -0pi -e 's|__ROOT_DIR__|'"$ROOT_DIR"'|g' "$shim"
done

chmod +x "$BIN_DIR/ctx" "$BIN_DIR/ctx-list" "$BIN_DIR/ctx-search" "$BIN_DIR/ctx-resume" "$BIN_DIR/ctx-start" "$BIN_DIR/ctx-delete" "$BIN_DIR/ctx-branch"

case ":${PATH}:" in
  *":${BIN_DIR}:"*) :;;
  *) echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$HOME/.zshrc";;
esac

echo "Installed repo-backed shims to $BIN_DIR: ctx, ctx-list, ctx-search, ctx-resume, ctx-start, ctx-delete, ctx-branch"
echo "These call the cloned repo at $ROOT_DIR when a global 'ctx' is not installed."
echo "If not already present, PATH was updated in ~/.zshrc. Open a new shell to pick up changes."
