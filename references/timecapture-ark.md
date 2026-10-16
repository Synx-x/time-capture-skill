<!-- plain: off -->
# Ark Time Capture adapter

Used when the config has `"timesheet": {"system": "ark-timecapture"}`. The page is
`https://theark.arksoft.co.za/TimeCapture`. It is an ASP.NET MVC page built on Kendo UI widgets.

Everything here was observed on the live page on 2026-09-30 (bundle `TimeCapture/Index?v=1.3.12.6`).
Re-check a behaviour if the bundle version changes.

## Read the page first

Run `scripts/timecapture_snapshot.js` through `javascript_tool`. It is read-only. It returns:

- `entries`: the rows already captured for the date shown, times in 24-hour `HH:MM`.
- `jobs`: the live Job list as `[id, name]`. Jobs roll over each contract period, so never
  hard-code them. Match the config's `job` keyword against these names.
- `categories`: `[id, name, takes_job, default_description, clickup_linked]`. See Category rules
  below for what each flag does to the form.

Pass `entries` to `build_blocks.py --existing` as `{"date", "start", "end", "label"}` rows. Only
the missing slots then get proposed.

Also read the last two or three captured days. They show how this user writes descriptions, which
category they use for support work, and when they untick Billable. Mirror that. The user's own
history outranks the category guide below.

`javascript_tool` is for reading only. Every change to the form goes through real clicks and keys.

## Form map

| Field | Element id | Widget | Behaviour |
|---|---|---|---|
| Capture For | `EmployeeID` | DropDownList | Defaults to the signed-in user. Leave it. |
| Date | `Date` | DatePicker `dd/MM/yyyy` | The input is **read-only**. Typing does nothing. Use the calendar button. |
| Category | `Category` | DropDownList with filter box | Required. |
| Job | `JobCardID` | DropDownList with filter box | Optional. Picking one ticks Billable. |
| VSO Task | `VsoTaskID` | DropDownList, cascades from Job, server filtering | Lists the 100 newest tasks. Typing an ID finds older ones. |
| Billable | `Billable` | Checkbox | |
| Start / End | `StartTime`, `EndTime` | TimePicker `h:mm tt`, 15-minute interval | Typing works. Start defaults to the last entry's end. |
| Objective | `ClickUpItemID` in `#ClickUpItemField` | DropDownList, hidden by default | Shows only for a ClickUp-linked category. Its label and whether it is required come from the server. No category was linked on 2026-09-30. |
| Description | `Description` | Textarea | Required. 250 words at most. |
| Save | `SaveTimeCapture` | Button | Posts one entry. Updates the entry instead when `isEdit` is true. |
| Clear | `ClearTimeCapture` | Button | Resets Category, Job and VSO Task only. Times stay, Billable stays ticked. |

