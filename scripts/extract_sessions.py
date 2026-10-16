"""Extract a day's activity from coding-agent session history.

Three sources, same output shape:

  jsonl    Raw Claude Code transcripts under <claude home>/projects, subagent
           transcripts included. Every record is stamped to the millisecond and
           says who wrote it, which makes it the richest source for `claude`.
  ccrider  The ccrider SQLite index (sources.ccrider_db, default
           ~/.config/ccrider/sessions.db). Covers Codex
           CLI, Copilot CLI, OpenCode, Pi, Antigravity and Amp as well as Claude
           Code, but keeps text messages only: no tool-only turns, no
           subagents, no token counts. Synced first unless --no-sync.
  hybrid   `claude` sessions from jsonl, every other provider from ccrider. Each
           session comes from one source only, so nothing is counted twice.

`auto` (the default) is hybrid when the ccrider database exists, else jsonl.

A per-session trace written by trace_hook.py adds what no transcript records:
when each turn ended, time spent waiting on a permission prompt, and when the
session closed. Read from `sources.trace_dir` when the file exists.

Emits JSON on stdout: one entry per session with activity in the window,
carrying the human turns (what was asked), the closing assistant text (what was
concluded), busy stretches, tool time, tokens and subagents. The caller
narrates. This script only gathers.

Usage:
    python extract_sessions.py [--date YYYY-MM-DD] [--days N] [--tz +02:00]
                              [--source auto|hybrid|jsonl|ccrider] [--no-sync]
                              [--provider NAME ...] [--project SUBSTR | --here]
                              [--max-chars N] [--idle-gap MIN] [--all]
"""

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

TAG_RE = re.compile(r"<[^>]+>")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Turns that arrive in the user slot but were not typed by the user. Only
# consulted when a record does not say who wrote it (ccrider, older transcripts).
NOISE_PREFIXES = (
    "Base directory for this skill:",
    "Caveat: The messages below were generated",
    "[SYSTEM NOTIFICATION",
    "Stop hook feedback:",
    "This session is being continued",
    "[thinking budget exceeded]",
    "[Request interrupted",
    "Reply with exactly",
    "<artifact-content-authored-by-others",
    "<recommended_plugins>",
    "<system-reminder>",
    "<task-notification>",
    "A session-scoped Stop hook is now active",
    "[Image: source:",
    "(Re-invocation of /",
)
INTERRUPT_PREFIX = "[Request interrupted"

# Session housekeeping commands name no work.
HOUSEKEEPING_RE = re.compile(
    r"^(\[invoked /(login|logout|model|clear|compact|config|status|cost|exit|resume|"
    r"effort|fast|help|permissions|hooks|mcp|context|usage|theme|vim)\]\s*)+$")

IGNORE_PREFIXES = ()


def parse_offset(text):
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", text.strip())
    if not match:
        raise argparse.ArgumentTypeError("tz must look like +02:00 or -05:00")
    sign = 1 if match.group(1) == "+" else -1
    return dt.timedelta(minutes=sign * (int(match.group(2)) * 60 + int(match.group(3))))


