<!-- plain: off -->
# time-capture

A timesheet and effort tracker for people who work through AI coding agents. It reads the
sessions your agents already recorded, rebuilds your day in 15-minute blocks, and fills your
timesheet once you approve the table. It also tells you how much your agents actually worked.

> Quick start: `npx skills add https://github.com/Synx-x/time-capture-skill -g -y`, or copy
> this folder into your skills folder (user level is `skills/time-capture`
> under your `claude` home, `~/.claude` unless `CLAUDE_CONFIG_DIR` moves it). Copy
> `config.example.json` to `config.json` in the state folder (below), then type `/time-capture`.
> You can also just ask "fill in my timesheet for today" and it starts on its own.

## Why this skill

The work that falls off a timesheet is the small stuff: the twenty-minute investigation for a
colleague, the PR review, the merge conflict at 4pm. Your agent sessions saw all of it, with
timestamps to the millisecond. This skill turns that history into entries you can check and
save, instead of reconstructing the day from memory on Friday.

It also answers a question a timesheet can't: when three agents ran at once, how much work got
done? That's the effort report.

## What's included

### The commands

| Command | What it does |
|---------|--------------|
| `/time-capture` | Builds today's timesheet table, asks once, then fills it in |
| `/time-capture yesterday`, `/time-capture 2026-09-29`, `/time-capture this week` | The same for another day or a range |
| `/time-capture effort` | Agent-hours against wall-clock hours, per session and subagent |
| `/time-capture fill` | Saves a table you already approved |
| `/time-capture standup` | A short written summary instead of a table |

Add a project name to any of them (`/time-capture effort PMCK`) to narrow it down.

### Where the evidence comes from

| Source | What it adds |
|--------|--------------|
| `claude` session transcripts | Every message, tool call and subagent, stamped to the millisecond, and who wrote each prompt |
| [ccrider](https://github.com/neilberkman/ccrider) | Sessions from `codex`, `copilot`, `opencode`, `pi`, `antigravity` and `amp` |
| git | What actually got committed, per repo |
| Azure DevOps | Real work item titles and IDs |
| Teams, Outlook mail and calendar, if connected | Meetings, calls and the requests behind the work, read for the whole period and used to pick each row's job and category |
| Your PMs, from the timesheet's PM list | Who runs which job, so a PM's "quick call?" becomes a scrum row sized by how long you were away from the keyboard |
| The optional hook trace | When each turn ended, time spent waiting on you, when a session closed |

### What the skill guarantees

- It never makes up a block to reach eight hours. Unexplained time goes on a "needs your input"
  list.
- It writes `UNKNOWN` instead of guessing a task number, so hours never land on the wrong job.
- It asks about anything ambiguous in a question prompt with ready-made answers, instead of
  guessing. Saving needs your yes, and a changed table needs a new one.
- It fills the timesheet by clicking and typing like you would, and checks each save landed.
- It never edits, copies or deletes a row you already captured, unless you ask for that change.
- Effort numbers are reported as measured, even when they add up to more hours than the day had.

## Usage

```
/time-capture
fill in my timesheet for yesterday
what did I get done this week? write it up for my one-on-one
/time-capture effort
how parallel was I today?
```

It shows the effort table first, then the timesheet table, then a short list of questions.
Answer them in one message and it reissues the whole table.

## Setup

1. Copy `config.example.json` to `config.json` in the state folder and fill in your timezone,
   workday, tracker and timesheet URL. The first run offers to build the `projects` list (which
   repo maps to which job) from your live job list, and asks you to confirm it.
2. Optional: install the hook trace for exact turn ends and permission waits. Run
   `python scripts/install_trace.py` for the settings block. See `references/trace.md`.

### Paths

Nothing in the skill assumes an install location or an OS. `scripts/_config.py` resolves every
path, and `python scripts/_config.py` prints them.

| What | Where |
|---|---|
| State folder (config, `trace/`, `pending/`, explore flag) | `$TIME_CAPTURE_HOME`, else `$XDG_CONFIG_HOME/time-capture`, else `~/.config/time-capture` |
| Config file | `$TIME_CAPTURE_CONFIG`, else `config.json` in the state folder |
| `claude` transcripts | `sources.claude_projects_root`, else `projects/` under `$CLAUDE_CONFIG_DIR` or `~/.claude` |
| ccrider index | `sources.ccrider_db`, else `~/.config/ccrider/sessions.db` |

`~` expands to the home folder on every OS, `%USERPROFILE%` on Windows.

## First run

The skill checks for a config, ccrider and a signed-in Azure CLI. Each missing piece is listed
with what it unlocks. One question follows with three answers: automatic setup, guided setup and
skip. A skip never blocks a run and leaves only those parts out.

## Requires

- Python 3.9 or newer.
- ccrider, for anything beyond `claude` sessions. Without it, the skill reads `claude`
  transcripts only.
- The Azure CLI with the `azure-devops` extension, for task titles. Without it, tasks come out
  as `UNKNOWN`.
- A browser the agent can drive, for filling the timesheet. Without it, you get the table and
  fill it in yourself.

## Supported timesheets

Ark Time Capture ships as an adapter (`references/timecapture-ark.md`). Any other system still
gets the table. Set `"fill": "propose"` in the config and nothing is filled.

## What's in this repository

- `SKILL.md`: the instructions the agent follows
- `scripts/`: session extraction, the 15-minute grid, the effort report, the first-run check
  (`preflight.py`), the hook trace and its installer, the explore guard, the timesheet and PM snapshots, and `_config.py`, which resolves
  every path
- `references/`: how each source works, the hook trace setup, the Ark Time Capture form map,
  and the Teams and Outlook search rules
- `config.example.json`: a starting config
- `LICENSE`: MIT
- `evals/`: test prompts for checking the skill after changes
