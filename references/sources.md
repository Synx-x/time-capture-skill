<!-- plain: off -->
# Session sources

`scripts/extract_sessions.py` reads session history from up to three places and emits the same
JSON shape from all of them. Each session comes from exactly one source, so nothing is counted
twice.

| Source | What it reads | Chosen when |
|---|---|---|
| `hybrid` | `claude` sessions from their transcript files, every other provider from ccrider | `auto` and the ccrider database exists (the default) |
| `jsonl` | `claude` transcript files only | `auto` and no ccrider database, or `--source jsonl` |
| `ccrider` | Every provider from the ccrider index, `claude` included | `--source ccrider` |

## What each source carries

The table below was measured on the 2026-09-30 sessions, with `claude` CLI 2.1.285 and ccrider
1.11.1 (parser version 1).

| Data point | Transcript files | ccrider | Hook trace |
|---|---|---|---|
| Message timestamps, to the millisecond | every record | text messages only | - |
| Tool-only assistant turns | yes | dropped (48 of 456 assistant records kept in one session) | - |
| Tool calls and durations | `tool_use` id paired with its `tool_result` | `tool_uses` table is empty | - |
| Who wrote a user record | `origin.kind` (`human`, `peer`, `task-notification`), `promptSource`, `isMeta` | no | `UserPromptSubmit` fires on queued and peer messages too |
| Subagent work | `<session>/subagents/agent-<id>.jsonl` plus `.meta.json` (type, description, model) | not imported | `SubagentStart` / `SubagentStop` |
| Tokens and model per request | `message.usage`, `message.model` | no | - |
| Turn length | `system/turn_duration`, on some turns only | no | `UserPromptSubmit` to `Stop` |
| Compactions | `system/compact_boundary` with duration | no | `PreCompact` / `PostCompact` |
| Waiting on a permission prompt | folded into the tool's duration | no | `PermissionRequest` |
| Session opened and closed | first and last record only | first and last message | `SessionStart` (`source`), `SessionEnd` (`reason`) |
| Other providers (`codex`, `copilot`, `opencode`, `pi`, `antigravity`, `amp`) | no | yes | no |

ccrider's gaps are why `claude` sessions come from their transcripts. On the sample day, the
transcripts showed 78 more busy minutes in one session than ccrider did, plus 42 subagents the
index never saw.

## Transcript files

Each `claude` session is one file, `<claude home>/projects/<project-slug>/<session-id>.jsonl`, with
one JSON object per line. The format is internal to the CLI and changes between versions. The
reader skips any record it cannot parse instead of failing.

The extractor uses these records:

| Record | Fields used |
|---|---|
| `type: user` | `timestamp`, `message.content`, `origin.kind`, `promptSource`, `isMeta`, `promptId`, `gitBranch`, `cwd`, `entrypoint` |
| `type: assistant` | `timestamp`, `message.id`, `message.model`, `message.usage`, `tool_use` blocks |
| `type: system` | `subtype` `turn_duration` (`durationMs`) and `compact_boundary` |

One API response becomes one record per content block, each repeating the same `usage`. Tokens
are counted once per `message.id`.

A user record whose content is a `tool_result` is tool output, not a person. A record with
`origin.kind` other than `human`, or `isMeta: true`, is harness text: a skill load, a subagent's
report, a task notification. Records with no `origin` (older versions) fall back to the prefix
filters in the script.

`entrypoint: sdk-cli` marks a headless run (`claude -p`), usually spawned by a hook or script.
The timesheet view drops sessions with no human turns. The effort view keeps them.

## ccrider

[ccrider](https://github.com/neilberkman/ccrider) keeps one SQLite index of coding-agent
sessions. `ccrider sync --help` (v1.11.1) lists the providers it imports:

| Provider id | Reads from |
|---|---|
| `claude` | `<claude home>/projects/` (`$CLAUDE_CONFIG_DIR`, else `~/.claude`) |
| `codex` | `~/.codex/sessions/` |
| `copilot` | `~/.copilot/session-state/` |
| `opencode` | `~/.local/share/opencode/opencode*.db` |
| `pi` | `~/.pi/agent/sessions/` |
| `antigravity` | `~/.gemini/antigravity-cli/brain/` |
| `amp` | the signed-in account |

The database is `sources.ccrider_db`, else `~/.config/ccrider/sessions.db`. The script opens it read-only.

**Sync first.** The index holds only what the last sync imported. The script runs `ccrider sync`
unless `--no-sync` is passed, and skips the sync when only `claude` sessions are wanted.

A full sync took 77 seconds on 2026-09-30, mostly on remote providers. Give the extractor a
10-minute timeout, and pass `--no-sync` on reruns in the same conversation.

**What the script filters.**

- Subagent rows (`is_sidechain`).
- User-slot rows whose content is a `tool_result`. ccrider stores these with `type = 'user'`,
  the same as a typed prompt.
- Harness text that arrives in the user slot: hook feedback, compaction notices, skill loads,
  image path echoes, and scripted probes like "Reply with exactly".
- Housekeeping commands with no arguments: `/login`, `/model`, `/clear` and similar.
- Any prefix listed in the config's `sources.ignore_prompts`. Hook-spawned one-shot sessions go
  here, such as a comment checker that opens every run with the same sentence.

**Timestamps** are Go `time.String()` values in UTC, e.g. `2026-09-01 06:15:14.895 +0000 UTC`.
The script compares the first 19 characters.

The ccrider MCP tools (`mcp__ccrider__search_sessions`, `get_session_messages`) help when one
session needs a closer read, for example to see what a long thread concluded at 11:00.

## Hook trace

The hook trace is an optional per-session file written by `scripts/trace_hook.py`. It fills the
three gaps no transcript covers: when each turn ended, time spent waiting on a permission prompt,
and when the session closed. Setup and record shape: `references/trace.md`.

## Busy time

A session counts as busy at each record's timestamp, across each tool call from its start to its
result, and across each traced turn from prompt to `Stop`. Stretches closer than
`sources.idle_gap_minutes` (default 15) join.

Traced permission waits are cut out, since the agent was not working while it waited on the user.

**Multi-agent work.** A `claude` session can drive a `codex` or `pi` session in a terminal pane.
Both then show activity for the same minutes. The child session is the same piece of work, so it
folds into the parent's timesheet block rather than being booked twice. The effort view still
counts both, because both agents worked.

## git

Transcripts record intent. Commits record outcome. For each distinct `project_path` in the day's
sessions, run:

```bash
git -C "<project_path>" log --all --regexp-ignore-case --since="<date> 00:00" --until="<date> 23:59" --author="<user email>" --format="%h %ad %d %s" --date=format-local:%H:%M
```

`git -C` finds the enclosing repository, so a session opened in a subfolder still works.

- `--author` matches case-sensitively by default, and commit emails often differ in case from the
  config. `--regexp-ignore-case` fixes that.
- `format-local` prints each time in the local timezone. Plain `format` keeps each commit's own
  offset, so commits made on another machine land in the wrong block.
- A session opened at a parent folder (a solution root, or `source/repos`) holds several repos.
  Run the command in each repo under it, and in each worktree `git worktree list` shows.

## Azure DevOps

Look up task titles with `az boards query`. WIQL searches every project the organisation holds
unless it filters on one, and it returns only the fields its `SELECT` names:

```sql
SELECT [System.Id], [System.Title], [System.WorkItemType], [System.State]
FROM WorkItems
WHERE [System.TeamProject] = '<ado_project>' AND [System.Id] IN (<ids>)
```
