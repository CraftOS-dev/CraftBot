# Context engine

Every time CraftBot calls the LLM, the context engine decides what the model actually sees: who the agent is, who you are, what's happening right now, and what it's being asked to decide. Understanding its layout explains most of CraftBot's token costs, most of its speed, and most of "why did the agent know that?"

## Overview
Every LLM call is two halves:

| Half | Contents | Changes between calls? | Cached? |
|---|---|---|---|
| **Static prefix** (system prompt) | Agent identity, your profile, personality, policy, environment, file-system map | No; byte-identical within a session | Yes (provider KV cache) |
| **Dynamic tail** (user prompt) | The decision template, current task, conversation history, live event stream, your query | Yes, every call | Only incrementally |

The split is the whole design. LLM providers cache a prompt *prefix*: as long as the opening bytes of a call are identical to a previous call, those tokens are nearly free and fast. So the engine pushes everything stable to the front and everything volatile to the back. A follow-up call in a long task pays full price only for the events that happened since the last call, not for the agent's entire identity again.

One consequence worth internalizing: **anything that varies call-to-call is banned from the prefix.** The clearest example is the current date and time. It would be natural to put "it is 14:32 on Thursday" in the system prompt, but that would change the prefix every call and bust the cache (Gemini's implicit caching is prefix-based, so even one changed byte invalidates everything after it). The engine deliberately keeps date/time out of the cached prefix. A dedicated `current_datetime_block` renders it for the dynamic tail, and every event in the stream carries its own timestamp, so the model still knows when things happened.

## System prompt contents

The engine assembles the system prompt from fixed sections in a fixed order:

| # | Section | What it contains | You control it via |
|---|---|---|---|
| 1 | Agent info | Capabilities, task system, working ethic, format standards | Nothing (built-in) |
| 2 | User profile | Your `USER.md`, verbatim | Edit [`USER.md`](agent-file-system.md) |
| 3 | Soul | Your `SOUL.md`, verbatim: personality and tone | Edit [`SOUL.md`](agent-file-system.md) |
| 4 | Language instruction | "Use the user's preferred language" rule | Language preference in `USER.md` |
| 5 | Policy | Safety, privacy, prompt-injection defense | Nothing (built-in) |
| 6 | Role info | Agent name + role persona | [Onboarding](../../start/onboarding.md) sets the name |
| 7 | Environment | Timezone, working directory, OS (stable facts only) | Nothing (detected) |
| 8 | File system | Map of `agent_file_system/`: what each file is for | Nothing (built-in) |
| 9 | Base instruction | One-line closing instruction | Nothing (built-in) |

Sections 2 and 3 are read from disk at prompt-build time, which is why editing `USER.md` or `SOUL.md` changes behavior on the very next call, with no restart. It also means an edit invalidates the cached prefix once. The first call after the edit pays full price, then caching resumes. The prompt templates behind each section are covered in [Prompts](prompts.md).

## Per-turn message contents

The tail is built per call and per session. Its ingredients, roughly back-to-front:

**The decision template.** Which one depends on what's being decided: conversation-mode action selection, in-task selection, session routing, and so on (see [Prompts](prompts.md)). Within the tail, static template text still comes first and volatile content last, for the same caching reason.

**`<current_task>`** holds the active task's name, instruction, and mode, plus **`<active_skills>`** (the instructions of any skill selected for the task) and agent state.

**`<conversation_history>`** holds the most recent user/agent messages (default **20**) from *before* the current task. This is context, not work: it lets a task understand "the thing we discussed a minute ago" without those messages polluting the task's own record.

**`<event_stream>`** is the live snapshot of the current session's [event stream](event-stream.md): every action started and finished, every message, every error, in order, with timestamps. This is the working memory of the task.

The two are easy to conflate but behave differently:

| | `<conversation_history>` | `<event_stream>` |
|---|---|---|
| Contains | Chat messages before the task | Everything during the task |
| Scope | Global, shared context | One per task session |
| Growth | Capped at recent 20 messages | Grows until summarized |
| Marked as | "historical context" | "the current situation" |

**`<message_source>`** appears when the triggering message came from an external platform (Telegram, Slack, Discord, ...). This small block identifies the platform, whether it's you or a third party, the sender, and the channel. This is how the agent replies on the right platform and how it knows a third-party message isn't an instruction from you.

**Memory** is deliberately *not* injected by the engine itself. When a message arrives or a task starts, the memory system logs a single `relevant_memories` event into the event stream: pointers to matching facts, not full content. The model sees memory as just another event, right next to the message that triggered the lookup. Full lifecycle in [Memory](memory.md).

## Cache behavior and cost

CraftBot uses two cache levels:

- **Prefix cache**: the static system prompt. Used for every call, including plain conversation. After the first call, the identity/profile/policy block is served from cache.
- **Session cache**: for tasks, the growing context is cached per task and per call type, and subsequent calls send only *delta events*, the events appended since the last sync. A 50-step task doesn't resend 49 steps of history on step 50.

Conversation mode uses prefix caching only. Tasks add session caching on top. The mechanics differ per provider (Anthropic uses `cache_control` blocks, Gemini an explicit context cache, BytePlus server-side prefix/session caches, OpenAI-style providers cache automatically), but the engine's prompt layout is what makes any of them effective.

The cost implication: a long task's per-step price is dominated by *new* events, not accumulated context. The corollary: anything that invalidates the prefix (editing `SOUL.md` mid-task, switching models) makes the next call pay full price. And when the event stream hits its summarization threshold, older events are compacted and session sync points reset. The next call repopulates the cache from the summarized stream.

## Inspecting the assembled prompt

- **Cache metrics in logs.** Grep `logs/` for `[CACHE METRICS]` lines. They report hits, misses, and the percentage of tokens served from cache per provider and call type. A healthy long task shows a high token-cache rate after the first few steps.
- **Memory injections.** `relevant_memories` events appear in the event stream panel like any other event, so you can see exactly which memories the model saw and when.
- **`[CONTEXT]` warnings** in logs flag failures to read `USER.md`/`SOUL.md`. If your profile edits seem ignored, look here first.

## Configuration

Cache behavior is tuned in the `cache` section of [`settings.json`](../configuration/config-json.md):

| Key | Default | Meaning |
|---|---|---|
| `cache.prefix_ttl` | `3600` | Seconds the system-prompt prefix cache is kept |
| `cache.session_ttl` | `7200` | Seconds a per-task session cache is kept (long tasks) |
| `cache.min_tokens` | `500` | Skip caching for prompts shorter than this |

The conversation-history window (20 messages) and the section order are code-level defaults, not settings. The event stream's summarization thresholds (which bound how large the dynamic tail can grow) are covered in [Event stream](event-stream.md).

!!! note "Implementation files"
    The engine is `agent_core/core/impl/context/engine.py` (`ContextEngine`). `make_prompt()` assembles the system sections in the order above. `get_event_stream()`, `get_task_state()`, and `get_message_source_block()` build the dynamic tail. `get_event_stream_delta()` / `mark_event_stream_synced()` implement session-cache delta tracking. Prompt templates live in `agent_core/core/prompts/`.

## Next

- [Prompts](prompts.md): the templates the engine assembles, and the files you edit to steer them
- [Event stream](event-stream.md): the dynamic half: summarization, delta tracking, thresholds
- [Memory](memory.md): how `relevant_memories` events get into the stream