Hidden fields: `ID` (0 for a new entry, else the entry being edited), `isEdit`, `EditVsoTaskID`
(the edited entry's task), `IsJobCardCategory` and `CurrentFinancialYearID`.

Saved rows land in the grid under the form (`#grid`), filtered to the selected date.

The grid toolbar holds Edit, Copy, Delete, Productive Filter and Split Time. Edit is the only one
safe to press without an explicit request, and it changes nothing until Save.

## Category rules

Changing Category runs one handler. It reads three flags off the selected category:

- `takes_job` false: the Job field is cleared and disabled, and Billable is unticked.
- `default_description`: copied into Description when Description is empty or still holds the
  previous category's default. Lunch fills in `Lunch`, Time Review fills in `Time review with `.
- `clickup_linked` true: the Objective dropdown appears and loads.

Picking a Job ticks Billable and empties the VSO Task list. Picking a VSO Task ticks Billable
again. So set Billable last, after Job and VSO Task.

## Editing an existing entry

Edit loads the selected grid row into the form. Select the row first, then press the toolbar Edit.

Edit fills in Date, times, Category, Description and Billable. Edit also sets `ID` to the entry id
and `isEdit` to true, so the next Save overwrites that entry. Reload the page to leave edit mode
without saving.

Two fields do not come back:

- **VSO Task stays blank.** The task id sits in `EditVsoTaskID`, but the dropdown shows
  `Select Vso Task` until you pick it again. Saving without re-picking it is untested. Pick it.
- **An expired Job loads blank.** Jobs roll over each contract period, and the Job list holds only
  live ones. An entry booked to an old job shows `Select Job...`. Saving it would move it to
  whichever job you pick.

Edit is the way to inspect an old entry. Walk the calendar back to its day, select it, and Edit
shows the form as it was filled.

## Time Review

Time Review lists every entry across a date range, at `https://theark.arksoft.co.za/TimeReview`.
It is the quickest way to learn a user's history.

The date range comes from `#StartDate` and `#EndDate`, with further filters for employee, job and
PM. The grid (`#grid`) pages on the server and groups rows by date, so flatten each group's `items`
when reading `dataSource.view()`. Page size `All` did not load. Pick `1000`.

Each row carries `ID`, `Category`, `CategoryDescription`, `JobCardID`, `JobCardName`, `VsoTaskID`,
`VsoTaskDescription`, `StartTime`, `EndTime`, `Description`, `ActualHours`, `CustomerName`,
`IsBillable`, `IsProductive`, `Status` (approval, 0 or 1), `VSOTaskNotRequired`, `AreaPath`,
`PMName` and `CreatedOn`.

Time Review is also an editor. Its toolbar has Save Changes, Cancel Changes, Delete, Batch Edit and
Export to Excel, and its cells edit in place. Read Time Review with `javascript_tool` only, and never
click inside its grid.

A year of history (2,646 rows, 2025-10-01 to 2026-09-30) showed:

- A no-job category never carried a job.
- Each job is replaced every period. One SLA job was replaced three times in a year. Match the
  config keyword against the live list every time.
- Standing tasks (scrums, user support, deployments) recur on each job. They are the right task for
  routine rows.
- About half the rows have `VSOTaskNotRequired` set, so a job row without a task is normal for
  some jobs.

### PM map

The PM filter (`#PMDropDownListFilter`) lists every PM, and each row's `PMName` ties a PM to jobs
and customers. Load a few months of rows, then run `scripts/timereview_pm_snapshot.js` through
`javascript_tool`. It is read-only and returns the PM options plus `[pm, rows, jobs, customers]`.
Merge it into `pm-map.json` in the state folder, keeping emails and `lead` entries already there.
Unverified: the PM filter's data fields were not read live. The script falls back across field
names, so check that `pm_options` is not empty.

Write the user's own summary (jobs by period, standing tasks, usual categories) to
`ark-history.json` in the state folder. It is personal data, so it stays out of the skill folder.

## Filling one entry

Get element refs with `find`, then act with `computer` clicks and typing. Take a screenshot after
each entry is filled and again after it saves.

1. **Date.** Click the calendar button right of the Date field. Use the month arrows if needed,
   then click the day. The grid reloads for that date.
2. **Category.** Skip this when the field already holds the right category. Click the Category
   field, then triple-click its filter box to clear any old text. Type part of the name, for
   example `Code Rev`. Press Down, then Return.
3. **Job.** Skip this for Lunch, leave and other no-job categories. Click the Job field, triple-click
   its filter box and type the job code (`J009892`). Press Down, then Return. Billable ticks itself.
4. **VSO Task.** Click the VSO Task field, triple-click its filter box and type the work item ID.
   Wait 1.5 seconds for the server filter, then press Down and Return. Entries read
   `ID - Type - Title`.
5. **Description.** Triple-click the textarea to select the old text, then type.
6. **Billable.** Read the checkbox and compare it with the planned value. Click it only if it differs.
7. **Times.** Triple-click Start time, type `3:15 PM`, press Tab. Focus lands on End time with its
   text selected. Type the end time and press Tab.
8. **Check.** Screenshot the form. Read the widget values with `javascript_tool` and compare them
   with the planned row: `Category`, `JobCardID`, `VsoTaskID`, `StartTime`, `EndTime`, `Billable`.
9. **Save.** Click Save.
10. **Confirm.** A good save reloads the grid and clears Description, Job and VSO Task. Category,
    Billable and the times keep their last values. The Category list pops open, so press Escape.
    Check the grid row count went up by one.

A failed save shows an error toast carrying the server's message. Stop and report it. Do not retry
blindly.

## Traps

- **Create Task sits under the VSO Task field.** The Find Task and Create Task buttons lie right
  below it. If the dropdown closes before a click lands, the click opens the Create Task Window.
  Close it with its X. Never press its Save, because that creates a work item in Azure DevOps.
- **A Job with no VSO Task still saves.** The request goes out first. Then a random "task missing"
  toast appears. Treat a job entry without a task as incomplete and ask for the task.
- **Overlap rules on the server are unverified.** Never save a row that overlaps a captured one.
  Check `entries` first.
- **Existing rows are not yours to change.** Editing, copying, splitting or deleting a captured
  row needs its own explicit request.
- **Output filtering.** The browser tool blanks results that look like cookies, query strings or
  base64. Return arrays of values, as the snapshot does, not raw source or `key=value` text.
- **Frozen renderer.** After many actions the tab can stop answering screenshots. Wait, call
  `tabs_context_mcp` again, and retry. Never work around it with JS writes.
- **Sign-in.** If the page shows a login screen, stop and ask the user to sign in. Never type
  credentials.
- **Typing goes nowhere after opening a dropdown.** Keys only reach the filter box once it has been
  clicked. It sits about 29px below its field.
- **The filter box keeps its old text.** Typing appends, so `Development` becomes
  `LunchDevelopment` and the top match is some unrelated category. Triple-click the box first, then
  check `dataSource.view()[0]` is the intended item before pressing Return.
- **Return alone picks the placeholder.** The first row is `Select...`, so press Down before Return.
- **`ctrl+a` types a literal `a`** in the textarea. Triple-click instead.
- **Billable carries over.** After a billable save the next form still has it ticked. A no-job row
  must be unticked by hand. The Lunch category unticks it and fills in `Lunch` by itself.
- **The Category popup reports open during its close animation.** `popup.visible()` stays true for
  about a second after Escape. Check the row count, not the popup, to confirm a save.
- **Filters lag.** The in-page filter can take over a second to apply. A guard that reads
  `dataSource.view()` too early sees the unfiltered list, so wait or re-read before failing.
- **Guard every step.** Batch each entry as: fill, a read-only JS check that throws on any
  mismatch, screenshot, Save, Escape, row-count check. A throw halts the batch before a bad save.

## Categories

Live list read on 2026-09-30. Re-read it with the snapshot rather than trusting this table.
`J` marks a category that takes a job (`takes_job`). Every other category disables the Job field.

| ID | Category | J | Typical use |
|---|---|---|---|
| 5 | Development | P | Writing or changing code, schema, scripts |
| 57 | Development Operations | | Email and Teams catch-up, branch and PR admin, deployments, environments |
| 74 | Code Review | P | Reviewing someone else's PR, acting on review comments |
| 36 | Scrum | P | Daily scrum and alignment meetings |
| 20 | Support | P | Live issues, client-reported faults |
| 42 | Testing and Docs | P | Manual test passes, writing docs |
| 53 | Business Analysis | P | Working out requirements, speccing |
| 13 | Research | P | Reading code or docs to answer a question, no change made |
| 19 | Project Management | P | Planning, status reporting, estimates |
| 75 | UI/UX Design | P | Design work with no code change |
| 82 | Dev check-ins / Buddy sessions | | 1:1s, pairing |
| 49 | Knowledge Transfer | P | Explaining a system to someone |
| 40 | Upskilling | P | Learning, courses |
| 60 | R&D | | Exploratory work |
| 11 | Lunch | | The midday break |
| 12 | Smoke | | Short breaks |
| 39 | Time Capturing | | Filling in this timesheet |

The rest cover leave, internal streams and admin. They are Academic Classes (56), Annual Leave
(23), Ark Property Group (77), CarbonPixel (84), Client Presentation (27), Deliver Training (28),
Family Responsibility Leave (70), General (1), Heart of Ark (78), HR Consulting (71),
IT Support (31), Load Shedding (47), Marketing (58), Maternity leave (68), Mentorship (73),
Oculux (79), Office Admin (2), Operations and Management (32), Overtime Leave (55),
Paternity leave (69), Pool, Padel & Social (80), Property Group (76), Receive Training (35),
Sales, Marketing, Quoting, Networking (21), Sick Leave (18), Staff Meeting (37), Study Leave (38),
Time Review (72), Travel (8) and Unpaid/Personal Leave (33). Of these, only Client Presentation,
Deliver Training, IT Support, Operations and Management, Sales and Travel take a job.

A session often spans two categories. Reviewing a stored procedure someone wrote, then rewriting
it, is Code Review followed by Development. Split on what the work was, not on which session it
sat in.

## Billable

Picking a Job ticks Billable. A row with no Job is not billable. Some users untick Billable on
job rows, for example rework on their own bug. Follow the user's recent history, and list every
unticked job row under "Needs your input".

## Descriptions

Write what a reviewer or the client needs months later: the system and the change. Match the
user's own voice from their recent rows. One sentence, occasionally two.
