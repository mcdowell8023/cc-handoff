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

Run the CLI with `--json` to get structured session data:

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py list --json
```

Options:
- `--limit N` — show N sessions (default: 15)
- `--project KEYWORD` — filter by project path keyword
- `--json` — output as JSON array (for building selection UI)

### Step 2: Let User Choose via Question Tool

Parse the JSON output and use the `question` tool to present choices. Build each option like this:

- **label**: `#N title` (e.g. `#13 feat_EPO 进度跟踪`)
- **description**: `[id_short] date | msgs msgs | project_path` (e.g. `[3d438b99] 04-03 16:02 | 1072 msgs | ~/wb/projcet/ai/system/worktree/claude`)

Use the full `project` path (not `project_short`) in the description so users can distinguish sessions from different worktrees.

Example question call:

```
question(questions=[{
  header: "选择会话",
  question: "你想导入哪个 Claude Code 会话继续工作？",
  options: [
    { label: "#13 feat_EPO 进度跟踪", description: "[3d438b99] 04-03 16:02 | 1072 msgs | ~/wb/projcet/ai/system/worktree/claude" },
    { label: "#14 feat_EPO 进度跟踪", description: "[90a83588] 04-03 16:02 | 1452 msgs | ~/wb/projcet/wb/project/service/worktree/claude" },
    ...
  ]
}])
```

After user selects, extract the `id_short` from the chosen option's description and use it for import.

### Step 3: Convert & Import

**IMPORTANT: Always use session ID (8+ chars), not row numbers. Row numbers can shift between calls.**

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py import <session-id>
```

This automatically:
1. Finds the JSONL transcript
2. Converts Claude Code format → OpenCode format
3. Runs `opencode import` to load the session
4. Outputs the **OpenCode session ID** and **source CC session ID**

### Step 4: Summarize the Imported Session

After import succeeds, you MUST summarize what was done in the Claude Code session. Do NOT just say "imported successfully" and stop.

**4a.** Show the import result info (OpenCode session ID, source CC session, message count).

**4b.** Run `info` to get session details:

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py info <session-id>
```

This shows: todo state, files modified, first user message, CWD, etc.

**4c.** Summarize to the user:
- What was the session about (from first user message + todo items)
- Current progress: which todos are ✅ completed, 🔄 in progress, ⬜ pending
- Files that were modified
- What remains to be done (pending/in-progress todos)

**4d.** Ask the user: "要继续未完成的工作，还是做别的？"

**DO NOT** search for or read from other existing OpenCode sessions. Only use the `info` output from the source CC session ID.

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
| `cc-handoff.py info <id>` | Show session details without importing |
| `cc-handoff.py set-title <id> <title>` | Cache a smart title for a session |
| `cc-handoff.py generate-titles` | Output sessions needing titles (JSON) |
| `cc-handoff.py list-handoffs` | Show auto-generated handoffs |

## Smart Title Generation

Sessions listed by `list` show auto-extracted titles (first user message or todo summary). For better readability, you can generate LLM-powered titles.

### When to Use

- User says "generate titles", "improve session titles", or sessions are hard to distinguish
- After listing sessions and seeing generic/duplicate titles

### Workflow

**Step 1**: Get sessions that need titles:

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py generate-titles
```

This outputs JSON with `session_id`, `project`, `git_branch`, `first_msg`, `msg_count`, and `date` for each untitled session.

**Step 2**: For each session in the output, generate a concise title (3-7 words, sentence-case) that captures the main topic or goal. Use the `first_msg`, `project`, and `git_branch` as context.

**Step 3**: Save each title:

```bash
python3 ~/.config/opencode/skills/cc-handoff/scripts/cc-handoff.py set-title <session-id> <title words>
```

**Step 4**: Verify with `list` — cached titles now appear instead of auto-extracted ones.

### Title Generation Guidelines

- 3-7 words, sentence case (e.g. "JWT auth middleware setup")
- Capture the main goal, not the first message verbatim
- Include domain context when helpful (e.g. "Dashboard chart performance fix")
- Avoid generic titles like "Code review" or "Bug fix"
- Ask user for confirmation before batch-generating (consumes LLM tokens)

## File Locations

| Path | Purpose |
|---|---|
| `~/.claude/projects/` | Claude Code session transcripts (JSONL) |
| `~/.claude/handoffs/` | Auto-generated handoff files + converted JSON |
| `~/.claude/hooks/rate-limit-handoff.sh` | StopFailure hook (auto-triggers on rate limit) |
