#!/bin/bash
# rate-limit-handoff.sh — Claude Code StopFailure hook
# Input: JSON on stdin (session_id, transcript_path, error_type, etc.)
# Output: ~/.claude/handoffs/ (handoff.md + transcript copy)
set -euo pipefail

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // "."')
ERROR_TYPE=$(echo "$INPUT" | jq -r '.error_type // "unknown"')
ERROR_MSG=$(echo "$INPUT" | jq -r '.error_message // ""')

HANDOFF_DIR="$HOME/.claude/handoffs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
HANDOFF_ID="${TIMESTAMP}_${SESSION_ID:0:12}"
mkdir -p "$HANDOFF_DIR"

TRANSCRIPT_COPY=""
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  TRANSCRIPT_COPY="${HANDOFF_DIR}/${HANDOFF_ID}_transcript.jsonl"
  cp "$TRANSCRIPT_PATH" "$TRANSCRIPT_COPY"
fi

python3 - "$TRANSCRIPT_COPY" "$HANDOFF_DIR" "$HANDOFF_ID" "$SESSION_ID" "$CWD" "$ERROR_TYPE" "$ERROR_MSG" << 'PYEOF'
import sys, json, re, os

transcript_path = sys.argv[1]
handoff_dir = sys.argv[2]
handoff_id = sys.argv[3]
session_id = sys.argv[4]
cwd = sys.argv[5]
error_type = sys.argv[6]
error_msg = sys.argv[7]

todos = []
files_read = set()
files_written = set()
user_messages = []
assistant_texts = []
tool_actions = []

if transcript_path and os.path.isfile(transcript_path):
    with open(transcript_path, 'r') as f:
        for line in f:
            try:
                obj = json.loads(line.strip())
                t = obj.get('type', '')

                if t == 'user':
                    # Real format: obj.message.content is the user text (string or list)
                    msg = obj.get('message', {})
                    content = ''
                    if isinstance(msg, dict):
                        mc = msg.get('content', '')
                        if isinstance(mc, str) and mc.strip():
                            content = mc
                        elif isinstance(mc, list):
                            parts = [b.get('text', '') for b in mc if isinstance(b, dict) and b.get('type') == 'text']
                            content = ' '.join(parts)
                    if not content:
                        content = str(obj.get('content', ''))
                    user_messages.append(re.sub(r'[\x00-\x1f]', ' ', content[:800]))

                elif t == 'assistant':
                    # Real format: obj.message.content is a list of blocks
                    msg = obj.get('message', {})
                    blocks = []
                    if isinstance(msg, dict):
                        mc = msg.get('content', [])
                        if isinstance(mc, list):
                            blocks = [b for b in mc if isinstance(b, dict)]
                    if not blocks:
                        c = obj.get('content', '')
                        if isinstance(c, list):
                            blocks = [b for b in c if isinstance(b, dict)]
                        elif isinstance(c, str) and c.strip():
                            blocks = [{'type': 'text', 'text': c}]

                    texts = [b.get('text', '') for b in blocks if b.get('type') == 'text']
                    text = re.sub(r'[\x00-\x1f]', ' ', ' '.join(texts)[:1500])
                    if text.strip():
                        assistant_texts.append(text)

                    # Tool uses are inside assistant blocks (not separate entries)
                    for block in blocks:
                        if block.get('type') != 'tool_use':
                            continue
                        tool = block.get('name', '')
                        inp = block.get('input', {})

                        if tool.lower() == 'todowrite' and 'todos' in inp:
                            todos = inp['todos']

                        tl = tool.lower()
                        if tl in ('edit', 'write'):
                            p = inp.get('filePath', '')
                            if p: files_written.add(p)
                        elif tl == 'read':
                            p = inp.get('filePath', '')
                            if p: files_read.add(p)

                        summary = f"{tool}"
                        if tl == 'bash':
                            cmd = inp.get('command', '')[:120]
                            summary = f"bash: {cmd}"
                        elif tl in ('edit', 'write', 'read'):
                            summary = f"{tool}: {inp.get('filePath','')}"
                        elif tl == 'grep':
                            summary = f"grep: {inp.get('pattern','')} in {inp.get('path','')}"
                        tool_actions.append(summary)
            except:
                pass

