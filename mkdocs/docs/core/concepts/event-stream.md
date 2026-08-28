# Event stream

The event stream is the agent's working record: an append-only log of everything that happens in a [task session](task-sessions.md) (messages, reasoning, action starts and results, task boundaries). It is simultaneously what the chat UI renders, what the LLM reads as history on every turn, and the raw material the [memory pipeline](memory.md) distills. If you want to know "what did the agent actually see when it made that decision", the answer is always: its event stream at that moment.

## Overview
- **One stream per session.** A main stream carries conversation-mode activity. Every task gets its own stream when it starts, so parallel tasks never read each other's history.
- **Recent events stay verbatim while old events get folded.** Each stream keeps a tail of full-fidelity events plus a rolling `head_summary`. When the tail grows past a token threshold, the oldest chunk is summarized by the LLM into the head and dropped from the tail.
- **Everything is an `Event`**: a message, a typed category, a severity, and optional structured fields (action inputs/outputs, platform, task status). Repeated identical events are collapsed into one record with a repeat counter instead of flooding the log.

What the LLM sees each turn is the stream's *prompt snapshot* (the head summary followed by the recent tail) assembled into context by the [context engine](context-engine.md).

## Event types

Every event carries a typed category. This is a closed set. Consumers route on it, never on message text:

| Event type | Recorded when |
|---|---|
| `user_message` | You send a message (locally or via a connected platform) |
| `agent_message` | The agent replies; this is what appears as a chat bubble |
| `reasoning` | The LLM explains why it picked the next action(s) |
| `action_start` / `action_end` | An action begins / finishes; carries the action name, a paired id, and structured input/output |
| `task_start` / `task_end` | A task's boundaries; `task_end` carries the final status |
| `todos` | The todo list changed |
| `waiting_for_user` | The task paused for your reply |
| `relevant_memories` | Memory retrieval injected context pointers |
| `system` / `error` | Harness notices and failures |
| `internal` | Bookkeeping the UI hides |

## How the UI renders it

The chat and the action panel are direct projections of streams:

- The UI watches all streams (main + every task) and routes each event **by its `event_type` only**: `agent_message` becomes a chat bubble, `action_start`/`action_end` become the live action rows, `todos` updates the checklist, `waiting_for_user` flips the status bar.
- `action_start` and `action_end` share an `action_id`, so the panel can pair them even when several copies of the same action run in parallel.
- Events may carry a shorter `display_message` for the UI while keeping the full `message` for the LLM and for debugging.

Nothing happens off the record: if the agent did it, there is an event for it, and the UI shows the ones that concern you.

!!! note "Implementation files"
    The event model and type enum are `agent_core/core/event_stream/event.py`. The per-stream mechanics (tail, summary, snapshots) are `agent_core/core/impl/event_stream/event_stream.py`. Stream creation per task and the file logging below are `EventStreamManager` in `agent_core/core/impl/event_stream/manager.py`.

## EVENT.md and EVENT_UNPROCESSED.md

Every event is also appended to markdown files in `agent_file_system/` (see [Agent file system](agent-file-system.md)), one line per event:

| File | Contents |
|---|---|
| `EVENT.md` | The complete history: every event from every stream, in `[YYYY-MM-DD HH:MM:SS] [kind]: message` format. Auto-rotated when it grows too large. |
| `EVENT_UNPROCESSED.md` | The staging buffer for the [memory pipeline](memory.md): the subset of events awaiting distillation into `MEMORY.md`, cleared after each processing run. |

Routine event kinds that the memory processor would always discard (action starts/ends, reasoning, todos, errors, waiting notices, memory-retrieval pointers) are filtered out at write time, so `EVENT_UNPROCESSED.md` contains only dialogue and meaningful state changes. During a memory-processing task the buffer is frozen entirely, so the processor's own events can't loop back into it.

These files are also the agent's own audit trail: when it troubleshoots itself, `EVENT.md` is the first place it greps.

## Automatic stream summarization

The stream is re-read by the LLM every turn, so each stream compacts itself:

1. When the tail exceeds **30,000 tokens**, the oldest events (down to a **10,000-token** surviving tail) are packaged with the existing head summary and sent to the LLM.
2. The LLM returns an updated summary. It replaces the head, and the summarized events are dropped from the tail.
3. A few protected event kinds (notably the task's recorded requirements) are never folded into a summary. They survive verbatim so the task's definition of done can't be summarized away.
4. If the LLM provider is failing, the stream falls back to pruning the oldest events *without* a summary rather than hammering a dead endpoint.

You can see this in the [logs](logs.md):

```text
[EventStream] Triggering summarization: 31204 tokens >= 30000 threshold
[EventStream] Summarization complete. Tokens: 9845
```

Separately, any single event message longer than about **16,000 characters** (a huge web page, a big file read) never enters the stream at all. It is written to the task's temp directory and replaced by a pointer event containing the file path and extracted keywords. The agent reads the file back with its file actions only if it actually needs the content. One oversized action result can't blow up every subsequent turn's prompt.

## Relation to caching and memory

- **Prompt caching.** Streams track per-call-type sync points so that, on cached turns, only events added since the last call are sent as a delta instead of re-sending the whole history. Summarization invalidates those sync points (the indices shift), which triggers a cache rebuild. The full story is in [Context engine](context-engine.md).
- **Long-term memory.** The stream is working memory. It ends with its task. Anything worth keeping across sessions flows through `EVENT_UNPROCESSED.md` into the memory pipeline (see [Memory](memory.md)).

## Where events appear in the UI and logs

- **The chat itself.** Bubbles, action rows, and todo updates are the stream, rendered.
- **On disk.** Follow the master log while you interact:

```bash
tail -f agent_file_system/EVENT.md
```

```text
[2026/07/17 10:14:02] [action_start]: web_search
[2026/07/17 10:14:04] [action_end]: web_search -> success (5 results)
[2026/07/17 10:14:09] [agent message to platform: CraftBot Interface]: Here's what I found...
```

- **In logs.** Grep `EventStream` in `logs/` for summarization and stream lifecycle activity.

## Limits

- The summarization thresholds (30k trigger / 10k keep) are constructor defaults of the stream, not user settings. They are tuned to balance context quality against per-turn cost.
- A summary is lossy by design. Recent events are exact. Older history is the LLM's condensation of it. Durable facts belong in [memory](memory.md), not in the stream.
- Task streams are removed when their task ends. The permanent records are `EVENT.md`, `TASK_HISTORY.md`, and whatever memory distilled.

## Next

- [Agent loop](agent-loop.md): the producer: every turn writes here
- [Task sessions](task-sessions.md): why each task gets its own stream
- [Context engine](context-engine.md): how snapshots and deltas reach the LLM
- [Memory](memory.md): how events become long-term memory
