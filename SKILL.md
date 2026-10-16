---
name: time-capture
description: Use when the user needs to account for their time, fill a timesheet, or see how much their coding agents worked. Rebuilds a day or week from every agent session (`claude` transcripts with subagents, plus `codex`, `copilot`, `opencode`, `pi`, `antigravity`, `amp` through ccrider), git, the work tracker and, when connected, the period's Teams messages, Outlook mail and calendar, which decide each row's job and category. Produces 15-minute timesheet entries with category, job, task, description and billable flag, asks about anything ambiguous in a question prompt with ready answers, fills the entries into the timesheet after one approval, and reports agent effort (agent-hours against wall-clock hours). Trigger on "capture my time", "fill in my timesheet", "do my time capture", "what did I work on today", "I'm behind on time capture", "timeline of yesterday", "what did I get done this week", "write up my standup", "how much did my agents do today", "effort across my sessions", "how parallel was I", even when the word timesheet never comes up, and when only part of the picture is wanted (one project, one afternoon, just the effort numbers).
argument-hint: "[effort | fill | standup] [today | yesterday | YYYY-MM-DD | this week] [project]"
---

# Time Capture

The user loses time twice: once doing the work, once trying to remember it days later. The
entries that get forgotten are the small ones: the twenty-minute investigation for a colleague,
the PR review, the merge conflict. Session history remembers exactly those.

Two views come out of the same evidence. The **timesheet** is wall-clock time, one row per block
of like work, ready to save. The **effort report** counts every agent's busy time separately, so
three agents working for an hour is three agent-hours.

## When to Use

- Filling or catching up on a timesheet, for a day or a range.
- Remembering what got done: a standup, a one-on-one summary, a weekly recap.
- Measuring agent effort: how long each session and subagent worked, and how parallel the day was.

## Commands

The words after `/time-capture` pick the mode. With none, run the timesheet for today.

| Invocation | Does |
|---|---|
| `/time-capture`, `/time-capture yesterday`, `/time-capture 2026-09-29` | Timesheet for that day: Method Steps 0 to 5b, then Step 6 once approved |
| `/time-capture this week`, `/time-capture last 5 days` | Timesheet per day across the range (`--days N`) |
| `/time-capture effort [day or range] [project]` | Effort report only. See "Effort report" |
| `/time-capture fill [day]` | Step 6 for a table already approved and saved as pending |
| `/time-capture standup`, `/time-capture week summary` | Prose instead of a table. See "Prose" |

A project word (`PMCK`, `Soga`) narrows every mode to sessions whose path contains it.

## Execution Contract

These hold in every mode.

1. **Evidence only.** Every block traces to sessions, commits, tracker items or something the
   user said. Never invent a block to reach the expected hours.
2. **`UNKNOWN` over plausible.** A task or job that cannot be evidenced is written as `UNKNOWN`.
   A wrong work item quietly bills hours to the wrong job.
3. **One approval per batch.** Saving to the timesheet submits a form. It needs a clear yes from
   the user for that exact table, given in chat or as an answer in the question prompt. A revised
   table needs a fresh yes.
4. **Ask, don't guess.** Every judgement call goes to the user as a question (Step 5b). A row
   whose answer is still open is held back from the fill.
5. **Real input when filling.** Click, type and press keys like a person. `javascript_tool` reads
   state and never sets it.
6. **Existing rows are the user's.** Never edit, split, copy or delete a captured row unless the
   user asks for that specific change.
7. **Effort is never trimmed.** Effort hours routinely exceed the day. Report them as measured.
   Only the timesheet view collapses to wall-clock time.

## Method

### Step 0: Load the config

Everything user-specific lives in the state folder, outside the skill folder, so an upgrade
never wipes it. The state folder is `$TIME_CAPTURE_HOME`, else `$XDG_CONFIG_HOME/time-capture`,
else `~/.config/time-capture`. It holds `config.json` (or `$TIME_CAPTURE_CONFIG`), `trace/`,
`pending/` and the explore flag. `scripts/_config.py` resolves every path. Run
`python "${CLAUDE_SKILL_DIR}/scripts/_config.py"` to print each one. Shape: `config.example.json`.

### Step 0b: First-run check

