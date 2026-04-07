---
name: cc-handoff
description: Use when continuing work from Claude Code, importing Claude Code sessions, or recovering from Claude Code rate limits. Triggers on "continue from Claude Code", "import Claude Code session", "rate limit", "pick up where Claude Code left off", "handoff", "resume Claude Code work".
---

# Claude Code → OpenCode Handoff

Continue Claude Code work inside OpenCode. Lists sessions, converts transcripts, imports them — you pick up exactly where you left off.

## When to Use

- Claude Code hit rate limit, you want to continue here
- You want to review/import a specific Claude Code session
- You see a macOS notification saying "已导入 OpenCode"

## Workflow

When user asks to continue from Claude Code or import a session:

### Step 1: List Available Sessions

Run the CLI tool to show recent Claude Code sessions:

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list
```

This shows a table of recent sessions with: session ID, project, date, size, message count, and title (first user message).

Options:
- `--limit N` — show N sessions (default: 15)
- `--project KEYWORD` — filter by project path keyword

### Step 2: Let User Choose

Present the session list to the user. Ask which session to import. User can specify by:
- Session ID (full or partial, e.g. `a1302f9c`)
- Row number from the list
- "latest" for the most recent session

### Step 3: Convert & Import

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import <session-id-or-number>
```

This automatically:
1. Finds the JSONL transcript
2. Converts Claude Code format → OpenCode format
3. Runs `opencode import` to load the session
4. Reports the imported session ID

### Step 4: Continue Working

After import succeeds, tell the user:
- The session is now available in OpenCode's session list
- They can continue the conversation naturally
- All tool calls, file edits, and todo state from Claude Code are preserved as context

## Auto-Handoff (Rate Limit)

If Claude Code's StopFailure hook already ran (macOS notification appeared), a pre-converted file exists:

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list-handoffs
```

This shows auto-generated handoff files from `~/.claude/handoffs/`. The latest one was already imported — just tell the user to continue working.

## Quick Reference

| Command | Purpose |
|---|---|
| `cc-handoff.py list` | List Claude Code sessions |
| `cc-handoff.py list --project ai-system` | Filter by project |
| `cc-handoff.py import <id>` | Convert + import a session |
| `cc-handoff.py import latest` | Import most recent session |
| `cc-handoff.py list-handoffs` | Show auto-generated handoffs |
| `cc-handoff.py info <id>` | Show session details without importing |

## File Locations

| Path | Purpose |
|---|---|
| `~/.claude/projects/` | Claude Code session transcripts (JSONL) |
| `~/.claude/handoffs/` | Auto-generated handoff files + converted JSON |
| `~/.claude/hooks/rate-limit-handoff.sh` | StopFailure hook (auto-triggers on rate limit) |
