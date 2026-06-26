---
name: memory-processor
description: Process raw events into distilled long-term memories using batch processing.
user-invocable: false
action-sets:
  - file_operations
---

# Memory Processor

The only way for agent to save event into long-term memory.

## Files

- `agent_file_system/EVENT_UNPROCESSED.md` - Source (read & clear batches)
- `agent_file_system/MEMORY.md` - Destination (append distilled memories)

## Todo Tracking (REQUIRED)

Use `task_update_todos` to track progress. Create todos at start, update as you go.

**Initial todos (create after reading first batch):**
```
1. [pending] Process and loop for each batch (25~50 lines).
2. [pending] Validate and cleanup
3. [pending] Complete task
```

**After each batch:** Mark current as completed, add next batch if more events exist.

## Batch Processing Workflow

Process 50 lines at a time to avoid memory issues.

### Steps:

1. **Read first batch**: `stream_read` EVENT_UNPROCESSED.md, offset=11, limit=50
2. **Create todos**: Use `task_update_todos` to create initial todo list
3. **Loop for each batch**:
   - Distill batch: Apply rules below, extract IMPORTANT memories only
   - Append memories: `stream_edit` MEMORY.md (append only)
   - Remove batch: `stream_edit` EVENT_UNPROCESSED.md (delete lines 12-61)
   - Update todos: Mark batch completed, add next batch if more events
4. **Validation** (mark todo in_progress):
   - Validate no more unprocessed events in EVENT_UNPROCESSED.md
   - Validate no duplicated memory in MEMORY.md
5. **End task**: `task_end` when validation passes

## Rules

- Silent background task. NEVER use send_message or interact with user.
- Immediately discard these event types:
  - `[reasoning]`, `[action_start]`, `[gui_action]`, `[screen_description]`
  - `[agent message]` - agent responses are NEVER saved
  - Greetings, small talk, acknowledgments ("hi", "thanks", "ok")
  - Screen descriptions ("The current screen displays...")
  - Truncated text ending in `...`

### Format (Strict)

```
[YYYY-MM-DD HH:MM:SS] [category] Full Name predicate object
```

Categories: `[fact]`, `[preference]`, `[event]`, `[decision]`, `[learning]`

### DISTILL, Don't Copy

**Input:**
```
[2026/02/09 06:33:10] [user message]: agent, i am an ai researcher at craftos
```

**Output:**
```
[2026-02-09 06:33:10] [fact] John is an AI researcher at CraftOS
```

Note: Get actual names from existing MEMORY.md. Never use "user", "conversation partner", or pronouns.

### No Duplicates

- Check MEMORY.md before saving. Skip if similar memory exists. 
- Actively remove memories you found duplicated in MEMORY.md, keeping only the latest one.

### Length Limit (Strict)

Each memory item MUST be <= 150 words, counted on the text AFTER the `[category]` tag.
If a distillation would exceed 150 words, compress further:
- Drop filler, restatements, and incidental detail
- Keep only the lasting-value core: subject, predicate, object, key qualifier
- If still too long, split into two atomic memories OR drop the less-important half

Never truncate mid-sentence; never end an item with `...`.

### CRITICAL DISTILLATION RULES

**Core principle:** Memory is for LASTING PERSONAL INSIGHTS that improve future interactions, not event logging.

**The Future Utility Test:** Before saving, ask: "Will knowing this help me serve the user better in a FUTURE conversation?" If the answer is no, discard it.

**NEVER save (these belong in EVENT.md, not MEMORY.md):**
- Task lifecycle: `task_completion`, `task_started`, `task_failed`
- Conversation content: `user_request`, `user message`, `agent message`
- Transient actions: what user asked agent to do, what agent did
- Status updates: "completed X", "working on Y", "finished Z"
- One-time context: information only relevant to the current task

**SAVE CONDITION:**

Only save the memory if it contains lasting value:
- User preference or personal fact
- Scheduled event with specific date
- Important decision
- Contact information or deadline

