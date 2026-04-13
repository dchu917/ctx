#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
SHIM_DIR="${HOME}/.contextfun/bin"
SEARCH="$HERE"
REPO=""
for _ in 1 2 3 4 5 6 7 8; do
  CAND="$(cd "$SEARCH/.." && pwd -P)"
  if [[ -f "$CAND/scripts/skills/ctx_start_skill.py" ]]; then
    REPO="$CAND"
    break
  fi
  SEARCH="$CAND"
done

# Parse args: everything before first -- is the name; rest are flags
NAME_TOKENS=()
FLAGS=()
for a in "$@"; do
  if [[ "$a" == --* ]]; then
    FLAGS+=("$a")
  else
    NAME_TOKENS+=("$a")
  fi
done

NAME="${NAME_TOKENS[*]:-${CTX_AGENT_WORKSTREAM:-}}"
CMD=(--format markdown --source claude)
if [[ ${#FLAGS[@]} -gt 0 ]]; then
  CMD=("${FLAGS[@]}" "${CMD[@]}")
fi
if [[ -n "$NAME" ]]; then
  CMD+=("$NAME")
fi

if [[ -x "$SHIM_DIR/ctx-start" ]]; then
  exec "$SHIM_DIR/ctx-start" "${CMD[@]}"
elif command -v ctx-start >/dev/null 2>&1; then
  exec ctx-start "${CMD[@]}"
elif command -v ctx >/dev/null 2>&1; then
  exec ctx start "${CMD[@]}"
elif [[ -n "$REPO" ]]; then
  exec python3 "$REPO/scripts/ctx_cmd.py" start "${CMD[@]}"
fi

echo "ContextFun not found: install ~/.contextfun/bin shims, install global ctx, or clone the repo." >&2
exit 2
