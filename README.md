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

The agent will:
1. Run `list --json` to get structured session data
2. Present an interactive selection dialog (via `question` tool)
3. Import your chosen session with full context
4. Summarize progress (completed/in-progress/pending tasks) and ask how to continue

### CLI

```bash
# List recent sessions (human-readable table with ID column)
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list

# List as structured JSON (for agent consumption)
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list --json

# Filter by project name
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list --project my-app

# Show session details (files modified, todos, messages)
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py info <session-id>
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py info 1        # by row number
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py info latest    # most recent

# Import by session ID, row number, or "latest"
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import a1302f9c
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import 1
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import latest

# List auto-generated handoff files
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list-handoffs
```

### Title Management

Claude Code stores session titles in the cloud (not locally). cc-handoff provides a local title cache with LLM-powered generation:

```bash
# Generate titles for sessions that don't have one yet
# Outputs JSON — agent uses LLM to produce 3-7 word titles
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py generate-titles

# Manually set a title for a session
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py set-title <session-id> My Feature Work
```

Cached titles are stored in `~/.config/opencode/skills/cc-handoff/title-cache.json` and displayed by `list` automatically.

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
2. Extracts metadata: message count, project path, date, session ID
3. Resolves session titles: cached LLM title → `[git_branch]` prefix + tail scan → first user message truncation
4. Converts Claude Code's format (tool calls embedded in assistant message blocks) to OpenCode's import format (messages with step-start/text/tool/step-finish parts)
5. Runs `opencode import` to load the session
6. Returns the OpenCode session ID for immediate continuation

## License

MIT
