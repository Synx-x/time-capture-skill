"""Print, or merge in, the settings block that installs the hook trace.

Hook commands cannot name a skill folder through a variable, so this script
writes the real paths for wherever the skill is installed: the Python running
this script and the absolute path of trace_hook.py next to it. Quoting follows
the OS, so paths with spaces work on Windows, macOS and Linux.

    python install_trace.py                    print the block
    python install_trace.py --settings FILE    merge it into FILE, after a .bak copy

Merging adds one entry per event and skips an event that already runs
trace_hook.py, so running it twice changes nothing.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

EVENTS = ("SessionStart", "SessionEnd", "UserPromptSubmit", "Stop", "PermissionRequest",
          "Notification", "SubagentStart", "SubagentStop", "PreCompact", "PostCompact")
MATCHER_EVENTS = {"PermissionRequest"}
HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace_hook.py")


def command():
    parts = [sys.executable, HOOK]
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return " ".join(shlex.quote(part) for part in parts)


def block():
    hook = {"type": "command", "async": True, "command": command()}
    hooks = {}
    for event in EVENTS:
        entry = {"hooks": [hook]}
        if event in MATCHER_EVENTS:
            entry = {"matcher": "*", **entry}
        hooks[event] = [entry]
    return {"hooks": hooks}


def merge(path):
    settings = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            settings = json.load(handle)
        shutil.copyfile(path, path + ".bak")
    current = settings.setdefault("hooks", {})
    added = []
    for event, entries in block()["hooks"].items():
        existing = current.setdefault(event, [])
        if "trace_hook.py" in json.dumps(existing):
            continue
        existing.extend(entries)
        added.append(event)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", help="settings file to merge the block into")
    args = ap.parse_args()
    if not args.settings:
        print(json.dumps(block(), indent=2))
        return
    added = merge(os.path.expanduser(args.settings))
    print(f"added {len(added)} events to {args.settings}" if added
          else f"{args.settings} already runs the trace on every event")


if __name__ == "__main__":
    main()
