#!/usr/bin/env bash
set -euo pipefail

PREFIX="${HOME}/.contextfun"
BIN_DIR="$PREFIX/bin"

mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/ctx-list" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx list
fi
if [[ -f "./scripts/ctx_cmd.py" ]]; then
  exec python3 ./scripts/ctx_cmd.py list
fi
echo "ctx not found. Ensure ContextFun is installed or run from repo root." >&2
exit 127
SH

cat > "$BIN_DIR/ctx-resume" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if command -v ctx >/dev/null 2>&1; then
  exec ctx go "$@"
fi
if [[ -f "./scripts/ctx_cmd.py" ]]; then
  exec python3 ./scripts/ctx_cmd.py go "$@"
fi
echo "ctx not found. Ensure ContextFun is installed or run from repo root." >&2
exit 127
SH

cat > "$BIN_DIR/ctx-start" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
# Pass through to start skill if available; otherwise fall back to ctx go
ROOT_REPO=""
HERE="$(pwd -P)"
SEARCH="$HERE"
for _ in 1 2 3 4 5 6 7 8; do
  CAND="$(cd "$SEARCH" && pwd -P)"
  if [[ -f "$CAND/scripts/skills/ctx_start_skill.py" ]]; then
    ROOT_REPO="$CAND"; break
  fi
  SEARCH="$CAND/.."
done
if [[ -n "$ROOT_REPO" ]]; then
  exec python3 "$ROOT_REPO/scripts/skills/ctx_start_skill.py" "$@"
fi
if command -v ctx >/dev/null 2>&1; then
  # Fallback: resume/go behavior
  exec ctx go "$@"
fi
echo "ContextFun not found. Install or run from repo root." >&2
exit 127
SH

chmod +x "$BIN_DIR/ctx-list" "$BIN_DIR/ctx-resume" "$BIN_DIR/ctx-start"

case ":${PATH}:" in
  *":${BIN_DIR}:"*) :;;
  *) echo "export PATH=\"$BIN_DIR:\$PATH\"" >> "$HOME/.zshrc";;
esac

echo "Installed shims to $BIN_DIR: ctx-list, ctx-resume, ctx-start"
echo "If not already present, PATH was updated in ~/.zshrc. Open a new shell to pick up changes."

