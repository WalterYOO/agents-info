#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agents-info: list local Claude Code sessions as a readable table or JSON.

Three data sources are merged:
  1. ~/.claude/sessions/<pid>.json   -> name, pid, sessionId, cwd, start, liveness
  2. transcript .jsonl               -> first/last real user message, turns, activity
  3. ~/.claude/session-data/*.tmp    -> ECC task summary (optional)

Read-only: never writes to disk, never touches the network.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
REGISTRY_DIR = os.path.join(HOME, ".claude", "sessions")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
SESSION_DATA_DIR = os.path.join(HOME, ".claude", "session-data")

USER_TYPE_RE = re.compile(rb'"type"\s*:\s*"user"')
AI_TITLE_RE = re.compile(rb'"type"\s*:\s*"ai-title"')
TS_RE = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')

# System-generated user records that look like user turns but are not.
SKIP_TEXTS = {
    "[Request interrupted by user]",
    "[Request interrupted by user for tool use]",
}

MAX_TEXT = 500  # keep transcript-derived strings bounded in JSON output

# ECC sometimes records subagent hand-backs as "tasks"; they are not user asks.
ECC_TASK_SKIP_PREFIXES = (
    "Another Claude session sent a message:",
    "[Subagent hand-back]",
    "<agent-message",
    "<task-notification>",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def project_slug(cwd):
    """Claude Code replaces every non-alphanumeric char with '-'.

    /Users/walter/dsh/embodied_ai_umi -> -Users-walter-dsh-embodied-ai-umi
    """
    return re.sub(r"[^A-Za-z0-9]", "-", cwd or "")


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, OverflowError):
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def from_millis(value):
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso_local(dt):
    return dt.astimezone().isoformat(timespec="seconds") if dt else None


def fmt_dt(dt):
    return dt.astimezone().strftime("%m-%d %H:%M") if dt else "—"


def fmt_ago(dt, now):
    if not dt:
        return ""
    seconds = (now - dt).total_seconds()
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return "%d分钟前" % int(seconds // 60)
    if seconds < 86400:
        return "%d小时前" % int(seconds // 3600)
    return "%d天前" % int(seconds // 86400)


def short_cwd(cwd, max_len=30):
    if not cwd:
        return "—"
    text = cwd
    if text.startswith(HOME + os.sep):
        text = "~" + text[len(HOME):]
    elif text == HOME:
        text = "~"
    if len(text) <= max_len:
        return text
    # Shorten by whole path components so the final directory name stays intact.
    parts = [p for p in text.split(os.sep) if p]
    for take in (2, 1):
        candidate = "…/" + os.sep.join(parts[-take:])
        if len(candidate) <= max_len:
            return candidate
    return candidate if parts else text


def one_line(text):
    return " ".join((text or "").split())


def truncate(text, limit):
    text = one_line(text)
    if limit and len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def md_cell(text, limit=None):
    value = truncate(text, limit)
    return value.replace("|", "\\|")


# --------------------------------------------------------------------------
# transcript
# --------------------------------------------------------------------------

def user_text(obj):
    """Return normalized user text, or None for tool results / meta noise."""
    message = obj.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content):
            return None
        chunks = [
            x.get("text", "")
            for x in content
            if isinstance(x, dict) and x.get("type") == "text"
        ]
        text = " ".join(chunks)
    else:
        return None
    text = one_line(text)
    if not text or text.startswith("<") or text in SKIP_TEXTS:
        return None
    return text[:MAX_TEXT]


def scan_transcript(path):
    info = {
        "turns": 0,
        "first": None,
        "last": None,
        "ai_title": None,
        "last_activity": None,
        "error": None,
    }
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                match = TS_RE.search(raw)
                if match:
                    info["last_activity"] = match.group(1).decode("utf-8", "replace")
                if AI_TITLE_RE.search(raw):
                    try:
                        title_obj = json.loads(raw)
                    except ValueError:
                        title_obj = None
                    if isinstance(title_obj, dict) and title_obj.get("type") == "ai-title":
                        title = one_line(title_obj.get("aiTitle") or "")
                        if title:
                            info["ai_title"] = title[:MAX_TEXT]
                if not USER_TYPE_RE.search(raw):
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if obj.get("type") != "user" or obj.get("isMeta"):
                    continue
                text = user_text(obj)
                if not text:
                    continue
                info["turns"] += 1
                if info["first"] is None:
                    info["first"] = text
                info["last"] = text
    except OSError as exc:
        info["error"] = str(exc)
    return info


def transcript_path(cwd, session_id):
    candidate = os.path.join(PROJECTS_DIR, project_slug(cwd), session_id + ".jsonl")
    if os.path.exists(candidate):
        return candidate
    # Fallback for cwd changes / unusual slugs: match the unique filename.
    matches = glob.glob(os.path.join(PROJECTS_DIR, "*", session_id + ".jsonl"))
    return matches[0] if matches else None


# --------------------------------------------------------------------------
# ECC session summaries
# --------------------------------------------------------------------------

def section_items(text, header):
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index
            break
    if start is None:
        return []
    items = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("### "):
            break
        if stripped.startswith("- "):
            item = one_line(stripped[2:])
            if item:
                items.append(item[:MAX_TEXT])
    return items


def find_ecc_summary(session_id):
    tail = session_id.replace("-", "")[-8:]
    if not tail:
        return None
    pattern = os.path.join(SESSION_DATA_DIR, "*-%s-session.tmp" % tail)
    matches = glob.glob(pattern)
    if not matches:
        return None
    path = max(matches, key=lambda p: os.path.getmtime(p))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    tasks = [
        item
        for item in section_items(text, "### Tasks")
        if not item.startswith(ECC_TASK_SKIP_PREFIXES)
    ]
    return {
        "path": path,
        "tasks": tasks[:5],
        "files": section_items(text, "### Files Modified")[:20],
    }


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def git_dirty(cwd):
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line.strip()])


# --------------------------------------------------------------------------
# build rows
# --------------------------------------------------------------------------

def load_registry():
    entries = []
    for path in glob.glob(os.path.join(REGISTRY_DIR, "*.json")):
        data = None
        # Claude Code rewrites these files in place; a read can catch a
        # partial write. Retry briefly before giving up on one entry.
        for attempt in range(3):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                break
            except ValueError:
                if attempt == 2:
                    break
                time.sleep(0.01)
            except OSError:
                break
        if not isinstance(data, dict) or not data.get("sessionId"):
            continue
        entries.append(data)
    return entries


def detect_current(entries):
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    pid = os.environ.get("CLAUDE_PID")
    if session_id:
        for entry in entries:
            if entry.get("sessionId") == session_id:
                return entry.get("sessionId")
    if pid:
        for entry in entries:
            if str(entry.get("pid")) == str(pid):
                return entry.get("sessionId")
    return None


def build_session(entry, include_ecc, include_git):
    session_id = entry["sessionId"]
    cwd = entry.get("cwd") or ""
    started = from_millis(entry.get("startedAt"))
    transcript = transcript_path(cwd, session_id)
    if transcript:
        scan = scan_transcript(transcript)
    else:
        scan = {
            "turns": 0,
            "first": None,
            "last": None,
            "ai_title": None,
            "last_activity": None,
            "error": "transcript 不存在",
        }

    last_activity = parse_iso(scan["last_activity"])
    if last_activity is None and transcript and os.path.exists(transcript):
        last_activity = datetime.fromtimestamp(
            os.path.getmtime(transcript), tz=timezone.utc
        )
    if last_activity is None:
        last_activity = from_millis(entry.get("updatedAt")) or started

    alive = pid_alive(entry.get("pid"))
    raw_status = entry.get("status") or "alive"
    status = raw_status if alive else "已退出"

    return {
        "name": entry.get("name") or session_id[:8],
        "session_id": session_id,
        "short_id": session_id[:8],
        "pid": entry.get("pid"),
        "alive": alive,
        "status": status,
        "raw_status": raw_status,
        "cwd": cwd,
        "started_at": iso_local(started),
        "last_activity": iso_local(last_activity),
        "user_turns": scan["turns"],
        "ai_title": scan["ai_title"],
        "first_user_message": scan["first"],
        "last_user_message": scan["last"],
        "ecc": find_ecc_summary(session_id) if include_ecc else None,
        "git_dirty": git_dirty(cwd) if include_git else None,
        "transcript": transcript,
        "error": scan["error"],
        "_started_dt": started,
        "_last_activity_dt": last_activity,
    }


def sort_sessions(sessions):
    def key(session):
        stamp = session.get("_last_activity_dt") or session.get("_started_dt")
        return (
            1 if session["alive"] else 0,
            1 if session["raw_status"] == "busy" else 0,
            stamp.timestamp() if stamp else 0,
        )
    return sorted(sessions, key=key, reverse=True)


# --------------------------------------------------------------------------
# renderers
# --------------------------------------------------------------------------

def render_md(sessions, matched, current_id, full, force_git=False):
    now = datetime.now(timezone.utc)
    alive = [s for s in matched if s["alive"]]
    busy = [s for s in alive if s["raw_status"] == "busy"]
    total = len(matched)
    shown = len(sessions)

    summary = "共 %d 个会话，%d 个在运行（busy %d / idle %d）" % (
        total, len(alive), len(busy), len(alive) - len(busy)
    )
    if shown < total:
        summary += "；显示前 %d 个" % shown
    lines = [summary + "。", ""]

    show_git = force_git or any(s["git_dirty"] is not None for s in sessions)
    headers = ["名称", "状态", "ID", "目录", "启动", "轮次", "最后活动",
               "会话标题", "首条", "最近一条", "ECC 任务"]
    if show_git:
        headers.insert(4, "未提交")

    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    def cap(value):
        return None if full else value

    for session in sessions:
        name = session["name"]
        status = session["status"]
        if session["session_id"] == current_id:
            name += " ★"
            status += "·本"

        last = fmt_dt(session["_last_activity_dt"])
        ago = fmt_ago(session["_last_activity_dt"], now)
        if ago:
            last += " (%s)" % ago

        topic = session["first_user_message"] or (
            "（无 transcript）" if session.get("error") else "—"
        )
        recent = session["last_user_message"] or "—"
        ecc = "—"
        if session.get("ecc"):
            items = session["ecc"].get("tasks") or []
            ecc = "；".join(items[:2]) or "—"

        title = session.get("ai_title") or "—"
        cells = [
            md_cell(name, cap(24)),
            status,
            session["short_id"],
            md_cell(short_cwd(session["cwd"], 10000 if full else 30), None),
            fmt_dt(session["_started_dt"]),
            str(session["user_turns"]),
            last,
            md_cell(title, cap(36)),
            md_cell(topic, cap(34)),
            md_cell(recent, cap(34)),
            md_cell(ecc, cap(44)),
        ]
        if show_git:
            dirty = session["git_dirty"]
            cells.insert(4, "—" if dirty is None else str(dirty))
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    current = next((s for s in sessions if s["session_id"] == current_id), None)
    if current:
        lines.append(
            "本会话：%s（%s，pid %s）"
            % (current["name"], current["short_id"], current["pid"])
        )
    else:
        lines.append("本会话：未识别（脚本可能不在 Claude Code 会话内运行）")
    lines.append(
        "接管会话：claude --resume <名字>；会话内 /resume <名字>"
        "（选择器里按 Ctrl+A 显示全部项目）"
    )
    return "\n".join(lines)


def render_json(sessions, matched, current_id):
    current = next((s for s in matched if s["session_id"] == current_id), None)
    payload = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total": len(matched),
        "shown": len(sessions),
        "alive": len([s for s in matched if s["alive"]]),
        "current_session": (
            {
                "name": current["name"],
                "session_id": current["session_id"],
                "pid": current["pid"],
            }
            if current else None
        ),
        "sessions": [],
    }
    for session in sessions:
        payload["sessions"].append(
            {k: v for k, v in session.items() if not k.startswith("_")}
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List local Claude Code sessions with topic, activity and ECC summary."
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--md", action="store_true", help="markdown table (default)")
    output.add_argument("--json", action="store_true", help="machine-readable JSON")
    parser.add_argument("--no-ecc", action="store_true", help="skip ECC session summaries")
    parser.add_argument("--git", action="store_true", help="add uncommitted-file count column")
    parser.add_argument("--full", action="store_true", help="do not truncate markdown cells")
    parser.add_argument("--alive-only", action="store_true", help="hide exited sessions")
    parser.add_argument("--limit", type=int, default=0, help="show at most N sessions")
    args = parser.parse_args(argv)

    entries = load_registry()
    current_id = detect_current(entries)
    sessions = [build_session(e, not args.no_ecc, args.git) for e in entries]
    matched = sort_sessions(sessions)
    if args.alive_only:
        matched = [s for s in matched if s["alive"]]
    shown = matched[: args.limit] if args.limit and args.limit > 0 else matched

    if args.json:
        print(render_json(shown, matched, current_id))
    else:
        print(render_md(shown, matched, current_id, args.full, force_git=args.git))
    return 0


if __name__ == "__main__":
    sys.exit(main())
