"""Turn extracted sessions into a 15-minute slot grid for timesheet capture.

Reads the JSON produced by extract_sessions.py and emits, per day, one row per
15-minute slot naming which sessions were active in it. Sessions overlap
constantly (a long thread runs while short ones interleave) and a timesheet
cannot double-book a slot. So the grid is the honest primitive: it says what was
in flight at each moment and leaves the apportioning to judgement.

Fixed personal blocks (lunch, breaks) come from the config's workday block.
Entries already in the timesheet can be passed with --existing and are marked
CAPTURED, so only the missing slots need proposing. Slots with no evidence are
marked GAP so they get filled deliberately rather than silently.

Teams, Outlook and calendar items can be passed with --context. A meeting
occupies its slots, so a slot with no session but a meeting is MEETING, not GAP.
A point item (a request, a status, a commitment) lands in the slot it was sent in.

A `call` item is a PM or lead asking the user to join a scrum or a call, with no
end time. Its length comes from the user's absence: the first silence of at least
--min-away minutes in the user's own prompts, starting within --call-search
minutes of the message, is the call. Agent minutes inside that silence are
reported as unattended. The call then fills its slots like a meeting.

A session occupies the slots its busy stretches (the extractor's `activity`)
touch. Subagent stretches are counted apart, as `subagent_hours`, so effort
shows the main thread and the helpers it spawned separately.

Usage:
    python extract_sessions.py --days 5 | python build_blocks.py
        [--expected-hours 8] [--fixed Lunch=12:30-13:00 ...] [--no-fixed]
        [--day-start 08:00] [--day-end 17:00] [--existing captured.json]
        [--context m365.json]

--existing takes a JSON list of {"date": "YYYY-MM-DD", "start": "HH:MM",
"end": "HH:MM", "label": "..."}. A row without "date" applies to every day.

--context takes a JSON list of {"date", "start", "end" (meetings only), "source"
(calendar, mail or teams), "kind" (meeting, call, request, status, commitment or
handover), "who", "subject", "category_hint", "job_hint", "from_me"}. The hints are
optional. An item with "from_me": true marks the user as present at that minute.
"""

import argparse
import datetime as dt
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _config  # noqa: E402

SLOT = 15


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def floor_slot(minutes):
    return minutes - (minutes % SLOT)


def ceil_slot(minutes):
    return minutes if minutes % SLOT == 0 else minutes + (SLOT - minutes % SLOT)


def slot_hours(n):
    return round(n * SLOT / 60, 2)


def parse_span(text):
    start, end = text.split("-")
    return to_min(start.strip()), to_min(end.strip())


def fixed_blocks(cfg, args):
    if args.no_fixed:
        return {}
    if args.fixed:
        pairs = [item.split("=", 1) for item in args.fixed]
    else:
        pairs = [(b["label"], b["span"]) for b in cfg["workday"].get("fixed_blocks") or []]
    return {label: parse_span(span) for label, span in pairs
            if span and span.lower() != "none"}


def busy_slots(day, activity):
    """Slots on `day` covered by a list of activity stretches."""
    slots = set()
    for stretch in activity or []:
        if stretch["date"] != day:
            continue
        start = floor_slot(to_min(stretch["start"]))
        end = max(ceil_slot(to_min(stretch["end"])), start + SLOT)
        slots.update(range(start, end, SLOT))
    return slots


def busy_minutes(day, activity):
    """Minutes of `day` covered by activity stretches. A lone message counts one minute."""
    minutes = set()
    for stretch in activity or []:
        if stretch["date"] == day:
            start = to_min(stretch["start"])
            minutes.update(range(start, max(to_min(stretch["end"]), start + 1)))
    return minutes


def presence(day, sessions, context):
    """Minutes on `day` when the user was demonstrably at the keyboard."""
    points = {to_min(t["at"]) for s in sessions for t in s["user_turns"] if t["date"] == day}
    points |= {to_min(r["start"]) for r in context
               if r.get("date") == day and r.get("from_me") and r.get("start")}
    return sorted(points)


def agent_minutes(day, sessions, start, end):
    """Minutes in [start, end) when any agent session was busy."""
    busy = set()
    for session in sessions:
        busy |= busy_minutes(day, session.get("activity"))
    return len([m for m in busy if start <= m < end])


