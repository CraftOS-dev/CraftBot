# Scheduling

Scheduling is how CraftBot works while you're not at the keyboard: a reminder at 3pm, a briefing every Monday, the nightly memory job. You create schedules by asking in chat. The agent stores them, and the scheduler turns each one into a run at the right moment.

## Overview
A schedule is three things: a **name**, an **instruction** (what the agent should do), and a **schedule expression** (when). All of them live in one JSON file, `app/config/scheduler_config.json`, alongside the system schedules CraftBot ships with.

At runtime, the scheduler (`app/scheduler/manager.py`) runs one background loop per enabled schedule. Each loop computes the next fire time, sleeps until then, and fires. "Firing" doesn't run anything directly. It emits a **trigger** into the same queue that your chat messages go through, and the agent loop picks it up and executes the instruction as a normal task in the schedule's declared mode (`simple` or `complex`). Everything downstream (todos, actions, task completion) works exactly like a task you started by hand. How triggers are queued and routed is covered in [Triggers](triggers.md).

One sibling system to keep separate: **recurring proactive tasks** live in `agent_file_system/PROACTIVE.md` and are executed by the proactive heartbeat, with their own permission tiers and planning cycle. Rule of thumb: "do X at this exact time" is a schedule, while "keep doing X hourly/daily/weekly under proactive governance" is a recurring proactive task. The scheduler is what *drives* proactive mode (see [system schedules](#system-schedules) below), but the two are configured differently. See [Proactive mode](../modes/proactive.md).

## Schedule expressions

The parser (`app/scheduler/parser.py`) accepts a fixed set of patterns, nothing freeform:

| Type | Write it as | Examples |
|---|---|---|
| Immediate | `immediate` | run right now, once |
| One-time | `at <time>`, `at <time> today`, `tomorrow at <time>`, `in N hours`, `in N minutes` | `at 3pm`, `at 3:30pm today`, `tomorrow at 9am`, `in 2 hours` |
| Daily | `every day at <time>` | `every day at 7am`, `every day at 3:30pm` |
| Weekly | `every <weekday> at <time>` | `every monday at 9am` |
| Interval | `every N hours`, `every N minutes` | `every 3 hours`, `every 30 minutes` |
| Cron | 5-field cron | `0 7 * * *`, `0 8 * * 1-5` |

Three things to know:

- **Exact patterns only.** `daily at 8`, `every weekday`, `every morning` are rejected. Anything the natural-language patterns can't express (weekdays-only, twice a day, first of the month) is expressible as cron (`0 8 * * 1-5`, `0,30 * * * *`, `0 8 1 * *`).
- **Times include am/pm** (`9am`, `3:30pm`) unless you use 24-hour cron.
- **All times are machine-local.** The scheduler uses the local clock of the machine CraftBot runs on.

You rarely type these yourself. The agent translates your request into a valid expression, and invalid ones are rejected at creation time with the supported formats listed.

## Creating schedules from chat

Just ask. There is no command:

```
Remind me in 30 minutes to take the bread out of the oven.
```

The agent calls the `schedule_task` action with `schedule: "in 30 minutes"` and an instruction like "Remind the user to take the bread out of the oven". A one-time schedule is created and **auto-removed after it fires**.

```
Every weekday at 8am, summarize my unread email and message me on Telegram.
```

"Weekday" isn't a supported phrase, so the agent expresses it as cron: `0 8 * * 1-5`. This becomes a recurring schedule that fires until you remove it.

What `schedule_task` records, beyond name/instruction/schedule:

| Field | Default | Meaning |
|---|---|---|
| `priority` | `50` | Trigger priority; lower fires first when multiple triggers are due |
| `enabled` | `true` | Created paused if `false` |
| `action_sets` / `skills` | none | Pre-load specific capabilities for the run (`core` covers most work) |
| `payload` | `{}` | Extra context passed into the run's trigger |

The spawned run scales itself to the instruction — see [Runs](../modes/index.md).

## Managing schedules

All from chat, each backed by an action:

| You say | Action | What happens |
|---|---|---|
| "What do you have scheduled?" | `scheduled_task_list` | Every schedule with its ID, expression, enabled state, last/next run time, and run count |
| "Pause the morning briefing" | `schedule_task_toggle` | Disables (or re-enables) by ID — the schedule stays in config, its loop stops |
| "Delete the bread reminder" | `remove_scheduled_task` | Removes it permanently |

For recurring **proactive** tasks in `PROACTIVE.md`, the equivalent actions are `recurring_add` (name, `hourly`/`daily`/`weekly`/`monthly` frequency, instruction, time/day, permission tier), `recurring_read` to list them, `recurring_update_task` to change or pause one, and `recurring_remove` to delete it. The agent asks for your consent before adding one. Same conversational surface: "show my recurring tasks", "disable the morning briefing habit".

## What happens when a schedule fires

Each fire creates a fresh session (`scheduled_<id>_<timestamp>`) and emits a trigger with a typed source: `SCHEDULED` for a recurring fire, `SCHEDULED_ONCE` for a one-time task, `SCHEDULED_IMMEDIATE` for `immediate`. Fires are emitted durably with **dedup keys** (a recurring fire is keyed to its scheduled minute, a one-time task to its ID), so a crash and retry can't run the same fire twice, and a one-time task can never double-execute (for example, an email sent twice). After a one-time task fires, it's deleted from the config. Recurring tasks update their `last_run`/`run_count` and go back to sleep until the next occurrence.

## If CraftBot was offline

Schedules only fire while CraftBot runs, which is the main argument for [service mode](../../start/service-mode.md). When it comes back up:

- **Recurring schedules are not back-filled.** The loop computes the next occurrence from *now*. A missed 7am briefing simply waits for tomorrow's 7am.
- **One-time schedules still fire.** The absolute fire time is persisted, so restarts can't push it forward. If it fires more than two minutes late, it runs as a **catch-up**: the executing agent is told when it was originally due and how late it is, and uses judgment. It proceeds if slightly late, confirms with you if the action is time-sensitive or irreversible, and skips if no longer relevant.
- **Already-fired one-time tasks are skipped** at startup even if a crash prevented their cleanup.

## System schedules

CraftBot ships with five schedules in `scheduler_config.json`. They power memory and proactive mode:

| ID | When | What |
|---|---|---|
| `memory-processing` | every day at 3am | Distills unprocessed events into long-term memory — see [Memory](memory.md) |
| `heartbeat` | `0,30 * * * *` (every half hour) | Executes due recurring tasks from `PROACTIVE.md` |
| `day-planner` | every day at 7am | Plans today's proactive tasks |
| `week-planner` | every Sunday at 5pm | Weekly proactive planning |
| `month-planner` | `0 8 1 * *` (1st of month, 8am) | Monthly proactive planning |

These are ordinary schedules (they show up in `scheduled_task_list` and can be toggled like any other), but disabling them switches off the corresponding subsystem: disabling `memory-processing` stops memory distillation, and disabling `heartbeat` stops recurring proactive tasks.

## Configuration and limits

- **File:** `app/config/scheduler_config.json`. Top-level `enabled` is the master switch. Each entry carries `id`, `name`, `instruction`, `schedule`, `enabled`, `priority`, `mode`, `recurring`, `action_sets`, `skills`, `payload`.
- **Hot reload.** The file is watched. Edits (yours or the agent's) are picked up without a restart. Invalid entries are skipped with a warning rather than breaking the rest.
- **Observing.** Scheduler activity is tagged `[SCHEDULER]` in the run logs: loop start, sleep-until times, every fire. See [Logs](logs.md).
- **Interval semantics.** `every 30 minutes` counts from startup/creation, not from clock boundaries. Use cron (`0,30 * * * *`) for clock-aligned runs.

## Next

- [Proactive mode](../modes/proactive.md): recurring tasks, permission tiers, and the planning cycle the system schedules drive
- [Service mode](../../start/service-mode.md): keep CraftBot alive so schedules actually fire
- [Triggers](triggers.md): the queue that fired schedules flow through