The first-run check is `python "${CLAUDE_SKILL_DIR}/scripts/preflight.py"`. It prints `ready`
and a `missing` list. A true `ready` means Step 1 starts at once.

A false `ready` means the user is new or partly set up. List each `missing` item with its
`unlocks` text, then make one `AskUserQuestion` call with three options:

- "Automatic setup": run each `fix` and write `config.json` from `config.example.json`. Ask only
  for values that can't be found: jobs, Azure DevOps org, timesheet URL. A step that needs the
  user, such as the `az login` browser window, pauses the run until it finishes. After the
  user confirms, rerun `preflight.py` and continue only when that item is gone. The `browser`
  item is dropped without asking when a browser tool is already connected. After the
  user confirms, rerun `preflight.py` and continue only when that item is gone. The `browser`
  item is dropped without asking when a browser tool is already connected.
- "Guided setup": give one step at a time and wait for each.
- "Skip": continue with what is available and list once what the run lacks.

The question covers items still missing and is asked once per session. A skip never blocks the
run. Without `AskUserQuestion`, list the items and fixes, then continue.

Commands below call `python`, meaning Python 3.9 or newer. Use `python3` where `python` is
missing (most macOS and Linux) and `py -3` on Windows without it on PATH.
`${CLAUDE_SKILL_DIR}` is the folder holding this file, wherever the skill is installed.
Shell snippets are written for a POSIX shell (bash, zsh, Git Bash). Each is a single line, so
it also runs in PowerShell once quoting is adjusted.

| Key | Holds |
|---|---|
| `timezone` | Local UTC offset, e.g. `+02:00` |
| `workday` | Day start and end, expected hours, fixed blocks such as lunch |
| `sources` | Session source (`auto`, `hybrid`, `jsonl`, `ccrider`), ccrider paths, provider filter, `ignore_prompts`, `idle_gap_minutes`, `trace_dir` |
| `work_tracker` | `kind` (`azure-devops`) and `org` URL |
| `timesheet` | `system` (adapter name), `url`, `fill` mode (`confirm` or `propose`) |
| `projects` | Ordered list mapping a path fragment (`match`) to a `job` keyword, an `ado_project`, `standing_tasks`, and an optional `support` job and task |

A repo's feature and project work goes on `job`. Support work in that repo goes on
`support.job` with `support.task`: a reported fault, a data fix, or an investigation someone
asked for.

**With no config yet**, copy `config.example.json` into place. Ask only what cannot be read:
timezone, workday, tracker org and timesheet URL. Build `projects` from the live job list
(Step 6 reads it) and the repos the sessions came from. Ask the user to confirm that mapping
before saving it.

`projects` is tried in file order, so specific fragments (`BMP.AWE`) go before broad ones
(`PMCK`). The `job` value is a substring of the live job name. Job codes roll over each contract
period, and a keyword survives the rollover.

### Step 1: Extract the sessions

```bash
python "${CLAUDE_SKILL_DIR}/scripts/extract_sessions.py" --date 2026-09-30
```

The default source is `hybrid`: `claude` sessions from their transcript files, every other
provider from ccrider. The transcripts carry what ccrider drops, namely tool-only turns, tool
durations, subagents, tokens, and a record of who wrote each message. `references/sources.md`
has the full comparison.

Flags: `--date`, `--days N` (a range ending on `--date`), `--project SUBSTR`, `--here`,
`--provider NAME` (repeatable), `--source`, `--no-sync`, `--tz`, `--max-chars`, `--idle-gap`,
`--all` (keep sessions with no human turns).

ccrider syncs first and can take a minute or two, so give the command a 10-minute timeout. Pass
`--no-sync` on reruns in the same conversation.

Each session carries `provider`, `project_path`, `user_turns` (human prompts only), `activity`
(busy stretches), `tools`, `tokens`, `subagents`, and a `job_hint` from the config. The hint is a
guess from the repo path. What the work was about wins: AWE work done inside the PMCK repo
belongs to the AWE job.

### Step 2: Build the slot grid

```bash
python "${CLAUDE_SKILL_DIR}/scripts/extract_sessions.py" --date 2026-09-30 --no-sync | python "${CLAUDE_SKILL_DIR}/scripts/build_blocks.py" --existing captured.json --context context.json
```

