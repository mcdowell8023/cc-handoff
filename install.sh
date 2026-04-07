#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="${HOME}/.config/opencode/skills/cc-handoff"
HOOK_DIR="${HOME}/.claude/hooks"
SETTINGS="${HOME}/.claude/settings.json"

echo "=== cc-handoff installer ==="
echo ""

# 1. Install OpenCode skill
if [[ -d "$SKILL_DIR" ]]; then
  echo "[skill] Updating $SKILL_DIR"
else
  echo "[skill] Installing to $SKILL_DIR"
fi

mkdir -p "$SKILL_DIR/scripts"
cp "$SCRIPT_DIR/SKILL.md" "$SKILL_DIR/SKILL.md"
cp "$SCRIPT_DIR/scripts/cc-handoff.py" "$SKILL_DIR/scripts/cc-handoff.py"
chmod +x "$SKILL_DIR/scripts/cc-handoff.py"
echo "[skill] ✅ Done"

# 2. Install Auto-Handoff hook (optional)
echo ""
read -r -p "Install Auto-Handoff hook? (auto-import on rate limit) [Y/n] " REPLY
REPLY="${REPLY:-Y}"

if [[ "$REPLY" =~ ^[Yy]$ ]]; then
  mkdir -p "$HOOK_DIR"
  cp "$SCRIPT_DIR/examples/rate-limit-handoff.sh" "$HOOK_DIR/rate-limit-handoff.sh"
  chmod +x "$HOOK_DIR/rate-limit-handoff.sh"
  echo "[hook] ✅ Installed to $HOOK_DIR/rate-limit-handoff.sh"

  # 3. Configure StopFailure hook in settings.json
  if [[ -f "$SETTINGS" ]]; then
    if grep -q "rate-limit-handoff" "$SETTINGS" 2>/dev/null; then
      echo "[config] StopFailure hook already configured in $SETTINGS"
    else
      echo "[config] ⚠️  Add this to $SETTINGS manually (merging JSON automatically is risky):"
      echo ""
      cat << 'HOOKJSON'
{
  "hooks": {
    "StopFailure": [
      {
        "matcher": "rate_limit",
        "hooks": [
          {
            "type": "command",
            "command": "bash $HOME/.claude/hooks/rate-limit-handoff.sh",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
HOOKJSON
      echo ""
      echo "[config] Or run: claude config set hooks.StopFailure ..."
    fi
  else
    echo "[config] $SETTINGS not found. Create it with the hook config above after installing Claude Code."
  fi
else
  echo "[hook] Skipped. You can install later by copying examples/rate-limit-handoff.sh to ~/.claude/hooks/"
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "Usage in OpenCode:"
echo '  Say "continue from Claude Code" or "import Claude Code session"'
echo ""
echo "CLI:"
echo "  python3 $SKILL_DIR/scripts/cc-handoff.py list"
echo "  python3 $SKILL_DIR/scripts/cc-handoff.py import latest"