def resolve_calls(day, sessions, context, min_away, search, cap):
    """Give each `call` item on `day` a start and end from the user's first absence after it."""
    here = presence(day, sessions, context)
    for row in context:
        if row.get("date") != day or row.get("kind") != "call" or row.get("end"):
            continue
        sent = to_min(row["start"])
        later = [m for m in here if m > sent]
        before = [m for m in here if m <= sent]
        marks = ([before[-1]] if before else []) + later
        gap = next(((a, b) for a, b in zip(marks, marks[1:])
                    if b - a >= min_away and sent - 2 <= a <= sent + search), None)
        if gap is None and later and later[-1] <= sent + search:
            gap = (later[-1], later[-1] + cap)
        if gap is None:
            row["estimate"] = {"found": False, "searched_until": to_hhmm(sent + search)}
            continue
        away_from, back_at = max(gap[0], sent), gap[1]
        length = min(back_at - away_from, cap)
        start = floor_slot(away_from)
        end = max(start + SLOT, start + round(length / SLOT) * SLOT)
        row.update({"start": to_hhmm(start), "end": to_hhmm(end), "kind": "meeting", "estimate": {
            "found": True, "message_at": to_hhmm(sent), "away_from": to_hhmm(away_from),
            "back_at": to_hhmm(back_at), "away_minutes": back_at - away_from,
            "capped": back_at - away_from > cap,
            "unattended_agent_minutes": agent_minutes(day, sessions, away_from, back_at)}})


def context_items(day, context):
    """`context` rows for `day`, each with the slots it covers."""
    items = []
    for row in context:
        if row.get("date") != day or not row.get("start"):
            continue
        start = to_min(row["start"])
        end = to_min(row["end"]) if row.get("end") else None
        covers = (set(range(floor_slot(start), max(ceil_slot(end), floor_slot(start) + SLOT), SLOT))
                  if end and row.get("kind") == "meeting" else {floor_slot(start)})
        items.append({**row, "_slots": covers, "_meeting": bool(end) and row.get("kind") == "meeting"})
    return items


def session_spans(day, sessions):
    """Per session on `day`: the prompted span and the slots its agent was busy in.

    The prompted span runs from the first to the last user turn. Busy slots come
    from the extractor's `activity` stretches, so an agent working unprompted
    still counts.
    """
    spans = []
    for session in sessions:
        times = sorted(to_min(t["at"]) for t in session["user_turns"] if t["date"] == day)
        busy = set()
        busy.update(busy_slots(day, session.get("activity")))
        minutes = busy_minutes(day, session.get("activity"))
        agent_minutes = [busy_minutes(day, agent.get("activity"))
                         for agent in session.get("subagents") or []]
        if not times and not busy:
            continue
        info = {
            "session": session["session"],
            "provider": session.get("provider", "claude"),
            "project": session["project"],
            "job_hint": (session.get("job_hint") or {}).get("job"),
            "branches": session["branches"],
            "prompted_from": None,
            "prompted_to": None,
            "busy": busy,
            "minutes": minutes,
            "agent_minutes": sum(len(spent) for spent in agent_minutes),
            "subagents": sum(1 for spent in agent_minutes if spent),
            "waiting_minutes": session.get("waiting_minutes") or 0,
            "tool_minutes": round(((session.get("tools") or {}).get("seconds") or 0) / 60, 1),
            "tokens": session.get("tokens"),
        }
        if times:
            info["prompted_from"] = floor_slot(times[0])
            info["prompted_to"] = max(ceil_slot(times[-1]), floor_slot(times[0]) + SLOT)
        if not busy:
            busy.update(range(info["prompted_from"], info["prompted_to"], SLOT))
        spans.append(info)
    return spans