The grid has one row per 15-minute slot, naming the sessions busy in it. Fixed blocks come from
the config. `--existing` takes the rows already in the timesheet and marks those slots
`CAPTURED`. Overrides: `--fixed Lunch=13:00-13:30` (repeatable), `--no-fixed`,
`--expected-hours`, `--day-start`, `--day-end`.

A slot counts as worked when any session's agent was busy in it, prompted or not. Each slot also
lists `prompted`, the sessions whose human turns span it. Slots marked `OVERLAP` need a decision
on which work owned those minutes. Give each stretch to the work the user was steering, as
`prompted` shows. Otherwise give it to the session with the most activity in that stretch.

### Step 3: Corroborate

A timesheet is a claim about what happened. An entry that overstates is worse than a missing one.

- **git.** Run `git log` per distinct `project_path` (command in `references/sources.md`).
  Transcripts record intent, commits record outcome, and the two differ often.
- **Work tracker.** Step 4 confirms task IDs and gives real titles.
- **Teams, Outlook and the calendar.** Read all three for every day of the target period
  whenever `mcp__claude_ai_Microsoft_365__*` tools beyond `authenticate` are available.
  Meetings, calls, the requests that started work, and who it was for show up here and nowhere
  else. Follow `references/m365.md`: calendar, then mail, then Teams, one day at a time for
  long ranges.
- **Look up the PMs.** `pm-map.json` in the state folder names the people who run the user's
  jobs. Build or refresh it from the timesheet's PM list when it is missing or a month old.
  Messages from these people decide jobs, and their call requests are scrums (next point).
- **Classify what you read.** Each kept item is a meeting, call, request, status, commitment or
  handover, with a job and category hint taken from who it is with. A `call` is a PM or lead
  asking the user to come over or join. The grid sizes it from the user's absence: the first
  prompt silence after the message, with the unattended agent minutes in it reported apart. Write them to
  `context.json` and rerun Step 2 with `--context context.json`. Meetings then fill their slots,
  and every other item sits in its slot as evidence for that row's job, category and description.

If M365 is not connected, say so in one line and carry on. Don't stall for auth.

### Step 4: Resolve tasks

Work item IDs show up in branch names, commit messages and PR titles. For Azure DevOps, pull
real titles with the config's `org` and the matched project's `ado_project`.

`az boards` needs the `azure-devops` extension. When it's missing, `az` prompts to install it and
dies on the prompt with an `EOFError`. Install it first: `az extension add --name azure-devops`.

List what the user touched. Their recently changed items usually map straight onto the day:

```bash
az boards query --org <org> --project "<ado_project>" -o json --wiql "SELECT [System.Id], [System.Title], [System.WorkItemType], [System.State] FROM WorkItems WHERE [System.AssignedTo] = @Me AND [System.ChangedDate] >= '<date - 7 days>' ORDER BY [System.ChangedDate] DESC"
```

Confirm one ID by projecting only the needed fields. The raw record is hundreds of lines:

```bash
az boards work-item show --id <id> --org <org> -o json --query "{id:id, title:fields.\"System.Title\", type:fields.\"System.WorkItemType\", state:fields.\"System.State\"}"
```

JMESPath needs **double** quotes around dotted field names. Single quotes make a string literal.

`standing_tasks` maps a category to the catch-all task a job uses for it, such as Scrum to a
"Dev Scrums" item. Use it when the work is that kind and no specific item fits. The user's
recent timesheet rows show more of these, so add each new one to the config.

Evidence for a task ID is a link: a branch, commit or PR naming it, a `standing_tasks` entry for
the row's category, or the user's own past rows booking that kind of work to it. A title that
reads like the work is not evidence. Without a link, write `UNKNOWN` and ask.

A task must exist in the timesheet's task list for the chosen job. A work item from the wrong
project cannot be entered, however well it matches. If `az` is missing or signed out, write
`UNKNOWN` throughout, say so once, and carry on.

### Step 5: Write the entries

Group contiguous slots into blocks of like work: one block per category-and-task, not per
session. Split a session that changed character, such as a review followed by a rewrite.

Open with the effort table (see "Effort report"), then the timesheet:

