#!/usr/bin/env python3
"""
cc-handoff.py — Claude Code → OpenCode session handoff tool

Commands:
  list [--limit N] [--project KEYWORD]   List Claude Code sessions
  info <session-id>                       Show session details
  import <session-id|number|latest>       Convert + import into OpenCode
  set-title <session-id> <title>          Cache a human-readable session title
  generate-titles                         Output sessions needing titles (for LLM)
  list-handoffs                           Show auto-generated handoff files

Session IDs can be partial (first 8+ chars match).
"""

import sys
import json
import os
import re
import glob
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")
CLAUDE_HANDOFFS = os.path.expanduser("~/.claude/handoffs")
TITLE_CACHE_PATH = os.path.expanduser(
    "~/.config/opencode/skills/cc-handoff/title-cache.json"
)
OPENCODE_BIN = None


def load_title_cache():
    """Load {session_id: title} from title-cache.json."""
    if not os.path.isfile(TITLE_CACHE_PATH):
        return {}
    try:
        with open(TITLE_CACHE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_title_cache(cache):
    """Write {session_id: title} to title-cache.json."""
    os.makedirs(os.path.dirname(TITLE_CACHE_PATH), exist_ok=True)
    with open(TITLE_CACHE_PATH, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def find_opencode():
    global OPENCODE_BIN
    if OPENCODE_BIN:
        return OPENCODE_BIN
    if shutil.which("opencode"):
        OPENCODE_BIN = "opencode"
        return OPENCODE_BIN
    candidate = os.path.expanduser("~/.opencode/bin/opencode")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        OPENCODE_BIN = candidate
        return OPENCODE_BIN
    return None


def decode_project_path(dirname):
    raw = dirname.replace("-", "/").lstrip("/")
    home = os.path.expanduser("~").lstrip("/")
    if raw.startswith(home + "/"):
        raw = raw[len(home) + 1 :]
    elif raw.startswith(home):
        raw = raw[len(home) :]
    return raw or "~"


def parse_timestamp(ts_str):
    if not ts_str:
        return 0
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def extract_user_text(obj):
    """Extract user's text from a Claude Code user entry.

    Claude Code format: obj.message.content can be:
      - string (plain user message)
      - list of blocks (may contain tool_result blocks — skip those)
    Falls back to obj.content if message field is absent.
    """
    msg = obj.get("message", {})
    if isinstance(msg, dict):
        mc = msg.get("content", "")
        if isinstance(mc, str) and mc.strip():
            return mc.strip()
        if isinstance(mc, list):
            texts = []
            for block in mc:
                if isinstance(block, dict):
                    bt = block.get("type", "")
                    if bt == "text":
                        texts.append(block.get("text", ""))
                    elif bt == "tool_result":
                        pass  # skip tool results
                elif isinstance(block, str):
                    texts.append(block)
            result = "\n".join(t for t in texts if t).strip()
            if result:
                return result

    content = obj.get("content", "")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(t for t in texts if t).strip()
    return ""


def extract_assistant_blocks(obj):
    """Extract content blocks from a Claude Code assistant entry.

    Returns list of dicts: [{type: "text"|"tool_use"|"thinking", ...}]
    Claude Code format: obj.message.content is a list of typed blocks.
    """
    msg = obj.get("message", {})
    if isinstance(msg, dict):
        mc = msg.get("content", [])
        if isinstance(mc, list):
            return [b for b in mc if isinstance(b, dict)]

    content = obj.get("content", "")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    if isinstance(content, str) and content.strip():
        return [{"type": "text", "text": content.strip()}]
    return []


def extract_tool_results_from_user(obj):
    """Extract tool_result blocks from a user entry (Claude Code sends results as user messages)."""
    msg = obj.get("message", {})
    results = []
    if isinstance(msg, dict):
        mc = msg.get("content", [])
        if isinstance(mc, list):
            for block in mc:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id", "")
                    content = block.get("content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for cb in content:
                            if isinstance(cb, dict) and cb.get("type") == "text":
                                text_parts.append(cb.get("text", ""))
                        content = "\n".join(text_parts)
                    results.append(
                        {"tool_use_id": tool_use_id, "output": str(content)[:3000]}
                    )
    return results


def scan_session(jsonl_path, quick=True):
    info = {
        "path": jsonl_path,
        "session_id": os.path.splitext(os.path.basename(jsonl_path))[0],
        "size": os.path.getsize(jsonl_path),
        "mtime": os.path.getmtime(jsonl_path),
        "msg_count": 0,
        "first_user_msg": "",
        "project": "",
        "project_short": "",
        "cwd": "",
        "git_branch": "",
        "title": "",
        "todos": [],
        "files_written": set(),
        "files_read": set(),
    }

    parent = os.path.basename(os.path.dirname(jsonl_path))
    info["project"] = decode_project_path(parent)
    parts = [p for p in info["project"].rstrip("/").split("/") if p]
    # Show last 2 path segments for better disambiguation (e.g. "ai-system/claude")
    if len(parts) >= 2:
        info["project_short"] = parts[-2] + "/" + parts[-1]
    else:
        info["project_short"] = parts[-1] if parts else ""

    line_limit = 80 if quick else None
    line_num = 0
    last_todo_summary = ""

    with open(jsonl_path, "r") as f:
        for line in f:
            line_num += 1
            if quick and line_limit and line_num > line_limit:
                remaining = sum(1 for _ in f)
                info["msg_count"] += remaining
                break

            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            t = obj.get("type", "")
            if t in ("user", "assistant"):
                info["msg_count"] += 1

            if not info["git_branch"]:
                gb = obj.get("gitBranch", "")
                if gb:
                    info["git_branch"] = gb

            if not info["cwd"]:
                ec = obj.get("cwd", "")
                if ec and ec != ".":
                    info["cwd"] = ec

            if t == "user" and not info["first_user_msg"]:
                text = extract_user_text(obj)
                if text:
                    info["first_user_msg"] = text[:200]

            if t == "assistant":
                blocks = extract_assistant_blocks(obj)
                for block in blocks:
                    bt = block.get("type", "")
                    if bt == "tool_use":
                        name = block.get("name", "").lower()
                        inp = block.get("input", {})

                        if name == "todowrite" and "todos" in inp:
                            info["todos"] = inp["todos"]
                            in_progress = [
                                t
                                for t in inp["todos"]
                                if t.get("status") == "in_progress"
                            ]
                            if in_progress:
                                last_todo_summary = in_progress[0].get("content", "")
                            elif inp["todos"]:
                                last_todo_summary = inp["todos"][0].get("content", "")

                        if not quick:
                            if name in ("edit", "write"):
                                fp = inp.get("filePath", "")
                                if fp:
                                    info["files_written"].add(fp)
                            elif name == "read":
                                fp = inp.get("filePath", "")
                                if fp:
                                    info["files_read"].add(fp)

                        if not info["cwd"]:
                            if inp.get("workdir"):
                                info["cwd"] = inp["workdir"]
                            elif name in ("edit", "write", "read"):
                                fp = inp.get("filePath", "")
                                if fp.startswith("/"):
                                    info["cwd"] = os.path.dirname(fp)

    info["title"] = _build_title(info, last_todo_summary)

    if quick and not last_todo_summary and info["size"] > 20000:
        tail_todo = _scan_tail_for_todo(jsonl_path)
        if tail_todo:
            info["title"] = tail_todo[:60]

    return info


def _scan_tail_for_todo(jsonl_path, tail_bytes=50000):
    last_todo_summary = ""
    try:
        fsize = os.path.getsize(jsonl_path)
        offset = max(0, fsize - tail_bytes)
        with open(jsonl_path, "r") as f:
            if offset > 0:
                f.seek(offset)
                f.readline()
            for line in f:
                line = line.strip()
                if not line or "todowrite" not in line.lower():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                for block in extract_assistant_blocks(obj):
                    if block.get("type") != "tool_use":
                        continue
                    if block.get("name", "").lower() != "todowrite":
                        continue
                    todos = block.get("input", {}).get("todos", [])
                    in_progress = [t for t in todos if t.get("status") == "in_progress"]
                    if in_progress:
                        last_todo_summary = in_progress[0].get("content", "")
                    elif todos:
                        last_todo_summary = todos[0].get("content", "")
    except Exception:
        pass
    return last_todo_summary


def _build_title(info, last_todo_summary):
    branch = info.get("git_branch", "")
    prefix = f"[{branch}] " if branch else ""

    if last_todo_summary:
        body = last_todo_summary[:60]
    elif info.get("first_user_msg", ""):
        clean = re.sub(r"[\n\r\t]+", " ", info["first_user_msg"]).strip()
        body = clean[:47] + "..." if len(clean) > 50 else clean
    else:
        body = "(empty session)"

    return prefix + body


def find_all_sessions():
    if not os.path.isdir(CLAUDE_PROJECTS):
        return []
    sessions = []
    for project_dir in glob.glob(f"{CLAUDE_PROJECTS}/*/"):
        for jsonl_file in glob.glob(f"{project_dir}/*.jsonl"):
            sessions.append(jsonl_file)
    sessions.sort(key=os.path.getmtime, reverse=True)
    return sessions


def find_session_by_id(session_id):
    for session_path in find_all_sessions():
        sid = os.path.splitext(os.path.basename(session_path))[0]
        if sid == session_id or sid.startswith(session_id):
            return session_path
    return None


# ─── Converter ───────────────────────────────────────────────────────────────


def tool_use_to_text(block):
    """Render a tool_use block as readable text for OpenCode."""
    name = block.get("name", "unknown")
    inp = block.get("input", {})
    nl = name.lower()

    if nl == "bash":
        cmd = inp.get("command", "")
        desc = inp.get("description", "")
        return f"[Tool: bash] {desc}\n```\n{cmd}\n```"
    elif nl in ("edit", "write"):
        return f"[Tool: {name}] {inp.get('filePath', '')}"
    elif nl == "read":
        return f"[Tool: {name}] {inp.get('filePath', '')}"
    elif nl == "grep":
        return f"[Tool: grep] pattern='{inp.get('pattern', '')}' path='{inp.get('path', '')}'"
    elif nl == "glob":
        return f"[Tool: glob] pattern='{inp.get('pattern', '')}' path='{inp.get('path', '')}'"
    elif nl == "todowrite":
        lines = ["[Tool: todowrite]"]
        for t in inp.get("todos", []):
            s = t.get("status", "?")
            c = t.get("content", "")
            icon = {"completed": "✅", "in_progress": "🔄", "pending": "⬜"}.get(
                s, "❓"
            )
            lines.append(f"  {icon} {c}")
        return "\n".join(lines)
    else:
        return f"[Tool: {name}] {json.dumps(inp, ensure_ascii=False)[:500]}"


def convert_jsonl_to_opencode(input_path, output_path=None):
    """Convert Claude Code JSONL to OpenCode importable JSON."""
    if not os.path.isfile(input_path):
        print(f"Error: {input_path} not found", file=sys.stderr)
        return None

    if output_path is None:
        stem = os.path.splitext(input_path)[0]
        if stem.endswith("_transcript"):
            stem = stem[: -len("_transcript")]
        output_path = f"{stem}_opencode.json"

    entries = []
    with open(input_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        print("Error: no valid JSON entries found", file=sys.stderr)
        return None

    basename = os.path.basename(input_path)
    session_match = re.search(r"([a-f0-9]{8}-[a-f0-9-]{27,})", basename)
    session_id = (
        f"ses_{session_match.group(1)[:12]}"
        if session_match
        else f"ses_imported_{int(datetime.now().timestamp())}"
    )

    timestamps = []
    for e in entries:
        ms = parse_timestamp(e.get("timestamp", ""))
        if ms > 0:
            timestamps.append(ms)
    created_ms = (
        min(timestamps) if timestamps else int(datetime.now().timestamp() * 1000)
    )
    updated_ms = max(timestamps) if timestamps else created_ms

    cwd = "."
    for e in entries:
        if e.get("type") == "assistant":
            for block in extract_assistant_blocks(e):
                if block.get("type") == "tool_use":
                    inp = block.get("input", {})
                    if inp.get("workdir"):
                        cwd = inp["workdir"]
                        break
                    fp = inp.get("filePath", "")
                    if fp.startswith("/"):
                        cwd = os.path.dirname(fp)
                        break
            if cwd != ".":
                break
        ec = e.get("cwd", "")
        if ec and ec != ".":
            cwd = ec

    # Pending tool_result map: tool_use_id → output text
    pending_results = {}

    oc_messages = []
    msg_counter = 0

    for e in entries:
        t = e.get("type", "")
        ts = parse_timestamp(e.get("timestamp", ""))

        if t == "user":
            # Check for tool_results (Claude Code sends results as user messages)
            tool_results = extract_tool_results_from_user(e)
            for tr in tool_results:
                pending_results[tr["tool_use_id"]] = tr["output"]

            user_text = extract_user_text(e)
            if not user_text:
                continue

            msg_counter += 1
            oc_messages.append(
                {
                    "info": {
                        "role": "user",
                        "time": {"created": ts},
                        "agent": "imported-from-claude-code",
                        "model": {
                            "providerID": "anthropic",
                            "modelID": "claude-opus-4.6",
                        },
                        "variant": "thinking",
                        "id": f"msg_imported_{msg_counter:04d}",
                        "sessionID": session_id,
                    },
                    "parts": [
                        {
                            "type": "text",
                            "text": user_text,
                            "id": f"prt_imported_{msg_counter:04d}_001",
                            "sessionID": session_id,
                            "messageID": f"msg_imported_{msg_counter:04d}",
                        }
                    ],
                }
            )

        elif t == "assistant":
            blocks = extract_assistant_blocks(e)
            if not blocks:
                continue

            has_content = False
            for block in blocks:
                bt = block.get("type", "")
                if bt == "text" and block.get("text", "").strip():
                    has_content = True
                elif bt == "tool_use":
                    has_content = True
            if not has_content:
                continue

            msg_counter += 1
            parts = []

            parts.append(
                {
                    "type": "step-start",
                    "id": f"prt_imported_{msg_counter:04d}_000",
                    "sessionID": session_id,
                }
            )

            part_counter = 1
            for block in blocks:
                bt = block.get("type", "")

                if bt == "text" and block.get("text", "").strip():
                    parts.append(
                        {
                            "type": "text",
                            "text": block["text"].strip(),
                            "time": {"start": ts, "end": ts},
                            "id": f"prt_imported_{msg_counter:04d}_{part_counter:03d}",
                            "sessionID": session_id,
                        }
                    )
                    part_counter += 1

                elif bt == "tool_use":
                    tool_id = block.get(
                        "id", f"call_{msg_counter:04d}_{part_counter:03d}"
                    )
                    tool_text = tool_use_to_text(block)
                    tool_output = pending_results.pop(tool_id, "")

                    tool_part = {
                        "type": "tool",
                        "tool": block.get("name", "unknown"),
                        "callID": tool_id,
                        "state": {
                            "status": "completed",
                            "input": block.get("input", {}),
                            "output": tool_output[:3000] if tool_output else "",
                            "title": tool_text[:100],
                            "metadata": {},
                            "time": {"start": ts, "end": ts},
                        },
                        "id": f"prt_imported_{msg_counter:04d}_{part_counter:03d}",
                        "sessionID": session_id,
                    }
                    parts.append(tool_part)
                    part_counter += 1

            parts.append(
                {
                    "type": "step-finish",
                    "reason": "end-turn",
                    "tokens": {
                        "total": 0,
                        "input": 0,
                        "output": 0,
                        "reasoning": 0,
                        "cache": {"write": 0, "read": 0},
                    },
                    "cost": 0,
                    "id": f"prt_imported_{msg_counter:04d}_fin",
                    "sessionID": session_id,
                }
            )

            oc_messages.append(
                {
                    "info": {
                        "parentID": oc_messages[-1]["info"]["id"]
                        if oc_messages
                        else None,
                        "role": "assistant",
                        "mode": "imported-from-claude-code",
                        "agent": "imported-from-claude-code",
                        "variant": "thinking",
                        "path": {"cwd": cwd, "root": "/"},
                        "cost": 0,
                        "tokens": {
                            "total": 0,
                            "input": 0,
                            "output": 0,
                            "reasoning": 0,
                            "cache": {"write": 0, "read": 0},
                        },
                        "modelID": "claude-opus-4.6",
                        "providerID": "anthropic",
                        "time": {"created": ts, "completed": ts},
                        "finish": "end-turn",
                        "id": f"msg_imported_{msg_counter:04d}",
                        "sessionID": session_id,
                    },
                    "parts": parts,
                }
            )

    # Inject messageID into all parts
    for m in oc_messages:
        msg_id = m["info"]["id"]
        for p in m.get("parts", []):
            if "messageID" not in p:
                p["messageID"] = msg_id

    title = "Imported from Claude Code"
    for m in oc_messages:
        if m["info"]["role"] == "user":
            for p in m.get("parts", []):
                if p.get("type") == "text" and p.get("text"):
                    title = p["text"][:80]
                    break
            break

    files_modified = set()
    for e in entries:
        if e.get("type") == "assistant":
            for block in extract_assistant_blocks(e):
                if block.get("type") == "tool_use" and block.get(
                    "name", ""
                ).lower() in ("edit", "write"):
                    fp = block.get("input", {}).get("filePath", "")
                    if fp:
                        files_modified.add(fp)

    oc_session = {
        "info": {
            "id": session_id,
            "slug": f"cc-import-{session_id[-8:]}",
            "projectID": "global",
            "directory": cwd,
            "title": title,
            "version": "1.3.17",
            "summary": {"additions": 0, "deletions": 0, "files": len(files_modified)},
            "time": {"created": created_ms, "updated": updated_ms},
        },
        "messages": oc_messages,
    }

    with open(output_path, "w") as f:
        json.dump(oc_session, f, ensure_ascii=False, indent=2)

    return output_path


# ─── Commands ────────────────────────────────────────────────────────────────


def cmd_list(args):
    limit = 15
    project_filter = None
    json_mode = False

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            project_filter = args[i + 1].lower()
            i += 2
        elif args[i] == "--json":
            json_mode = True
            i += 1
        else:
            i += 1

    sessions = find_all_sessions()
    title_cache = load_title_cache()
    results = []

    for path in sessions:
        info = scan_session(path, quick=True)
        if project_filter and project_filter not in info["project"].lower():
            continue
        cached = title_cache.get(info["session_id"])
        if cached:
            info["title"] = cached
        results.append(info)
        if len(results) >= limit:
            break

    if not results:
        if json_mode:
            print("[]")
        else:
            print("No Claude Code sessions found.")
            print(f"Looking in: {CLAUDE_PROJECTS}")
        return

    if json_mode:
        out = []
        for idx, info in enumerate(results, 1):
            out.append(
                {
                    "num": idx,
                    "id": info["session_id"],
                    "id_short": info["session_id"][:8],
                    "date": datetime.fromtimestamp(info["mtime"]).strftime(
                        "%m-%d %H:%M"
                    ),
                    "size_kb": info["size"] // 1024,
                    "msgs": info["msg_count"],
                    "project": info["project"],
                    "project_short": info["project_short"],
                    "title": info["title"] or "(empty)",
                    "git_branch": info.get("git_branch", ""),
                }
            )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print(
        f"\n{'#':<4} {'ID':<10} {'Date':<12} {'Size':<8} {'Msgs':<6} {'Project':<28} Title"
    )
    print("─" * 120)
    for idx, info in enumerate(results, 1):
        dt = datetime.fromtimestamp(info["mtime"]).strftime("%m-%d %H:%M")
        sz = f"{info['size'] // 1024}KB"
        proj = info["project_short"][:26]
        title = info["title"] or "(empty)"
        sid_short = info["session_id"][:8]
        print(
            f"{idx:<4} {sid_short:<10} {dt:<12} {sz:<8} {info['msg_count']:<6} {proj:<28} {title}"
        )
        full_path = info.get("project", "")
        if full_path and full_path != info["project_short"]:
            print(f"{'':4} {'':10} {'':12} {'':8} {'':6} └─ ~/{full_path}")

    print(f"\nTotal: {len(results)} sessions.")
    print(
        "Use `import <session-id>` (8+ char ID) to import. Row numbers may shift between calls."
    )


def resolve_session_path(target):
    """Resolve a target (session-id, row number, or 'latest') to a JSONL path."""
    sessions = find_all_sessions()

    if target == "latest":
        return sessions[0] if sessions else None
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx]
        print(
            f"Invalid row number: {target} (have {len(sessions)} sessions)",
            file=sys.stderr,
        )
        return None
    return find_session_by_id(target)


def cmd_info(args):
    if not args:
        print("Usage: cc-handoff.py info <session-id|number|latest>", file=sys.stderr)
        sys.exit(1)

    target = args[0]
    path = resolve_session_path(target)
    if not path:
        print(f"Session not found: {target}", file=sys.stderr)
        sys.exit(1)

    info = scan_session(path, quick=False)

    print(f"\n{'=' * 60}")
    print(f"Session:  {info['session_id']}")
    print(f"Project:  {info['project']}")
    print(f"Path:     {info['path']}")
    print(f"Size:     {info['size'] // 1024} KB")
    print(f"Messages: {info['msg_count']}")
    print(
        f"Modified: {datetime.fromtimestamp(info['mtime']).strftime('%Y-%m-%d %H:%M:%S')}"
    )
    if info["cwd"]:
        print(f"CWD:      {info['cwd']}")

    if info["first_user_msg"]:
        print(f"\nFirst user message:")
        print(f"  {info['first_user_msg']}")

    if info["todos"]:
        print(f"\nTodo state ({len(info['todos'])} items):")
        for t in info["todos"]:
            s = t.get("status", "?")
            c = t.get("content", "")
            icon = {"completed": "✅", "in_progress": "🔄", "pending": "⬜"}.get(
                s, "❓"
            )
            print(f"  {icon} {c}")

    if info["files_written"]:
        print(f"\nFiles modified ({len(info['files_written'])}):")
        for f in sorted(info["files_written"]):
            print(f"  {f}")

    print(f"{'=' * 60}")


def cmd_import(args):
    if not args:
        print("Usage: cc-handoff.py import <session-id|number|latest>", file=sys.stderr)
        sys.exit(1)

    target = args[0]
    path = resolve_session_path(target)

    if not path:
        print(f"Session not found: {target}", file=sys.stderr)
        sys.exit(1)

    session_id = os.path.splitext(os.path.basename(path))[0]
    print(f"Converting: {session_id}")
    print(f"Source:     {path}")
    print(f"Size:       {os.path.getsize(path) // 1024} KB")

    output_dir = os.path.expanduser("~/.claude/handoffs")
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"{output_dir}/{timestamp}_{session_id[:12]}_opencode.json"

    result = convert_jsonl_to_opencode(path, output_path)
    if not result:
        print("Conversion failed.", file=sys.stderr)
        sys.exit(1)

    with open(output_path) as f:
        oc_data = json.load(f)
    msg_count = len(oc_data.get("messages", []))
    print(f"Converted:  {msg_count} messages → {output_path}")

    oc_bin = find_opencode()
    if not oc_bin:
        print(f"\nOpenCode not found. Manual import:")
        print(f"  opencode import {output_path}")
        return

    print(f"Importing into OpenCode...")
    try:
        result = subprocess.run(
            [oc_bin, "import", output_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            oc_session_id = oc_data.get("info", {}).get("id", "")
            print(f"✅ Imported successfully!")
            print(f"\nOpenCode session ID: {oc_session_id}")
            print(f"Source CC session:   {session_id}")
            print(
                f"Project:             {decode_project_path(os.path.basename(os.path.dirname(path)))}"
            )
            print(f"\nTo continue, open this session in OpenCode.")
        else:
            print(f"Import returned code {result.returncode}")
            if result.stderr:
                print(f"stderr: {result.stderr[:500]}")
            print(f"\nManual import: opencode import {output_path}")
    except subprocess.TimeoutExpired:
        print(f"Import timed out. Manual import:")
        print(f"  opencode import {output_path}")
    except Exception as exc:
        print(f"Import error: {exc}")
        print(f"Manual import: opencode import {output_path}")


def cmd_list_handoffs(args):
    if not os.path.isdir(CLAUDE_HANDOFFS):
        print("No handoffs directory found.")
        return

    handoffs = sorted(
        glob.glob(f"{CLAUDE_HANDOFFS}/*_handoff.md"),
        key=os.path.getmtime,
        reverse=True,
    )

    oc_files = sorted(
        glob.glob(f"{CLAUDE_HANDOFFS}/*_opencode.json"),
        key=os.path.getmtime,
        reverse=True,
    )

    if not handoffs and not oc_files:
        print("No handoff files found.")
        return

    print(f"\nHandoff summaries ({len(handoffs)}):")
    for h in handoffs[:10]:
        dt = datetime.fromtimestamp(os.path.getmtime(h)).strftime("%m-%d %H:%M")
        sz = f"{os.path.getsize(h) // 1024}KB"
        name = os.path.basename(h)
        print(f"  {dt}  {sz:<6}  {name}")

    if oc_files:
        print(f"\nConverted sessions ({len(oc_files)}):")
        for fpath in oc_files[:10]:
            dt = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%m-%d %H:%M")
            sz = f"{os.path.getsize(fpath) // 1024}KB"
            name = os.path.basename(fpath)
            print(f"  {dt}  {sz:<6}  {name}")

    latest = os.path.join(CLAUDE_HANDOFFS, "latest_handoff.md")
    if os.path.islink(latest):
        target = os.readlink(latest)
        print(f"\nLatest: {os.path.basename(target)}")

    log = os.path.join(CLAUDE_HANDOFFS, "handoff.log")
    if os.path.isfile(log):
        print(f"\nRecent log entries:")
        with open(log) as lf:
            lines = lf.readlines()
            for line in lines[-5:]:
                print(f"  {line.strip()}")


def cmd_set_title(args):
    if len(args) < 2:
        print("Usage: cc-handoff.py set-title <session-id> <title...>", file=sys.stderr)
        sys.exit(1)

    sid = args[0]
    title = " ".join(args[1:])

    path = find_session_by_id(sid)
    if not path:
        print(f"Session not found: {sid}", file=sys.stderr)
        sys.exit(1)

    full_sid = os.path.splitext(os.path.basename(path))[0]
    cache = load_title_cache()
    cache[full_sid] = title
    save_title_cache(cache)
    print(f"Title set: {full_sid[:12]}... → {title}")


def cmd_generate_titles(args):
    sessions = find_all_sessions()
    cache = load_title_cache()
    limit = 20

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            i += 1

    needs_title = []
    for path in sessions:
        sid = os.path.splitext(os.path.basename(path))[0]
        if sid in cache:
            continue
        info = scan_session(path, quick=True)
        snippet = info.get("first_user_msg", "")[:300]
        if not snippet:
            continue
        needs_title.append(
            {
                "session_id": sid,
                "project": info.get("project", ""),
                "git_branch": info.get("git_branch", ""),
                "first_msg": snippet,
                "msg_count": info.get("msg_count", 0),
                "date": datetime.fromtimestamp(info["mtime"]).strftime("%Y-%m-%d"),
            }
        )
        if len(needs_title) >= limit:
            break

    if not needs_title:
        print("All sessions already have cached titles.")
        return

    print(json.dumps(needs_title, ensure_ascii=False, indent=2))
    print(
        f"\n# {len(needs_title)} sessions need titles.",
        file=sys.stderr,
    )
    print(
        "# For each, generate a 3-7 word title and run:",
        file=sys.stderr,
    )
    print(
        "#   cc-handoff.py set-title <session-id> <title>",
        file=sys.stderr,
    )


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "list": cmd_list,
        "ls": cmd_list,
        "info": cmd_info,
        "import": cmd_import,
        "set-title": cmd_set_title,
        "generate-titles": cmd_generate_titles,
        "list-handoffs": cmd_list_handoffs,
        "handoffs": cmd_list_handoffs,
    }

    if cmd in ("--help", "-h", "help"):
        print(__doc__)
        sys.exit(0)

    handler = commands.get(cmd)
    if not handler:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(f"Available: {', '.join(commands.keys())}", file=sys.stderr)
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