**ALWAYS save (high future utility):**
- WHO the user is (identity, profession, relationships, contacts)
- WHAT the user likes/dislikes (preferences, opinions, feelings, pet peeves)
- HOW the user wants things done (communication style, workflows, standards)
- WHEN things matter to them (deadlines, scheduled events, recurring patterns)
- WHY the user makes decisions (goals, motivations, priorities)

**Examples of future utility:**
- ✓ "John prefers concise responses" → Agent adjusts tone in ALL future chats
- ✓ "John is allergic to peanuts" → Agent remembers for ANY food-related task
- ✗ "John asked to schedule a meeting" → Only relevant to that one task
- ✗ "Task completed successfully" → No future value

## Allowed Actions

`stream_read`, `stream_edit`, `memory_search`, `grep_files`, `task_end`, `task_update_todos`

## FORBIDDEN Actions

`send_message`, `ignore`, `run_shell`

## Example

**Batch 1 (50 lines):**
- Line 1: DISCARD (greeting)
- Line 2: DISCARD (agent message)
- Line 3: SAVE → `[2026-02-09 06:33:10] [fact] John is an AI researcher`
- Line 4: SAVE → `[2026-02-09 06:33:10] [event] John has a meeting with Sarah from Company ABC on 15/2/2026, with unknown location`
- Lines 5-50: DISCARD (routine)

**Todo update after batch 1:**
```
1. [completed] Process batch 1 (lines 12-61)
2. [in_progress] Process batch 2 (lines 12-61)
3. [pending] Validate and cleanup
4. [pending] Complete task
```

**Result:** 50 events → 1 memory, progress tracked via todos

### Example: compressing a verbose event to <= 150 words

**Input (raw, rambling):**
```
[2026-03-12 10:04:22] [user message]: so i was thinking about the trip next month, we're still planning to fly to tokyo on april 18th, staying at the shinjuku hilton for six nights, my wife emma is coming, and we also want to try the sushi place called sukiyabashi jiro that my friend kenji recommended, oh and the flight is on ANA from LAX, departing 10:55am, i need to remember to pack the camera and charger, and i'm a bit anxious because last time i forgot my passport
```

**Output (<= 150 words, two atomic memories):**
```
[2026-03-12 10:04:22] [event] John and Emma fly Tokyo on 2026-04-18 via ANA from LAX 10:55am, staying Shinjuku Hilton 6 nights
[2026-03-12 10:04:22] [preference] John wants to try Sukiyabashi Jiro sushi in Tokyo (recommended by Kenji)
```

Anxiety, packing reminder, and narrative framing are dropped — no lasting utility.

## Pruning Mode

Triggered when the task instruction contains a "Pruning phase" directive (MEMORY.md has reached the item-count cap).

### Workflow

Add these todos alongside the event-processing todos:

```
N+1. [pending] Read MEMORY.md header + oldest block
N+2. [pending] Consolidate/merge/drop oldest items
N+3. [pending] Replace oldest block in MEMORY.md
```

Execute AFTER event processing completes:

1. `stream_read` MEMORY.md from line 11 (skip the header block) up to the oldest-N range indicated in the task instruction.
2. Decide, item by item, what to merge / drop / keep. See ranking heuristics below. The 150-word limit still applies to every merged item.
3. `stream_edit` MEMORY.md to replace the oldest block with the consolidated set. The `# Memory Log` / `## Overview` / `## Memory` header (lines 1-10) must remain intact.

### Ranking heuristics (drop priority, highest first)

1. Stale `[event]` items whose date has passed and have no lasting consequence.
2. Duplicate or near-duplicate facts about the same subject — keep the most recent/complete one; merge timestamps into a single canonical entry.
3. Weak-signal preferences or one-off observations that fail the Future Utility Test.
4. Superseded items (older preference that a newer item contradicts) — keep the newer one.

### Never drop

- Personal identity facts (name, role, relationships)
- Contact information
- Stated hard preferences (allergies, strict dislikes, required workflows)
- Active commitments and goals with a future date

### Critical

- No hard-coded "drop oldest N" rule — judge utility first, use age only as a tiebreaker.
- Target a final item count at least `prune_target` below the pre-prune count (the task instruction states the exact number).
- When in doubt, merge rather than drop.
