#!/bin/bash
set -euo pipefail

SKILL_DIR="${HOME}/.config/opencode/skills/cc-handoff"

if [[ -d "$SKILL_DIR" ]]; then
  echo "Updating existing installation at $SKILL_DIR"
else
  echo "Installing cc-handoff skill to $SKILL_DIR"
fi

mkdir -p "$SKILL_DIR/scripts"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/SKILL.md" "$SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/scripts/cc-handoff.py" "$SKILL_DIR/scripts/cc-handoff.py"
chmod +x "$SKILL_DIR/scripts/cc-handoff.py"

echo ""
echo "✅ Installed to $SKILL_DIR"
echo ""
echo "Usage in OpenCode:"
echo '  Say "continue from Claude Code" or "import Claude Code session"'
echo ""
echo "CLI usage:"
echo "  python3 $SKILL_DIR/scripts/cc-handoff.py list"
echo "  python3 $SKILL_DIR/scripts/cc-handoff.py import latest"
