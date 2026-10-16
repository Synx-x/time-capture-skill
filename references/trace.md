<!-- plain: off -->
# Hook trace

`scripts/trace_hook.py` appends one line per lifecycle event to a per-session file. The
extractor joins it onto the session's transcript. It is optional: without it, every number
still comes from the transcript, and the three gaps below stay estimates.

| Gap in the transcript | Filled by |
|---|---|
| No marker for the end of a turn (`system/turn_duration` appears on some turns only) | `Stop`, paired with the `UserPromptSubmit` before it |
| A permission prompt's wait is folded into the tool call's duration | `PermissionRequest`, closed by that tool call's `tool_result` |
| No record of the window closing | `SessionEnd` and its `reason` |

It also records `SessionStart` (`source`: startup, resume, clear, compact), `SubagentStart` and
`SubagentStop` (`agent_id`, `agent_type`), `PreCompact` and `PostCompact` (`trigger`), and
`Notification` (`notification_type`, e.g. `idle_prompt`).

## Record shape

One JSON object per line in `<trace_dir>/<session_id>.jsonl`:

```json
{"ts": "2026-09-30T16:57:25.712+00:00", "event": "UserPromptSubmit", "prompt_id": "cf2392c4-...", "permission_mode": "auto", "cwd": "C:\\Users\\me\\repos"}
```

`ts` is stamped by the hook, since no hook payload carries a time. The join keys:

| Trace field | Matches in the transcript |
|---|---|
| `prompt_id` | a user record's `promptId` |
| `tool_use_id` | a `tool_use` block's `id` and its `tool_result`'s `tool_use_id` |
| `agent_id` | the file `<session>/subagents/agent-<agent_id>.jsonl` |

No prompt text, tool input or assistant output is written. The transcript already holds those,
and a second copy is a second place for them to leak from.

`trace_dir` is `$TIME_CAPTURE_TRACE_DIR`, else `sources.trace_dir` from the config, else
`trace/` under the state folder (see Paths in the README). The hook and the extractor resolve
it the same way.

## Install

The hook is a command hook that reads the event payload on stdin, writes one line, prints
nothing and always exits 0. A broken trace never blocks a turn.

**Plain settings file.** Run the installer from wherever the skill lives. It prints one entry per
event with `async: true`, so the harness never waits on it. The paths are real ones: the Python
that ran it and the absolute path of `trace_hook.py`. Hook commands cannot name a skill folder
through a variable, so a hand-written `~/...` path breaks when the skill moves.

```bash
python scripts/install_trace.py                       # print the block
python scripts/install_trace.py --settings <file>     # merge into a settings file, .bak kept
```

Merging skips an event that already runs `trace_hook.py`, so a second run changes nothing. The
hooks reference at https://code.claude.com/docs/en/hooks documents `async` and the event names.
Reinstall after moving the skill folder or changing Python.

With `async: true` the `ts` lands when the hook process starts, a few milliseconds after the
event. That is well inside the minute resolution the reports use.

**Hook dispatcher.** A setup that routes every event through one dispatcher script adds a thin
wrapper to its hooks folder instead. The wrapper declares the events and runs `trace_hook.py`
with the payload already on stdin. Keep the wrapper free of logic, so the trace code ships with
the skill.

`PreToolUse` and `PostToolUse` are left out on purpose. Tool durations already come from the
transcript, and a hook on every tool call adds a process start to each one.

## Checking it works

Send a prompt, let the turn finish, then read the newest file in the trace folder. It should
hold a `UserPromptSubmit` line followed by a `Stop` line with the same session. The effort report
prints how many `claude` sessions had no trace, which is every session from before the install.

Codex, Pi and the other providers have no equivalent hook here. Their timing comes from ccrider's
message timestamps only.
