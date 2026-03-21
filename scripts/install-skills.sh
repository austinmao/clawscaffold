#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$(dirname "$SCRIPT_DIR")/skills"
TARGET="${1:-}"

case "$TARGET" in
  claude-code|cc)
    DEST="${HOME}/.claude/skills"
    ;;
  openclaw|oc)
    DEST="skills/platform/compiler"
    ;;
  *)
    echo "Usage: install-skills.sh <claude-code|openclaw>"
    echo "  claude-code  Copy to ~/.claude/skills/"
    echo "  openclaw     Copy to ./skills/platform/compiler/"
    exit 1
    ;;
esac

mkdir -p "$DEST"
for skill_dir in "$SKILLS_DIR"/*/; do
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$DEST/$skill_name"
  cp "$skill_dir/SKILL.md" "$DEST/$skill_name/SKILL.md"
  echo "Installed $skill_name → $DEST/$skill_name/"
done
echo "Done. ${#} skills installed to $DEST"
