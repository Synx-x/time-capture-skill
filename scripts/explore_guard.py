"""Block every write to the timesheet while explore mode is on.

Exploring the timesheet (opening old entries with Edit, walking the calendar back,
opening dropdowns to list their options) must never save, delete or change a row.
This PreToolUse hook enforces that for the browser tools while the flag file
exists:

  <state dir>/explore.json   (or $TIME_CAPTURE_EXPLORE_FLAG, state dir per _config.py)

    {"viewport": [1834, 940],
     "forbidden": [{"name": "Save", "css": [886, 277, 945, 304]}, ...]}

`css` is [left, top, right, bottom] in page pixels, read with a read-only
getBoundingClientRect pass before the first click. Clicks arrive in the frame of
the latest screenshot, which is the viewport scaled down evenly, so the hook
scales each rect by frame width over viewport width. An entry may carry `rect`
(already in frame coordinates) instead, which is only valid for `frame`.

While the flag exists the hook denies:
  - a click, double-click or triple-click whose point falls in a forbidden rect
    (with a small margin), directly or inside browser_batch
  - form_input, which sets values without real input
  - javascript_tool text that writes: .value(, .trigger(, .click(, dispatchEvent,
    submit, ajax, fetch with a method, .checked =, .val(
Everything else passes. Delete the flag file to leave explore mode.

Clicks land in the frame of the latest screenshot, and that frame changes size
when the window or page layout does. On PostToolUse the hook reads the frame from
each screenshot result into explore-frame.json. A click is denied while the
flag's `frame` differs from it, until the explorer re-records the rects.

Reads the PreToolUse or PostToolUse payload on stdin. Prints a deny decision or
nothing.
"""

import json
import os
import re
import sys

MARGIN = 6
CLICKS = {"left_click", "double_click", "triple_click", "right_click"}
JS_WRITES = re.compile(
    r"\.value\s*\(\s*[^)\s]|\.trigger\s*\(|\.click\s*\(|dispatchEvent|\.submit\s*\(|"
    r"ajax|method\s*:\s*['\"](post|put|delete|patch)|\.checked\s*=|\.val\s*\(\s*[^)\s]|"
    r"\.select\s*\(\s*\d|\.text\s*\(\s*['\"]",
    re.I)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config import state_dir  # noqa: E402


def flag_path():
    configured = os.environ.get("TIME_CAPTURE_EXPLORE_FLAG")
    return os.path.expanduser(configured) if configured else os.path.join(
        state_dir(), "explore.json")


FRAME_RE = re.compile(r"coordinate frame: (\d+)x(\d+)")


def frame_path():
    return os.path.join(os.path.dirname(flag_path()), "explore-frame.json")


def last_frame():
    try:
        with open(frame_path(), encoding="utf-8") as handle:
            return json.load(handle).get("frame")
    except (OSError, ValueError):
        return None


def record_frame(payload):
    found = FRAME_RE.findall(json.dumps(payload.get("tool_response") or ""))
    if found:
        with open(frame_path(), "w", encoding="utf-8") as handle:
            json.dump({"frame": [int(found[-1][0]), int(found[-1][1])]}, handle)


def load_flag():
    path = flag_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"forbidden": [], "broken": True}


def hit(point, rect):
    x, y = point
    left, top, right, bottom = rect
    return left - MARGIN <= x <= right + MARGIN and top - MARGIN <= y <= bottom + MARGIN


def frame_rect(target, flag, seen):
    """A forbidden area in the current screenshot frame."""
    if "css" in target and flag.get("viewport") and seen:
        scale = seen[0] / flag["viewport"][0]
        return [round(value * scale) for value in target["css"]]
    return target.get("rect")


def check_action(name, params, flag):
    """Reason to deny one browser action, or None."""
    short = name.rsplit("__", 1)[-1]
    if short == "form_input":
        return "form_input sets values directly, and explore mode allows no writes"
    if short == "javascript_tool":
        text = params.get("text") or ""
        found = JS_WRITES.search(text)
        if found:
            return f"javascript_tool text writes to the page (`{found.group(0)}`)"
        return None
    if short == "computer" and params.get("action") == "key":
        if re.search(r"\b(Delete|ctrl\+s|cmd\+s)\b", params.get("text") or "", re.I):
            return f"key `{params.get('text')}` can delete or save"
        return None
    if short == "computer" and params.get("action") in CLICKS:
        point = params.get("coordinate")
        if not point or len(point) != 2:
            return None
        seen = last_frame()
        fixed = any("rect" in target for target in flag.get("forbidden") or [])
        if fixed and seen and flag.get("frame") and list(flag["frame"]) != list(seen):
            return (f"the screenshot frame is now {seen[0]}x{seen[1]} but the forbidden "
                    f"rects were recorded for {flag['frame'][0]}x{flag['frame'][1]}. "
                    "Re-record them before clicking")
        for target in flag.get("forbidden") or []:
            if hit(point, frame_rect(target, flag, seen) or [0, 0, -1, -1]):
                return f"click at {point} lands on {target.get('name')}"
    return None


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return
    flag = load_flag()
    if flag is None:
        return
    if payload.get("hook_event_name") == "PostToolUse":
        record_frame(payload)
        return
    tool = payload.get("tool_name") or ""
    params = payload.get("tool_input") or {}
    if tool.endswith("browser_batch"):
        actions = [(item.get("name") or "", item.get("input") or {})
                   for item in params.get("actions") or []]
    else:
        actions = [(tool, params)]
    for name, action in actions:
        reason = check_action(name, action, flag)
        if reason:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "time-capture explore mode: " + reason + ". Exploring never saves or "
                    "changes a row. Delete " + flag_path() + " to leave explore mode."),
            }}))
            return


if __name__ == "__main__":
    main()
