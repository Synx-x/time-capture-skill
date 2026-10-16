"""Load the user's timeline config and match session paths to jobs.

The config and all state (trace, pending tables, explore flag) live outside the
skill folder, so a skill upgrade never wipes them. Every path resolves here, so
the skill works from any install location and on any OS:

  state_dir()    $TIME_CAPTURE_HOME, else $XDG_CONFIG_HOME/time-capture,
                 else ~/.config/time-capture
  config_path()  $TIME_CAPTURE_CONFIG, else <state_dir>/config.json
  claude_home()  $CLAUDE_CONFIG_DIR, else ~/.claude

Missing keys fall back to DEFAULTS, so a missing or partial file still works.
"""

import copy
import json
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env_path(name):
    value = os.environ.get(name)
    return os.path.normpath(os.path.expanduser(value)) if value else None


def state_dir():
    xdg = _env_path("XDG_CONFIG_HOME")
    return (_env_path("TIME_CAPTURE_HOME")
            or (os.path.join(xdg, "time-capture") if xdg else None)
            or os.path.join(os.path.expanduser("~"), ".config", "time-capture"))


def claude_home():
    return _env_path("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def resolve(path, default):
    """Expand a configured path, or fall back to `default` when it is unset."""
    return os.path.normpath(os.path.expanduser(path)) if path else default

DEFAULTS = {
    "timezone": "+02:00",
    "workday": {
        "start": "08:00",
        "end": "17:00",
        "expected_hours": 8,
        "fixed_blocks": [{"label": "Lunch", "span": "12:30-13:00", "category": "Lunch"}],
    },
    "sources": {
        "sessions": "auto",
        "ccrider_bin": "ccrider",
        "ccrider_db": None,
        "ccrider_sync": True,
        "providers": None,
        "claude_projects_root": None,
        "ignore_prompts": [],
        "idle_gap_minutes": 15,
        "trace_dir": None,
    },
    "work_tracker": {"kind": None, "org": None},
    "timesheet": {"system": None, "url": None, "fill": "confirm"},
    "projects": [],
}


def config_path():
    return _env_path("TIME_CAPTURE_CONFIG") or os.path.join(state_dir(), "config.json")


def trace_dir(cfg=None):
    configured = (cfg or {}).get("sources", {}).get("trace_dir")
    return _env_path("TIME_CAPTURE_TRACE_DIR") or resolve(
        configured, os.path.join(state_dir(), "trace"))


def projects_root(cfg):
    return resolve(cfg["sources"].get("claude_projects_root"),
                   os.path.join(claude_home(), "projects"))


def ccrider_db(cfg):
    return resolve(cfg["sources"].get("ccrider_db"),
                   os.path.join(os.path.expanduser("~"), ".config", "ccrider", "sessions.db"))


def _merge(base, over):
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load():
    cfg = copy.deepcopy(DEFAULTS)
    path = config_path()
    cfg["_path"] = path
    cfg["_found"] = os.path.exists(path)
    if cfg["_found"]:
        with open(path, encoding="utf-8") as handle:
            _merge(cfg, json.load(handle))
    return cfg


def match_project(cfg, path):
    """Return the first `projects` entry whose match string is in `path`.

    Entries are tried in file order, so list the specific ones (BMP.AWE) before
    the broad ones (PMCK).
    """
    if not path:
        return None
    haystack = path.replace("\\", "/").lower()
    for entry in cfg.get("projects", []):
        needles = entry.get("match") or []
        if isinstance(needles, str):
            needles = [needles]
        if any(n.lower() in haystack for n in needles):
            return {k: v for k, v in entry.items() if k != "match"}
    return None


if __name__ == "__main__":
    loaded = load()
    for name, value in (("skill", SKILL_DIR), ("state", state_dir()), ("config", config_path()),
                        ("config found", loaded["_found"]), ("trace", trace_dir(loaded)),
                        ("transcripts", projects_root(loaded)), ("ccrider db", ccrider_db(loaded))):
        print(f"{name:13} {value}")
