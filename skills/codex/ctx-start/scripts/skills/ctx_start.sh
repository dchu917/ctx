#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
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

if [[ -z "$REPO" ]]; then
  echo "ContextFun repo not found. Clone the repo and reinstall skills." >&2
  exit 2
fi

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
CMD=(--format markdown --source codex)
if [[ ${#FLAGS[@]} -gt 0 ]]; then
  CMD=("${FLAGS[@]}" "${CMD[@]}")
fi
if [[ -n "$NAME" ]]; then
  CMD+=("$NAME")
fi

if command -v ctx-start >/dev/null 2>&1; then
  exec ctx-start "${CMD[@]}"
elif command -v ctx >/dev/null 2>&1; then
  exec ctx start "${CMD[@]}"
else
  exec python3 "$REPO/scripts/ctx_cmd.py" start "${CMD[@]}"
fi
