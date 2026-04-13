#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
SHIM_DIR="${HOME}/.contextfun/bin"
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

NAME="${*:-${CTX_AGENT_WORKSTREAM:-}}"
CMD=(--format markdown --source codex)
if [[ -n "$NAME" ]]; then
  CMD+=("$NAME")
fi

if [[ -x "$SHIM_DIR/ctx-resume" ]]; then
  exec "$SHIM_DIR/ctx-resume" "${CMD[@]}"
elif command -v ctx-resume >/dev/null 2>&1; then
  exec ctx-resume "${CMD[@]}"
elif command -v ctx >/dev/null 2>&1; then
  exec ctx resume "${CMD[@]}"
elif [[ -n "$REPO" ]]; then
  exec python3 "$REPO/scripts/ctx_cmd.py" resume "${CMD[@]}"
fi

echo "ContextFun not found: install ~/.contextfun/bin shims, install global ctx, or clone the repo." >&2
exit 2
