#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
SHIM_DIR="${HOME}/.contextfun/bin"
SEARCH="$HERE"
REPO=""
for _ in 1 2 3 4 5 6 7 8; do
  CAND="$(cd "$SEARCH/.." && pwd -P)"
  if [[ -f "$CAND/scripts/ctx_cmd.py" ]]; then
    REPO="$CAND"
    break
  fi
  SEARCH="$CAND"
done

if [[ -x "$SHIM_DIR/ctx-branch" ]]; then
  exec "$SHIM_DIR/ctx-branch" "$@"
elif command -v ctx-branch >/dev/null 2>&1; then
  exec ctx-branch "$@"
elif command -v ctx >/dev/null 2>&1; then
  exec ctx branch "$@" --format markdown
elif [[ -n "$REPO" ]]; then
  exec python3 "$REPO/scripts/ctx_cmd.py" branch "$@" --format markdown
fi

echo "ContextFun not found: install ~/.contextfun/bin shims, install global ctx, or clone the repo." >&2
exit 2
