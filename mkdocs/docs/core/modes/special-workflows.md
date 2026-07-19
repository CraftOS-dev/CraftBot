# Special workflows

Two kinds of turns are never started by a user message: **memory processing** and **proactive processing**. They arrive as typed triggers from the scheduler, are checked *before* any task or conversation routing in the agent loop, and each one does the same thing: it creates an ordinary simple task loaded with a dedicated skill, then lets the normal task machinery do the work.

This page covers the mechanics. For what the memory pipeline actually distills, see [Memory](../concepts/memory.md). For the full user guide to proactive behavior, see [Proactive](proactive.md).

## How they differ from user tasks

| | User task | Special workflow task |
|---|---|---|
| Started by | Your message → `task_start` | Scheduler trigger → handler creates the task |
| Trigger type | Untyped / message payload | `memory_processing`, `proactive_heartbeat`, `proactive_planner` |
| Acknowledgement | Agent acknowledges you | None — silent by design |
| Approval gate | Complex tasks wait for you | Never waits; ends silently with `task_end` |
| Enable switch | Always on | `memory.enabled` / `proactive.enabled` in settings |
| Concurrency | Parallel tasks allowed | A workflow lock blocks overlapping runs |

The silence is deliberate and comes from the skills these tasks load: their instructions explicitly override the normal "acknowledge immediately, confirm before ending" rules, because a background run that waited for confirmation every 30 minutes would pile up forever. The one exception: a planner that wants to *suggest* a new recurring task does message you and waits for approval (see [Proactive](proactive.md#the-approval-model)).

You can still watch these tasks like any other: they appear in the task panel (named `Heartbeat`, `Day Planner`, ...), their actions show in the action panel, they append to `TASK_HISTORY.md`, and they log under the `[MEMORY]` and `[PROACTIVE]` tags in `logs/<run>/main.log`.

## The memory workflow

Fires when a trigger carries `type: "memory_processing"`. By default that is the scheduler entry `memory-processing` (`every day at 3am` in `app/config/scheduler_config.json`), plus a one-off replay at startup if `EVENT_UNPROCESSED.md` still holds unprocessed events from before the last shutdown.

The handler runs a short checklist before creating anything:

1. **Enabled?** If `memory.enabled` is off in settings, skip.
2. **Anything to do?** If `EVENT_UNPROCESSED.md` is missing or holds no event lines, skip.
3. **Already running?** A `memory_processing` workflow lock guarantees one run at a time. If a slow previous run is still going when the trigger fires, the new trigger is dropped and the next scheduled fire picks up the work.
4. **Pruning needed?** If `MEMORY.md` has grown past its configured maximum item count, the run also gets a pruning phase.

It then creates a simple-mode task with the `memory-processor` skill. That task reads `EVENT_UNPROCESSED.md`, scores each event for long-term value, checks for duplicates, writes the keepers to `MEMORY.md`, and clears the buffer. While it runs, the event stream sets a skip flag so the memory task's own events don't loop back into the unprocessed buffer; the flag and the lock are both released when the task ends. The distillation semantics (what gets kept, the fact format, pruning) are covered in [Memory](../concepts/memory.md).

## The proactive workflow

Fires when a trigger carries `type: "proactive_heartbeat"` or `"proactive_planner"`. Both are skipped entirely when `proactive.enabled` is off in settings. Two variants:

### Heartbeat

The scheduler fires it every 30 minutes, at `:00` and `:30` (cron `0,30 * * * *`). The handler collects every due recurring task from `PROACTIVE.md` across all frequencies (hourly, daily, weekly, monthly). If nothing is due, it returns silently and no task is created. Otherwise it creates **one** unified simple-mode task named `Heartbeat`, with action sets `file_operations`, `proactive`, `web_research` and the `heartbeat-processor` skill. The instruction summarizes what's due (e.g. "Due tasks: 2 daily, 1 weekly (3 total)"), and the task executes each due item and records its outcome.

### Planner

Three scheduler entries fire it: `day-planner` (every day at 7 AM), `week-planner` (every Sunday at 5 PM), and `month-planner` (the 1st of the month at 8 AM). Each creates a simple-mode task named `Day Planner` / `Week Planner` / `Month Planner` with action sets `file_operations`, `proactive` and the matching `day-planner` / `week-planner` / `month-planner` skill. The planner reviews recent interactions and updates the Goals / Plan / Status section of `PROACTIVE.md`. Rarely, and only with your approval, it proposes new recurring tasks.

## Trigger routing summary

| Trigger `type` | Handler | Creates | Skipped when |
|---|---|---|---|
| `memory_processing` | Memory workflow | Simple task, `memory-processor` skill | Memory disabled, no events, or lock held |
| `proactive_heartbeat` | Proactive heartbeat | One `Heartbeat` simple task | Proactive disabled, or nothing due |
| `proactive_planner` | Proactive planner | `<Scope> Planner` simple task | Proactive disabled |
| anything else | Normal routing | — | — |

All schedules live in `app/config/scheduler_config.json` and can be toggled individually (see [Scheduling](../concepts/scheduling.md)). Because they're clock-driven, none of them fire while CraftBot isn't running. For reliable nightly and weekend runs, keep the agent up via [service mode](../../start/service-mode.md).

## Related

- [Proactive](proactive.md): the full guide: PROACTIVE.md format, permission tiers, the approval model
- [Memory](../concepts/memory.md): what the memory task actually does with your events
- [Triggers](../concepts/triggers.md): trigger anatomy and the priority queue
- [Agent loop](../concepts/agent-loop.md): where the short-circuit routing lives
