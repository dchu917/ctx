#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
SEARCH="$HERE"
REPO=""
for _ in 1 2 3 4 5 6 7 8; do
  CAND="$(cd "$SEARCH/.." && pwd -P)"
  if [[ -f "$CAND/scripts/skills/ctx_resume_skill.py" ]]; then
    REPO="$CAND"
    break
  fi
  SEARCH="$CAND"
done

if [[ -z "$REPO" ]]; then
  echo "ContextFun repo not found. Clone the repo and reinstall skills." >&2
  exit 2
fi

NAME="${*:-}"

exec python3 "$REPO/scripts/skills/ctx_resume_skill.py" \
  ${NAME:+--name "$NAME"} \
  --format markdown
