#!/usr/bin/env bash
set -euo pipefail

# Install SKILL.md bundles into Codex/Claude skill directories by symlinking.
# Usage:
#   scripts/install_skills.sh --codex-dir ~/.codex/skills --claude-dir ~/.claude/skills

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd -P)
# Defaults based on common locations; override via flags or env vars
CODEX_DIR="${CODEX_SKILLS_DIR:-}"
CLAUDE_DIR="${CLAUDE_SKILLS_DIR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex-dir) CODEX_DIR="$2"; shift 2;;
    --claude-dir) CLAUDE_DIR="$2"; shift 2;;
    -h|--help)
      echo "Usage: $0 --codex-dir <path> --claude-dir <path>"; exit 0;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

echo "==> Installing skills from $ROOT_DIR/skills"

if [[ -z "$CODEX_DIR" ]]; then
  CODEX_DIR="$HOME/.codex/skills"
fi
if [[ -n "$CODEX_DIR" ]]; then
  echo "[Codex] Target: $CODEX_DIR"
  mkdir -p "$CODEX_DIR"
  for d in "$ROOT_DIR/skills/codex"/*; do
    [[ -f "$d/SKILL.md" ]] || continue
    name=$(basename "$d")
    src="$d"
    dst="$CODEX_DIR/$name"
    rm -rf "$dst" 2>/dev/null || true
    ln -s "$src" "$dst"
    echo "  - Linked $name"
  done
fi

if [[ -z "$CLAUDE_DIR" ]]; then
  CLAUDE_DIR="$HOME/.claude/skills"
fi
if [[ -n "$CLAUDE_DIR" ]]; then
  echo "[Claude] Target: $CLAUDE_DIR"
  mkdir -p "$CLAUDE_DIR"
  for d in "$ROOT_DIR/skills/claude"/*; do
    [[ -f "$d/SKILL.md" ]] || continue
    name=$(basename "$d")
    src="$d"
    dst="$CLAUDE_DIR/$name"
    rm -rf "$dst" 2>/dev/null || true
    ln -s "$src" "$dst"
    echo "  - Linked $name"
  done
fi

cat <<EOF

Done.
- Restart your app/CLI to pick up new skills if required.
- Inside each skill folder, SKILL.md describes usage (calls scripts/skills/* under this repo).
EOF
