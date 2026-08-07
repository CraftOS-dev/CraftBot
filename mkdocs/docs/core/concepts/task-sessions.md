# Sessions

A **session** is one lane of work. It owns its own [event stream](event-stream.md), its own durable [trigger](triggers.md) queue, and its own workspace directory, so parallel work never leaks context between lanes. A **run** is one wake of a session: the agent works turn by turn until it delivers a final message (or ends silently), and the session then sits idle until the next input wakes it.

## Overview

- There are three kinds of session: the **main** session (external platforms, scheduled work, background workflows), **chat** sessions (the conversations you create in the browser), and **living_ui** sessions (dedicated build lanes for Living UI projects).
- Each session processes one turn at a time. Different sessions run independently and in parallel.
- Each session has a persistent scratch directory at `agent_file_system/workspace/sessions/<session_id>/`, removed only when the session is deleted.

## How your message finds its session

There is no hidden routing. The destination is explicit:

| Where you send it | Where it lands |
|---|---|
| Typed into a chat session in the browser | That session |
| Sent from a connected platform (Telegram, Slack, …) | The main session |
| Reply on a specific message bubble | The session that message belongs to |

Messages are durably parked in the trigger store before processing, so a crash can't lose them. If several inputs are waiting when a session's turn starts, they are folded into one turn as a numbered checklist — see [Triggers](triggers.md).

!!! note "Implementation files"
    Message intake is `_handle_chat_message()` in `app/agent_base.py`. Session lifecycle lives in `app/session/session_manager.py`; the per-session consumer loop is `SessionRuntimeManager` in `app/triggers/runtime.py`.

## Runs

A run starts when a trigger wakes the session (your message, a schedule, a background workflow) and advances turn by turn:

- Each turn, the agent picks one or more actions; if any of them is real work, the framework queues a continuation and the run keeps going.
- The run ends when the agent's only actions are terminal: a **final message** (one without the "still working" flag) or a silent `end_turn` for inputs that need no reply.
- A follow-up from you starts a **new run in the same session**. The event stream carries the context over, so the conversation feels continuous.

## Waiting for your reply

When the agent needs an answer, it asks the question as its final message and the run ends. An idle session costs nothing — no polling, no token spend. Your next message in that session wakes it as a new run with the question and your answer both in context. Clicking reply on the specific bubble is always unambiguous.

## Parallel work

Chat sessions let you run several conversations at once. Each session gets:

| Per-session resource | Why it matters |
|---|---|
| Its own event stream | Work in one lane never appears in another lane's context |
| Its own trigger queue | Turns are serialized within a session, interleaved fairly across sessions |
| Its own workspace dir | `agent_file_system/workspace/sessions/<session_id>/` for scratch files |
| Its own run budgets | Action and token limits are counted per run, not globally |

To spin off separate work from inside a run, the agent uses `schedule_task(schedule="immediate")` — the spun-off work executes as its own run without disturbing the current one.

## Session state

What a session carries between turns:

| State | Meaning |
|---|---|
| Loaded action sets | Which action groups the agent can use ([Actions & action sets](actions-and-action-sets.md)) |
| Loaded skills | [Skills](skills.md) whose instructions are active; load and unload mid-run |
| Todos | The visible checklist for substantial work (`update_todos`) |
| Requirements | The deliverable contract (`set_requirement`), pinned into context every turn |
| Event stream | The full per-session record everything above is read back from |

Action sets and skills are not fixed: the agent expands or shrinks its own surface mid-run (`add_action_sets`, `use_skill`, `unload_skill`), and background workflows temporarily load what they need.

## Lifecycle

1. **Created.** You create chat sessions in the browser (the main session always exists). The session gets its event stream, trigger queue, and workspace dir. Chat sessions auto-title themselves from the first exchange, and you can rename them.
2. **Active.** Runs come and go. Session state persists across runs and across restarts — sessions are restored at boot with their queued triggers intact.
3. **Cleared or deleted.** Clearing a session (`/clear`) empties its conversation. Deleting it removes the session, its stream, and its workspace directory.

## Where sessions appear in the UI

- The **session list** in the browser: one entry per chat session, with an always-visible live row while the agent is working.
- The **activity view**: each run's actions, chunked, with inputs and outputs.
- **On disk:** `agent_file_system/workspace/sessions/<session_id>/` for scratch files; `agent_file_system/EVENT.md` for the permanent cross-session record. See [Agent file system](agent-file-system.md).

## Limits

- Per-run action and token budgets stop runaway work: at 100% the agent pauses behind a Continue/Stop choice and the session idles until you pick. Token accounting counts only uncached tokens, so long conversations with a warm cache go further than raw usage suggests.
- A force-stop from the UI cancels the in-flight turn and clears the run's queued continuations.

## Next

- [Runs](../modes/index.md): how the agent scales its process to the size of the work
- [Your first task](../../start/first-task.md): watch sessions and runs in practice
- [Agent loop](agent-loop.md): how a turn actually executes
- [Event stream](event-stream.md): the per-session record everything above writes to
