# Memory

Memory is how CraftBot remembers you across sessions: that you prefer Telegram, that the Q3 report lives in `workspace/reports/`, that you hate bullet-point summaries. It's a five-stage pipeline (capture, distill, index, recall, inject) running over plain markdown files, and every stage of it is inspectable on disk.

## Overview
| Stage | What happens | Where |
|---|---|---|
| **Capture** | Events pile up as the agent works | `agent_file_system/EVENT_UNPROCESSED.md` |
| **Distill** | A nightly task keeps the ~5% worth remembering | writes `MEMORY.md`, clears the buffer |
| **Index** | Facts are embedded and keyword-indexed | ChromaDB at `chroma_db_memory/` + BM25 |
| **Recall** | A query returns the top matching facts | hybrid vector + keyword search |
| **Inject** | Matches appear in the agent's context as one event | the [event stream](event-stream.md) |

Two design choices explain most of memory's behavior. First, **the source of truth is a text file**: `MEMORY.md` holds one fact per line as `[timestamp] [type] content`. The vector database is just an index over it, rebuildable at any time. Second, **retrieval returns pointers, not content**: the agent sees "there's a relevant fact about X in MEMORY.md" plus a short summary, and reads the full text only if it needs to. Context stays small, and recall stays broad.

## Capture: the unprocessed buffer

As the agent works, noteworthy events (your messages, task outcomes, decisions) are appended to `EVENT_UNPROCESSED.md`. This is a raw buffer, not memory yet: it contains the routine alongside the significant, and nothing in it has been judged. It *is* already searchable (see indexing below), so a fact from an hour ago is recallable tonight even though it hasn't been distilled.

## Distill: the nightly processor

Once a day at **3 a.m.** (a `"every day at 3am"` entry in `app/config/scheduler_config.json`), the scheduler fires a memory-processing trigger. If the machine was asleep at 3 a.m., a startup check replays it: whenever CraftBot launches and finds unprocessed events, it fires the same trigger. Either way the result is a silent background task. It runs with the `memory-processor` skill and is explicitly forbidden from messaging you.

The task's job:

1. Read `EVENT_UNPROCESSED.md`.
2. **Discard 95%+** of events. Greetings, agent messages, and routine chatter never become memories.
3. Rewrite (not copy) the keepers into `MEMORY.md` as `[YYYY-MM-DD HH:MM:SS] [category] subject predicate object` lines, each capped at 150 words.
4. Clear the buffer.

When `MEMORY.md` has grown past the item cap (default **200** items), the same run adds a **pruning phase**: merge related items about the same subject, drop duplicates and low-utility items, and remove roughly the oldest **135**, keeping high-utility facts regardless of age. Memory therefore has a steady-state size and does not grow forever.

A workflow lock guarantees only one memory-processing task runs at a time. If last night's run is still going when the next trigger fires, the new trigger is skipped, not queued. And events generated *during* processing are excluded from the buffer, so the processor can't feed itself.

## Index: hybrid, local, incremental

Five files are indexed (`INDEX_TARGET_FILES`): `AGENT.md`, `PROACTIVE.md`, `MEMORY.md`, `USER.md`, and `EVENT_UNPROCESSED.md`. Chunking depends on the file's shape: `MEMORY.md` and `EVENT_UNPROCESSED.md` get **one chunk per item line**, so each fact is retrievable on its own instead of through a single embedding of the whole file. The profile-style files are chunked per markdown section.

Each chunk is indexed twice:

- **Vector**: embedded with **BGE-small-en-v1.5** (a local sentence-transformers model chosen for its wide relevant-vs-noise score separation) into an embedded ChromaDB at `chroma_db_memory/`.
- **Keyword**: a BM25 index, rebuilt in-memory from the chunk set, which catches what embeddings handle poorly: proper nouns, dates, IDs, and code identifiers. A lightweight entity extractor pulls names and identifiers into chunk metadata to strengthen this channel.

A file watcher keeps the index current: edit any indexed file (or let the nightly processor rewrite `MEMORY.md`) and the changed file is re-indexed after a ~30-second debounce. Only changed content is re-embedded.

## Recall: hybrid scoring

