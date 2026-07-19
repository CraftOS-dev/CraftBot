# Simple task mode

Simple task mode is CraftBot's lightweight path for work that fits in two or three actions: look something up, send one message, convert one file. There is no todo list, no planning step, and no approval gate. The agent does the work, delivers the result, and ends the task by itself. Most day-to-day requests run this way.

For the guided version, see [Your first task](../../start/first-task.md#walkthrough-1-a-simple-task). This page is the complete behavior reference.

## When the agent picks simple

The mode is chosen once, when the agent calls `task_start` with `task_mode: "simple"`. You don't set it, and it doesn't change for the task's lifetime. The agent is trained to pick simple when all of these hold:

- The work is completable in roughly 2–3 actions (weather lookup, calculation, a single search-and-summarize, one message send).
- The result **is** the reply, with no file or artifact you need to review.
- Nothing irreversible happens externally (no purchases, no destructive writes).

Anything heavier routes to [complex task](complex-task.md) instead. If the agent guessed wrong and answered actionable work in plain conversation, phrase the request as a deliverable and it will start a task.

## Lifecycle

```
task_start(task_mode="simple")     ← from conversation mode
        │
        ▼
(optional) send_message            ← brief acknowledgement
        │
        ▼
execute the 1–3 work actions       ← may be parallel in one turn
        │
        ▼
send_message                       ← deliver the result
        │
        ▼
task_end                           ← auto-completes; no approval gate
```

Rules the agent follows in this mode:

- **No todos.** Simple tasks never call `task_update_todos` and never use phase prefixes. The work is small enough that planning would only slow it down.
- **Never ends silently.** The final `send_message` with the result always precedes (or accompanies) `task_end`.
- **Auto-completion.** Unlike complex tasks, there is no confirmation step. The task card flips to completed the moment the agent calls `task_end`.

Each turn of a running simple task goes through the same four-phase beat as every other workflow (select actions, prepare them, execute them, finalize) but action selection uses a streamlined simple-task prompt with no todo-management instructions. See [Agent loop](../concepts/agent-loop.md).

## What the agent can do inside a simple task

Starting a task is what unlocks the real action surface. Conversation mode can only reply, start tasks, or ignore. At `task_start`, CraftBot automatically selects **action sets** (groups of related actions) and **skills** based on your request; those selections are locked in when the task starts. Mid-task, the agent can add or remove action sets via the `action_set_management` action, but skills cannot be swapped. A different skill means a new task. See [Actions and action sets](../concepts/actions-and-action-sets.md) and [Skills](../concepts/skills.md).

One structural limit: `task_start` cannot be called from inside a task. If a simple task needs to spawn separate work, the agent uses `schedule_task` with `schedule="immediate"` instead.

## Caching and cost

Simple tasks use **session-level prompt caching**: across the task's few turns, the context prefix is reused and only new events are appended, so multi-turn execution stays cheap. Conversation mode, by contrast, gets prefix caching only. Combined with the short action count, this makes simple tasks the fastest and cheapest way CraftBot does real work. See [Context engine](../concepts/context-engine.md).

## Waiting for you

A simple task can pause on you: if the agent sends a question with `wait_for_user_reply=true`, the task's `waiting_for_user_reply` flag is set and trigger scheduling pauses. Your next reply routes straight back into the task ([session routing](../concepts/task-sessions.md)). If no reply arrives, the agent re-queues a silent wait trigger every 3 hours, so the task idles without consuming tokens.

## When the work grows mid-task

Simple mode has a deliberate escape hatch, and it is *not* silently chaining more actions. If the agent discovers mid-task that the job is bigger than simple:

1. It stops, delivers the partial result via `send_message`, and calls `task_end`.
2. It schedules the remainder as a new complex task: `schedule_task(schedule="immediate", mode="complex", ...)`.

The task's `mode` field never changes mid-task. A task that started simple ends simple, and the heavier work gets a proper complex task with todos and an approval gate.

## Limits and failure paths

Simple tasks run on the same safety machinery as complex ones, even though they rarely hit it:

- **Per-task counters.** Every task tracks `action_count` and `token_count`. Defaults are 500 actions and 12,000,000 tokens per task (`app/config.py`). At 80% the agent gets a warning event telling it to wrap up; at 100% the task pauses and you get a Continue/Abort choice in chat. Details in [Complex task limits](complex-task.md#action-and-token-limits).
- **Errors.** Failed actions return `status: "error"` and the agent adapts (retry once for transient failures, change approach otherwise). If it can't recover, it tells you what failed and ends the task with `task_end(status="abort")`.
- **Fatal LLM failures.** Repeated consecutive LLM call failures (bad key, exhausted credits) cancel the task automatically to prevent infinite retries. You'll see a clear error dialog, and fixing the provider configuration is on you. See [LLM providers](../providers/llm.md).

## Observing a simple task

| Where | What you see |
|---|---|
| Task panel | A task card with no todo list; flips to completed on `task_end` |
| Action panel | Each action with inputs and results — nothing is hidden |
| `agent_file_system/TASK_HISTORY.md` | A summary record appended when the task ends (name, status, summary, instruction, skills, action sets) |
| `logs/<run>/main.log` | Grep `[TASK]` for lifecycle events, `[ACTION]` for execution; the simple-task workflow logs at debug level |

More on logs in [Logs](../concepts/logs.md).

## Related

- [Complex task](complex-task.md): the mode for everything that needs a plan
- [Task modes overview](index.md): the decision map
- [Task sessions](../concepts/task-sessions.md): parallel tasks and reply routing
- [Agent loop](../concepts/agent-loop.md): the shared turn cycle