# Build handoff — optimized for AI agent consumption
out = []
out.append("# Claude Code Handoff\n")
out.append(f"- session: {session_id}")
out.append(f"- dir: {cwd}")
out.append(f"- error: {error_type} — {error_msg}")
out.append(f"- transcript: {transcript_path}\n")

# Todo state (most actionable section)
out.append("## Task State\n")
if todos:
    for t in todos:
        s = t.get('status', '?')
        c = t.get('content', '')
        icon = {'completed': 'DONE', 'in_progress': 'WIP', 'pending': 'TODO'}.get(s, '?')
        out.append(f"- [{icon}] {c}")
else:
    out.append("(no todos)")

# Files touched
out.append("\n## Files Modified\n")
for f in sorted(files_written):
    out.append(f"- {f}")
if not files_written:
    out.append("(none)")

out.append("\n## Files Read\n")
for f in sorted(files_read - files_written):
    out.append(f"- {f}")
if not (files_read - files_written):
    out.append("(none)")

# Conversation summary — last 5 user messages + last 3 assistant responses
out.append("\n## Recent User Messages (last 5)\n")
for msg in user_messages[-5:]:
    out.append(f"> {msg[:400]}\n")

out.append("## Recent Assistant Output (last 3)\n")
for txt in assistant_texts[-3:]:
    out.append(f"{txt[:800]}\n---\n")

# Recent tool actions (last 15)
out.append("## Recent Tool Actions (last 15)\n")
for action in tool_actions[-15:]:
    out.append(f"- {action}")

# Resume instructions
out.append(f"""
## Resume

Claude Code (after quota resets):
  claude --resume {session_id}

OpenCode (immediate, reads this file):
  Read this file: {handoff_dir}/{handoff_id}_handoff.md
  Or symlink: {handoff_dir}/latest_handoff.md

Full transcript for deep context:
  {transcript_path}
""")

handoff_file = f"{handoff_dir}/{handoff_id}_handoff.md"
with open(handoff_file, 'w') as f:
    f.write('\n'.join(out))

# Symlink
latest = f"{handoff_dir}/latest_handoff.md"
if os.path.islink(latest) or os.path.exists(latest):
    os.remove(latest)
os.symlink(handoff_file, latest)

print(handoff_file)
PYEOF

HANDOFF_FILE="${HANDOFF_DIR}/${HANDOFF_ID}_handoff.md"

# Use cc-handoff.py (the canonical converter) instead of cc2oc-converter.py
CC_HANDOFF="$HOME/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py"
CONVERTER="$(dirname "$0")/cc2oc-converter.py"
OC_IMPORT_OK=""
if [[ -n "$TRANSCRIPT_COPY" && -f "$TRANSCRIPT_COPY" ]]; then
  if [[ -f "$CC_HANDOFF" ]]; then
    python3 "$CC_HANDOFF" import "$SESSION_ID" 2>/dev/null && OC_IMPORT_OK="yes"
  elif [[ -f "$CONVERTER" ]]; then
    OC_IMPORT_FILE="${HANDOFF_DIR}/${HANDOFF_ID}_opencode.json"
    if python3 "$CONVERTER" "$TRANSCRIPT_COPY" "$OC_IMPORT_FILE" 2>/dev/null; then
      if command -v opencode &>/dev/null || [[ -x "$HOME/.opencode/bin/opencode" ]]; then
        OC_BIN="${HOME}/.opencode/bin/opencode"
        command -v opencode &>/dev/null && OC_BIN="opencode"
        "$OC_BIN" import "$OC_IMPORT_FILE" 2>/dev/null && OC_IMPORT_OK="yes"
      fi
    fi
  fi
fi

NOTIF_SUBTITLE="见 ~/.claude/handoffs/latest_handoff.md"
[[ -n "$OC_IMPORT_OK" ]] && NOTIF_SUBTITLE="已导入 OpenCode，可直接继续"

if command -v osascript &>/dev/null; then
  osascript -e "display notification \"Claude Code 额度耗尽，handoff 已生成\" with title \"⚠️ Rate Limit\" subtitle \"${NOTIF_SUBTITLE}\"" 2>/dev/null || true
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | ${ERROR_TYPE} | session=${SESSION_ID} | handoff=${HANDOFF_FILE} | oc_import=${OC_IMPORT_OK:-no}" >> "${HANDOFF_DIR}/handoff.log"

exit 0
