#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
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

if command -v ctx-list >/dev/null 2>&1; then
  exec ctx-list
elif command -v ctx >/dev/null 2>&1; then
  exec ctx list
elif [[ -n "$REPO" ]]; then
  exec python3 "$REPO/scripts/ctx_cmd.py" list
else
  echo "ContextFun not found: install globally (ctx) or clone repo with scripts/ctx_cmd.py" >&2
  exit 2
fi