```markdown
# Time capture, Wednesday 30 September 2026

| Start | End | Hrs | Category | Job | Task | Description | Bill |
|---|---|---|---|---|---|---|---|
| 07:30 | 10:15 | 2.75 | Development | J009902 - PMCK - AWE System & Reports | 50799 | Added menu item overrides tab to AWE and blocked direct URL access to hidden modules. | Y |
| 12:30 | 13:00 | 0.50 | Lunch | - | - | Lunch | N |
| 14:00 | 15:00 | 1.00 | *captured* | J009892 - FORMIDABLE - SLA 2026 [JUL- DEC] | 47647 | Fixing BC permissions PR | Y |

**Total: 8.00h** · captured 1.00h · to add 6.50h · fixed 0.50h

## Needs your input
- 07:15-07:30: no evidence either side. Start of the Soga session?
- 10:15-11:00: AWE build and the scheduler interval work overlap. Given to AWE.
```

Rules that make the table usable:

- **15-minute boundaries only.** Round to where the work sat.
- **Absorb small gaps.** A ten-minute hole between two stretches of the same work was that work.
  Flag a gap only when it could be something else, or the work either side differs.
- **Show captured rows but never re-propose them.** Mark them *captured* so the total adds up.
- **When the day overruns, say so.** 9.5 evidenced hours in an 8-hour day means overlapping
  threads were counted twice somewhere, and the user needs to choose.
- **Work inside a fixed block** means they worked through lunch. Note it, don't drop either.
- **Write the live job name**, as the timesheet lists it, not the config keyword. The code in the
  name shows which period's job it is.
- **A timesheet row is the person's time.** A slot where only an agent ran, after the user's last
  prompt, stays out of the table. List it under "Needs your input" with the agent's end time.
  It still counts in the effort report.
- **A call or meeting owns its slots.** The user was there, not at the keyboard. Any agent work
  in those slots counts in the effort report only.
- **A credential in a transcript** gets one line under "Needs your input" saying where it sits
  and to rotate it. Never repeat the value.
- **A session with no job match** (`job_hint` null, or its job missing from the live list) gets
  `UNKNOWN` in the Job column and a line under "Needs your input".
- **End with "Needs your input"**, listing every judgement call and every gap.

Save the table as `pending/<date>.json` in the state folder with `status: draft`, so
`/time-capture fill` can pick it up later. Set `status: saved` once Step 6 finishes.

### Step 5b: Clarify

Show the draft first (see "Output template"), then put every open judgement call to the user
with the `AskUserQuestion` tool. A question in a prompt gets answered. A bullet at the end of a
long report gets skimmed.

What becomes a question:

- A slot with two plausible jobs or categories: overlapping threads, a meeting during agent work,
  or a request from one client while working on another client's repo.
- A captured row the evidence disagrees with. Offer "keep as captured" first, since the row
  is the user's.
- A gap the evidence cannot fill, and an agent-only slot after the user's last prompt.
- A call whose length could not be found, was capped, or overlaps lunch. Offer the estimated
  span first, then a 15-minute and a 30-minute option.
- Someone calling scrums who is not in `pm-map.json`.
- A task ID with no link, and a session with no job match.
- Billable on a job row where the user's history is mixed.

How to ask:

- Up to 4 questions per call, ordered by the hours at stake. Run more rounds only if needed.
- Each question names the time span and the evidence in one sentence. The `header` is the span,
  e.g. `10:30-12:30`.
- 2 to 4 options, each a concrete row outcome ("AWE job, Client Presentation"). Put the
  evidence-backed choice first and mark it `(Recommended)`. The user can always pick Other.
- Never ask what the user already told you, or what the evidence settles.

Fold every answer into the table and reissue it whole. Record a corrected mapping in the config's
`projects`. Then ask for the save approval in one more `AskUserQuestion` call, with the options
"Save N entries", "Change something first" and "Don't save". A row the user answered "skip" stays
out.

Without the `AskUserQuestion` tool (a headless run, a subagent, another harness), list the same
questions under "Needs your input" with their options, and stop there.

### Step 6: Fill the timesheet

This step runs only when `timesheet.system` names an adapter and `timesheet.fill` is `confirm`.
For `ark-timecapture`, read `references/timecapture-ark.md` first. It has the form map, the fill
procedure and the traps.

