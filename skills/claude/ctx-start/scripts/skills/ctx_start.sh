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

NAME="${NAME_TOKENS[*]:-}"

exec python3 "$REPO/scripts/skills/ctx_start_skill.py" \
  ${NAME:+--name "$NAME"} \
  --agent claude \
  --format markdown \
  --source claude \
  "${FLAGS[@]}"
