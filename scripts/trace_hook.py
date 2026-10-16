"""Append one timing record per Claude Code lifecycle event to a per-session trace.

The session transcript already stamps every message to the millisecond, so this
hook records only what the transcript cannot tell apart:

  UserPromptSubmit   the prompts a person typed, as opposed to hook, tool and
                     task-notification text that also lands in the user slot
  Stop               the exact end of each turn (the transcript has no marker)
  PermissionRequest  when the agent stopped to wait for approval
  Notification       idle and permission prompts, meaning time spent waiting on you
  SubagentStart/Stop the span and type of every subagent
  PreCompact/PostCompact, SessionStart, SessionEnd  session lifecycle

Hook payloads carry no timestamp, so the hook stamps its own. Each record keeps
the keys that join back to the transcript: `prompt_id` matches a user record's
`promptId`, `tool_use_id` a tool_use block's `id`, `agent_id` the file
`<session>/subagents/agent-<agent_id>.jsonl`.

No prompt text, tool input or assistant output is stored. The transcript holds
those already.

Writes to $TIME_CAPTURE_TRACE_DIR, else <state dir>/trace (see _config.py), one
file per session: <session_id>.jsonl. Always exits 0 and prints nothing, so a
broken trace never blocks a turn. It reads no config file, so it stays fast.

Run it as a command hook on each event above, with the payload on stdin.
`install_trace.py` prints the settings block with this file's real path.
"""

import datetime as dt
import json
import os
import sys

KEEP = (
    "prompt_id", "agent_id", "agent_type", "tool_use_id", "tool_name",
    "source", "reason", "trigger", "notification_type", "permission_mode",
    "stop_hook_active", "cwd",
)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config import trace_dir  # noqa: E402


def record(payload):
    event = payload.get("hook_event_name")
    session = payload.get("session_id")
    if not event or not session:
        return None
    row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
           "event": event}
    row.update({key: payload[key] for key in KEEP if payload.get(key) not in (None, "")})
    return session, row


def main():
    try:
        made = record(json.loads(sys.stdin.read() or "{}"))
        if not made:
            return
        session, row = made
        folder = trace_dir()
        os.makedirs(folder, exist_ok=True)
        safe = "".join(ch for ch in session if ch.isalnum() or ch in "-_")
        with open(os.path.join(folder, safe + ".jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - a trace must never break the session
        pass


if __name__ == "__main__":
    main()
