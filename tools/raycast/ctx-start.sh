#!/usr/bin/env bash
#
# Raycast Script Command
#
# @raycast.schemaVersion 1
# @raycast.title ctx start
# @raycast.mode silent
# @raycast.packageName ContextFun
# @raycast.author ContextFun
# @raycast.authorURL https://github.com/dchu917/ctx
# @raycast.argument1 {"type": "text", "placeholder": "workstream (optional)", "optional": true}
# @raycast.description Start a ContextFun session, auto-pull transcripts, copy pack, and paste status into the frontmost app.

set -euo pipefail

ROOT_DIR="$HOME/path/to/context-fun"  # CHANGE: absolute path to this repo
SCRIPT="$ROOT_DIR/scripts/skills/ctx_start_skill.py"

NAME="${1:-}"

if [[ -n "$NAME" ]]; then
  python3 "$SCRIPT" --name "$NAME" | pbcopy
else
  python3 "$SCRIPT" | pbcopy
fi

# Paste into frontmost app (macOS)
osascript -e 'tell application "System Events" to keystroke "v" using {command down}'

echo "ContextFun: start triggered${NAME:+ for '$NAME'} (status pasted)."
