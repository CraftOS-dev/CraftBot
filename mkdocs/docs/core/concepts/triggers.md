# Triggers

A trigger is the unit of "wake up and do something" in CraftBot: a small durable record saying *react to this, at this time, for this session*. Every reaction the agent ever has (your messages, schedules, task continuations, memory processing, proactive heartbeats) starts as a trigger. Understanding triggers tells you what your agent will still do after a crash, a reboot, or a week of your laptop being closed.

## Overview
The trigger system has two layers:

- **A priority queue in memory** decides *order*: the trigger with the earliest `fire_at` timestamp runs first. Ties break by `priority` (lower number wins). A trigger with `fire_at` in the future simply sleeps in the queue until its time comes. The queue holds at most one trigger per session. A newer trigger for the same session supersedes the queued one.
- **A SQLite ledger on disk** provides *durability*: every trigger is written to the store **before** it is enqueued, claimed when the [agent loop](agent-loop.md) picks it up, and settled when the turn finishes. A crash at any point between those steps means re-delivery on the next boot, not loss.

One trigger in, one turn of the agent loop out.

!!! note "Implementation files"
    The trigger dataclass is `agent_core/core/trigger.py`. The durable front door is `TriggerService` in `app/triggers/service.py`. The ledger is `app/triggers/store.py` (a `triggers` table inside `sessions.db` under the app data directory). The typed sources are `app/triggers/sources.py`.

## What creates triggers

Every producer declares a typed source, so you can always tell *why* the agent woke up:

| Source | Fired when |
|---|---|
| `user_message` | You send a message, in the browser or from a connected platform (priority 3, fires immediately) |
| `scheduled` / `scheduled_once` / `scheduled_immediate` | The [scheduler](scheduling.md) fires a recurring schedule, a one-time schedule, or a run-right-now task |
| `task_continuation` | A task turn finished and queued its next step (priority 5 for simple tasks, 7 for complex) |
| `resume` | A task restored at boot is re-woken to continue |
| `restart_notice` | First turn after a restart; delivers the consolidated "I was restarted" chat message |
| `limit_reached` | A task hit its action/token budget and is parked awaiting your Continue/Abort choice |
| `memory` | The memory-processing job is due (see [Memory](memory.md)) |
| `proactive_heartbeat` / `proactive_planner` | [Proactive mode](../modes/proactive.md) sweeps due recurring tasks or runs a day/week/month planner |
| `onboarding` | The post-install onboarding interview |
| `skill_workflow` | A skill-driven workflow step |
| `living_ui_dev` / `living_ui_crash_fix` / `living_ui_import` | Living UI build, crash-repair, and import work |

Lower `priority` numbers win a tie, so your messages (3) preempt task continuations (5–7), which preempt scheduled background work (default 50).

## Anatomy

Each trigger carries:

| Field | Purpose |
|---|---|
| `fire_at` | Unix timestamp when it becomes eligible to run |
| `priority` | Tie-breaker within the same `fire_at`; lower = sooner |
| `next_action_description` | Human-readable statement of what to do; this is what the LLM reads |
| `payload` | Context: the user message, platform, flags |
| `session_id` | Which [session/task](task-sessions.md) it belongs to |
| `waiting_for_reply` | True when the trigger exists only to keep a paused task alive |
| `source` | Typed origin from the table above |
| `id` | Row id in the durable store |

## Lifecycle and durability

The path from "something happened" to "the agent reacted" has an explicit state machine:

| Stage | Store state | What it means |
|---|---|---|
| `emit()` | `PENDING` | Written to SQLite *first*, then enqueued. From this point a crash loses nothing. |
| `next()` | `CLAIMED` | The consumer picked it up and is running the turn. |
| `ack()` | `DONE` | The turn completed. |
| `nack()` | `PENDING` again, or `DEAD` | The turn raised: retried with exponential backoff (30s, 60s, 120s… capped at 1 hour), dead-lettered after 5 attempts. |

Three additional behaviors:

- **Parking protects your messages.** An incoming chat message is durably *parked* in the store **before** the session-routing LLM call runs. If CraftBot crashes mid-routing, the parked row is re-delivered as a fresh session at next boot. The message you typed is never lost. Once routed, the parked copy is settled.
- **Dedup keys prevent double-fires.** Work whose identity predates the trigger (a schedule occurrence, a boot-time task resume) carries a dedup key. Inserting the same work twice is a database-level no-op, so a crash retry can't run your 9am schedule twice.
- **Dead letters are announced.** A trigger that exhausts its retries doesn't vanish: the agent posts a chat message ("A background task trigger failed repeatedly and was parked…") so you know work stopped and can ask it to retry.

## What happens at boot

Every start-up runs `rehydrate()` before anything else:

1. Orphaned `CLAIMED` rows (in flight when the process died) go back to `PENDING`.
2. All `PENDING` rows are loaded into the queue. This is how scheduled work, waiting tasks, and unrouted messages survive restarts.
3. Rows more than **24 hours** past due are dropped as stale (settled, not fired). A week-old "check the news at 8am" shouldn't fire seven times on Monday.
4. Rows **more than 2 minutes** overdue get a catch-up note appended to their description.

The catch-up note is what you observe as sensible behavior after downtime. The agent is told the trigger was due some time ago while CraftBot was offline and to use judgment: carry it out if it's only slightly late and still relevant, confirm with you first if it's significantly late or the action is irreversible (sending an email, posting a message), or skip it if it no longer matters.

Rehydration also garbage-collects settled rows older than 7 days, and runs *before* restored tasks re-emit their `resume` triggers so the dedup index catches duplicates.

## Observable behavior

| You see | Why |
|---|---|
| The agent replies instantly while a task runs in the background | Your `user_message` trigger (priority 3) interleaves ahead of the task's continuations |
| A scheduled task fires normally seconds after you reboot | The pending trigger rehydrated from the store |
| "This was due 3 hours ago, still want me to send it?" | The catch-up note on an overdue rehydrated trigger |
| An "I was restarted" summary message after boot | The `restart_notice` trigger |
| "A background task trigger failed repeatedly and was parked…" | Dead-letter after 5 failed attempts |
| A task silently waits days for your answer | Its `waiting_for_reply` trigger re-arms itself in 3-hour hops, no LLM involved |

To watch trigger activity directly, grep the [logs](logs.md):

```bash
grep -E "TriggerService|\[TRIGGER|\[CONSUMER\]" logs/<latest>.log
```

```text
[TriggerService] Rehydrated 3 pending trigger(s) from previous run
[CONSUMER] Trigger consumer started
[TRIGGER] Creating new trigger for session: 4f2c1a
```

## Limits

The durability policy is fixed, not user-configurable. The values are deliberate:

| Constant | Value |
|---|---|
| Retry attempts before dead-letter | 5 |
| Retry backoff | 30s doubling, capped at 1 hour |
| Catch-up note threshold | 2 minutes overdue |
| Stale drop threshold | 24 hours overdue |
| Settled-row garbage collection | 7 days |

Note that `nack()` retries cover consumer-level failures only. Errors inside a turn are handled by the [agent loop](agent-loop.md) itself and rarely consume the retry budget.

## Next

- [Agent loop](agent-loop.md): what a claimed trigger actually runs
- [Task sessions](task-sessions.md): how a `user_message` trigger finds the right task
- [Scheduling](scheduling.md): the main producer of future-dated triggers
- [Proactive mode](../modes/proactive.md): heartbeats and planners as trigger sources