def main():
    cfg = _config.load()
    work = cfg["workday"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected-hours", type=float, default=float(work.get("expected_hours", 8)))
    ap.add_argument("--fixed", action="append",
                    help="Label=HH:MM-HH:MM, repeatable; replaces the config's fixed blocks")
    ap.add_argument("--no-fixed", action="store_true", help="no fixed blocks at all")
    ap.add_argument("--day-start", default=work.get("start"),
                    help="grid starts no later than this (config workday.start)")
    ap.add_argument("--day-end", default=work.get("end"))
    ap.add_argument("--existing", help="JSON file of entries already in the timesheet")
    ap.add_argument("--context", help="JSON file of Teams, Outlook and calendar items")
    ap.add_argument("--min-away", type=int, default=10,
                    help="silence in the user's prompts that counts as away on a call")
    ap.add_argument("--call-search", type=int, default=30,
                    help="minutes after a call message to look for the user leaving")
    ap.add_argument("--call-cap", type=int, default=60, help="longest a call can be estimated")
    ap.add_argument("--input", default="-")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    data = json.loads(raw)
    fixed = fixed_blocks(cfg, args)

    existing = []
    if args.existing:
        with open(args.existing, encoding="utf-8") as handle:
            existing = json.load(handle)

    context = []
    if args.context:
        with open(args.context, encoding="utf-8") as handle:
            context = json.load(handle)

    sessions = data.get("sessions", [])
    day_set = {t["date"] for s in sessions for t in s["user_turns"]}
    day_set |= {a["date"] for s in sessions for a in s.get("activity") or []}
    day_set |= {r["date"] for r in existing if r.get("date")}
    day_set |= {r["date"] for r in context if r.get("date")}
    by_day = OrderedDict((day, sessions) for day in sorted(day_set))

    days = []
    for day, day_sessions in by_day.items():
        spans = session_spans(day, day_sessions)
        captured = [(to_min(r["start"]), to_min(r["end"]), r.get("label", "captured"))
                    for r in existing if r.get("date") in (None, day)]
        resolve_calls(day, day_sessions, context, args.min_away, args.call_search, args.call_cap)
        items = context_items(day, context)
        if not spans and not captured and not items:
            continue

        bounds = [(min(s["busy"]), max(s["busy"]) + SLOT) for s in spans]
        bounds += [(a, b) for a, b, _ in captured]
        bounds += list(fixed.values())
        bounds += [(min(i["_slots"]), max(i["_slots"]) + SLOT) for i in items if i["_meeting"]]
        grid_start = floor_slot(min(a for a, _ in bounds))
        grid_end = ceil_slot(max(b for _, b in bounds))
        if args.day_start:
            grid_start = min(grid_start, to_min(args.day_start))
        if args.day_end:
            grid_end = max(grid_end, to_min(args.day_end))

        slots = []
        for point in range(grid_start, grid_end, SLOT):
            here = [s["session"] for s in spans if point in s["busy"]]
            prompted = [s["session"] for s in spans if s["prompted_from"] is not None
                        and s["prompted_from"] <= point < s["prompted_to"]]
            label = next((n for n, (a, b) in fixed.items() if a <= point < b), None)
            done = next((lab for a, b, lab in captured if a <= point < b), None)
            meetings = [i["subject"] for i in items if i["_meeting"] and point in i["_slots"]]
            notes = [f'{i.get("source")} {i.get("kind")}: {i.get("who") or "?"}, {i.get("subject")}'
                     for i in items if not i["_meeting"] and point in i["_slots"]]
            if done:
                state = "CAPTURED"
            elif label:
                state = label
            elif not here and meetings:
                state = "MEETING"
            elif not here:
                state = "GAP"
            else:
                state = "OVERLAP" if len(here) > 1 else "WORK"
            slots.append({
                "start": to_hhmm(point),
                "end": to_hhmm(point + SLOT),
                "fixed": label,
                "captured": done,
                "sessions": here,
                "prompted": prompted,
                "meetings": meetings,
                "context": notes,
                "state": state,
            })

        states = [s["state"] for s in slots]
        done_n = states.count("CAPTURED")
        evidenced = states.count("WORK") + states.count("OVERLAP") + states.count("MEETING")
        fixed_n = sum(1 for s in slots if s["fixed"] and not s["captured"])
        # Effort counts each session's (and subagent's) busy minutes apart, so it sums past
        # wall-clock time. Only the timesheet view, `slots`, collapses to one row per slot.
        effort, agent_effort, wall_minutes = [], [], set()
        for span in spans:
            busy = sorted(span.pop("busy"))
            minutes = span.pop("minutes")
            wall_minutes |= minutes
            span["busy_from"], span["busy_to"] = to_hhmm(busy[0]), to_hhmm(busy[-1] + SLOT)
            span["effort_hours"] = round(len(minutes) / 60, 2)
            span["slot_hours"] = slot_hours(len(busy))
            span["subagent_hours"] = round(span.pop("agent_minutes") / 60, 2)
            agent_effort.append(span["subagent_hours"])
            for key in ("prompted_from", "prompted_to"):
                if span[key] is not None:
                    span[key] = to_hhmm(span[key])
            effort.append(span["effort_hours"])
        wall = len(wall_minutes) / 60
        days.append({
            "date": day,
            "weekday": dt.date.fromisoformat(day).strftime("%A"),
            "grid": {"from": to_hhmm(grid_start), "to": to_hhmm(grid_end)},
            "sessions": spans,
            "effort": {
                "session_hours": round(sum(effort), 2),
                "subagent_hours": round(sum(agent_effort), 2),
                "agent_hours": round(sum(effort) + sum(agent_effort), 2),
                "wall_clock_hours": round(wall, 2),
                "parallelism": round(sum(effort) / wall, 2) if wall else 0,
                "waiting_minutes": round(sum(s["waiting_minutes"] for s in spans), 1),
            },
            "slots": slots,
            "context": [{k: v for k, v in i.items() if not k.startswith("_")} for i in items],
            "hours": {
                "captured": slot_hours(done_n),
                "evidenced": slot_hours(evidenced),
                "fixed": slot_hours(fixed_n),
                "meeting": slot_hours(states.count("MEETING")),
                "gap": slot_hours(states.count("GAP")),
                "expected": args.expected_hours,
                "shortfall": round(args.expected_hours - slot_hours(done_n + evidenced + fixed_n), 2),
            },
        })

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    json.dump({"days": days}, sys.stdout, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
