"""Report agent effort for a day: how long every session and subagent worked.

Effort is not the timesheet. Parallel sessions each count their own busy time,
so effort hours run past the wall clock. The ratio between the two is the
parallelism: how many agents were working at once, on average, while any was.

Runs extract_sessions.py and build_blocks.py, joins their output, and prints a
Markdown report (or the joined JSON with --json). Sessions with no human turns
(headless runs, hook-spawned agents) are kept, because they are agent effort
too, and marked as such.

Usage:
    python effort.py [--date YYYY-MM-DD] [--days N] [--project SUBSTR]
                     [--provider NAME ...] [--no-sync] [--idle-gap MIN]
                     [--human-only] [--json]
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script, args, stdin=None):
    done = subprocess.run([sys.executable, os.path.join(HERE, script)] + args,
                          input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if done.returncode != 0:
        sys.exit(f"{script} failed: {done.stderr.strip()[-400:]}")
    return done.stdout


def hours(value):
    return f"{value:.1f}" if value else "0"


def thousands(value):
    if not value:
        return "-"
    return f"{value / 1000:.0f}k" if value >= 1000 else str(value)


def concurrency(day):
    """Per hour: the most sessions busy in any one 15-minute slot."""
    by_hour = {}
    for slot in day["slots"]:
        hour = slot["start"][:2]
        by_hour[hour] = max(by_hour.get(hour, 0), len(slot["sessions"]))
    return [(hour, count) for hour, count in sorted(by_hour.items()) if count]


def render(day, extracted):
    lookup = {s["session"]: s for s in extracted["sessions"]}
    effort = day["effort"]
    title = dt.date.fromisoformat(day["date"]).strftime("%A %d %B %Y")
    lines = [
        f"# Effort, {title}",
        "",
        f"**{hours(effort['agent_hours'])} agent-hours** "
        f"({hours(effort['session_hours'])} in sessions, "
        f"{hours(effort['subagent_hours'])} in subagents) across "
        f"**{hours(effort['wall_clock_hours'])} wall-clock hours**. "
        f"Parallelism {effort['parallelism']} (session-hours over wall clock).",
    ]
    if effort.get("waiting_minutes"):
        lines.append(f"Waiting on you at permission prompts: {effort['waiting_minutes']:.0f} min.")
    lines += [
        "",
        "| Session | Agent | Project | Job | Busy | Effort h | Subagents h | Tool min "
        "| Output tokens | Your turns |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for span in sorted(day["sessions"], key=lambda s: -s["effort_hours"]):
        info = lookup.get(span["session"], {})
        turns = len(info.get("user_turns") or [])
        agent = span["provider"]
        if info.get("entrypoint") and info["entrypoint"] != "cli":
            agent += f" ({info['entrypoint']})"
        lines.append(
            f"| {span['session']} | {agent} | {span['project']} | {span['job_hint'] or '-'} "
            f"| {span['busy_from']}-{span['busy_to']} | {hours(span['effort_hours'])} "
            f"| {hours(span['subagent_hours'])} | {span['tool_minutes']:.0f} "
            f"| {thousands((span.get('tokens') or {}).get('output'))} "
            f"| {turns or 'none'} |")
    strip = concurrency(day)
    if strip:
        lines += ["", "Sessions busy at once, peak per hour: " +
                  "  ".join(f"{hour}h {count}" for hour, count in strip)]
    claude = [s for s in extracted["sessions"] if s["provider"] == "claude"]
    untraced = [s for s in claude if not s.get("trace")]
    if untraced:
        lines += ["", f"{len(untraced)} of {len(claude)} `claude` sessions have no hook trace, "
                      "so their turn ends and permission waits come from the transcript alone."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--days", type=int)
    ap.add_argument("--project")
    ap.add_argument("--provider", action="append")
    ap.add_argument("--no-sync", action="store_true")
    ap.add_argument("--idle-gap", type=int)
    ap.add_argument("--tz")
    ap.add_argument("--human-only", action="store_true",
                    help="leave out sessions with no human turns")
    ap.add_argument("--json", action="store_true", help="print the joined data, not Markdown")
    args = ap.parse_args()

    passthrough = []
    for flag in ("date", "days", "project", "idle_gap", "tz"):
        value = getattr(args, flag)
        if value is not None:
            passthrough += ["--" + flag.replace("_", "-"), str(value)]
    for name in args.provider or []:
        passthrough += ["--provider", name]
    if args.no_sync:
        passthrough.append("--no-sync")
    if not args.human_only:
        passthrough.append("--all")

    extracted_raw = run("extract_sessions.py", passthrough)
    blocks = json.loads(run("build_blocks.py", ["--no-fixed"], stdin=extracted_raw))
    extracted = json.loads(extracted_raw)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.json:
        json.dump({"extracted": extracted, "blocks": blocks}, sys.stdout, indent=1,
                  ensure_ascii=False)
        return
    reports = [render(day, extracted) for day in blocks["days"]]
    print("\n\n".join(reports) if reports else "No agent activity in that window.")
    for note in extracted.get("notes") or []:
        print(f"\n_{note}_")


if __name__ == "__main__":
    main()