A query fans out to both channels, and candidates are merged with a weighted score: **0.65 × vector similarity + 0.35 × normalized BM25**. Results below a relevance floor are dropped. The rest are ranked and cut to top-k. In practice, "what did we decide about the deploy pipeline" is carried by the vector channel, and "JIRA-4821" is carried by BM25. If the BM25 dependency is missing, retrieval degrades gracefully to pure vector search.

## Inject: memory as an event

Recall is trigger-driven, not per-LLM-call. At the moments new context enters the system (a user message arrives, a message is routed into a task, a task is created), the injector runs a retrieval with the incoming text as the query (`min_relevance` 0.5, top 5). If anything clears the bar, it logs **one `relevant_memories` event** into that session's event stream:

```text
- [MEMORY.md] item:preference: Prefers PDF deliverables over docx (relevance: 0.81)
- [USER.md] ## Communication: Update only at milestones, no play-by-play (relevance: 0.66)
```

If nothing clears the bar, nothing is logged. There is no empty "no memories found" event. The event contains pointers and summaries, not full content, and the agent follows up with `read_file` when a pointer matters. The [context engine](context-engine.md) never splices memory into prompts directly. The model receives memory as an event next to the message that triggered it.

## Observe and influence it

- **Watch injections live**: `relevant_memories` events appear in the event stream panel like any other event. In `logs/`, grep for `[MEMORY QUERY]` and `[MEMORY RESULT]` to see every retrieval and its scores.
- **Search on demand**: the agent has a `memory_search` action available in tasks. Ask it "what do you remember about X" and watch it use it.
- **Read the files**: `MEMORY.md` is plain text. Open it to see exactly what the agent knows. `EVENT_UNPROCESSED.md` shows what's queued for tonight.
- **Correct a memory**: tell the agent ("that's wrong, my timezone is JST now") and let the correction flow through the pipeline, or edit `USER.md` directly for profile facts. Don't hand-edit `MEMORY.md`: it's harness-managed (the file itself and the agent's instructions both say so), and the item format, ordering, and index all assume the processor owns it.
- **Reset**: the interface's memory settings can list, edit, or remove individual memory items and reset `MEMORY.md` from its template.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `memory.enabled` (settings.json) | `true` | Master switch; off disables capture, injection, and the nightly processor |
| `memory.max_items` | `200` | Item cap on `MEMORY.md` before pruning runs |
| `memory.prune_target` | `135` | Approx. oldest items removed per pruning phase |
| `memory.item_word_limit` | `150` | Max words per distilled memory item |
| `MEMORY_EMBEDDING_MODEL` (env var) | `BAAI/bge-small-en-v1.5` | Embedding model; any sentence-transformers model, or `default` for ChromaDB's built-in |
| `MEMORY_PROCESSING_SCHEDULE_HOUR` (`app/config.py`) | `3` | Hour of the daily processing run |

With `memory.enabled: false`, the agent still works. It just starts every session knowing only what's in `USER.md` and the current conversation.

**Privacy.** The entire pipeline is local: facts live in markdown on your disk, ChromaDB runs embedded (no server), and embeddings are computed on your machine by a local model. The only stage that leaves your machine is what always does: LLM calls to your configured provider, which includes the nightly distillation task reading your event buffer. With a local provider such as Ollama, nothing leaves at all.

!!! note "Implementation files"
    `agent_core/core/impl/memory/manager.py` holds `MemoryManager` (chunking, hybrid `retrieve()`, `create_memory_processing_task`). `injector.py` holds `inject_memory_event`, called from message arrival and task creation. `bm25_index.py` and `entity_extractor.py` implement the keyword channel, and `memory_file_watcher.py` re-indexes on file change. Item thresholds are read live from settings by `app/ui_layer/settings/memory_settings.py`. The distillation workflow is in the `memory-processor` skill.

## Next

- [Agent file system](agent-file-system.md): the files memory reads and writes
- [Event stream](event-stream.md): where captured events come from and where recalled memories land
- [Context engine](context-engine.md): how a `relevant_memories` event reaches the model
- [Onboarding](../../start/onboarding.md): where `USER.md`, the profile half of memory, gets its start
