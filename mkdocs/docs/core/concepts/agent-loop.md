# Agent loop

The agent loop is the cycle CraftBot runs every time something wakes it up: claim a [trigger](triggers.md), fold in everything else that's due, let the LLM pick actions, execute them, and queue the follow-up. This cycle explains why runs tick forward one step at a time, why the agent can wait days for your reply without burning tokens, and why a restart doesn't lose work in flight.

## Overview
CraftBot does not run continuously. The agent sleeps until a trigger fires (your message, a schedule, a run's own "continue" note) then runs **exactly one turn** and goes back to sleep. The design has three properties:

1. **One trigger batch, one turn.** A turn is a single pass through the loop: the LLM picks one or more [actions](actions-and-action-sets.md), CraftBot executes them, and the results land on the [event stream](event-stream.md). Everything due for the session at that moment folds into the same turn (see [Triggers](triggers.md)).
2. **Continuation is a new trigger, not a loop.** A ten-step run is not a `while` loop held in memory. Each turn that doesn't end the run enqueues a fresh `run_continuation` trigger for the same session. The next turn picks it up. Waiting is just a trigger with a `fire_at` timestamp in the future.
3. **State lives outside the process.** Progress is recorded in the session's todos, its event stream, and the durable trigger queue, so a crash or restart between turns re-delivers the pending trigger and the run resumes where it left off.

This is also why several sessions can run "at once": each [session](task-sessions.md) has its own trigger queue and its own serial consumer loop, and their turns interleave (up to 3 turns execute concurrently across sessions, one at a time within each).

## The outer loop

Each session's consumer loop drives its turns:

| Step | What happens |
|---|---|
| 1. Claim | The loop waits for the next due trigger in its session's queue, drains everything else already due, and merges the batch into one turn; all merged rows are marked claimed |
| 2. React | `agent.react(trigger)` runs one full turn (everything below) |
| 3. Settle | On success the trigger rows are `ack()`ed (done); on an exception they are `nack()`ed, which retries them with backoff |

A crash between claim and settle leaves the triggers claimed. The next boot re-delivers them. The guarantee is *at-least-once*, never silently lost. The details are on the [Triggers](triggers.md) page.

!!! note "Implementation files"
    The per-session consumer loops are `SessionRuntimeManager` in `app/triggers/runtime.py` (batch merging is `_merge_triggers` in the same file). The turn itself is `AgentBase.react()` in `app/agent_base.py`. Claim/ack/nack live in `app/triggers/service.py`.

## Inside a turn: react()

`react()` runs a fixed sequence — there is no routing and no per-task workflow fork; every turn goes through the same pipeline:

| Order | Step | What happens |
|---|---|---|
| 1 | Restart notice | If the trigger is a restart notice, the prebuilt "I was restarted" message goes to chat and the turn returns — no LLM call |
| 2 | Resolve the session | The trigger's `session_id` names its session directly |
| 3 | Workflow pre-check | For `memory` / `proactive_*` triggers: skip the turn if no work is due; otherwise load the workflow's skills and action sets onto the session for this run (see [Special workflows](../modes/special-workflows.md)) |
| 4 | Announce | The turn's cause — or the aggregated checklist of causes — is logged onto the event stream, along with any queued user messages |
| 5 | Run bookkeeping | If the trigger starts a new run (a user message, a schedule — anything but a continuation), the run's budgets and state are reset |
| 6 | Pipeline | select → prepare → execute → finalize (below) |

## The turn pipeline

Every turn — main session, chat session, or Living UI session — runs the same four phases:

1. **Select.** One LLM call chooses one or more actions and their inputs, based on the trigger, the current requirements and todos, and the event stream.
2. **Prepare.** Each selected action is resolved by name from the session's loaded action sets and its inputs are bound.
3. **Execute.** The actions run, in parallel when more than one was selected (up to 10 per batch). Every action logs `action_start` / `action_end` events, which is what the action panel in the browser renders live.
4. **Finalize.** The turn's outcome decides the run's fate: if every executed action was terminal — a final `send_message` (without `continue_work=true`) or `end_turn` — the run ends and the session goes idle. Otherwise a **new `run_continuation` trigger** is enqueued for the session and the next turn follows.

The finalize phase drives multi-step work. A run making twenty tool calls is roughly twenty turns, each handed to the next by a continuation trigger. Between turns the agent is idle, free to run a different session's turn or to sleep.

## What happens when you send a message

Putting it together, end to end:

1. Your message is durably recorded as a `user_message` trigger for the [session](task-sessions.md) you typed it in. Messages arriving from a connected platform land in the main session.
2. The session's loop claims it — together with anything else due for that session — and calls `react()`.
3. A new run starts. For a quick request the agent just answers: the final `send_message` ends the run. For substantial work it records requirements, acknowledges you, plans todos, and works turn by turn (see [How runs scale](../modes/index.md)).
4. If the agent needs your answer before it can continue, it asks the question as its final message. The run ends and the session sleeps at zero cost. Your reply wakes a **new run in the same session** — the shared event stream carries the context over.

## Watch it run

- **In the browser.** The chat, todo list, and action panel are a live rendering of the loop: each visible action is one entry in a turn's execute phase.
- **In the logs.** Every app start writes a folder under `logs/` ([Logs](logs.md)). Grep for the loop's own tags:

```bash
grep -E "\[REACT\]|\[ACTION\]|SessionRuntime" logs/<run>/all.log
```

```text
[SessionRuntime] Loop started for session main
[REACT] starting...
[ACTION] Ready to run 1 action(s): ['send_message']
[SessionRuntime] Aggregated 2 queued trigger(s) (user_message, run_continuation) into one turn for main
```

- **On disk.** Every event a turn produces is also appended to `agent_file_system/EVENT.md` ([Event stream](event-stream.md)).

## Limits and error handling

- **Per-run budgets.** Each run counts its actions and tokens. At 100% of either limit the run pauses and you get a Continue/Stop choice in chat; picking Continue resets the counters and the run resumes on the next trigger. Token accounting bills only *uncached* tokens, so warm-cache runs go much further than raw usage suggests.
- **Waiting costs nothing.** A run that ends with a question leaves nothing scheduled and invokes no LLM while it waits — the next message simply wakes the session.
- **Force-stop.** You can stop a run from the UI: the in-flight turn is cancelled, child processes are killed, and queued continuation triggers are purged. Queued user messages and schedules stay. The next message starts a fresh run.
- **Errors don't kill the loop.** Exceptions inside a turn are caught by `react()` itself, logged, and surfaced to the affected session. The session's loop keeps running. Failures that escape a turn entirely cause a `nack()`: retry with exponential backoff, then a dead-letter message in chat rather than silent loss (see [Triggers](triggers.md)).
- **Feature switches.** Disabling memory or proactive mode in settings makes their triggers no-ops: the workflow pre-check (step 3 above) returns without doing anything.

## Next

- [Triggers](triggers.md): everything that wakes the loop, and what survives a restart
- [Sessions](task-sessions.md): the lanes runs execute in, and what each one owns
- [Event stream](event-stream.md): the record each turn reads from and writes to
- [How runs scale](../modes/index.md): quick requests vs substantial work, compared
