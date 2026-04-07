# cc-handoff

Continue Claude Code work in [OpenCode](https://github.com/sst/opencode) — list sessions, pick one, auto-convert and import.

## Problem

Claude Code (Max subscription) runs out of quota mid-task. Context is lost. Work stops.

## Solution

An OpenCode skill that:
1. Lists all your Claude Code sessions
2. Lets you pick one to import
3. Converts the JSONL transcript to OpenCode format
4. Imports it — you continue exactly where you left off

Also includes a StopFailure hook that does this automatically on rate limit.

## Install

```bash
git clone https://github.com/mcdowell8023/cc-handoff.git
cd cc-handoff
./install.sh
```

Or manually copy to `~/.config/opencode/skills/cc-handoff/`.

## Usage

### In OpenCode (as a skill)

Say any of these to trigger the skill:
- "continue from Claude Code"
- "import Claude Code session"
- "handoff"
- "pick up where Claude Code left off"

The agent will list sessions, let you choose, and import.

### CLI

```bash
# List recent sessions
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list

# Filter by project
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list --project my-app

# Show session details (files modified, todos, messages)
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py info <session-id>

# Import by row number, session ID, or "latest"
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import 1
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import latest
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import a1302f9c

# List auto-generated handoff files
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list-handoffs
```

## Auto-Handoff (Rate Limit Hook)

Add a StopFailure hook to `~/.claude/settings.json` so Claude Code automatically hands off on rate limit:

```json
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
```

Copy the hook script:
```bash
cp examples/rate-limit-handoff.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/rate-limit-handoff.sh
```

When Claude Code hits a rate limit, it will:
1. Save the transcript
2. Generate a handoff summary
3. Convert and import into OpenCode
4. Send a macOS notification

## Requirements

- Python 3.8+
- [OpenCode](https://github.com/sst/opencode) installed and in PATH
- Claude Code sessions in `~/.claude/projects/`

## How It Works

Claude Code stores transcripts as JSONL files in `~/.claude/projects/`. This tool:

1. Scans all project directories for `.jsonl` session files
2. Extracts metadata: first user message (as title), message count, project path
3. Converts Claude Code's format (tool calls embedded in assistant message blocks) to OpenCode's import format (messages with step-start/text/tool/step-finish parts)
4. Runs `opencode import` to load the session

## License

MIT
