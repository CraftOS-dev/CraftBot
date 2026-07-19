# Agent loop

The agent loop is the cycle CraftBot runs every time something wakes it up: claim a [trigger](triggers.md), route it to a workflow, let the LLM pick actions, execute them, and queue the follow-up. This cycle explains why tasks tick forward one step at a time, why the agent can wait hours for your reply without burning tokens, and why a restart doesn't lose work in flight.

## Overview
CraftBot does not run continuously. The agent sleeps until a trigger fires (your message, a schedule, a task's own "continue" note) then runs **exactly one turn** and goes back to sleep. The design has three properties:

1. **One trigger, one turn.** A turn is a single pass through the loop: the LLM picks one or more [actions](actions-and-action-sets.md), CraftBot executes them, and the results land on the [event stream](event-stream.md).
2. **Continuation is a new trigger, not a loop.** A ten-step task is not a `while` loop held in memory. Each turn ends by enqueuing a fresh continuation trigger for the same session. The next turn picks it up. Waiting is just a trigger with a `fire_at` timestamp in the future.
3. **State lives outside the process.** Progress is recorded in the task's todos, its event stream, and the durable trigger queue, so a crash or restart between turns re-delivers the pending trigger and the task resumes where it left off.

This is also why several tasks can run "at once": their triggers interleave through the same loop, each turn scoped to its own [session](task-sessions.md).

## The outer loop

A single consumer drives everything:

| Step | What happens |
|---|---|
| 1. Claim | `trigger_service.next()` waits for the next due trigger and marks its durable record as claimed |
| 2. React | `agent.react(trigger)` runs one full turn (everything below) |
| 3. Settle | On success the trigger is `ack()`ed (done); on an exception it is `nack()`ed, which retries it with backoff |

A crash between claim and settle leaves the trigger claimed. The next boot re-delivers it. The guarantee is *at-least-once*, never silently lost. The details are on the [Triggers](triggers.md) page.

!!! note "Implementation files"
    The consumer is `_consume_triggers()` in `app/ui_layer/controller/ui_controller.py`. The turn itself is `AgentBase.react()` in `app/agent_base.py`. Claim/ack/nack live in `app/triggers/service.py`.

## Inside a turn: routing

`react()` checks the trigger, then the session's state, in a fixed order. First match wins:

| Order | Condition | What runs |
|---|---|---|
| 1 | Trigger is a restart notice | Posts the prebuilt "I was restarted" message to chat and returns — no LLM call |
| 2 | Trigger source is `memory` | Memory workflow — spawns a task that distills recent events into long-term [memory](memory.md) |
| 3 | Trigger source is `proactive_heartbeat` / `proactive_planner` | [Proactive](../modes/proactive.md) workflow — collects due recurring tasks or runs a planner |
| 4 | Task waiting for your reply, and this trigger carries no message | Re-schedules the wait for another 3 hours and returns — the task keeps sleeping |
| 5 | Session has a running **complex** task | Complex-task workflow — todo-driven, approval-gated |
| 6 | Session has a running **simple** task | Simple-task workflow — linear, auto-completing |
| 7 | Anything else | Conversation workflow — no task exists yet |

Before steps 4–7, the turn initializes the session and, if the trigger carries a user message routed in mid-task, records it onto the event stream so the LLM sees it.

The three main workflows (5–7) differ in prompt shape, todo handling, and caching (compared side by side in [Task modes](../modes/index.md)) but they all execute the same four-phase pipeline.

## The turn pipeline

Every conversation, simple-task, and complex-task turn runs the same four phases:

1. **Select.** One LLM call chooses one or more actions and their inputs, based on the task instruction, todos, and the event stream. In conversation mode the menu is deliberately tiny: reply, start a task (several in parallel is allowed), or deliberately ignore a message that needs no reaction.
2. **Prepare.** Each selected action is resolved by name from the task's action sets and its inputs are bound.
3. **Execute.** The actions run, in parallel when more than one was selected. Every action logs `action_start` / `action_end` events, which is what the action panel in the browser renders live.
4. **Finalize.** The action output is inspected: did it create a task? ask for a delay (`wait`)? flag `waiting_for_user_reply`? Then a **new continuation trigger** is enqueued for the session (or for each task that a parallel `task_start` created) and the turn ends.

The finalize phase drives multi-step work. A complex task making twenty tool calls is roughly twenty turns, each handed to the next by a `task_continuation` trigger. Between turns the agent is idle, free to run a different task's turn or to sleep.

## What happens when you send a message

Putting it together, end to end:

1. Your message is durably recorded, then [session routing](task-sessions.md) decides whether it continues an existing task or opens a fresh session.
2. A `user_message` trigger fires. The consumer claims it and calls `react()`.
3. No task is running for the fresh session, so the conversation workflow runs: the LLM either answers directly (`send_message`) or calls `task_start`.
4. If a task started, finalize queues a continuation trigger. Each subsequent turn works a todo, until the agent sends you a result and (for complex tasks) waits for your approval before `task_end`.
5. If the agent asked you something mid-task, the task flips to waiting-for-reply and its trigger sleeps. Your answer routes back and wakes it immediately.

## Watch it run

- **In the browser.** The task card, todo list, and action panel are a live rendering of the loop: each visible action is one entry in a turn's execute phase.
- **In the logs.** Every run writes to `logs/` ([Logs](logs.md)). Grep for the loop's own tags:

```bash
grep -E "\[REACT\]|\[WORKFLOW|\[ACTION\]|\[TRIGGER" logs/<latest>.log
```

```text
[REACT] starting...
[WORKFLOW: CONVERSATION] Query: what's the weather in Tokyo
[ACTION] Ready to run 1 action(s): ['task_start']
[TRIGGER] Creating new trigger for session: 4f2c1a
```

- **On disk.** Every event a turn produces is also appended to `agent_file_system/EVENT.md` ([Event stream](event-stream.md)).

## Limits and error handling

- **Per-task budgets.** Each task counts its actions and tokens. At 80% of either limit the agent gets a warning event telling it to wrap up. At 100% the task pauses and you get a Continue/Abort choice in chat. Nothing runs unbounded.
- **Waiting costs nothing.** A task waiting for your reply re-schedules itself in 3-hour hops without invoking the LLM (step 4 in the routing table).
- **Errors don't kill the loop.** Exceptions inside a turn are caught by `react()` itself, logged, and surfaced to the affected session. The consumer keeps running. Failures that escape a turn entirely cause a `nack()`: retry with exponential backoff, then a dead-letter message in chat rather than silent loss (see [Triggers](triggers.md)).
- **Feature switches.** Disabling memory or proactive mode in settings makes their triggers no-ops. Routing steps 2 and 3 return without doing anything.

## Next

- [Triggers](triggers.md): everything that wakes the loop, and what survives a restart
- [Task sessions](task-sessions.md): how messages find the right task, and how tasks live and end
- [Event stream](event-stream.md): the record each turn reads from and writes to
- [Task modes](../modes/index.md): conversation vs simple vs complex, compared
