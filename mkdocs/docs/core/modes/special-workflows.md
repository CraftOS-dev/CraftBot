# Workflow runs

Some runs are never started by a user message: **memory processing**, the **proactive heartbeat**, and the **proactive planners**. They arrive as typed triggers from the scheduler and run **in the main session**, like any other run, with one twist: at run start the workflow's dedicated skill and action sets are loaded onto the session, and at run end they are unloaded again, so the main session's prompt doesn't accumulate background skills permanently.

This page covers the mechanics. For what the memory pipeline actually distills, see [Memory](../concepts/memory.md). For the full user guide to proactive behavior, see [Proactive](proactive.md).

## How they differ from your runs

| | Run from your message | Workflow run |
|---|---|---|
| Started by | Your message | Scheduler trigger |
| Trigger source | `USER_MESSAGE` | `MEMORY`, `PROACTIVE_HEARTBEAT`, `PROACTIVE_PLANNER` |
| Capabilities | Whatever the agent loads as it works | Workflow skill + action sets, loaded for the run, unloaded at run end |
| Acknowledgement | Agent acknowledges you | None: silent by design |
| Run end | Final `send_message` delivers to you | `end_turn`, or a tier-1 notification as the final message |
| Enable switch | Always on | `memory.enabled` / `proactive.enabled` in settings |
| Concurrency | Per-session serialization | The same per-session serialization: the main session runs one turn at a time, and everything due folds into the next turn |

Before a workflow run starts, a **pre-check** decides whether there is anything to do. If not (memory disabled, empty buffer, no due proactive tasks), the turn is skipped entirely and no run happens. If the aggregated trigger batch also carried user messages, those are still processed; workflow triggers never swallow your input.

The silence is deliberate and comes from the skills these runs load: their instructions explicitly override the normal "acknowledge immediately" communication rules, because a background run that messaged you every 30 minutes would be noise. The one exception: a planner that wants to *suggest* a new recurring task does message you, as a question that ends its run (see [Proactive](proactive.md#the-approval-model)).

You can still watch these runs like any other: their actions show in the action panel, their events land in the main session's stream, and they log under the `[MEMORY]` and `[PROACTIVE]` tags in `logs/<run>/all.log`.

## The memory workflow

Fires on a `MEMORY`-source trigger. By default that is the scheduler entry `memory-processing` (`every day at 3am` in `app/config/scheduler_config.json`), plus a one-off replay at startup if `EVENT_UNPROCESSED.md` still holds unprocessed events from before the last shutdown.

The pre-check runs a short checklist before starting anything:

1. **Enabled?** If `memory.enabled` is off in settings, skip.
2. **Anything to do?** If `EVENT_UNPROCESSED.md` is missing or holds no event lines, skip.
3. **Pruning needed?** If `MEMORY.md` has grown past its configured maximum item count, the pruning instruction is folded into the same run.

The run then loads the `memory-processor` skill (with the `file_operations` action set). It reads `EVENT_UNPROCESSED.md`, scores each event for long-term value, checks for duplicates, writes the keepers to `MEMORY.md`, and clears the buffer. While it runs, the event stream sets a skip flag so the run's own events don't loop back into the unprocessed buffer; the flag resets when the run ends. The distillation semantics (what gets kept, the fact format, pruning) are covered in [Memory](../concepts/memory.md).

## The proactive workflow

Fires on `PROACTIVE_HEARTBEAT` or `PROACTIVE_PLANNER` triggers. Both are skipped entirely when `proactive.enabled` is off in settings. Two variants:

### Heartbeat

The scheduler fires it every 30 minutes, at `:00` and `:30` (cron `0,30 * * * *`). The pre-check collects every due recurring task from `PROACTIVE.md` across all frequencies (hourly, daily, weekly, monthly). If nothing is due, the turn is skipped and no run happens. Otherwise **one** heartbeat run starts, loaded with the `heartbeat-processor` skill and the action sets `file_operations`, `proactive`, `web_research`. Its instruction summarizes what's due (e.g. "Due tasks: 2 daily, 1 weekly (3 total)"), and the run executes each due item: quick tier-0/1 items inline, heavier items spun off as their own runs via `schedule_task(schedule="immediate", ...)`. Each item's outcome is recorded to its `outcome_history` via `recurring_update_task`, and the run ends with `end_turn` or with a tier-1 notification as its final message.

### Planner

Three scheduler entries fire it: `day-planner` (every day at 7 AM), `week-planner` (every Sunday at 5 PM), and `month-planner` (the 1st of the month at 8 AM). Each starts a run loaded with the matching `day-planner` / `week-planner` / `month-planner` skill plus the `file_operations` and `proactive` action sets (a planner skill can declare more, e.g. the day planner also pulls in scheduler, calendar, and web access). The planner reviews recent interactions and updates the Goals / Plan / Status section of `PROACTIVE.md`. Rarely, and only with your approval, it proposes new recurring tasks.

## Trigger routing summary

| Trigger source | Loads | Skipped when |
|---|---|---|
| `MEMORY` | `memory-processor` skill + `file_operations` | Memory disabled, or no unprocessed events |
| `PROACTIVE_HEARTBEAT` | `heartbeat-processor` + `file_operations`, `proactive`, `web_research` | Proactive disabled, or nothing due |
| `PROACTIVE_PLANNER` | `<scope>-planner` + `file_operations`, `proactive` | Proactive disabled |
| anything else | Normal run, nothing pre-loaded | never pre-checked |

All schedules live in `app/config/scheduler_config.json` and can be toggled individually (see [Scheduling](../concepts/scheduling.md)). Because they're clock-driven, none of them fire while CraftBot isn't running. For reliable nightly and weekend runs, keep the agent up via [service mode](../../start/service-mode.md).

## Related

- [Proactive](proactive.md): the full guide: PROACTIVE.md format, permission tiers, the approval model
- [Memory](../concepts/memory.md): what the memory run actually does with your events
- [Triggers](../concepts/triggers.md): trigger anatomy and per-session queues
- [Agent loop](../concepts/agent-loop.md): where the workflow pre-check lives