def iso_stamp(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def strip_markup(text):
    """Drop system-reminder / command-scaffolding blocks, keep the human words."""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", " ", text, flags=re.S)
    text = re.sub(r"<local-command-[^>]*>.*?</local-command-[^>]*>", " ", text, flags=re.S)
    text = re.sub(r"<task-notification>.*?</task-notification>", " ", text, flags=re.S)
    text = re.sub(r"<recommended_plugins>.*?</recommended_plugins>", " ", text, flags=re.S)
    # Slash-command invocations matter (they name the work), so surface the name
    # and args rather than deleting the whole block.
    text = re.sub(r"<command-message>.*?</command-message>", " ", text, flags=re.S)
    text = re.sub(r"<command-name>(.*?)</command-name>", r"[invoked \1]", text, flags=re.S)
    text = re.sub(r"<command-args>(.*?)</command-args>", r"\1", text, flags=re.S)
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_noise(raw, stripped, human=None):
    """True when a user-slot message is not a person asking for work.

    `human` is the transcript's own verdict (origin.kind). When it is known the
    text filters are skipped, except housekeeping and configured ignores.
    """
    if not stripped or len(stripped) < 2 or HOUSEKEEPING_RE.match(stripped):
        return True
    if human is False:
        return True
    prefixes = tuple(IGNORE_PREFIXES) if human else NOISE_PREFIXES + tuple(IGNORE_PREFIXES)
    return any(raw.lstrip().startswith(p) or stripped.startswith(p) for p in prefixes)


def blocks_text(content, kind):
    """Text of a message's content blocks, or None when it carries no words.

    A user-slot message holding a tool_result is tool output, not the user.
    An assistant message holding only tool_use blocks concluded nothing.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind_ = block.get("type")
        if kind_ == "tool_result" and kind == "user":
            return None
        if kind_ == "text":
            parts.append(block.get("text", ""))
        elif kind_ == "image":
            parts.append("[image attached]")
    return "\n".join(parts) if parts else None


def short_id(session_id):
    match = UUID_RE.search(session_id or "")
    return (match.group(0) if match else session_id or "")[:8]


def merge_spans(spans, idle_gap):
    """Join (start, end) spans closer than `idle_gap` into stretches, per day."""
    merged = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] <= idle_gap and start.date() == merged[-1][0].date():
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def cut_spans(spans, cuts):
    """Remove the `cuts` intervals from `spans`. Both are (start, end) lists."""
    result = spans
    for cut_start, cut_end in cuts:
        kept = []
        for start, end in result:
            if cut_end <= start or cut_start >= end:
                kept.append([start, end])
                continue
            if start < cut_start:
                kept.append([start, cut_start])
            if cut_end < end:
                kept.append([cut_end, end])
        result = kept
    return result


def span_rows(spans):
    return [{"date": a.strftime("%Y-%m-%d"), "start": a.strftime("%H:%M"),
             "end": b.strftime("%H:%M"), "minutes": round((b - a).total_seconds() / 60, 1)}
            for a, b in spans]


class Session:
    """Accumulates one session's in-window activity. Times are local."""

    def __init__(self, session_id, provider, project_path):
        self.session_id = session_id
        self.provider = provider
        self.project_path = project_path
        self.entrypoint = None
        self.user_turns = []
        self.branches = set()
        self.first_at = self.last_at = None
        self.first_day = self.last_day = None
        self.closing = self.closing_at = None
        self.stamps = []
        self.intervals = []
        self.waits = []
        self.interrupts = 0
        self.compactions = 0
        self.turn_ms = 0
        self.tool_start = {}
        self.tool_end = {}
        self.tools = collections.defaultdict(lambda: [0, 0.0])
        self.tokens = collections.Counter()
        self.models = collections.Counter()
        self.message_ids = set()
        self.subagents = []
        self.trace = None
        self.agent_type = self.description = None

    def touch(self, when_local, branch):
        local = when_local.strftime("%H:%M")
        day = when_local.strftime("%Y-%m-%d")
        self.stamps.append(when_local)
        if branch:
            self.branches.add(branch)
        self.first_at = self.first_at or local
        self.first_day = self.first_day or day
        self.last_at, self.last_day = local, day
        return local, day

    def busy(self, idle_gap):
        """Stretches where the agent was working, prompted or not.

        Every message and every tool call from its start to its result marks the
        session busy. A silence longer than `idle_gap` ends a stretch. Time spent
        waiting on a permission prompt is cut out: the agent was not working.
        """
        spans = [(when, when) for when in self.stamps] + list(self.intervals)
        return cut_spans(merge_spans(spans, idle_gap), self.waits)

    def tool_summary(self):
        calls = sum(count for count, _ in self.tools.values())
        seconds = sum(secs for _, secs in self.tools.values())
        top = sorted(self.tools.items(), key=lambda item: -item[1][1])[:6]
        return {"calls": calls, "seconds": round(seconds),
                "top": [[name, count, round(secs)] for name, (count, secs) in top]}

    def token_summary(self):
        if not self.tokens:
            return None
        return dict(self.tokens)

    def to_dict(self, cfg, max_chars, idle_gap):
        project = self.project_path or ""
        stretches = self.busy(idle_gap)
        return {
            "session": short_id(self.session_id),
            "session_id": self.session_id,
            "provider": self.provider,
            "entrypoint": self.entrypoint,
            "project": os.path.basename(project.rstrip("\\/")) or project,
            "project_path": project,
            "job_hint": _config.match_project(cfg, project),
            "date": self.first_day,
            "date_end": self.last_day,
            "first_at": self.first_at,
            "last_at": self.last_at,
            "branches": sorted(self.branches),
            "user_turns": self.user_turns,
            "interrupts": self.interrupts,
            "activity": span_rows(stretches),
            "busy_minutes": round(sum((b - a).total_seconds() for a, b in stretches) / 60, 1),
            "waiting_minutes": round(sum((b - a).total_seconds() for a, b in self.waits) / 60, 1),
            "tools": self.tool_summary() if self.tools else None,
            "tokens": self.token_summary(),
            "models": [name for name, _ in self.models.most_common()],
            "turn_seconds": round(self.turn_ms / 1000) if self.turn_ms else None,
            "compactions": self.compactions,
            "subagents": [agent.subagent_dict(idle_gap) for agent in self.subagents],
            "trace": self.trace,
            "closing_at": self.closing_at,
            "closing_text": (self.closing or "")[:max_chars],
        }

    def subagent_dict(self, idle_gap):
        stretches = self.busy(idle_gap)
        return {
            "agent_id": self.session_id,
            "agent_type": self.agent_type,
            "description": self.description,
            "models": [name for name, _ in self.models.most_common()],
            "first_at": self.first_at,
            "last_at": self.last_at,
            "activity": span_rows(stretches),
            "busy_minutes": round(sum((b - a).total_seconds() for a, b in stretches) / 60, 1),
            "tools": self.tool_summary() if self.tools else None,
            "tokens": self.token_summary(),
        }


def add_turn(session, kind, text, when_local, branch, max_chars, human=None):
    local, day = session.touch(when_local, branch)
    if text is None:
        return
    if kind == "user":
        if text.lstrip().startswith(INTERRUPT_PREFIX):
            session.interrupts += 1
            return
        body = strip_markup(text)
        if not is_noise(text, body, human):
            session.user_turns.append({"at": local, "date": day, "text": body[:max_chars]})
    elif kind == "assistant":
        body = text.strip()
        if body:
            session.closing, session.closing_at = body, local


# --- ccrider index -----------------------------------------------------------

ccrider_db = _config.ccrider_db


def ccrider_bin(cfg):
    name = cfg["sources"].get("ccrider_bin") or "ccrider"
    return name if os.path.exists(os.path.expanduser(name)) else shutil.which(name)


def ccrider_sync(cfg, db):
    binary = ccrider_bin(cfg)
    if not binary:
        return "skipped: ccrider binary not found"
    try:
        done = subprocess.run([os.path.expanduser(binary), "sync", "--db", db],
                              capture_output=True, text=True, timeout=600,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"failed: {exc}"
    tail = (done.stdout or done.stderr).strip().splitlines()
    return tail[-1] if tail else f"exit {done.returncode}"


def ccrider_stamp(text):
    # Stored as Go's time.String() in UTC, e.g. "2026-09-01 06:15:14.895 +0000 UTC".
    return dt.datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)


def from_ccrider(cfg, db, start_utc, end_utc, offset, providers, max_chars, skip=()):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    lo = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    hi = end_utc.strftime("%Y-%m-%d %H:%M:%S")
    sql = """
        SELECT s.session_id, s.provider, COALESCE(s.project_path, s.cwd, m.cwd),
               COALESCE(m.git_branch, s.git_branch), m.type, m.content,
               m.text_content, m.timestamp
        FROM messages m JOIN sessions s ON s.id = m.session_id
        WHERE m.timestamp >= ? AND m.timestamp < ?
          AND m.type IN ('user', 'assistant')
          AND COALESCE(m.is_sidechain, 0) = 0
    """
    params = [lo, hi]
    if providers:
        sql += " AND s.provider IN (%s)" % ",".join("?" * len(providers))
        params += providers
    if skip:
        sql += " AND s.provider NOT IN (%s)" % ",".join("?" * len(skip))
        params += list(skip)
    sql += " ORDER BY s.session_id, m.timestamp, m.sequence"

    sessions = {}
    for sid, provider, project, branch, kind, content, text_content, stamp in conn.execute(sql, params):
        try:
            when = ccrider_stamp(stamp)
        except (TypeError, ValueError):
            continue
        if not (start_utc <= when < end_utc):
            continue
        session = sessions.setdefault(sid, Session(sid, provider, project))
        text = text_content
        if content:
            try:
                message = json.loads(content)
            except ValueError:
                message = None
            if isinstance(message, dict) and "content" in message:
                text = blocks_text(message["content"], kind)
        add_turn(session, kind, text, when + offset, branch, max_chars)
    conn.close()
    return list(sessions.values())


# --- raw transcript files ----------------------------------------------------

def human_verdict(row):
    """Who wrote a user record, per the transcript: True, False or None (unknown)."""
    if row.get("isMeta"):
        return False
    origin = row.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin["kind"] == "human"
    source = row.get("promptSource")
    if source:
        return source in ("typed", "queued", "suggestion_accepted")
    return None


def read_transcript(path, session, start_utc, end_utc, offset, max_chars, sidechain_ok):
    """Fold one transcript file into `session`."""
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (row.get("isSidechain") and not sidechain_ok) or not row.get("timestamp"):
                continue
            kind = row.get("type")
            if kind not in ("user", "assistant", "system"):
                continue
            try:
                when = iso_stamp(row["timestamp"])
            except ValueError:
                continue
            if not (start_utc <= when < end_utc):
                continue
            local = when + offset
            session.project_path = session.project_path or row.get("cwd")
            session.entrypoint = session.entrypoint or row.get("entrypoint")
            message = row.get("message") or {}
            content = message.get("content")

            if kind == "system":
                session.touch(local, row.get("gitBranch"))
                if row.get("subtype") == "turn_duration":
                    session.turn_ms += int(row.get("durationMs") or 0)
                elif row.get("subtype") == "compact_boundary":
                    session.compactions += 1
                continue

            if kind == "assistant":
                message_id = message.get("id") or row.get("requestId")
                if message_id and message_id not in session.message_ids:
                    session.message_ids.add(message_id)
                    usage = message.get("usage") or {}
                    session.tokens["input"] += int(usage.get("input_tokens") or 0)
                    session.tokens["output"] += int(usage.get("output_tokens") or 0)
                    session.tokens["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                    session.tokens["cache_write"] += int(usage.get("cache_creation_input_tokens") or 0)
                    if message.get("model"):
                        session.models[message["model"]] += 1
                for block in content if isinstance(content, list) else ():
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        session.tool_start[block.get("id")] = (local, block.get("name") or "?")

            if kind == "user" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    tool_id = block.get("tool_use_id")
                    session.tool_end[tool_id] = local
                    if tool_id in session.tool_start:
                        began, name = session.tool_start.pop(tool_id)
                        session.tools[name][0] += 1
                        session.tools[name][1] += max((local - began).total_seconds(), 0)
                        session.intervals.append((began, local))

            text = blocks_text(content, kind)
            human = human_verdict(row) if kind == "user" else None
            add_turn(session, kind, text, local, row.get("gitBranch"), max_chars, human)


def read_subagents(folder, start_utc, end_utc, offset, max_chars):
    agents = []
    for path in sorted(glob.glob(os.path.join(folder, "agent-*.jsonl"))):
        agent_id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        agent = Session(agent_id, "claude", None)
        read_transcript(path, agent, start_utc, end_utc, offset, max_chars, sidechain_ok=True)
        if not agent.stamps:
            continue
        try:
            with open(path[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as handle:
                meta = json.load(handle)
            agent.agent_type, agent.description = meta.get("agentType"), meta.get("description")
        except (OSError, ValueError):
            pass
        agents.append(agent)
    return agents


def read_trace(cfg, session, start_utc, end_utc, offset):
    """Join the hook trace onto `session`: turn ends, permission waits, open/close."""
    folder = _config.trace_dir(cfg)
    path = os.path.join(folder, session.session_id + ".jsonl")
    if not os.path.exists(path):
        return
    events = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                when = iso_stamp(row["ts"])
            except (ValueError, KeyError):
                continue
            if start_utc <= when < end_utc:
                events.append((when + offset, row))
    if not events:
        return
    events.sort(key=lambda pair: pair[0])
    turns, opened, waits = [], None, []
    summary = {"prompts": 0, "turns_ended": 0, "permission_prompts": 0, "idle_prompts": 0,
               "opened_at": None, "closed_at": None, "close_reason": None}
    for index, (when, row) in enumerate(events):
        event = row.get("event")
        if event == "UserPromptSubmit":
            summary["prompts"] += 1
            opened = opened or when
        elif event in ("Stop", "StopFailure"):
            summary["turns_ended"] += 1
            if opened:
                turns.append((opened, when))
                opened = None
        elif event == "PermissionRequest":
            summary["permission_prompts"] += 1
            answered = session.tool_end.get(row.get("tool_use_id"))
            if answered is None:
                answered = next((later for later, _ in events[index + 1:]), None)
            if answered and answered > when:
                waits.append((when, answered))
        elif event == "Notification" and row.get("notification_type") == "idle_prompt":
            summary["idle_prompts"] += 1
        elif event == "SessionStart" and not summary["opened_at"]:
            summary["opened_at"] = when.strftime("%H:%M")
        elif event == "SessionEnd":
            summary["closed_at"] = when.strftime("%H:%M")
            summary["close_reason"] = row.get("reason")
    session.intervals.extend(turns)
    session.waits.extend(waits)
    summary["turns"] = span_rows(turns)
    session.trace = summary


def from_jsonl(cfg, start_utc, end_utc, offset, max_chars):
    root = _config.projects_root(cfg)
    found = []
    for path in glob.glob(os.path.join(root, "*", "*.jsonl")):
        # A file holding messages from the window cannot have been last written
        # before the window opened, so mtime is a safe, cheap prefilter.
        try:
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
        except OSError:
            continue
        if mtime < start_utc:
            continue
        session = Session(os.path.basename(path)[:-6], "claude", None)
        read_transcript(path, session, start_utc, end_utc, offset, max_chars, sidechain_ok=False)
        if not session.stamps:
            continue
        session.subagents = read_subagents(os.path.join(path[:-6], "subagents"),
                                           start_utc, end_utc, offset, max_chars)
        read_trace(cfg, session, start_utc, end_utc, offset)
        session.project_path = session.project_path or os.path.basename(os.path.dirname(path))
        found.append(session)
    return found


def main():
    global IGNORE_PREFIXES
    cfg = _config.load()
    # Prompts that scripted or hook-spawned sessions open with. A session left
    # with no human turns after filtering is dropped unless --all.
    IGNORE_PREFIXES = tuple(cfg["sources"].get("ignore_prompts") or ())
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="local date YYYY-MM-DD (default: today)")
    ap.add_argument("--days", type=int, default=1, help="number of days ending on --date")
    ap.add_argument("--tz", default=cfg["timezone"], help="local UTC offset, e.g. +02:00")
    ap.add_argument("--source", choices=("auto", "hybrid", "jsonl", "ccrider"),
                    default=cfg["sources"].get("sessions") or "auto")
    ap.add_argument("--no-sync", action="store_true", help="skip `ccrider sync`")
    ap.add_argument("--provider", action="append",
                    help="provider to keep (repeatable): claude, codex, pi, ...")
    ap.add_argument("--project", help="keep sessions whose project path contains this")
    ap.add_argument("--here", action="store_true", help="keep only the current directory's sessions")
    ap.add_argument("--max-chars", type=int, default=600)
    ap.add_argument("--idle-gap", type=int,
                    default=int(cfg["sources"].get("idle_gap_minutes") or 15),
                    help="minutes of silence that end a session's busy stretch")
    ap.add_argument("--all", action="store_true",
                    help="keep sessions with no human turns (headless, hook-spawned)")
    args = ap.parse_args()

    offset = parse_offset(args.tz)
    if args.date:
        end_day = dt.date.fromisoformat(args.date)
    else:
        end_day = (dt.datetime.now(dt.timezone.utc) + offset).date()
    start_day = end_day - dt.timedelta(days=args.days - 1)
    start_utc = dt.datetime.combine(start_day, dt.time.min, dt.timezone.utc) - offset
    end_utc = dt.datetime.combine(end_day + dt.timedelta(days=1), dt.time.min, dt.timezone.utc) - offset

    db = ccrider_db(cfg)
    source = args.source
    if source == "auto":
        source = "hybrid" if os.path.exists(db) else "jsonl"
    providers = args.provider or cfg["sources"].get("providers")

    notes = []
    if not cfg["_found"]:
        notes.append(f"no config at {cfg['_path']}, using defaults")
    sessions = []
    if source in ("ccrider", "hybrid"):
        if not os.path.exists(db):
            sys.exit(f"ccrider database not found at {db}")
        wants_others = not providers or any(p != "claude" for p in providers)
        if wants_others or source == "ccrider":
            if cfg["sources"].get("ccrider_sync", True) and not args.no_sync:
                notes.append("ccrider sync: " + ccrider_sync(cfg, db))
            skip = ("claude",) if source == "hybrid" else ()
            sessions += from_ccrider(cfg, db, start_utc, end_utc, offset, providers,
                                     args.max_chars, skip)
    if source in ("jsonl", "hybrid") and (not providers or "claude" in providers):
        sessions += from_jsonl(cfg, start_utc, end_utc, offset, args.max_chars)
    if source == "jsonl" and providers and providers != ["claude"]:
        notes.append("jsonl source only holds Claude Code sessions, other providers skipped")

    needle = os.getcwd() if args.here else args.project
    if needle:
        needle = needle.replace("\\", "/").lower()
        sessions = [s for s in sessions
                    if needle in (s.project_path or "").replace("\\", "/").lower()]

    idle_gap = dt.timedelta(minutes=args.idle_gap)
    kept = [s for s in sessions if s.user_turns or args.all]
    dropped = len(sessions) - len(kept)
    if dropped:
        notes.append(f"{dropped} session(s) with no human turns left out (use --all to keep)")
    out_sessions = [s.to_dict(cfg, args.max_chars, idle_gap) for s in kept]
    out_sessions.sort(key=lambda s: (s["date"] or "", s["first_at"] or ""))
    by_provider = collections.Counter(s["provider"] for s in out_sessions)
    traced = sum(1 for s in out_sessions if s.get("trace"))

    out = {
        "local_date_from": start_day.isoformat(),
        "local_date_to": end_day.isoformat(),
        "utc_offset": args.tz,
        "source": source,
        "config": cfg["_path"] if cfg["_found"] else None,
        "notes": notes,
        "sessions_with_activity": len(out_sessions),
        "sessions_with_trace": traced,
        "by_provider": dict(by_provider),
        "sessions": out_sessions,
    }
    # Windows consoles default to cp1252 and choke on arrows/dashes in transcripts.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