1. **Read before proposing.** Open the timesheet page and run the adapter's snapshot for the
   date. It returns the captured rows (Step 2's `--existing`), the live job list and the
   categories. Read the last two or three captured days too, for the user's habits: description
   voice, categories for support work, standing tasks, unticked Billable. Do this before Step 5,
   so the table already follows those habits.
2. **One approval for the batch.** This is the save question that closes Step 5b. Rows with
   `UNKNOWN` in Job or Task, or an unanswered question, are held back until the user settles them.
3. **Fill with real input.** Screenshot each filled form before Save and the grid after it.
4. **Verify each save** against a fresh snapshot or the grid's row count. On any error toast,
   stop, report, and leave the remaining rows unsaved.
5. **Report** in the "Summary output" format.

## Output template

Every timesheet run replies in this order. A section with nothing in it is left out.

````markdown
<One or two sentences: the day, what is already captured, what this adds, the sources read.>

## Effort, <Weekday DD Month YYYY>
**N agent-hours** (N in sessions, N in subagents) across **N wall-clock hours**. Parallelism N.
| Session | Project | Job | Busy | Effort h | Subagents h | Your turns | What it was |

## Context from Teams and Outlook
- 11:30-12:30 meeting: AWE demo with <who>. Client Presentation, PMCK - AWE.
- 08:25 request from <who>: <subject>. Points at PMCK - SLA.
- 09:39 call from <PM>: "swing by the scrum room". Away 10:00-10:17, so Scrum 10:00-10:15.
  1 agent minute ran unattended.

## Time capture, <Weekday DD Month YYYY>
| Start | End | Hrs | Category | Job | Task | Description | Bill |
**Total: N h** · captured N h · to add N h · fixed N h

<One line per new row on the evidence behind it, only where it is not obvious.>

## Captured rows the evidence disagrees with
<Bullets. Rows stay as captured unless the user changes them.>

## Needs your input
<Only what could not be asked in the prompt, or the full question list when there is no prompt.>

Open threads: <commitments and handovers still open at day's end>
Coverage: <sources and days read, and what a throttle or page cap cut off>
````

Then the clarifying questions (Step 5b), the reissued table, and the save question.

## Summary output

After Step 6, reply with this and nothing else:

````markdown
Saved N entries to <timesheet> for <date>: N.NN h.

| Start | End | Job | Task | Hrs | Result |
| 12:45 | 13:00 | J009902 - PMCK - AWE System & Reports | 50799 | 0.25 | saved |

Held back: <row, and the reason: UNKNOWN task, unanswered question, user said skip>
Day total now N.NN h against N expected.
Pending file: pending/<date>.json, status saved.
````

A failed save stops the fill. The summary then lists the saved rows, the failed row and its error
text, and the rows not attempted.

## Effort report

`/time-capture effort` runs one script and reports what it prints:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/effort.py" --date 2026-09-30 [--days N] [--project SUBSTR] [--no-sync] [--json]
```

It chains Steps 1 and 2 and prints, per day:

- **Agent-hours**, split into session hours and subagent hours, against **wall-clock hours**.
  Parallelism is session hours divided by wall-clock hours. Subagent minutes run inside their
  parent session's minutes, so they are left out of it.
- **One row per session**: agent, project, job, busy window, effort hours, subagent hours, tool
  minutes, output tokens, and how many turns the user typed. Headless runs (`sdk-cli`) are
  included and marked, since they are agent work too. `--human-only` drops them.
- **Peak concurrency per hour**, the most sessions busy in any one 15-minute slot.
- **Waiting on you**, the traced minutes agents sat at a permission prompt.

Effort counts exact busy minutes, not 15-minute slots, so a two-minute subagent counts two
minutes. Add a one-line summary per session from its `user_turns` and `closing_text`. Keep the
numbers as the script printed them.

For effort across a range, pass `--days`. The report prints one section per day.

## Steering

What the user says in the invoking message overrides the defaults.

| They say | Do this |
|---|---|
| "yesterday", "Friday", "the 2nd", "this week" | `--date` / `--days` |
| "more detail in the descriptions" | Two or three sentences per entry naming files, procs or screens |
| "just the PMCK work" | `--project PMCK` |
| "only my Codex sessions" | `--provider codex` |
| "focus on the warranty stuff" | Still account for the whole day, expand the named thread |
| "I worked through lunch", "took lunch at 1" | `--no-fixed` or `--fixed Lunch=13:00-13:30` |
| "I only did half a day" | `--expected-hours 4` |
| "no tasks, I'll add them" | Skip Step 4 |
| "just give me the table" | Skip Step 6 |
| "leave out the time I spent on X" | Drop X's slots and give them to the other work running then |

**Facts the user supplies outrank anything inferred.** A statement like "I had a call with
Kuipertech from 11 to 12" is what happened in those slots. Sessions cannot see meetings, calls,
desk conversations or thinking time. Place the statement on the grid and rebuild around it.

- **Their block displaces yours.** If a session looked active 11:00-12:00 during their meeting,
  the meeting wins and the session's work moves to the slots either side. Say so in one line.
- **Ask once.** When "Needs your input" gets answered, fold every answer in and reissue the whole
  table. Don't re-ask what they've told you.
- **A mid-review fact** regenerates the affected rows only. Show the revised table, not a diff.
- **A mapping they correct** ("Soga work goes on the ARKSOFT job") goes into the config's
  `projects` list, so the next run gets it right.

## Prose

A standup note, a one-on-one summary or "what did I do today" wants narrative, not the table.
Keep it to one line per work item, at most about 20 words, tag Teams and email context inline, report failures as
failures, and close with open threads and commitments made to other people. For a week, group
by day and open with the two or three threads that ran through it. Offer the table as a
follow-up.

## Optional: hook trace

The transcripts cannot say when a turn ended, how long an agent sat at a permission prompt, or
when the window closed. `scripts/trace_hook.py` records those per session when installed as a
command hook on the lifecycle events. Nothing in this skill depends on it. With it, busy time
excludes permission waits and each turn has an exact end. Setup, record shape and join keys:
`references/trace.md`.

## Optional: explore mode

Mapping a timesheet page means opening old entries and dropdowns without saving anything.
`scripts/explore_guard.py` enforces that as a browser-tool hook while
`explore.json` exists in the state folder. It denies clicks on the listed buttons, `form_input`,
JS that writes, and the Delete and save keys. Record the button rects in page pixels before the
first click. Delete the flag file when the mapping is done. The flag shape is in the script's
docstring.

## Failure Modes

| Symptom | Fix |
|---|---|
| A session's busy time looks short, or its subagents are missing | The run used `--source ccrider`, which drops tool-only turns and subagents. Use the default `hybrid` source. |
| Effort for today stops hours before now | ccrider was not synced. Rerun without `--no-sync`, or use `hybrid`, which reads `claude` transcripts live. |
| Hook text, subagent reports or task notifications listed as user turns | They lack `origin.kind: human`. Check the extractor read the transcript, not ccrider, and add any repeated opener to `sources.ignore_prompts`. |
| Subagent hours balloon to hours for a handful of short helpers | Effort was counted in 15-minute slots. Use `effort.py`, which counts exact minutes. |
| All project work in a repo booked to its support job | `support.job` is for reported faults, data fixes and requested investigations only. Feature work goes on `job`. |
| A block proposed to make the day reach the expected hours | Remove it. List the unaccounted time under "Needs your input". |
| A plausible task ID with no evidence behind it | Replace with `UNKNOWN` and hold the row back from the fill. |
| A dropdown selected "Select..." or an unrelated category | Return alone picks the placeholder, and the filter box keeps old text. Triple-click the filter box, type, press Down, then Return. See `references/timecapture-ark.md`. |
| A no-job row saved as billable | Billable carries over from the previous save. Read the checkbox before each save. |
| Form values set through `javascript_tool` | Stop. Refill with real input. JS writes skip the page's own handlers and hide the bugs a person would hit. |
| A captured row edited or deleted while filling | Only a specific request from the user allows that. Report what changed. |
| An Edit of an old row shows a blank Job or VSO Task | Expired jobs drop out of the Job list, and Edit never refills VSO Task. Reload the page to leave edit mode. See `references/timecapture-ark.md`. |
| git shows no commits on a day with sessions | `--author` is case-sensitive, and a parent-folder session hides its repos. Use `--regexp-ignore-case` and run git in each repo under the folder. |
| Effort hours trimmed so they fit inside the workday | Put them back. Effort and timesheet are separate views, and only the timesheet collapses. |
