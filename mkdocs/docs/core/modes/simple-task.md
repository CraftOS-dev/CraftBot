# Quick requests

Most day-to-day requests fit in a short answer or one to three actions: look something up, send one message, convert one file. For these, the agent skips all ceremony. There is no todo list, no requirement contract, and no planning step. It does the work, delivers the result, and the delivery itself ends the run. This page is the complete behavior reference for that path; for the guided version, see [Your first task](../../start/first-task.md).

## When a request stays quick

Nothing is chosen up front. The agent simply keeps the process minimal when all of these hold:

- The work is completable in roughly 1-3 actions (a weather lookup, a calculation, a single search-and-summarize, one message send).
- The result **is** the reply, with no file or artifact you need to review.
- Nothing irreversible happens externally (no purchases, no destructive writes).

Anything heavier gets the full [substantial work](complex-task.md) treatment: a requirement contract, a todo plan, and verification.

## Lifecycle

```
trigger (your message)
        │
        ▼
execute the 1-3 work actions       ← may be parallel in one turn
        │
        ▼
send_message                       ← the result; final message, ends the run
```

Rules the agent follows on this path:

- **No todos.** Quick runs never call `update_todos` and never use phase prefixes. The work is small enough that planning would only slow it down.
- **Never ends silently after doing work.** A run that produced something always ends with a final `send_message` summarizing the result.
- **The reply is the terminator.** A `send_message` without `continue_work=true` is what ends the run; there is no separate completion action.

## When no reply is needed at all

Some inputs deserve no response: an emoji-only acknowledgement, or noise from a group-chat integration where the message isn't addressed to the agent. For these the agent calls `end_turn`, which ends the run silently. `end_turn` is only for inputs that need no response; using it to skip a deserved reply is a hard rule violation, and it refuses to fire while a Living UI project is still building.

## What the agent can do inside a quick run

Any loaded action is callable on any turn, and the agent can expand or shrink its own action surface in place: `add_action_sets` / `remove_action_sets` load and unload action-set bundles, and `use_skill` / `unload_skill` do the same for skills, all mid-run. The new actions appear in the next turn's prompt. So a quick request that needs one integration action is still quick: the agent loads the set, fires the action, and replies. See [Actions and action sets](../concepts/actions-and-action-sets.md) and [Skills](../concepts/skills.md).

To spin off separate work without holding up the reply, the agent uses `schedule_task` with `schedule="immediate"`, which queues a trigger that starts its own run within seconds.

## Follow-ups

There is no waiting state. Once the final message lands, the session sleeps. Your next message wakes a **new run in the same session**, and the session's event stream carries the full context over, so "actually, make that Celsius" just works. See [Sessions](../concepts/task-sessions.md).

## When the work grows mid-run

Nothing is locked in at the start, so a request that turns out bigger than it looked doesn't need to be restarted or handed off. The agent scales up in place: it locks the deliverable with `set_requirement`, sends a one-line acknowledgement (`send_message` with `continue_work=true`), lays out a phase-prefixed plan with `update_todos`, and continues as [substantial work](complex-task.md). Independent side-work it discovers along the way gets spun off with `schedule_task(schedule="immediate", ...)` as its own run.

## Limits and failure paths

Quick runs sit on the same safety machinery as everything else, even though they rarely hit it:

- **Per-run counters.** Every run tracks `action_count` and `token_count` against `max_actions_per_task` and `max_tokens_per_task` (defaults 150 actions and 6,000,000 tokens, in `agent_core/core/state/types.py`). At 100% of either, the run pauses and you get a Continue/Stop choice in chat. Details in [Substantial work](complex-task.md#action-and-token-limits).
- **Errors.** Failed actions return `status: "error"` and the agent adapts: one retry for transient failures, a changed approach otherwise. If it can't recover, the final message tells you what failed and why.
- **Fatal LLM failures.** Repeated consecutive LLM call failures (bad key, exhausted credits) halt the run to prevent infinite retries. You'll see a clear error message, and sending any new chat message (for example "continue") resumes normally once the provider configuration is fixed. See [LLM providers](../providers/llm.md).

## Observing a quick run

| Where | What you see |
|---|---|
| Chat | The final reply (and nothing else: no narration, no status pings) |
| Action panel | Each action with inputs and results, nothing hidden |
| `agent_file_system/EVENT.md` | The main session's full event log |
| `logs/<run>/all.log` | Grep `[REACT]` for the run flow, `[ACTION]` for execution |

More on logs in [Logs](../concepts/logs.md).

## Related

- [Substantial work](complex-task.md): the path for everything that needs a plan
- [Runs overview](index.md): how the agent scales its process
- [Sessions](../concepts/task-sessions.md): reply routing and parallel sessions
- [Agent loop](../concepts/agent-loop.md): the shared turn cycle
