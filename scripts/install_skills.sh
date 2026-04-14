#!/usr/bin/env bash
set -euo pipefail

# Install SKILL.md bundles into Codex/Claude skill directories by symlinking.
# Usage:
#   scripts/install_skills.sh --codex-dir ~/.codex/skills --claude-dir ~/.claude/skills
#   scripts/install_skills.sh --skills-root ~/.contextfun/skills

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd -P)
# Defaults based on common locations; override via flags or env vars
CODEX_DIR="${CODEX_SKILLS_DIR:-}"
CLAUDE_DIR="${CLAUDE_SKILLS_DIR:-}"
SKILLS_ROOT="${CTX_SKILLS_ROOT:-$ROOT_DIR/skills}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex-dir) CODEX_DIR="$2"; shift 2;;
    --claude-dir) CLAUDE_DIR="$2"; shift 2;;
    --skills-root) SKILLS_ROOT="$2"; shift 2;;
    -h|--help)
      echo "Usage: $0 [--skills-root <path>] [--codex-dir <path>] [--claude-dir <path>]"; exit 0;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ ! -d "$SKILLS_ROOT" ]]; then
  echo "Skills root not found: $SKILLS_ROOT" >&2
  exit 1
fi

echo "==> Installing skills from $SKILLS_ROOT"

if [[ -z "$CODEX_DIR" ]]; then
  CODEX_DIR="$HOME/.codex/skills"
fi
if [[ -n "$CODEX_DIR" ]]; then
  echo "[Codex] Target: $CODEX_DIR"
  mkdir -p "$CODEX_DIR"
  for d in "$SKILLS_ROOT/codex"/*; do
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
  for d in "$SKILLS_ROOT/claude"/*; do
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
- Installed skills are linked from: $SKILLS_ROOT
EOF
