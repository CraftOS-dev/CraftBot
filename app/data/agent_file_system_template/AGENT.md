---
version: 3
purpose: agent operations manual
---

# AGENT.md

Your ops manual. Grep `## <topic>` to load what you need.

## Index

<!-- index -->
```
add MCP server          → ## MCP
add skill               → ## Skills
connect platform        → ## Integrations
switch model            → ## Models
set API key             → ## Models
generate document       → ## Documents
build Living UI         → ## Living UI
schedule recurring task → ## Proactive
edit config file        → ## Configs
start a task            → ## Tasks
handle an error         → ## Errors
read / edit a file      → ## Files
discover an action      → ## Actions
persistent storage      → ## File System
long-running work       → ## Workspace
self-improve            → ## Self-Improvement
edit AGENT/USER/SOUL.md → ## Self-Edit
look up a term          → ## Glossary
```
<!-- /index -->

---

## Runtime

You run inside `AgentBase.react(trigger)` at [app/agent_base.py](app/agent_base.py). Each turn: one trigger is consumed, the LLM picks one or more actions, the executor runs them, events are appended to streams, and (often) a new trigger is queued for the next turn.

### Trigger anatomy

Triggers live in a priority queue at [agent_core/core/impl/trigger/queue.py](agent_core/core/impl/trigger/queue.py), ordered by `fire_at` (Unix timestamp) then `priority` (lower number = higher priority). Each trigger carries:

```
fire_at:                  float    when it should fire
priority:                 int      ordering within same fire_at
next_action_description:  str      human-readable hint
payload:                  dict     routing + context
session_id:               str|None which session/task this belongs to
waiting_for_reply:        bool     paused for user input
```

`payload.type` is the routing key:
```
"memory_processing"   → memory workflow      (creates a memory-processor task)
"proactive_heartbeat" → proactive heartbeat  (creates a Heartbeat task)
"proactive_planner"   → proactive planner    (creates a day/week/month planner task)
<absent or other>     → falls through to task / conversation routing by session state
```

Trigger producers:
- The scheduler ([app/config/scheduler_config.json](app/config/scheduler_config.json)) — fires `memory_processing`, `proactive_heartbeat`, `proactive_planner` on cron.
- External-comms listeners and the UI — fire triggers carrying user messages in the payload.
- Actions you invoke — `wait`, `task_end`, and others enqueue follow-up triggers via `triggers.put(...)`.

### react() routing (in order)

```
1.  _is_memory_trigger(trigger)        → _handle_memory_workflow         → return
2.  _is_proactive_trigger(trigger)     → _handle_proactive_workflow      → return
3.  _extract_trigger_data(trigger)
4.  _initialize_session(...)
5.  record user_message in trigger payload (if any) into the event stream
6.  if active task is waiting_for_user_reply AND no user_message arrived
        → re-queue the trigger with a 3-hour delay → return
7.  _is_complex_task_mode(session)     → _handle_complex_task_workflow
8.  _is_simple_task_mode(session)      → _handle_simple_task_workflow
9.  default                            → _handle_conversation_workflow
```

Steps 7-9 share the same shape: `_select_action` (LLM picks actions; session caching for cache hits) → `_retrieve_and_prepare_actions` → `_execute_actions` → `_finalize_action_execution`. The differences are session state, todo handling, and caching strategy.

### Workflows

**memory** — `_handle_memory_workflow`
- Trigger source: scheduler `memory-processing` (daily 3am) or startup replay if EVENT_UNPROCESSED.md is non-empty.
- Behavior: spawns a task that uses the `memory-processor` skill. The task reads EVENT_UNPROCESSED.md, scores events, distills important ones into MEMORY.md, clears the buffer. May also prune MEMORY.md if `max_items` is exceeded.
- During this task, `event_stream_manager.set_skip_unprocessed_logging(True)` is on, so the task's own events do not loop back into EVENT_UNPROCESSED.md. Reset on `task_end`.
- Skipped entirely if `is_memory_enabled()` is False.
- See `## Memory`.

**proactive heartbeat** — `_handle_proactive_heartbeat`
- Trigger source: scheduler `heartbeat` (cron `0,30 * * * *`).
- Behavior: `proactive_manager.get_all_due_tasks()` collects due recurring tasks across all frequencies. If none, returns silently. Otherwise creates one `Heartbeat` task: `mode=simple`, `action_sets=[file_operations, proactive, web_research]`, `skill=heartbeat-processor`.
- Skipped entirely if `is_proactive_enabled()` is False.
- See `## Proactive`.

**proactive planner** — `_handle_proactive_planner`
- Trigger source: scheduler `day-planner` (daily 7am), `week-planner` (Sun 5pm), `month-planner` (1st 8am).
- Behavior: creates a task named `<Day|Week|Month> Planner`, mode=simple, action_sets=[file_operations, proactive], skill=`<scope>-planner`. Task instruction: review recent interactions and update the Goals/Plan/Status section of PROACTIVE.md.

**complex task** — `_handle_complex_task_workflow`
- Active when a task exists for the session and `task.is_simple_task() == False`.
- Full todo state machine; user-approval gate at the end. Session caching enabled for multi-turn efficiency. Parallel action execution supported.
- See `## Tasks` for the full lifecycle.

**simple task** — `_handle_simple_task_workflow`
- Active when a task exists for the session and `task.is_simple_task() == True`.
- Same select→prepare→execute→finalize flow as complex; no todos; auto-ends. Session caching enabled.

**conversation** — `_handle_conversation_workflow`
- Active when no task is running for the session.
- Same flow as simple/complex but uses prefix caching only (no session cache). Supports parallel `task_start` to launch multiple tasks at once.
- If the executed actions return a `task_id`, the session adopts that task and subsequent triggers route to the task workflow.

### Re-entry and waiting

Calling `wait` or having a task in `waiting_for_user_reply` does not block the loop — it queues a trigger with `fire_at` in the future. When that trigger fires:
- If the wait was for a user reply and one arrived → process normally.
- If no user message arrived but the task is still flagged `waiting_for_user_reply` → react re-queues the trigger with a fresh 3-hour delay and returns. The agent silently waits without consuming context.

### Components attached at construction

You do not call these directly, but every action routes through them. Knowing what owns what helps you debug:

```
LLMInterface           text + vision generation gateway
ActionLibrary          DB-backed action storage (atomic + divisible)
ActionManager          action lifecycle
ActionRouter           LLM-based action selection
ActionExecutor         sandboxed (ephemeral venv) or internal execution
TaskManager            task lifecycle, per-task event streams, session storage
StateManager           session state, current_task_id, current_task
ContextEngine          builds system + user prompt each turn (KV cache aware)
MemoryManager          ChromaDB-backed RAG over agent_file_system
EventStreamManager     appends to EVENT.md / EVENT_UNPROCESSED.md / per-task streams
MCPClient              external MCP tool servers
SkillManager           SKILL.md discovery + selection + reload
Scheduler              cron-driven trigger fires from scheduler_config.json
ProactiveManager       PROACTIVE.md registry + get_all_due_tasks()
ExternalCommsManager   platform listeners + senders
WorkflowLockManager    blocks concurrent memory / proactive runs
```

### Workflow locks

[agent_core/core/impl/workflow_lock/manager.py](agent_core/core/impl/workflow_lock/manager.py) gates concurrent runs of background workflows. Lock names in use:

```
"memory_processing"        only one memory-processor task at a time
"proactive_*"              one proactive workflow per scope at a time
```

If a trigger fires while its lock is held, the new trigger is dropped silently. The next scheduled fire will pick up the work. This is by design — do not work around it.

### State and context every turn

What the LLM sees on each `_select_action` call:
- Static system prompt (your role, policy, file-system map, environment).
- The relevant slice of the event stream (recent actions, results, user messages).
- Memory pointers retrieved by the ContextEngine for relevance.
- Current task state if a task is active (instruction, todos, action sets, skills selected).
- The list of currently available actions (filtered by selected action sets and current mode).

Knowing this shape helps you decide what context to enrich. Need history beyond what's in the stream? Use `memory_search` (`## Memory`) or read TASK_HISTORY.md / CONVERSATION_HISTORY.md directly (`## File System`).

---

## Tasks

Three runtime modes route through this section: **conversation**, **simple**, **complex**. Each has a distinct purpose, action surface, and starting move.

### Conversation mode

Active when **no task is running** for the session. Default state when a user message arrives in a fresh session.

Action surface in conversation mode is intentionally small ([agent_core/core/prompts/action.py](agent_core/core/prompts/action.py)):
```
task_start(...)        begin a task — THE way user requests become work
send_message(...)      reply without starting a task
ignore                 user input needs no reply (e.g. emoji-only ack)
```

You CANNOT call file ops, web search, MCP tools, integrations, or skills directly from conversation mode. To unlock them, start a task first.

You MAY emit multiple `task_start` actions in parallel from a single conversation turn. Example: user says "research topic A and topic B" → two parallel `task_start` calls, one per topic.

When to stay in conversation mode:
- Greeting, small talk, clarifying question.
- Acknowledging a user message that needs no work.
- Routing decisions where the user must confirm before any task starts (e.g. "do you want me to delete X?").

When to leave conversation mode (call `task_start`):
- ANY request that needs file access, web, MCP, skills, integrations, or memory beyond what's in your current context.
- Even if you "think" you know the answer — if the request is computer-based and could benefit from verification, start a task. Do not refuse a task by claiming a limitation without checking.

### Starting a task: `task_start` vs `schedule_task`

```
From conversation (no active task)  →  task_start(task_name, task_description, task_mode)
From inside a task (simple/complex) →  schedule_task(name, instruction, schedule="immediate", mode, ...)
For later / recurring execution     →  schedule_task(name, instruction, schedule="<expr>", ...)
```

**`task_start` cannot be called from inside another task.** If you're mid-task and need to spawn a separate one, use `schedule_task` with `schedule="immediate"`. The two actions create equivalent task objects — the difference is the entry point.

`schedule_task` schedule expressions (validated by [app/scheduler/parser.py](app/scheduler/parser.py)):
```
"immediate"               run right now (queues an immediate trigger)
"at 3pm" / "at 3:30pm"    one-time today
"tomorrow at 9am"         one-time tomorrow
"in 2 hours" / "in 30 minutes"    one-time relative
"every day at 7am"        recurring daily
"every monday at 9am"     recurring weekly
"every 3 hours"           recurring interval
"0 7 * * *"               cron (5-field)
```
Times must include `am`/`pm`. Freeform like "daily at", "weekly", "every morning", "every weekday" are NOT accepted.

One-time scheduled tasks are auto-removed after firing. Recurring schedules persist in [app/config/scheduler_config.json](app/config/scheduler_config.json).

### Simple mode

Use for work completable in 2-3 actions where no user approval is required at the end.

Pick simple when:
- Quick lookup (weather, time, exchange rate).
- Single-answer question (calculation, conversion).
- Search and summarize where the result is the response.
- No file the user must review.
- No irreversible external action (no sends, no payments, no destructive writes).

Flow:
```
1. task_start(task_mode="simple", ...)            ← from conversation
   OR schedule_task(mode="simple", schedule="immediate", ...)  ← from inside a task
2. (optional) send_message — brief ack
3. Execute the 1-3 actions
4. send_message — deliver the result
5. task_end                                       ← auto-completes, no approval gate
```

Simple-mode rules:
- No `task_update_todos`. No phase prefixes. The work is small enough that planning would slow you down.
- Session caching IS active during simple-mode multi-turn execution (cache hits across the 2-3 turns).
- If during execution you discover the work is bigger than simple — STOP. End the simple task with the partial result via `send_message` + `task_end`. Then `schedule_task(schedule="immediate", mode="complex")` for the remainder. Do NOT silently chain more actions in simple mode.

### Complex mode

Use for multi-step work, file outputs, irreversible operations, anything the user calls a "project", or anything spanning multiple sessions.

Pick complex when:
- Plan has more than 3 actions.
- Output is a file or artifact the user should review and approve.
- Work touches external state (sends messages, makes purchases, modifies third-party data).
- Work spans multiple sessions or days (mission-scale — see `## Workspace`).

State machine:
```
task_start(task_mode="complex", ...)             ← from conversation
   OR schedule_task(mode="complex", schedule="immediate", ...)  ← from inside a task
       │
       ▼
send_message                                      ← acknowledge IMMEDIATELY
       │
       ▼
task_update_todos(<full plan, all "pending", phase-prefixed>)
       │
       ▼
loop {
    mark ONE todo "in_progress"
    execute relevant actions (parallel within the same todo is fine)
    mark that todo "completed"
    if you discover missing info → add a fresh "Collect:" todo, revert
}
       │
       ▼
send_message(<final result + explicit approval request>)
       │
       ▼
wait for user reply  ← queues a future trigger; you do NOT block, see ## Runtime
       │
       ▼
task_end                                          ← only after explicit approval
```

### Todo phase prefixes (mandatory in complex mode)

Every todo must begin with one of these prefixes:
```
Acknowledge:   Restate the user's goal in your own words
Collect:       Gather inputs (read files, search, ask user, list integrations)
Execute:       Do the work (generate, transform, send, write)
Verify:        Check the output meets the goal (re-read files, run tests, smoke-test)
Confirm:       Present the result to the user for approval
Cleanup:       Remove temp files, restore state, close connections
```

Rules:
- Exactly ONE todo `in_progress` at a time. Always.
- Never skip Verify on todos that produce files or change external state.
- Never reach Cleanup before Confirm has been signed off by the user.
- If during Execute you discover missing info, add a new `Collect:` todo and revert. Do not guess.
- Cleanup is also where you remove `workspace/tmp/{task_id}/` artifacts you do not want to persist (the directory is auto-cleaned anyway, but explicit cleanup catches files saved elsewhere).

### Action sets and skills (locked at task start)

When a task is created via `task_start` or `schedule_task`, action sets and skills are selected automatically by the LLM based on the task description ([app/internal_action_interface.py](app/internal_action_interface.py) `do_create_task`). If the task was started via a skill slash command (e.g. `/pdf`), the pre-selected skill bypasses LLM skill selection but action sets are still LLM-selected and merged with skill-recommended ones.

Once the task starts, the selection is **locked**. Mid-task changes:
- Action sets: `action_set_management` action can add/remove sets.
- Skills: cannot be swapped mid-task. End the task and start a new one if you need a different skill.

### Output destinations

- Files the user should keep across sessions → `agent_file_system/workspace/`
- Drafts, sketches, intermediate state → `agent_file_system/workspace/tmp/{task_id}/` (auto-cleaned on `task_end` and on agent start)
- Mission-scale, multi-task initiatives → `agent_file_system/workspace/missions/<mission_name>/INDEX.md`

See `## Workspace` for the mission template and scan-on-start protocol.

### Common task-mode mistakes to avoid

- Starting in **simple**, work grows mid-task → do NOT silently chain more actions. End simple, schedule complex.
- Calling `task_start` **from inside a task** → it doesn't work that way. Use `schedule_task` instead.
- Using `schedule_task("immediate")` **from conversation** → use `task_start`. Conversation is built around it; using `schedule_task` from conversation creates an extra trigger hop.
- Calling `task_end` **without a final `send_message`** → simple tasks must deliver the result; complex tasks must summarize and request approval. Never end silently.
- Marking todos `completed` **before the actions ran** → mark `in_progress`, run, then mark `completed`.
- Adding planning todos like `Acknowledge: Plan the work` to simple tasks → simple tasks do not use todos at all.

---

## Communication Rules

The user only sees what you send via `send_message` (or `send_message_with_attachment`). Everything else — actions, errors, internal reasoning — is invisible to them.

Cadence:
- **Acknowledge immediately** after `task_start`. One sentence is enough. Don't wait for the first action to complete.
- **Update on milestones**, not on every action. A milestone is: phase transition (Collect → Execute), significant finding, blocker, request for input.
- **Stay silent during tight Verify loops.** If you're re-reading a file three times to check formatting, do not narrate each read.
- **Final message before `task_end`** must summarize what was done, list any artifacts (with paths), and explicitly request approval.

Channel choice:
- Default: in-context chat.
- If the user has a `Preferred Messaging Platform` set in `USER.md` and the task is asynchronous (proactive task, scheduled completion), prefer that platform.
- Use `send_message_with_attachment` when sending generated files; pass the workspace path.

What NOT to send:
- Internal reasoning ("I'm now thinking about...").
- Tool-call narration ("Let me run grep_files...").
- Repeated acknowledgements after the first.
- Status pings during fast operations.

Hard rules:
- Never end a complex task without explicit approval.
- Never end any task silently.
- Never claim success when an action failed — see `## Errors`.

---

## Errors

You operate inside a harness with multiple safety layers. Some failures are handled automatically; others require you to recover deliberately. Knowing which is which is the difference between a productive recovery and an infinite loop.

### Action result schema (read this first)

EVERY action — built-in, MCP-routed, or skill-spawned — returns a dict with at minimum:

```
{
  "status": "success" | "error",
  "message": "<human-readable detail>",     # present on error, often present on success
  ... action-specific output fields ...
}
```

Before you treat an action's output as a result you can act on, **check `status`**. If `status == "error"`, the `message` field tells you what went wrong. Failing to check `status` and proceeding as if everything worked is the most common avoidable failure mode in this harness.

### Error event kinds in the event stream

The event stream ([agent_core/core/impl/event_stream/manager.py](agent_core/core/impl/event_stream/manager.py)) records errors in distinct event kinds. You will see these when reviewing your own past steps:

```
"error"          react-level errors. LLM failures, exceptions in workflow handlers.
                 Display message comes from classify_llm_error() (see below).
"action_error"   actions DROPPED before execution: parallel-constraint violations,
                 missing actions, invalid decisions.
                 (Distinct from an action that ran and returned status=error.)
"warning"        soft warnings that you must heed:
                 - Action limit at 80% / 100%
                 - Token limit at 80% / 100%
                 - Other harness alerts
"internal"       limit-choice messages, system-side info.
```

When you see an `"error"` or `"action_error"` event in the stream, it has already been logged. You do NOT need to log it again. You DO need to react to it.

### Harness-level safety nets (do not duplicate)

The harness already handles certain failures so you do not have to. Recognizing them prevents you from stepping on the harness.

**Per-action timeout** ([agent_core/core/impl/action/executor.py](agent_core/core/impl/action/executor.py))
- Default `DEFAULT_ACTION_TIMEOUT = 6000` seconds (100 min). Individual actions may declare shorter timeouts.
- On timeout, the action returns:
  ```
  {"status": "error", "message": "Execution timed out after Ns while running <internal|sandboxed> action."}
  ```
- Recovery: the timeout is final for that invocation. Either retry with smaller scope (fewer rows, narrower regex, smaller batch) or split the work into multiple actions.

**LLM consecutive-failure circuit breaker** ([agent_core/core/impl/llm/errors.py](agent_core/core/impl/llm/errors.py), [agent_core/core/impl/llm/interface.py](agent_core/core/impl/llm/interface.py))
- After repeated consecutive LLM failures (auth, network, etc.), the harness raises `LLMConsecutiveFailureError`.
- `_handle_react_error` walks the exception chain (`__cause__`/`__context__`) to detect this and **automatically cancels the task** via `task_manager.mark_task_cancel(...)`. The agent's last instruction is cached in `_llm_retry_instructions[session_id]` for retry-after-fix.
- A `LLM_FATAL_ERROR` UI event is emitted so the user sees a clear failure dialog.
- **Implication:** if you see `MSG_CONSECUTIVE_FAILURE` ("LLM calls have failed N consecutive times. Task aborted to prevent infinite retries."), the task is already gone. Do NOT try to re-create it. The user must check their LLM configuration.

**Action limit (`max_actions_per_task`, minimum 5)** ([agent_core/core/state/types.py](agent_core/core/state/types.py))
- Tracked in `STATE.get_agent_property("action_count")` against `max_actions_per_task`.
- At **80%** the harness logs a `"warning"` event:
  > "Action limit nearing: 80% of the maximum actions (N actions) has been used. Consider wrapping up the task or informing the user that the task may be too complex. If necessary, mark the task as aborted to prevent premature termination."
  - Your response: **wrap up**. Send the best result you have, or ask the user whether to abort. Do NOT ignore.
- At **100%** the harness logs a `"warning"`, sends a Continue/Abort chat message to the user, and PAUSES the task. `_check_agent_limits` returns False; the next trigger does not get scheduled. The task resumes only when the user picks Continue (limits reset) or Abort.

**Token limit (`max_tokens_per_task`, minimum 100000)** ([agent_core/core/state/types.py](agent_core/core/state/types.py))
- Same 80% warning / 100% pause pattern as actions, but for cumulative token usage.
- 80% warning text is identical except "tokens" instead of "actions".
- 100% triggers the same Continue/Abort gate.
- Your response at 80%: same as action warning — wrap up or summarize aggressively.

**Parallel constraint violations**
- The router may drop an action before it runs and surface a `"action_error"` event with `_error` describing the constraint (e.g., "ignore must run alone", "cannot run multiple send_message in parallel").
- The action is not executed; subsequent actions in the same batch may still run.
- Recovery: re-issue the action sequentially in the next turn, not in parallel.

### LLM error classes (from `classify_llm_error`)

When an LLM call fails non-fatally, `classify_llm_error()` returns one of these messages. Knowing the class tells you whether retrying makes sense and what to tell the user:

```
MSG_AUTH         (HTTP 401/403)   "Unable to connect to AI service. Check your API key in Settings."
                                  → DO NOT retry. Tell user to set/fix API key. See ## Models.
MSG_MODEL        (HTTP 404)       "The selected AI model is not available."
                                  → DO NOT retry. Tell user model name is wrong/unavailable.
MSG_CONFIG       (HTTP 400)       "AI service configuration error. The selected model may not support required features."
                                  → DO NOT retry. May indicate a feature flag (vision, tool use) not supported by chosen model.
MSG_RATE_LIMIT   (HTTP 429)       "AI service is rate-limited. Please wait a moment and try again."
                                  → Retryable after delay. Consider enabling slow_mode in settings.
MSG_SERVICE      (HTTP 5xx)       "AI service is temporarily unavailable. Please try again later."
                                  → Retryable. Often transient.
MSG_CONNECTION   (timeout, ConnectionError)  "Unable to reach AI service. Check your internet."
                                  → Retryable if connectivity recovers.
MSG_GENERIC      (unmatched)      "An error occurred with the AI service."
                                  → Investigate before retrying.
```

These come back as user-friendly strings to display; the harness wraps them in `"error"` events. You see them via the event stream and `display_message`.

### Failure taxonomy and recovery decision

There are four failure types. Identify which one you are in, then follow the matching recovery.

**TRANSIENT**
- Symptoms: rate limit, transient 5xx, connection error, file lock, sandbox process hiccup.
- Action: wait briefly, retry ONCE with the same params.
- Budget: 1 retry per action invocation. No second retry on the same params.

**APPROACH**
- Symptoms: action returned `status=error` with a "bad params" / "not found" / "invalid format" message. Semantic mismatch (you grepped the wrong file, ran the wrong action).
- Action: change the approach. Different action, different params, different plan. Do NOT retry the same call unchanged.
- Examples:
  - `read_file` on a non-existent path → `find_files` first.
  - `schedule_task` with `"daily at 9am"` rejected → use `"every day at 9am"` (the validated format).

**IMPOSSIBLE**
- Symptoms: missing access (no API key, no integration), hardware action needed (physical printer), policy violation, user data the agent cannot access.
- Action: stop. `send_message` explaining what was tried and why it cannot work. Offer alternatives if any. For complex tasks, mark the task aborted.
- Examples:
  - `/linkedin login` required → ask user to authenticate.
  - "send a fax" → state limitation, suggest email.

**LOOP**
- Symptoms: same action + same params + same error TWICE.
- Action: stop immediately. Escalate to user with a specific question. Do NOT try a third time.
- Why: loops burn action/token budget and produce no progress. The harness's `max_actions_per_task` and `LLMConsecutiveFailureError` limits are backstops, not your primary safety.

### Recovery patterns by error source

**File / shell / Python action returns `status=error`**
- Read the `message` field. It often points at the fix (file not found, permission, syntax error, missing dep).
- If the message says missing dependency for `run_python` / `run_shell`, install it via `pip install`/`npm install` in a follow-up `run_shell` call (auto-installed in sandboxed mode for declared `requirements`, but ad-hoc imports require explicit install).
- If it says path not found, `find_files` or `list_folder` to locate before retry.

**Web / fetch action returns error**
- HTTP 4xx → URL or auth wrong. Don't retry the same URL.
- HTTP 5xx or timeout → transient. One retry, then fall back (different URL, cached source, or report unavailability).
- Empty result on `web_search` → broaden query or try a different search term. Do NOT keep retrying the same query.

**Schedule / proactive action returns error**
- Schedule expression rejected by parser → see `## Tasks` for the validated format list. Re-issue with a supported expression.
- Recurring task creation fails → check PROACTIVE.md for syntax errors near your edit; the file's HTML markers (`PROACTIVE_TASKS_START`/`END`) must remain intact.

**MCP tool returns error**
- Server-side error in the MCP tool → check EVENT.md for stderr from the MCP server process. Often missing API key in the server's `env` block.
- Tool not found → server may be disabled in `mcp_config.json` or the `action_set_name` not loaded. See `## MCP`.

**Action limit / token limit warning at 80%**
- Wrap up. Send the partial result and ask the user whether to continue.
- If the work genuinely needs more budget, ask the user explicitly — they can pick Continue at the 100% gate and the limits reset.
- Marking the task as aborted (`task_end` with status=aborted/failed) is preferable to silently exceeding the limit and pausing the task.

**Action limit / token limit reached (100%)**
- The task is paused; you don't get a next trigger until the user chooses Continue or Abort.
- Do NOT attempt to schedule anything or send messages — the harness has already sent the user a Continue/Abort dialog.
- When the user picks Continue, your next trigger arrives with limits reset.

**LLM call failed (non-fatal)**
- The harness retries internally up to its consecutive-failure threshold.
- If you see a `"error"` event with one of the `MSG_*` strings, treat it according to the class table above.
- If it escalates to `LLMConsecutiveFailureError` (`MSG_CONSECUTIVE_FAILURE`), the task is already cancelled. Do not try to recreate it.

### Self-troubleshooting via logs

When the action's `status=error` message does not tell you enough to recover, drop down to the runtime logs. The agent harness writes everything it does to disk, and you can read it.

**Three log surfaces. Know which to use for what.**

```
EVENT.md                       agent_file_system/EVENT.md
                               your perspective: events you produced/observed
                               (action_start, action_end, send_message, error,
                               warning, action_error, internal). Already on disk
                               and indexed by memory_search.

logs/<timestamp>.log           project_root/logs/
                               runtime perspective: harness internals, every
                               subsystem's INFO/WARN/ERROR log line. Loguru
                               format. Rotates at 50 MB, kept 14 days.
                               This is where stderr from sandboxed actions,
                               MCP server output, and Python tracebacks land.

diagnostic/logs/actions/       diagnostic/logs/actions/<ts>_<slug>.log.json
                               per-action diagnostic dump (when run via the
                               diagnostic harness). Contains full input/output
                               for individual actions. See diagnostic/README.md.
```

**Picking the right surface:**
- "What did I do, and what did the harness say back?" → EVENT.md.
- "Why did this action / MCP / hot-reload actually fail?" → `logs/<timestamp>.log`.
- "I want to replay one specific action's full input/output" → `diagnostic/logs/actions/`.

**Log line format (loguru):**
```
2026-05-03 16:00:12.066 | INFO     | agent_core.core.database_interface:__init__:60 - Action registry loaded. 195 actions...
^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
timestamp                  level      module:function:line                          message
```
- Levels: `DEBUG` < `INFO` < `WARNING` < `ERROR`. Default file threshold is INFO; harness emits a lot at INFO, so most context is captured.
- The `module:function:line` segment tells you exactly where in the codebase the message came from. You can `read_file <module path>` and jump to the line for full context.

**Subsystem tags you will see in messages.** Most subsystems prefix their log lines with a bracketed tag — grep for these:

```
[REACT]            react loop main flow                       app/agent_base.py
[REACT ERROR]      react-level exceptions caught              app/agent_base.py:_handle_react_error
[ACTION]           action preparation and execution           app/agent_base.py:_execute_actions
[TASK]             task lifecycle (create, update, end)       agent_core/core/impl/task/manager.py
[MEMORY]           memory indexing and processing             agent_core/core/impl/memory/manager.py
[MCP]              MCP server init, connect, tool calls       agent_core/core/impl/mcp/client.py
[SETTINGS]         settings load and updates                  agent_core/core/impl/settings/manager.py
[CONFIG_WATCHER]   hot-reload events                          agent_core/core/impl/config/watcher.py
[LIMIT]            action/token limit choice messages         app/agent_base.py
[SESSION]          session cache lifecycle                    agent_core/core/impl/llm/interface.py
[STATE]            state-debug snapshots                      app/agent_base.py
[ONBOARDING]       onboarding state                           agent_core/core/impl/onboarding/manager.py
[PROACTIVE]        proactive workflow                         app/proactive/manager.py
[RESTORE]          startup task restoration                   app/agent_base.py:_restore_sessions
[AGENT]            agent init, mode toggles                   app/agent_base.py:__init__
[LLM FACTORY]      LLM provider construction                  agent_core/core/impl/llm/interface.py
```

**Self-troubleshooting workflow.** When an action returns an error you cannot decode from `message` alone:

```
1. Identify the latest log file:
     list_folder logs/                        ← logs are timestamped, latest is freshest
2. Find the time window of the failure:
     - From EVENT.md, note the timestamp of the failing event.
     - That same timestamp will exist in logs/<latest>.log (within seconds).
3. Grep around that time + the relevant subsystem tag:
     grep_files "[MCP]"   logs/<latest>.log -A 5 -B 1   ← MCP server failure?
     grep_files "[ACTION]" logs/<latest>.log -A 5 -B 1   ← action execution issue?
     grep_files "ERROR"    logs/<latest>.log -B 2 -A 10  ← any error-level line + context
4. If a Python traceback is present, read upward from the traceback to the
   most recent INFO line in the same subsystem — that tells you the last
   successful step before the failure.
5. The "module:function:line" field on the failing log line points at the code
   path. read_file <module path> with offset = line - 30 to inspect.
6. Decide:
     - The error is in your action params       → ## Errors / APPROACH
     - The error is in a subsystem (MCP server crash, settings parse error,
       hot-reload exception)                   → ## MCP / ## Configs / ## Hot Reload
     - The error is in the LLM call             → see classify_llm_error classes above
     - The error is environmental (no API key,
       missing dep, port in use)               → tell the user, do not retry blindly
```

**Concrete grep recipes:**

```
# Did an MCP server crash on startup or fail to connect?
grep_files "[MCP]" logs/<latest>.log -A 3
# → look for "Failed to connect", "subprocess exited", non-zero return codes.

# Did the config watcher fail to apply a hot reload?
grep_files "[CONFIG_WATCHER]" logs/<latest>.log -A 3

# Did settings.json fail to parse?
grep_files "[SETTINGS]" logs/<latest>.log -A 3

# Did an action time out, and which one?
grep_files "Execution timed out" logs/<latest>.log -B 5

# Did the LLM hit consecutive failures?
grep_files "LLMConsecutiveFailureError\|MSG_CONSECUTIVE_FAILURE" logs/<latest>.log -A 5

# Did a sandboxed action subprocess produce stderr?
grep_files "venv\|requirements\|subprocess" logs/<latest>.log -A 3

# What did the agent's _check_agent_limits last log?
grep_files "[LIMIT]" logs/<latest>.log -A 2

# When did the last task end, and how?
grep_files "[TASK].*ended\|task_end\|mark_task_cancel" logs/<latest>.log -A 3

# Find the last 100 ERROR-level lines across the whole log:
grep_files "| ERROR " logs/<latest>.log -A 5
```

**Acting on what you find.** A log line is data, not a fix. The decision rules:

```
If the log shows                               then
─────────────────────────────────────────────  ──────────────────────────────────────
[MCP] subprocess exited with code N            MCP server crashed. Inspect its env in
                                               mcp_config.json. Likely missing API
                                               key or wrong command path. See ## MCP.

[SETTINGS] JSONDecodeError                     settings.json is malformed. Read the
                                               file, find the syntax error around the
                                               reported line, fix via stream_edit.

[CONFIG_WATCHER] reload failed                 the change was not picked up. Save
                                               again, or check the file is tracked in
                                               watcher.register() (see ## Hot Reload).

[REACT ERROR] LLMConsecutiveFailureError       harness already cancelled the task.
                                               Tell user to fix LLM config. Do NOT
                                               retry. See ## Models.

[LIMIT] ... 100% ... Waiting for user choice   task is paused. Do not issue actions
                                               until next trigger. See ## Errors above.

ModuleNotFoundError in run_python output       the script needs a dependency. Install
                                               via run_shell "pip install <pkg>" or
                                               declare in action requirements.

PermissionError / OSError on file write        the path is wrong, locked, or outside
                                               the allowed scope. Verify with
                                               list_folder; prefer workspace/ for
                                               outputs.

Long gaps between INFO lines (no activity)     the loop may be waiting for a trigger
                                               (waiting_for_user_reply, scheduled
                                               fire). Check the next trigger fire_at
                                               in ProactiveManager / Scheduler.
```

**When logs are the only honest source of truth.** Some failures do not surface as `status=error` in the action result — they manifest as the action *seeming to work* but the side effect not happening (e.g., `run_shell` returns 0 but a script printed "ok" while silently catching an exception; an MCP tool returns success but logged a warning that the operation was a no-op). When you suspect a silent failure, grep the logs for the timestamp of your action and look for `WARNING` or unexpected `ERROR` lines around it.

**Rotation and freshness.** Log files rotate at 50 MB and old files are kept for 14 days. The latest file by mtime is the one with current activity. If your investigation needs older history (e.g., a crash from yesterday), `list_folder logs/` and pick by timestamp.

**Do not ask the user for log content you can read yourself.** The user does not have a better view than you do. If they ask "what's the error?", read the log, summarize, and explain. They are not your support layer — you are theirs.

### Surfacing failures to the user

Mid-task (recoverable):
- `send_message` with: what failed (one sentence), what you tried (1-3 bullets), what you'll try next (one sentence).
- Do not surface every transient retry. The user does not need to know about a single rate-limit retry that succeeded.

Terminal (cannot recover):
- For complex tasks: `send_message` with the failure summary + any salvageable partial result, then `task_end` with a failed-status summary.
- For simple tasks: `send_message` with the failure, then `task_end`.
- Mark task aborted via `task_manager.mark_task_cancel(...)` semantics ONLY through the proper action paths (don't try to invoke internals directly).
- Never fabricate success. If you couldn't read the file, do not paraphrase what you "would have" found.

### When you're blocked but not failed

You're blocked when you don't know what to do next AND retrying won't help. The recovery is information, not action.

```
1. State the blocker plainly: "I can't proceed because <X>."
2. List what you tried: "- Tried <A>: <result>. - Tried <B>: <result>."
3. Ask ONE specific question — not "what should I do".
   Good:  "Should I use the Slack bot token from settings.oauth.slack, or do you want me to reuse the existing /slack login session?"
   Bad:   "What do you want me to do?"
```

### Common error-handling anti-patterns

- **Treating action output as success without checking `status`.** The #1 source of silent failures. Always read the `status` field before using output.
- **Retrying the same action with the same params** after `status=error` and no change. The error will repeat. Either change a parameter, change the action, or stop.
- **Ignoring `"warning"` events** about action/token limits. The harness will pause your task soon — get ahead of it. At 80%, wrap up or send the partial result.
- **Continuing to issue actions while limit-paused (100%).** They will not fire. The user is being shown a Continue/Abort dialog. Wait for the next trigger.
- **Trying to retry after `LLMConsecutiveFailureError`.** The task is already cancelled by `_handle_react_error`. Do NOT recreate it. Tell the user the LLM configuration needs attention.
- **Catching exceptions in `run_python` / `run_shell` and printing "ok".** The harness sees `status=success` if your script swallows the error. Always propagate non-zero exit codes / raise on failure.
- **Fabricating success messages on failure.** Forbidden. If you couldn't read the file or call the API, do not paraphrase what you "would have" produced.
- **Asking open-ended "what should I do" questions.** Always one specific question with an implied default ("Use the bot token from settings.oauth.slack, or reuse the existing /slack login session?").
- **Self-detected logical loops.** The consecutive-failure breaker only catches LLM-call failures. If you keep choosing slightly different params for the same action and getting the same business-logic error (e.g., "user not found" three times with three different IDs you guessed), that is a logical loop. Stop and ask the user.

### What the harness does NOT do for you

- It does NOT change your approach when an action fails. You must.
- It does NOT pick a different action when one returns `status=error`. You must.
- It does NOT detect a logical loop you've created (same action with slightly different params, same error). The consecutive-failure breaker only catches LLM-call failures, not action-result failures. You must detect logical loops.
- It does NOT verify that an action's `status=success` result actually achieved your goal. Verify (re-read the file you wrote, re-query the data you updated). See `## Tasks` Verify phase.

---

## Files

### read_file
- Returns `cat -n` formatted lines plus a `has_more` flag.
- Default limit is 2000 lines. Use `offset` and `limit` for targeted reads.
- For files larger than 500 lines: read the head first to learn structure, then `grep_files` for the section you need, then `read_file` with the right offset and limit.
- Full input schema: [app/data/action/read_file.py](app/data/action/read_file.py).

### grep_files
Three output modes:
- `files_with_matches`: returns file paths only. Use for discovery ("which files contain X").
- `content`: returns matching lines with line numbers. Use for investigation.
- `count`: returns match counts per file. Use for frequency checks.

Supported parameters: `glob`, `file_type`, `before_context` / `after_context`, `case_insensitive`, `multiline`.

Full input schema: [app/data/action/grep_files.py](app/data/action/grep_files.py).

### stream_read + stream_edit
- Use as a pair when modifying an existing file.
- `stream_read` returns the exact bytes.
- `stream_edit` applies a precise diff.
- Preferred over `write_file` for edits. Preserves unrelated content and avoids whole-file overwrites.

### write_file
Use only when:
- Creating a brand new file, OR
- Doing a deliberate full rewrite of a small file.

Never use `write_file` to patch an existing large file. Use `stream_edit`.

### find_files vs list_folder
- `list_folder`: top-level listing of a single directory.
- `find_files`: recursive name pattern search across a tree.

### convert_to_markdown vs read_pdf
- `read_pdf`: direct PDF reading with page support.
- `convert_to_markdown`: for office formats (docx, xlsx, pptx) you intend to grep afterwards.

### Anti-patterns
- Repeated full reads of large files. Use `grep_files` plus offset reads instead.
- Chaining four `read_file` calls when one `grep_files` would answer the question.
- Reading binary files as text. Use the dedicated action (`read_pdf`, `describe_image`, `understand_video`, etc.).

---

## File System

Your persistent file system is `agent_file_system/`. Every file has a defined writer, reader, format, and update rule. Files marked `DO NOT EDIT` are managed by harness subsystems. Touching them creates inconsistency you cannot recover from.

```
agent_file_system/
├── AGENT.md                  Operational manual (this file)
├── USER.md                   User profile
├── SOUL.md                   Personality (injected to system prompt)
├── FORMAT.md                 Document / design standards
├── MEMORY.md                 Distilled facts                     DO NOT EDIT
├── EVENT.md                  Full event log                      DO NOT EDIT
├── EVENT_UNPROCESSED.md      Memory-pipeline staging buffer      DO NOT EDIT
├── CONVERSATION_HISTORY.md   Rolling dialogue log                DO NOT EDIT
├── TASK_HISTORY.md           Task summaries                      DO NOT EDIT
├── PROACTIVE.md              Recurring tasks + Goals/Plan/Status
├── GLOBAL_LIVING_UI.md       Global Living UI design rules
├── MISSION_INDEX_TEMPLATE.md Template for mission INDEX.md files
└── workspace/                Sandbox for task outputs (see ## Workspace)
```

### Indexed for memory_search

The MemoryManager indexes a fixed set of files for semantic retrieval ([agent_core/core/impl/memory/manager.py](agent_core/core/impl/memory/manager.py), constant `INDEX_TARGET_FILES`):

```
AGENT.md
PROACTIVE.md
MEMORY.md
USER.md
EVENT_UNPROCESSED.md
```

Editing any of these triggers re-indexing via [agent_core/core/impl/memory/memory_file_watcher.py](agent_core/core/impl/memory/memory_file_watcher.py). Other files in `agent_file_system/` are NOT indexed. To find content in non-indexed files, use `grep_files` directly.

### AGENT.md
- Purpose: operational manual for you.
- Write access: user (manually); you (only for operational improvements you have learned, see `## Self-Edit`).
- Read pattern: `read_file` / `grep_files` on demand. Always grep by `## <Topic>` header.
- Format: structured markdown. Stable `## <Topic>` headers. HTML comment markers (`<!-- name -->` ... `<!-- /name -->`) around schema and command blocks.
- Update rule: bump `version:` in front matter on material changes. Sync to `app/data/agent_file_system_template/AGENT.md` when the change should ship to new installs.

### USER.md
- Purpose: persona and preferences of the user. Read at the start of any user-facing task.
- Write access: the agent (after confirming with the user); the onboarding wizard.
- Read pattern: at session start, when personalizing responses, when picking communication channel.
- Format: plain markdown sections. Standard sections: `## Identity`, `## Communication Preferences`, `## Agent Interaction`, `## Life Goals`, `## Personality`.
- Update rule: confirm the preference is durable before writing. One-off requests do not belong here.

### SOUL.md
- Purpose: personality, tone, behavior. Injected directly into the system prompt every turn.
- Write access: user (primarily); you only on explicit user request.
- Read pattern: the system reads on every turn. You do NOT need to `read_file` it during normal operation.
- Caution: edits affect every interaction immediately on next turn. Confirm with user before saving.

### FORMAT.md
- Purpose: design and formatting standards for documents you generate.
- Write access: user (preferences); you when the user supplies a new rule (with confirmation).
- Read pattern: `grep_files "## <filetype>" agent_file_system/FORMAT.md` before generating any document. See `## Documents`.
- Sections: `## global` (universal rules), `## pptx`, `## docx`, `## xlsx`, `## pdf`. Type-specific sections override `## global`.

### MEMORY.md
- Purpose: distilled long-term memory. Survives across sessions.
- Write access: ONLY the memory processor (daily 3am job, plus startup replay if EVENT_UNPROCESSED.md is non-empty).
- Hard rule: you MUST NOT edit MEMORY.md directly. Use the memory pipeline. See `## Memory`.
- Read pattern: `memory_search` action (RAG, returns relevance-ranked pointers). Do NOT grep MEMORY.md directly for retrieval.
- Format: `[YYYY-MM-DD HH:MM:SS] [type] content` — one fact per line.
- Types: `capability`, `project`, `workspace`, `focus`, `preference`, `analysis`, `user_complaint`, `system_warning`, `system_limit`.

### EVENT.md
- Purpose: complete chronological event log. Append-only.
- Write access: EventStreamManager. Hard rule: DO NOT edit.
- Read pattern: `read_file` / `grep_files` for self-troubleshooting. See `## Errors` for log workflow.
- Format: `[YYYY/MM/DD HH:MM:SS] [event_type]: payload`. Multi-line payloads continue on subsequent lines.
- Auto-rotated when size threshold is exceeded.

### EVENT_UNPROCESSED.md
- Purpose: staging buffer for events awaiting memory distillation.
- Write access: EventStreamManager (filtered subset of EVENT.md events). Hard rule: DO NOT edit.
- Read pattern: the memory processor reads it daily 3am. See `## Memory`.
- Cleared: after each successful memory-processing run.
- Filter: events of kind `action_start`, `action_end`, `todos`, `error`, `waiting_for_user` are NOT staged. The pipeline focuses on user-facing dialogue and important state changes.
- Skip flag: during memory-processing tasks, `set_skip_unprocessed_logging(True)` prevents the task's own events from looping back. Reset automatically on `task_end`.

### CONVERSATION_HISTORY.md
- Purpose: rolling dialogue record across all sessions.
- Write access: EventStreamManager (on every user/agent message). Hard rule: DO NOT edit.
- Read pattern: when restoring context for a returning user or reviewing what was said.
- Format: `[YYYY/MM/DD HH:MM:SS] [sender]: message`. Sender is `user` or `agent`. Multi-line messages continue under one header.
- Lifespan: permanent. Never auto-cleared.

### TASK_HISTORY.md
- Purpose: summary of every completed (or cancelled) task.
- Write access: appended on `task_end`. Hard rule: DO NOT edit.
- Read pattern: when checking past outcomes for a similar task.
- Format: one markdown section per task:
  ```
  ### Task: <task name>
  - **Task ID:** <id>
  - **Status:** completed | cancelled | failed
  - **Created:** <ISO timestamp>
  - **Ended:** <ISO timestamp>
  - **Summary:** <one-paragraph outcome>
  - **Instruction:** <original task instruction>
  - **Skills:** <skill names used>
  - **Action Sets:** <action set names used>
  ```

### PROACTIVE.md
- Purpose: recurring proactive task definitions plus the planner-maintained Goals / Plan / Status section.
- Write access: `recurring_add` / `recurring_update_task` / `recurring_remove` actions; planners (day, week, month).
- Read pattern: every heartbeat (every 30 min); planners on their schedules; you when the user asks about scheduled work. See `## Proactive`.
- Format: YAML blocks between `<!-- PROACTIVE_TASKS_START -->` and `<!-- PROACTIVE_TASKS_END -->` markers, followed by a Goals / Plan / Status section.
- Authority: PROACTIVE.md is the source of truth for the Decision Rubric, Permission Tiers, and recurring-task YAML schema. Do NOT duplicate that content elsewhere.

### GLOBAL_LIVING_UI.md
- Purpose: global design rules applied to every Living UI project.
- Write access: user (primarily). You only when the user supplies a new universal rule with confirmation.
- Read pattern: before creating any Living UI project. See `## Living UI`.
- Sections: Design Preferences (colors, theme, font, border radius, spacing), Always Enforced rules, Optional rules, Custom rules.

### MISSION_INDEX_TEMPLATE.md
- Purpose: template for `workspace/missions/<name>/INDEX.md`. See `## Workspace`.
- Write access: static template. DO NOT edit.
- Read pattern: when starting a mission, copy this template into the mission directory and fill it in.
- Fields: Goal, Status, Key Findings, What's Been Tried, Next Steps, Resources & References, Constraints & Notes.

### Living UI projects (workspace/living_ui/)

Living UI projects live at `agent_file_system/workspace/living_ui/<project_name>_<hash>/`. Internal structure varies project to project depending on what the user asked for (different stacks, frameworks, file layouts). Do NOT assume any particular structure beyond the three required files below. To see what's actually in a specific project, `list_folder` it. For lifecycle (create, modify, restart, inspect), use `living_ui_actions`. See `## Living UI`.

Required files (every project has these):

```
workspace/living_ui/<name>_<hash>/
├── LIVING_UI.md          Per-project doc: purpose, decisions, project-specific rules
├── config/
│   └── manifest.json     Project metadata: name, hash, ports, capabilities
└── logs/                 Project logs (timestamped). Format and filenames vary per project.
```

- `LIVING_UI.md`: read this first when working on an existing project. Records purpose, design decisions, and any project-specific overrides of `GLOBAL_LIVING_UI.md`.
- `config/manifest.json`: read by the runtime to identify the project and its assigned ports. Do not rename a project directory by hand. Re-register via `living_ui_actions` instead.
- `logs/`: where the project's runtime, build, and console output land. First place to grep when a project misbehaves.

Everything else (backend, frontend, build output, dependency caches, databases) is project-specific. To learn what a fresh-from-template project would contain (one possible shape, not the only one), see [app/data/living_ui_template/](app/data/living_ui_template/).

### Files outside agent_file_system/

Some persistent state the agent interacts with lives outside this directory:

```
app/config/settings.json              model, API keys, OAuth, cache              (## Configs)
app/config/mcp_config.json            MCP server registry                         (## MCP)
app/config/skills_config.json         enabled / disabled skills                   (## Skills)
app/config/external_comms_config.json platform listener configs                   (## Integrations)
app/config/scheduler_config.json      cron schedules                              (## Proactive)
app/config/onboarding_config.json     first-run state                             (## Onboarding)
skills/<name>/SKILL.md                installed skills                            (## Skills)
.credentials/<platform>.json          OAuth tokens, bot tokens, API keys
                                      DO NOT print contents to chat or logs
logs/<timestamp>.log                  runtime logs                                (## Errors)
chroma_db_memory/                     ChromaDB index for memory_search
                                      DO NOT edit
```

---

## Workspace

`agent_file_system/workspace/` is your sandbox for task output. Three subdirectories with distinct lifecycles:

```
agent_file_system/workspace/
├── <files at root>           Persistent task outputs the user should keep across sessions
├── tmp/
│   └── {task_id}/            Per-task scratch directory. Auto-cleaned.
├── missions/
│   └── <mission_name>/       Multi-task initiative. Persists indefinitely.
│       ├── INDEX.md          Required (template at MISSION_INDEX_TEMPLATE.md)
│       └── <mission files>
└── living_ui/
    └── <name>_<hash>/        Living UI projects. See ## File System.
```

### Where to put a file

```
Type of file                                      → Destination
final document the user should keep               → workspace/<filename>
draft, sketch, intermediate state, scratch        → workspace/tmp/{task_id}/<filename>
mission deliverable (multi-task initiative)       → workspace/missions/<mission_name>/<filename>
Living UI project file                            → workspace/living_ui/<name>_<hash>/...
```

### Lifecycle rules

- `workspace/` (root): never auto-cleaned. Anything you save here persists until the user deletes it.
- `workspace/tmp/{task_id}/`: created automatically by `task_manager._prepare_task_temp_dir(task_id)` when a task starts. Cleaned by `task_manager.cleanup_all_temp_dirs(...)` on `task_end` AND on agent startup (excluding currently-restored tasks). Use this for anything you don't need after the task ends.
- `workspace/missions/<name>/`: never auto-cleaned. The mission's `INDEX.md` is what future-you reads to restore context.
- `workspace/living_ui/<name>_<hash>/`: managed via `living_ui_actions`. Do not rename or delete by hand. See `## Living UI`.

### Path discipline

- Always use absolute paths when invoking actions: `agent_file_system/workspace/<...>`. Never relative paths.
- Inside an action result you may receive a path; pass it through verbatim. Do not normalize.
- Filenames: lowercase, snake_case or kebab-case, no spaces. Example: `tsla_analysis_2026_05_04.pdf`.
- For task-scoped files use the actual `task_id`, not a guess. The harness sets `task.temp_dir` on task creation; the path is `agent_file_system/workspace/tmp/{task_id}/`.

### Missions: when to create one

Create `workspace/missions/<mission_name>/INDEX.md` when ANY of:
- Work spans multiple sessions or days.
- Plan has more than ~10 todos.
- User uses words like "project", "initiative", "ongoing", "campaign", "phase".
- Output of this task will feed into a future task.

If the answer is "no" to all, do NOT create a mission. A single complex task is enough.

### Missions: scan-on-start

At the start of every complex task:
```
1. list_folder agent_file_system/workspace/missions/
2. If any directory name looks relevant to the user's request:
     read_file agent_file_system/workspace/missions/<name>/INDEX.md
3. Decide:
     - Resume an existing mission              → continue updating its INDEX.md
     - Create a new mission                    → copy MISSION_INDEX_TEMPLATE.md
     - One-off complex task, not a mission     → no mission directory
```

This is non-optional. Skipping the scan causes duplicate work and lost context.

### Mission INDEX.md fields

Template lives at [agent_file_system/MISSION_INDEX_TEMPLATE.md](agent_file_system/MISSION_INDEX_TEMPLATE.md). Required fields:

- **Goal**: what "done" looks like, with concrete deliverables.
- **Status**: one of `Not started | In progress | Blocked | Completed | Abandoned`. Plus last task summary, last updated date.
- **Key Findings**: distilled discoveries. The most important section. This is what future-you reads to restore context. Keep it tight and current.
- **What's Been Tried**: approaches plus outcomes. Prevents repeating failed attempts.
- **Next Steps**: concrete actions a fresh task can pick up immediately. Be specific enough that no further investigation is needed to start.
- **Resources & References**: links, file paths, tools, contacts.
- **Constraints & Notes**: deadlines, user preferences, environmental limits.

### Mission INDEX.md update cadence

- At task start (resuming a mission): read INDEX.md fully. Add a `Status` line for the new task.
- During the task: append to `Key Findings` whenever you learn something durable. Append to `What's Been Tried` after any completed approach (success or failure).
- Before `task_end`: update `Status`, write `Next Steps` so a fresh task session can pick up immediately. If the mission is done, mark `Status: Completed`.

A mission with stale `Next Steps` is worse than no mission. Always leave it actionable.

### What does NOT belong in workspace/

- Configuration files (use `app/config/`).
- Skills (use `skills/`).
- Credentials (use `.credentials/`).
- Logs (auto-go to `logs/<timestamp>.log`).
- Editing AGENT.md / USER.md / SOUL.md / FORMAT.md (these are in `agent_file_system/`, not `workspace/`).

---

## Documents

[agent_file_system/FORMAT.md](agent_file_system/FORMAT.md) is the source of truth for every document you generate (PDF, pptx, docx, xlsx, and any other file-format output). Read it before generating; it carries the user's brand colors, fonts, writing style, and layout rules.

### FORMAT.md structure

```
## global       universal rules: brand colors, fonts, writing style, layout
## pptx         slide-deck specifics (aspect ratio, margins, slide types, typography)
## docx         Word document standards
## xlsx         spreadsheet standards
## pdf          PDF generation standards
```

The user can add more file-type sections (e.g., `## md`, `## csv`). Type-specific sections OVERRIDE `## global` for that file type.

### Protocol before generating any document

```
1. grep_files "## <filetype>" agent_file_system/FORMAT.md -A 50
   Read the file-type section in full.

2. grep_files "## global" agent_file_system/FORMAT.md -A 50
   Read the global section in full.

3. If the file-type section is missing, fall back to global only.

4. Apply the combined rules to your output: colors, fonts, spacing,
   layout, writing style, language conventions, brand assets.

5. After generating, verify the output matches by re-reading the produced
   file (or summary of it). Especially for visual artifacts (PDF, pptx).
```

This is non-optional. Generating documents without reading FORMAT.md produces inconsistent outputs the user has to redo.

### Action support

Document generation actions in the standard action set:
```
create_pdf              build a PDF from markdown / text
                        (preferred over rendering via run_python)
convert_to_markdown     normalize office formats before further processing
read_pdf                read a PDF with page support
```

Skills that compose document workflows (sample):
```
pdf, docx, pptx, xlsx          per-format end-to-end generation skills
file-format                    format normalization and conversion
compile-report-advance         multi-source compilation
```

If a skill exists for the target format (e.g., `pdf`), prefer invoking it (`/pdf` slash or LLM-selected) over composing actions yourself. Skills already encode the FORMAT.md read step and the right action sequence.

### Updating FORMAT.md

Edit when the user gives a durable formatting preference:
```
"always use a serif font in reports"            → ## global, font rule
"company logo is at /path/to/logo.png"          → ## global, brand asset
"PDF reports should have 1-inch margins"        → ## pdf, margins
"slide decks should be 16:9 with dark theme"   → ## pptx, layout / theme
```

Edit procedure:
```
1. Confirm scope: "global rule for all docs, or just for <filetype>?"
2. stream_edit FORMAT.md, write to the right section.
3. Send the user the exact lines you wrote so they can correct.
```

DO NOT silently change FORMAT.md. The user owns their style guide.

### Pitfalls

- Generating a document without reading FORMAT.md. Visible inconsistency cost.
- Mixing global and per-type rules incorrectly: per-type wins for that type, global wins everywhere else.
- Adding a new file-type section without user consent. Ask first.
- Storing the user's brand assets (logo URLs, colors) in MEMORY.md or USER.md instead of FORMAT.md. They belong in FORMAT.md.

---

## Living UI

"Living UI" = generated React / HTML / single-page-app projects that have persistent state and are served from CraftBot. Each project is a self-contained mini-app (kanban board, habit tracker, dashboard, etc.) the user can interact with through their browser. Lifecycle is managed via `living_ui_actions`.

Code: [app/data/action/living_ui_actions.py](app/data/action/living_ui_actions.py). File system layout: see `## File System` "Living UI projects" subsection.

### What you actually do for a Living UI request

You do NOT hand-write the project scaffold. The Living UI generator handles file scaffolding via the `living_ui_actions` action set. Your job is:
1. Capture the user's intent (what is the app for, what state does it persist, what views / interactions).
2. Apply GLOBAL_LIVING_UI.md design rules and any project-specific overrides.
3. Use the appropriate Living UI skill (`living-ui-creator`, `living-ui-modify`, `living-ui-manager`) to drive the generator.

### Skills for Living UI lifecycle

```
living-ui-creator    start a new project. Walks scaffolding + initial state design.
living-ui-modify     edit an existing project (add features, change layout, fix bugs).
living-ui-manager    list, inspect, archive, restart projects.
```

Prefer invoking these via slash (`/living-ui-creator`) or via LLM selection. They encode the right read-rules-first protocol and the right action sequence.

### Protocol BEFORE creating any Living UI project

```
1. Read GLOBAL_LIVING_UI.md (small file, ~80 lines). It defines:
   - Primary / secondary / accent colors
   - Theme behavior (system / dark / light)
   - Component preferences (preset components, no inline styles,
     react-toastify, async spinners, toast CRUD feedback,
     confirmation dialogs, validation, mobile responsive, etc.)
   - Optional rules (drag-and-drop, keyboard shortcuts, item count
     badges, search/filter, bulk selection, dark-mode-only, animations)
   - User-defined custom rules

2. Apply global rules first; only override on explicit user instruction.

3. After creation, the project should respect EVERY "Always Enforced" rule
   in GLOBAL_LIVING_UI.md (no inline styles, preset components, async
   spinners, etc.).
```

If the user wants project-specific design that conflicts with GLOBAL_LIVING_UI.md, confirm the override before applying.

### Per-project structure (what's guaranteed)

Each project lives at `agent_file_system/workspace/living_ui/<name>_<hash>/`. The internal structure varies per project (different stacks possible). Only three files are guaranteed:

```
LIVING_UI.md          per-project doc: purpose, decisions, project-specific rules
config/manifest.json  project metadata: name, hash, ports, capabilities
logs/                 project runtime / build / console logs (timestamped)
```

For full file-system details and the do-not-rename rule, see `## File System` "Living UI projects" subsection.

### Editing an existing project

```
1. read LIVING_UI.md to understand purpose + project-specific rules.
2. list_folder the project to see what's actually there.
3. Use living-ui-modify skill (don't hand-edit unless the skill
   isn't suitable).
4. After changes, the project should still respect GLOBAL_LIVING_UI.md.
```

When the project misbehaves: grep `logs/` first (frontend console output is piped there via ConsoleCapture). See `## File System` "Living UI projects" subsection for log details.

### Updating GLOBAL_LIVING_UI.md

Edit only when the user gives a NEW universal rule that should apply to ALL Living UI projects (e.g., "never use animations", "always include dark mode toggle"). For project-specific overrides, edit the project's own `LIVING_UI.md` instead.

Edit procedure: same pattern as FORMAT.md — confirm scope, stream_edit, confirm to user.

### Pitfalls

- Hand-writing the project scaffold instead of using `living_ui_actions` / Living UI skills. The generator does it correctly; manual scaffolds drift from the template.
- Using inline styles. Forbidden by GLOBAL_LIVING_UI.md.
- Skipping the GLOBAL_LIVING_UI.md read for "simple" projects. Even simple ones should respect global rules.
- Renaming a project directory by hand. Re-register via `living_ui_actions` instead — the manifest.json is the source of truth for the project's name.
- Putting project-wide design changes in GLOBAL_LIVING_UI.md when they should be in the per-project LIVING_UI.md.

---

## Actions

Actions are the only way you do anything. The runtime presents the currently-available actions to you in your prompt each turn. If you need a capability that is not in the current list, you must either expand the active action sets (see `## Action Sets`) or read the source to learn what to call.

### Where actions live

Built-in actions are Python files under [app/data/action/](app/data/action/). The action name does NOT always match the filename:

```
app/data/action/<file>.py             one or more @action() registrations
app/data/action/CUSTOM_ACTION_GUIDE.md guide for authoring new actions
app/data/action/<platform>/...        platform-specific bundles (one file may register 10+ actions)
```

Examples of files with multiple registrations:
- `action_set_management.py` registers `add_action_sets`, `remove_action_sets`, `list_action_sets`.
- `skill_management.py` registers `list_skills`, `use_skill`.
- `integration_management.py` registers `list_available_integrations`, `connect_integration`, `check_integration_status`, `disconnect_integration`.
- `discord/discord_actions.py`, `slack/slack_actions.py`, `telegram/telegram_actions.py`, `notion/notion_actions.py`, `linkedin/linkedin_actions.py`, `jira/jira_actions.py`, `github/github_actions.py`, `outlook/outlook_actions.py`, `whatsapp/whatsapp_actions.py`, `twitter/twitter_actions.py`, `google_workspace/{gmail,google_calendar,google_drive}_actions.py` each register many actions.

Total registered built-in actions: roughly 195 (varies by version). The exact number is logged at startup in `logs/<timestamp>.log` — search for `Action registry loaded`.

### How to discover actions

You have three discovery paths. Pick by purpose.

**1. By name (when you already know it).** Read the source:
```
read_file app/data/action/<action_name>.py
```

**2. By capability (when you do NOT know the name).** Grep descriptions and names across the folder:
```
grep_files 'name="' app/data/action/ -A 1            # list all action names + first description line
grep_files 'description=' app/data/action/ -A 0      # list all descriptions
grep_files '<keyword>' app/data/action/ -A 2 -B 1    # find actions matching a concept
```

**3. By currently-loaded set (what you can call right now).** Two options:
- The runtime puts the current action list in your prompt every turn. That list is authoritative.
- Call the `list_action_sets` action to see which sets are loaded plus all actions in them. Useful when the prompt list is truncated or you suspect a set is missing.

### `@action(...)` decorator schema

Every action is registered via the `@action` decorator at [agent_core/core/action_framework/registry.py](agent_core/core/action_framework/registry.py). When you read an action's `.py` file, these are the fields you will see:

```
name             str   required. Unique identifier the LLM uses to call the action.
description      str   shown to the LLM. This is how you decide whether to use the action.
mode             str   "CLI" | "ALL". Visibility filter.
default          bool  legacy. If True, action is always available. Prefer action_sets.
execution_mode   str   "internal" (in-process) | "sandboxed" (ephemeral venv subprocess).
platforms        str|list  "linux" | "windows" | "darwin" | "all". Default: ["all"].
input_schema     dict  JSON-schema-like description of parameters. Read this for param names and types.
output_schema    dict  JSON-schema-like description of return shape. Read this to know what to expect.
requirement      list  pip packages auto-installed in sandbox before execution.
test_payload     dict  test input for diagnostic harness. The "simulated_mode" key bypasses real execution.
action_sets      list  set names this action belongs to. Determines when it's loaded.
parallelizable   bool  default True. False = action runs alone in its turn (write ops, state changes).
```

Key implications when reading an action:
- `mode="CLI"` actions exist (e.g. `read_file`, `task_start`). They are loaded by default.
- `parallelizable=False` actions cannot be batched. The router will sequence them. Examples: `task_update_todos`, `add_action_sets`, `remove_action_sets`.
- `execution_mode="sandboxed"` means the action runs in a fresh venv subprocess with `requirement` packages installed automatically. `run_python` is sandboxed; most other actions are internal.
- `default=True` means the action is in the action list regardless of which sets are loaded. Common defaults: `task_start`, `send_message`, `ignore`. Prefer adding to an `action_sets` list over using `default=True`.

### Built-in action categories (orientation only — read source for current state)

```
core                     send_message, task_start, task_end, task_update_todos, ignore, wait,
                         add_action_sets, remove_action_sets, list_action_sets,
                         list_skills, use_skill,
                         list_available_integrations, connect_integration,
                         check_integration_status, disconnect_integration

file_operations          read_file, grep_files, find_files, list_folder, stream_edit, write_file,
                         read_pdf, convert_to_markdown, create_pdf

shell                    run_shell, run_python

web_research             web_fetch, web_search, http_request

memory                   memory_search

proactive / scheduler    schedule_task, scheduled_task_list, schedule_task_toggle,
                         remove_scheduled_task, recurring_add, recurring_read,
                         recurring_update_task, recurring_remove

image                    describe_image, generate_image, perform_ocr

video                    understand_video

clipboard                clipboard_read, clipboard_write

comms                    send_message_with_attachment

living_ui                living_ui_http, living_ui_import_external, living_ui_import_zip,
                         living_ui_notify_ready, living_ui_report_progress, living_ui_restart

per-platform integrations  Discord, Slack, Telegram, Notion, LinkedIn, Jira, GitHub,
                           Outlook, WhatsApp, Twitter, Google Workspace
                           (each has its own bundle file; loaded via integration action sets)
```

This grouping is informal. The authoritative grouping per action is the `action_sets=[...]` list in its decorator. When in doubt, grep the source.

### Calling an action

You do not call actions directly in code. You emit an action decision in your turn output. Format (illustrative):

```
{"action_name": "read_file", "parameters": {"file_path": "agent_file_system/AGENT.md", "limit": 200}}
```

The router validates the name and parameters against the action's `input_schema`, then the executor runs it. The result returns as a dict matching `output_schema`. See `## Errors` for the standard `{"status": "success" | "error", ...}` envelope.

### Authoring a new action

If you discover the harness is missing a capability you need repeatedly:
1. Read [app/data/action/CUSTOM_ACTION_GUIDE.md](app/data/action/CUSTOM_ACTION_GUIDE.md).
2. Pick a similar existing action as a template (e.g. for a file op, copy `read_file.py`).
3. Create the new file under [app/data/action/](app/data/action/) with a single `@action(...)` decorator.
4. Register it in the right `action_sets`.
5. Restart is required for code changes (hot-reload covers configs, NOT new action files). See `## Hot Reload`.

For everything routine (existing capabilities), prefer composing existing actions over authoring new ones.

---

## Action Sets

An action set is a named bundle of actions you load together. Loading a set makes all its actions available in your prompt; the LLM can then call them. Sets exist to keep your prompt small (only the actions you need) without sacrificing capability.

Code: [app/action/action_set.py](app/action/action_set.py) (`ActionSetManager`). Set descriptions: [app/action/action_set.py](app/action/action_set.py) `DEFAULT_SET_DESCRIPTIONS`.

### How sets are discovered

Sets are NOT hardcoded. They are discovered dynamically by scanning every registered action's `action_sets=[...]` declaration. Any name an action declares becomes a valid set. This means:
- Adding a new action to a new set name silently creates that set.
- MCP servers auto-register as `mcp_<server_name>` sets via `action_set_name` in `mcp_config.json`. See `## MCP`.
- A set with no actions is invisible (the discovery scans actions, not a static list).

To list every set currently visible to the runtime, call the `list_action_sets` action.

### Built-in sets (with curated descriptions)

`DEFAULT_SET_DESCRIPTIONS` has explicit descriptions for these eight sets:

```
core                  Essential actions, always available
file_operations       File and folder manipulation
web_research          Internet search and browsing
document_processing   PDF and document handling
image                 Image viewing, analysis, OCR
video                 Video analysis
clipboard             Clipboard read/write
shell                 Command line and Python execution
```

Any set name not in `DEFAULT_SET_DESCRIPTIONS` is presented to the LLM as `Custom action set: <name>`.

### Other sets actually used by built-in actions

Beyond the eight curated sets, these sets exist because actions declare them:

```
proactive             schedule_task, scheduled_task_list, recurring_*, schedule_task_toggle, ...
scheduler             schedule_task, schedule_task_toggle (alongside proactive)
content_creation      generate_image, create_pdf, ...
living_ui             living_ui_http, living_ui_restart, ...

per-integration sets (loaded only when the user has the integration connected):
discord, slack, telegram_bot, telegram_user, whatsapp, twitter,
notion, linkedin, jira, github, outlook, google_workspace
```

This list is illustrative, not authoritative. Run `list_action_sets` for the live list. Read [app/action/action_set.py](app/action/action_set.py) for the source.

### `core` is always loaded

[app/action/action_set.py](app/action/action_set.py) `compile_action_list`:

```
required_sets = set(selected_sets) | {"core"}
```

You cannot opt out of `core`. Whatever else you pass to `task_start`, `core` is added. `core` includes (at minimum):

```
send_message, task_start, task_end, task_update_todos, ignore, wait,
add_action_sets, remove_action_sets, list_action_sets,
list_skills, use_skill,
list_available_integrations, connect_integration,
check_integration_status, disconnect_integration,
clipboard_read, clipboard_write
```

(Note: `clipboard_read` and `clipboard_write` are in `core`, not in a separate `clipboard` set, despite the curated description suggesting otherwise.)

### How sets are loaded

Three mechanisms, in order of preference:

1. **At `task_start`** — pass the names in the `action_sets` parameter. The LLM-driven creator (`do_create_task`) auto-selects sets based on the task description; you can also pre-select via skill slash commands like `/pdf`. `core` is added automatically.
2. **Mid-task** — call `add_action_sets(action_sets=[...])` or `remove_action_sets(action_sets=[...])`. The action list is recompiled and the new actions appear in the next turn's prompt.
3. **Via skill selection** — if a skill's `SKILL.md` frontmatter has `action-sets: [...]`, those sets are auto-loaded when the skill is selected. See `## Skills`.

After loading, the new actions ARE in your prompt the next turn. You do not need to re-fetch or refresh anything.

### Picking the right sets

Match the task's actual needs. Loading every set bloats the prompt and slows action selection.

```
Lightweight task                  core + file_operations
Web research / lookup             core + web_research
Document generation               core + file_operations + document_processing
Multimedia work                   core + image (and/or video)
Shell / scripting                 core + shell + file_operations
Living UI work                    core + living_ui + file_operations + shell
Proactive task setup              core + proactive
Per-platform integration          core + <integration_name>  (e.g. core + slack)
```

Defaults that almost always make sense: `core + file_operations`. Add others as the task requires.

### Tracking what is loaded

Two ways to know what set is currently active for a task:
1. The current prompt's action list (always authoritative).
2. The `list_action_sets` action returns `{ available_sets, current_sets, current_actions }`.

If you suspect a set was supposed to be loaded but isn't (an action you expect to see is missing), call `list_action_sets` to confirm before assuming you have to manually add it with `add_action_sets`.

### Set lifecycle relative to a task

- Sets are LOCKED when the task is created. The task's `compiled_actions` list is built once.
- `add_action_sets` / `remove_action_sets` are the only mid-task mutations. They re-run `compile_action_list` and update the task's available actions.
- When the task ends, the set selection is gone. The next task starts fresh.
- Skills do NOT swap mid-task. To use a different skill, end the task and start a new one.

See `## Tasks` for task-level lifecycle and `## Runtime` for how the action list reaches your prompt each turn.

---

## Slash Commands

Slash commands are USER-invoked at the chat input. The agent does NOT call slash commands; the agent uses actions (see `## Actions`). Slash commands are documented here so you understand what the user just typed when they invoke one, and so you can answer questions about them.

Sources of truth (in order of authority):
1. Built-in command files: [app/ui_layer/commands/builtin/](app/ui_layer/commands/builtin/). One file per top-level command.
2. Integration commands: dynamically registered from `INTEGRATION_HANDLERS` in [app/credentials/handlers.py](app/credentials/handlers.py). One slash command per registered handler.
3. Skill commands: every skill with `user-invocable: true` (default) in its `SKILL.md` frontmatter is auto-registered as `/<skill_name>`.

Run `/help` for the live list. If you need to verify a specific command, read its file.

### General commands

```
/help [command]      list all commands, or detail one. Always available.
/menu                show the main menu
/clear               clear the conversation
/clear_tasks         clear finished tasks (completed, failed, aborted) from the action panel
/reset               reset the agent to its initial state
/exit                quit the application
/update              check for updates and update CraftBot
/provider <name>     switch LLM provider (openai, anthropic, google, byteplus, remote)
```

### Credential and integration overview

```
/cred list           list all stored credentials across integrations
/cred status         show connection status for every integration
/cred integrations   list available integration types
```

`/cred` does not connect or disconnect; use `/<integration>` for that.

### MCP server management

```
/mcp list                          list configured MCP servers + enabled state
/mcp add <name> <command> [args]   register a new MCP server (stdio)
/mcp add-json <json>               register from a full JSON entry
/mcp remove <name>                 remove a server
/mcp enable <name>                 enable a server (next reload picks it up)
/mcp disable <name>                disable a server
/mcp env <name> <KEY> <value>      set an env variable on a server entry
```

Edits go to [app/config/mcp_config.json](app/config/mcp_config.json) and are hot-reloaded. See `## MCP` and `## Configs`.

### Skill management

```
/skill list                                    list installed skills + enabled state
/skill info <name>                             show metadata + body of a skill
/skill enable <name>                           move a skill into enabled_skills
/skill disable <name>                          move a skill into disabled_skills
/skill install <source>                        install from a git URL or path
/skill create [name] [description]             scaffold a new skill (uses craftbot-skill-creator)
/skill remove <name>                           delete a skill from skills/ directory
/skill reload                                  rediscover skills (manual hot-reload)
```

Edits go to [app/config/skills_config.json](app/config/skills_config.json) and the [skills/](skills/) directory. See `## Skills`.

### Skill direct invocation

Every skill with `user-invocable: true` in its frontmatter (default) is registered as a slash command:

```
/<skill_name> [args]    invoke the skill directly
```

When the user types this, the runtime starts a task with the skill pre-selected (bypassing LLM skill selection in `do_create_task`). Examples that exist in the current build: `/pdf`, `/docx`, `/pptx`, `/xlsx`, `/weather-check`, `/get-weather`, etc. The list depends on which skills are enabled in [app/config/skills_config.json](app/config/skills_config.json).

### Integration commands (auth + lifecycle)

For each registered integration in `INTEGRATION_HANDLERS`, a slash command `/{integration}` is auto-registered:

```
/<integration> status                    show connection state, accounts
/<integration> connect [...credentials]  connect (token-based) — fields depend on integration
/<integration> disconnect [account_id]   remove a connection
/<integration> login-qr                  for whatsapp_web (QR scan flow)
/<integration> invite                    for OAuth-capable integrations (browser flow)
```

Currently registered (per [app/credentials/handlers.py](app/credentials/handlers.py) `INTEGRATION_HANDLERS`):

```
google              OAuth flow.   /google invite | status | disconnect
slack               OAuth + token. /slack invite | connect <bot_token> [workspace_name] | status | disconnect
notion              OAuth + token. /notion invite | connect <token> | status | disconnect
linkedin            OAuth flow.   /linkedin invite | status | disconnect
discord             Token flow.   /discord connect <bot_token> | status | disconnect
telegram            Bot + user.   /telegram connect <bot_token> | status | disconnect
                                  (user-account flow has additional sub-commands; see /help telegram)
whatsapp            Web (QR).     /whatsapp login-qr [phone] | status | disconnect
whatsapp_business   API tokens.   /whatsapp_business connect <phone_number_id> <access_token> | status | disconnect
outlook             OAuth flow.   /outlook invite | status | disconnect
jira                Token flow.   /jira connect ... | status | disconnect
github              Token flow.   /github connect <token> | status | disconnect
twitter             Token flow.   /twitter connect ... | status | disconnect
```

The exact `connect` fields per integration are defined in `INTEGRATION_REGISTRY` at [app/external_comms/integration_settings.py](app/external_comms/integration_settings.py). Use `/help <integration>` to see what credentials it expects.

### Agent-provided commands

Skills can register commands at runtime via the agent command wrapper ([app/ui_layer/commands/builtin/agent_command.py](app/ui_layer/commands/builtin/agent_command.py)). These appear in `/help` alongside built-in commands. To audit what's currently registered, ask the user to run `/help` and paste the output, or read the live command registry from the running process.

### When the user types a slash command

If a user types a slash command and you receive the resulting task or message:
- The runtime processes the command BEFORE you see it. Your role is to react to its outcome, not to re-execute.
- For `/<skill_name>`, the runtime creates a task with the skill pre-selected. You take over from there.
- For `/<integration> connect` or `/cred status`, the result lands in the chat as text. The user may then ask you to do something with the now-connected integration.
- For `/clear`, `/clear_tasks`, `/reset`, `/exit`: state changes happen immediately. You may not have continuity with prior conversation/tasks after these.

---

## Configs

The agent's behavior is shaped by JSON config files under [app/config/](app/config/). When you need to change settings about yourself (model, API keys, MCP servers, skills, schedules, integrations), you edit one of these files. The harness watches them and reloads automatically.

This section is the source of truth for: every config file's full schema, what each key controls, the hot-reload mechanism, what does and does NOT take effect without restart, and the edit-and-verify workflow.

### The six config files

```
app/config/settings.json              model, API keys, OAuth, cache, browser, memory          hot-reload
app/config/mcp_config.json            MCP server registry                                     hot-reload
app/config/skills_config.json         enabled / disabled skills                               hot-reload
app/config/external_comms_config.json telegram + whatsapp listener configs                    hot-reload
app/config/scheduler_config.json      cron schedules                                          hot-reload
app/config/onboarding_config.json     first-run state                                         NOT watched
```

You may also encounter MCP server entries that point at standalone JSON files; those are imported at MCP load time and follow `mcp_config.json`'s lifecycle.

### Editing protocol (memorize this)

```
1.  read_file <config_path>                       see current state
2.  decide what to change
3.  stream_edit <config_path> ...                 make the edit (preserves unrelated content)
4.  wait ~0.5s for debounce                        the watcher coalesces rapid saves
5.  verify the reload happened                    see "Verifying a reload" below
6.  if no effect: check logs/<latest>.log for     [SETTINGS] / [MCP] / [CONFIG_WATCHER] errors
    [CONFIG_WATCHER] / [MCP] / [SETTINGS] errors
```

Use `stream_edit`, never `write_file`, on configs. A whole-file rewrite risks losing unrelated keys the runtime relies on (e.g. `api_keys_configured` bookkeeping, your own `oauth` clients).

If the file is malformed JSON after your edit, the reload fails and the previous in-memory config keeps running. Read the file back and fix the syntax. `[SETTINGS] JSONDecodeError` will appear in the log.

### Hot-reload mechanism

Source: [agent_core/core/impl/config/watcher.py](agent_core/core/impl/config/watcher.py) (`ConfigWatcher` singleton).

```
backend                  watchdog library if installed; polling (1s) fallback otherwise
watch granularity        the watcher subscribes to each config file's PARENT DIRECTORY,
                         then filters events by registered file path
debounce                 0.5 seconds. Rapid saves within 500ms are coalesced into one reload.
trigger                  on file modification:
                           1. cancel any pending debounce timer for that path
                           2. start a fresh 0.5s timer
                           3. on timer fire, call the registered reload callback
callback execution       sync callbacks run in the watcher thread. Async callbacks are
                         scheduled on the main event loop via run_coroutine_threadsafe.
log signature            "[CONFIG_WATCHER] Registered watch for <name>"  (at startup)
                         "[CONFIG_WATCHER] Started watching config files"
                         per-reload: "[SETTINGS] Reloaded ..." / "[MCP] Reloaded ..." etc.
```

### Per-config reload behavior

Every watched config has a specific reload callback registered at startup ([app/agent_base.py](app/agent_base.py) `_initialize_config_watcher`):

```
settings.json
  callback        settings_manager.reload + invalidate_settings_cache
  effect          provider/model/API keys updated for the NEXT LLM call.
                  An in-flight call uses the OLD config; the next turn uses the new one.
  log signature   [SETTINGS] Reloaded ...

mcp_config.json
  callback        mcp_client.reload  (async)
  effect          servers with enabled=true that are not connected get connected.
                  servers that became enabled=false get disconnected.
                  newly-added servers register their action set as mcp_<name>.
                  tools appear in the next turn's action list (after action set is loaded).
  log signature   [MCP] Loaded config with N server(s) ... [MCP] Connecting to '<name>' ...

skills_config.json
  callback        skill_manager.reload + ui_controller.sync_skill_commands
  effect          skill discovery re-runs on skills/. Newly-enabled skills become
                  selectable; disabled skills disappear. Slash commands for
                  user-invocable skills are re-registered (/{skill_name} appears or vanishes).
                  Effect on a running task: the active task keeps its locked skill list.
                  New skills are only available to the NEXT task.
  log signature   [SKILL] Reloaded skills_config ...

external_comms_config.json
  callback        registered after external_comms initialization
  effect          telegram and whatsapp listeners start, stop, or reconfigure based on
                  enabled / mode changes. Other platforms (discord, slack, etc.) are not
                  in this file - they are managed by .credentials/ + /<integration> commands.
  log signature   [EXT_COMMS] Reloaded ...

scheduler_config.json
  callback        scheduler.reload  (async)
  effect          schedules re-parsed. New entries fire on their first matching window.
                  Removed entries do not fire next cycle.
                  Currently-firing tasks are not interrupted.
  log signature   [SCHEDULER] Reloaded ...

onboarding_config.json
  callback        NONE (not watched).
  effect          you do not edit this file. It is managed by the onboarding flow.
                  If you change it manually, restart is required.
```

### What does NOT take effect on a config save

- An action set already selected for an active task (locked at `task_start`).
- An LLM call already in flight (uses the old config; next turn uses the new one).
- A skill body / metadata change on a running task (skills are locked at task creation).
- New built-in actions added by creating a new `.py` file under `app/data/action/` (code change, requires restart).
- Changes to OS environment variables not stored in any config file (requires restart).
- Code changes anywhere in `app/`, `agent_core/`, `agents/` (requires restart).

If any of these apply, end the current task, restart only what's needed (often nothing - just start a new task), and the new config will be in force.

### Verifying a reload

By config:

```
settings.json
  - check logs:  grep_files "[SETTINGS]" logs/<latest>.log -A 1
  - or read back: read_file app/config/settings.json (confirm your edit landed)
  - in next task: model/provider/api_key changes are observable when an LLM call fires

mcp_config.json
  - check logs:  grep_files "[MCP]" logs/<latest>.log -A 2
  - look for:    "Connecting to '<server-name>'", "[StdioTransport] Starting subprocess"
  - in next task: list_action_sets shows mcp_<server-name> as a registered set

skills_config.json
  - run /skill list (user-side) or
  - call list_skills action  → confirms enabled/disabled state
  - new /<skill_name> slash commands appear after sync_skill_commands fires

external_comms_config.json
  - check logs:  grep_files "[EXT_COMMS]" logs/<latest>.log -A 2
  - if telegram/whatsapp enabled and started, expect connection success messages

scheduler_config.json
  - check logs:  grep_files "[SCHEDULER]" logs/<latest>.log -A 2
  - call scheduled_task_list action  → confirms entries
```

If the log shows the reload fired but the change still isn't reflected: the change probably falls in "What does NOT take effect on a config save" above. End the current task or restart as appropriate.

### Schemas

The blocks below are dictionary-style: keys, valid values, and defaults. Read the actual JSON file (`read_file app/config/<name>.json`) when you need current values.

<!-- schema:settings.json -->
```
File: app/config/settings.json

version: string                  (CraftBot version this config was written for; do not edit)

general:
  agent_name: string             (the user-facing name of this agent, e.g. "CraftBot")
  os_language: string            (BCP-47 / ISO code, e.g. "en")

proactive:
  enabled: bool                  (master switch for proactive workflow; if false,
                                  proactive_heartbeat and planners are skipped)

memory:
  enabled: bool                  (master switch for memory_search and memory pipeline)
  max_items: int                 (default 200; cap on MEMORY.md before pruning)
  prune_target: int              (default 135; how many items remain after a prune)
  item_word_limit: int           (default 150; words per stored memory item)

model:
  llm_provider: "openai" | "anthropic" | "google" | "byteplus" | "remote"
  vlm_provider: same options
  llm_model: string | null       (null = provider default; e.g. "claude-sonnet-4-5-20250929")
  vlm_model: string | null
  slow_mode: bool                (true throttles requests for rate-limited providers)
  slow_mode_tpm_limit: int       (tokens per minute when slow_mode is true)

api_keys:
  openai: string                 (sk-...)
  anthropic: string              (sk-ant-...)
  google: string                 (Gemini API key)
  byteplus: string

endpoints:
  remote_model_url: string       (for "remote" provider, e.g. Ollama base URL)
  byteplus_base_url: string      (default https://ark.ap-southeast.bytepluses.com/api/v3)
  google_api_base: string        (override for Gemini API base URL)
  google_api_version: string     (override for Gemini API version)
  remote: string                 (default http://localhost:11434; Ollama endpoint)

oauth:
  google:    { client_id, client_secret }     (used by /google invite OAuth flow)
  linkedin:  { client_id, client_secret }     (used by /linkedin invite)
  slack:     { client_id, client_secret }     (used by /slack invite)
  notion:    { client_id, client_secret }     (used by /notion invite)
  outlook:   { client_id }                    (used by /outlook invite)

web_search:
  google_cse_id: string          (Google Custom Search Engine ID for web_search action)

cache:
  prefix_ttl: int                (seconds; cache TTL for the system-prompt prefix)
  session_ttl: int               (seconds; cache TTL for per-session state)
  min_tokens: int                (skip caching prompts below this token count)

browser:
  port: int                      (default 7926; CraftBot browser frontend port)
  startup_ui: bool               (auto-open browser at startup)

api_keys_configured:             (BOOKKEEPING - reflects which keys are non-empty)
  openai: bool
  anthropic: bool
  google: bool
  byteplus: bool
```
<!-- /schema:settings.json -->

<!-- schema:mcp_config.json -->
```
File: app/config/mcp_config.json

mcp_servers: [
  {
    name: string                                   required, unique within file
    description: string                            human-readable, shown to the LLM
    transport: "stdio" | "sse" | "websocket"       default "stdio"
    command: string                                required for stdio (e.g. "npx", "uv", "python")
    args: [string]                                 stdio command arguments
    url: string                                    required for sse / websocket
    env: { KEY: VALUE }                            environment variables passed to the server process
    enabled: bool                                  controls whether the server connects on load/reload
    action_set_name: string                        default "mcp_<name>"; the action set tools register under
  }
]

Patterns by transport:
  NPX (Node):     transport="stdio"  command="npx"     args=["-y", "@org/server-name", ...optional-args]
  Python (uv):    transport="stdio"  command="uv"      args=["run", "--directory", "<path>", "main.py"]
  Python (pip):   transport="stdio"  command="python"  args=["-m", "<module>", ...args]
  Remote SSE:     transport="sse"    url="http://localhost:3000/mcp"
  Remote WS:      transport="websocket" url="ws://..."

When a server is enabled and connects, all its tools become callable as actions
under its action_set_name. To use them in a task, load that set via add_action_sets
or via task_start's auto-selection.
```
<!-- /schema:mcp_config.json -->

<!-- schema:skills_config.json -->
```
File: app/config/skills_config.json

auto_load: bool                  default true; if false, no skills are loaded at startup
enabled_skills: [skill_name]     skills available for selection / slash invocation
disabled_skills: [skill_name]    explicitly turned off; loader sets enabled=false
project_skills_dir: string       default "skills"; where SKILL.md directories are discovered

Skills are discovered by scanning <project_skills_dir>/<name>/SKILL.md.
A skill in disabled_skills is loaded but flagged disabled (the LLM does not see it).
A skill not listed in either is loaded and enabled by default if auto_load is true.

To enable a skill: move its name from disabled_skills to enabled_skills.
To remove a skill entirely: also delete the directory under skills/.
SKILL.md frontmatter fields: see ## Skills.
```
<!-- /schema:skills_config.json -->

<!-- schema:external_comms_config.json -->
```
File: app/config/external_comms_config.json

telegram:
  enabled: bool                  master switch for the telegram listener
  mode: "bot" | "mtproto"        bot = Bot API; mtproto = user-account API
  bot_token: string              required for mode=bot (from @BotFather)
  bot_username: string           the bot's @username (without the @)
  api_id: string                 required for mode=mtproto (from my.telegram.org)
  api_hash: string               required for mode=mtproto
  phone_number: string           required for mode=mtproto (E.164 format)
  auto_reply: bool               if true, incoming messages route to the agent

whatsapp:
  enabled: bool                  master switch for whatsapp listener
  mode: "web" | "business"       web = WhatsApp Web (Playwright); business = Cloud API
  session_id: string             web mode: cached browser session
  phone_number_id: string        business mode (from Meta business)
  access_token: string           business mode
  auto_reply: bool

NOTE: Other platforms (discord, slack, gmail, notion, linkedin, outlook,
google, jira, github, twitter) do NOT live in this file.
- Their credentials live under .credentials/<platform>.json.
- OAuth client_id/secret for some live in settings.json's "oauth" section.
- Connect/disconnect via /<platform> commands.
See ## Integrations and ## Slash Commands.
```
<!-- /schema:external_comms_config.json -->

<!-- schema:scheduler_config.json -->
```
File: app/config/scheduler_config.json

enabled: bool                                master switch for the scheduler
schedules: [
  {
    id: string                               unique identifier
    name: string                             human-readable
    instruction: string                      what the agent should do when fired
    schedule: string                         natural language OR cron (see formats below)
    enabled: bool                            individual schedule on/off
    priority: int                            1-100, lower = higher priority
    mode: "simple" | "complex"               task mode for the spawned task
    recurring: bool                          true = stays after firing; false = one-shot
    action_sets: [string]                    sets to load before the task fires
    skills: [string]                         skills to inject before the task fires
    payload: { type: string, ... }           passed to react()'s trigger.payload
                                             type drives workflow routing (see ## Runtime):
                                              "memory_processing", "proactive_heartbeat",
                                              "proactive_planner", "scheduled", ...
  }
]

Schedule formats (parser at app/scheduler/parser.py):
  Natural:  "every day at 3am"
            "every sunday at 5pm"
            "every 30 minutes"
            "every 3 hours"
            "tomorrow at 9am"
            "in 2 hours"
            "in 30 minutes"
            "at 3pm"
            "immediate"
  Cron:     "0,30 * * * *"
            "0 7 * * *"
            "0 8 1 * *"

Built-in schedules (do NOT remove):
  memory-processing  every day at 3am   payload.type="memory_processing"
  heartbeat          0,30 * * *         payload.type="proactive_heartbeat"
                                         skill: heartbeat-processor
  day-planner        every day at 7am   payload.type="proactive_planner" scope=day
  week-planner       every sunday at 5pm payload.type="proactive_planner" scope=week
  month-planner      0 8 1 * *          payload.type="proactive_planner" scope=month
```
<!-- /schema:scheduler_config.json -->

<!-- schema:onboarding_config.json -->
```
File: app/config/onboarding_config.json

hard_completed: bool                  wizard finished (collected user_name, language, tone, etc.)
soft_completed: bool                  conversational interview task finished
hard_completed_at: ISO timestamp | null
soft_completed_at: ISO timestamp | null
user_name: string
agent_name: string
agent_profile_picture: string | null

This file is NOT hot-reloaded. It is managed by the onboarding flow.
Do NOT edit this file as part of normal operation.
```
<!-- /schema:onboarding_config.json -->

### Common edits and recipes

Switch LLM provider:
```
read_file app/config/settings.json
stream_edit app/config/settings.json
   model.llm_provider: "openai" → "anthropic"
   model.llm_model: "<old>"     → "claude-sonnet-4-5-20250929"
api_keys.anthropic must be set or the next LLM call fails (see ## Models).
```

Set an API key (when user provides one):
```
stream_edit app/config/settings.json
   api_keys.<provider>: ""        → "<key>"
   api_keys_configured.<provider>: false → true
```

Enable an MCP server already in the file:
```
stream_edit app/config/mcp_config.json
   mcp_servers[i].enabled: false → true
   if env requires a token, fill it
```

Add a new MCP server: see `## MCP` for the full recipe.

Enable / disable a skill:
```
stream_edit app/config/skills_config.json
   move <name> between enabled_skills and disabled_skills
```

Add a recurring schedule: prefer the `schedule_task` or `recurring_add` actions
over editing scheduler_config.json directly. They validate the schedule expression.
See `## Proactive`.

### Pitfalls

- JSON syntax errors silently keep the OLD config in memory. The reload fires, the
  parser fails, the manager logs the error, and the previous state remains active.
  Always verify after editing.
- Editing `version` in settings.json does nothing useful and may confuse the next install.
- `api_keys_configured` is bookkeeping. If you set a key, also flip the boolean.
- `core` action set is hardcoded as always-included (see `## Action Sets`). You cannot
  disable it via config.
- The watcher subscribes to parent DIRECTORIES, so creating a new file in app/config/
  is detected, but the file must be explicitly registered for any reload to fire.
- Sandboxed actions (run_python with requirements) install their packages on first
  call, NOT on config save. The config has no effect on action sandboxes.

---

## MCP

MCP (Model Context Protocol) servers extend your tool inventory at runtime. Use MCP when you need a capability that no built-in action covers and no skill can compose. Each connected MCP server registers its tools as actions under a dedicated action set, callable through the same action interface as everything else.

Code: [agent_core/core/impl/mcp/client.py](agent_core/core/impl/mcp/client.py) (`MCPClient`, singleton). Config: [app/config/mcp_config.json](app/config/mcp_config.json). Schema in `## Configs`.

### How MCP fits in

```
mcp_config.json (your edit)
        │
        ▼
MCPClient.initialize() at startup     OR    MCPClient.reload() on hot-reload
        │
        ▼
for each enabled server:
   spawn subprocess (stdio) OR open connection (sse/websocket)
   discover its tools
   register tools as actions in action set "mcp_<server_name>"
        │
        ▼
to use: load the action set in a task (auto-selected, or via add_action_sets)
        │
        ▼
LLM calls the tool just like any other action
```

The action set name is `mcp_<name>` by default, or whatever `action_set_name` is set to in the entry. After a successful connect, expect log lines like:

```
[MCP] Connecting to '<name>' (stdio): <command> <args>
[MCP] Successfully connected to '<name>' with N tools
[MCP] Registered N tools from server '<name>' into action set 'mcp_<name>'
```

### Pre-defined servers in this codebase

The shipped `mcp_config.json` contains roughly 157 server entries (most `enabled: false`). Examples of always-shipped, commonly-enabled ones:

```
filesystem            @modelcontextprotocol/server-filesystem      file ops on cwd
playwright-mcp        @playwright/mcp                              browser automation
amadeus-hotels-mcp    travel API                                    hotels search
github-mcp            @modelcontextprotocol/server-github           GitHub API
```

Categories present in the shipped config: filesystem, browser automation, calendar/email/notes, finance/markets/crypto, productivity, OS integrations, fitness, search, media, AI/image, e-commerce, dev tools, security, design, analytics, real estate. To enumerate: `grep_files '"name":' app/config/mcp_config.json` returns the full list.

Before adding a NEW server, check the existing entries. The capability you need may already be there as `enabled: false` — flipping the flag is safer than adding a duplicate.

### Add or enable a server (recipe)

```
1. read_file app/config/mcp_config.json
2. Decide:
     - The server already exists with enabled: false  → flip to true (skip to step 5)
     - You need a new server                         → continue
3. web_search "<capability> MCP server"
   Common naming patterns:
     @modelcontextprotocol/server-<name>      official servers
     @<org>/<name>-mcp                        community servers
     GitHub repos following the MCP spec
4. stream_edit app/config/mcp_config.json
   Append to mcp_servers array. Use the schema from ## Configs.
   Set enabled: true. Set env keys (API tokens, etc.) if required.
5. Wait ~0.5s for the watcher to debounce.
6. Verify: see "Verifying a server is live" below.
7. If verification fails, see "Failure modes and log signatures".
```

If the server's `env` requires a credential (API key, OAuth token, bot token), ASK THE USER for it. Do not invent values. Empty env strings are common defaults; the server will report missing-credential errors at first tool call.

### Transport patterns

```
stdio (subprocess, most common)
  transport: "stdio"
  command:   "npx" | "uv" | "python" | "node" | <executable>
  args:      [...]
  env:       { KEY: VALUE }
  url:       (omit)

  Examples:
    NPX:        command="npx",    args=["-y", "@modelcontextprotocol/server-filesystem", "."]
    Python uv:  command="uv",     args=["run", "--directory", "C:/path/to/server", "main.py"]
    Python pip: command="python", args=["-m", "<module_name>"]
    Node:       command="node",   args=["<path-to-script.js>"]

sse (server-sent events, remote)
  transport: "sse"
  url:       "http://localhost:3000/mcp"  or  "https://<host>/mcp"
  command:   (omit)
  env:       (often unused; the server handles its own auth)

websocket (remote)
  transport: "websocket"
  url:       "ws://..."  or  "wss://..."
```

If the server author provides a `claude_desktop_config.json` snippet (common pattern), copy the `command`, `args`, and `env` directly. The schema is identical.

### Verifying a server is live

After enabling/adding, in order of cheapness:

```
1. grep the latest log for the server's name:
     grep_files "[MCP].*<server_name>" logs/<latest>.log -A 1
   Expect: "Successfully connected" + "Registered N tools".

2. confirm the action set is registered:
     call list_action_sets   → look for "mcp_<server_name>" in the result.

3. load the set into your task:
     call add_action_sets({"action_sets": ["mcp_<server_name>"]})
     The new tools appear in the next turn's action list.

4. call a tool from the set.
   If it returns status=success, you're done. If status=error, the message
   will usually point at credentials or remote-service issues.
```

If steps 1-2 fail, the server did not connect. Go to "Failure modes" below.
If steps 3-4 fail, the server connected but tool execution is broken. Usually credentials.

### Failure modes and log signatures

```
Symptom in log                                       Likely cause              Fix
───────────────────────────────────────────────────  ────────────────────────  ──────────────────────────
[MCP] Failed to load MCP config from <path>: ...     malformed JSON in         re-read mcp_config.json,
                                                     mcp_config.json           fix syntax via stream_edit

[MCP] Failed to connect to '<name>' - check          missing dep / wrong path  reproduce in run_shell:
server configuration                                                            run the exact command +
                                                                                args. Inspect stderr.

[StdioTransport] Starting subprocess: <cmd>          subprocess started but    check the next few log
followed by no "Successfully connected"              died early                lines for stderr from
                                                                                the subprocess.

[MCP] Exception connecting to '<name>': <type>: ...  any other connect-time    type tells you the class:
                                                     error                     FileNotFoundError = command
                                                                                missing; ConnectionError =
                                                                                remote unreachable.

server connected, tool calls return                  missing or wrong env      ask user for the key, set
"unauthorized" / "missing API key" / "401"           variable                   it via /mcp env <name>
                                                                                <KEY> <value>, or
                                                                                stream_edit the env block.

server connected, tool calls hang                    wrong transport (e.g.     fix transport in config.
                                                     sse server marked stdio)

server connected, tool calls succeed but always      remote rate limited       slow down or upgrade the
return errors after first burst                                                remote-service plan.
```

Reproducing a stdio server outside the harness:

```
run_shell "<command> <args...>"   ← run literally what's in the config
```

If the subprocess fails standalone, the harness will fail too. Fix it standalone first.

### Hot-reload behavior on save

`MCPClient.reload(config_path)` does the following on each `mcp_config.json` save:

```
1. re-parse mcp_config.json
2. for each currently-connected server:
     if not in new config OR enabled=false in new config  →  disconnect
3. for each enabled server in new config:
     if not currently connected                            →  connect, register tools
4. re-register all tools as actions
5. return { success, disconnected[], connected[], failed[], total_tools }
```

Implications:
- Toggling `enabled` cleanly connects or disconnects a single server.
- Editing `env` for a connected server does NOT take effect until the server reconnects. Disable then re-enable, or call `mcp_client.reload()` after the file change.
- Tasks already running keep their LOCKED action sets. New MCP tools become callable in the NEXT task or after `add_action_sets`.

### Slash commands (user-side)

```
/mcp list                                  servers + connection state
/mcp add <name> <command> [args...]        register a stdio server
/mcp add-json <json>                       register from a full JSON entry
/mcp remove <name>                         remove from config
/mcp enable <name>                         flip enabled to true
/mcp disable <name>                        flip enabled to false
/mcp env <name> <KEY> <value>              set/update an env var
```

The agent does NOT call slash commands. If the user has not exposed an MCP server you need, edit the config directly via `stream_edit`.

### When to choose MCP vs alternatives

```
Need a capability and...

an existing built-in action covers it           →  use the action  (## Actions)
a skill could compose existing actions          →  write/use a skill (## Skills)
a third party already ships an MCP server       →  add MCP server (here)
the user has a connected integration            →  use integration actions (## Integrations)
nothing exists, you have to write code          →  author a new action (## Actions)
```

MCP is for capabilities you cannot get any other way without writing Python. The cost is process management, network, and an extra credential to maintain.

### Permission and disclosure

- Adding/enabling an MCP server modifies your runtime tool surface. Tell the user before doing it.
- If `env` requires credentials, ASK first. Do not write empty placeholders to "test" — that just creates noise in logs and confuses the user.
- After successful enable, summarize what tools the new server adds (count + a few names).

---

## Skills

A skill is a markdown file with structured instructions that get injected into your prompt when selected. Skills exist for reusable workflows and codified domain knowledge that compose existing actions. Use a skill instead of an MCP server when no new tools are needed, just better instructions.

Code: [agent_core/core/impl/skill/loader.py](agent_core/core/impl/skill/loader.py) (`SkillLoader`), [agent_core/core/impl/skill/config.py](agent_core/core/impl/skill/config.py) (`SkillMetadata`, `Skill`, `SkillsConfig`), [agent_core/core/impl/skill/manager.py](agent_core/core/impl/skill/manager.py) (`SkillManager` singleton).

### What a skill is

```
A directory:                  skills/<name>/
                              ├── SKILL.md         required
                              └── <support files>  optional, referenced by SKILL.md

A SKILL.md file:              YAML frontmatter (metadata)
                              + markdown body (instructions injected into your prompt)

When selected during a task:  body appended to your context until task_end.
                              action-sets it declares are auto-loaded.
                              /<name> slash command is registered (if user-invocable).
```

A skill is NOT a process, NOT a tool, NOT an action. It is text instructions plus a small bundle of action-set selections. The tools it uses are existing actions (built-in, MCP, integrations).

### SKILL.md format

```
---
name: <unique_id>                      required. Snake-case or kebab-case.
description: <one paragraph>           required. The LLM reads this to decide
                                        when to select. Be specific about WHEN
                                        and WHAT triggers selection. Vague
                                        descriptions never get selected.
argument-hint: <hint>                  optional. Shown in /help when user types
                                        /<name>. Example: "<city>" or "<file_path>".
user-invocable: true                   optional, default true.
                                        true = registers /<name> slash command.
                                        false = only LLM-selectable mid-task.
allowed-tools: [<action_name>, ...]    optional. If non-empty, ONLY these actions
                                        are callable while the skill is active.
                                        Empty / omitted = no restriction.
action-sets: [<set_name>, ...]         optional. Auto-loaded when the skill is
                                        selected. Use this to declare what tools
                                        the skill needs (e.g. file_operations,
                                        web_research, mcp_<server_name>).
---

# <Skill title>

<Markdown body. Headings, lists, code blocks, examples - anything you'd put
in a procedure document. This text is appended to your prompt for the
duration of the task.>
```

Frontmatter parsing (regex `^---\s*\n(.*?)\n---\s*\n(.*)$`):
- The file MUST start with `---` on the first line.
- The frontmatter MUST be valid YAML.
- Keys may use `kebab-case` OR `snake_case`. Both `argument-hint` and `argument_hint` work; same for the others.
- If `name` is missing, the directory name is used.
- If `description` is missing, the first non-heading paragraph of the body is used (truncated to 200 chars).

### Variable substitution in the body

When a skill is invoked with arguments (e.g. `/get-weather Tokyo`), the body's variables are substituted before injection ([SkillLoader.substitute_variables](agent_core/core/impl/skill/loader.py)):

```
$ARGUMENTS         the full argument string ("Tokyo")
$ARGUMENTS[0]      first positional arg, 0-indexed
$ARGUMENTS[1]      second positional arg
$0, $1, $2 ...     shorthand for $ARGUMENTS[N]
```

If the skill is selected by the LLM mid-task (not via slash invocation), arguments are typically empty and these placeholders resolve to empty strings. Write skills to handle both invocation paths.

### Discovery and enable flow

```
1. SkillLoader.discover_skills(search_dirs=[skills/], config=SkillsConfig)
   scans <project_skills_dir>/<name>/SKILL.md files
   parses frontmatter + body via FRONTMATTER_PATTERN
2. for each parsed skill:
     if name in disabled_skills (skills_config.json)  -> enabled=false
     else                                             -> enabled=true
3. enabled skills are presented to the LLM each task turn for selection
4. user-invocable + enabled skills are registered as /<name> slash commands
```

Discovery runs at startup AND on every save of [app/config/skills_config.json](app/config/skills_config.json). The directory itself is NOT watched, so adding a brand-new skill directory requires either editing `skills_config.json` (any save triggers rediscovery) or running `/skill reload`.

### How a skill gets selected for a task

Two paths:

**Path 1: User invocation via slash command.** When the user types `/<skill_name> [args]`:
```
1. The runtime calls do_create_task(...) with pre_selected_skills=[<skill_name>]
2. LLM skill selection is BYPASSED (user already chose).
3. LLM action-set selection still runs, then merges with skill's action-sets.
4. Body is injected with $ARGUMENTS substituted.
5. Task starts. Skill stays active for the entire task.
```

**Path 2: LLM selection.** When the user makes a request without slashing in:
```
1. do_create_task runs LLM skill+action-set selection (single LLM call).
2. LLM picks zero, one, or more relevant skills based on their `description`.
3. For each picked skill: body injected, action-sets merged, task starts.
4. Skills picked stay active until task_end.
```

Skills CANNOT be swapped mid-task. To change skills, end the task and start a new one. Action sets CAN be swapped mid-task (see `## Action Sets`).

### `allowed-tools` restriction

When `allowed-tools` is non-empty in the frontmatter, the action filter narrows to ONLY those names while the skill is active. Use this for safety-critical skills where you want to prevent the LLM from straying. Leave empty (the default) for normal skills.

### `action-sets` auto-loading

When a skill is selected, every name in its `action-sets` is added to the task's action sets. The merger logic (in `do_create_task` at [app/internal_action_interface.py](app/internal_action_interface.py)):

```
final_action_sets = dedup(skill.action_sets + llm_selected_action_sets)
```

A skill that needs `web_research`, `file_operations`, and an MCP server should declare:
```
action-sets:
  - web_research
  - file_operations
  - mcp_<server_name>
```

Don't rely on the LLM to pick the right sets. Declare them.

### Adding a new skill

Three paths, in order of preference:

**1. Use the built-in `craftbot-skill-creator` skill.**
```
User runs:    /craftbot-skill-creator <name> <description>
or LLM picks craftbot-skill-creator mid-task
```
This skill walks through the scaffold (writes the SKILL.md, sets up the directory, suggests action-sets). Most reliable path.

**2. Install from a git repo.**
```
1. read_file app/config/skills_config.json       (avoid duplicates)
2. web_search "<capability> SKILL.md github"     (or known skill repos)
3. run_shell "git clone <url> skills/<name>"
4. stream_edit app/config/skills_config.json
     - move <name> from disabled_skills (if present) to enabled_skills
     - or just add it to enabled_skills if new
5. wait ~0.5s for hot-reload
6. verify: /skill list (user-side) or call list_skills action
```

**3. Author by hand.**
```
1. mkdir skills/<name>
2. write_file skills/<name>/SKILL.md
   (use the format above; copy a similar existing skill as template)
3. stream_edit app/config/skills_config.json to add to enabled_skills
4. wait ~0.5s for hot-reload
5. verify
```

After adding, the skill is available to the NEXT task. The currently-running task (if any) keeps its locked skill list.

### Enable and disable

A skill's enabled state is governed by its presence in `enabled_skills` vs `disabled_skills` in [app/config/skills_config.json](app/config/skills_config.json):

```
enabled_skills:    [<name>, ...]    skills available for LLM selection / slash invocation
disabled_skills:   [<name>, ...]    explicitly OFF (loaded but invisible)
not in either:                       loaded as enabled if auto_load=true (default)
```

Toggle via `stream_edit` on `skills_config.json`, OR via the user-side commands `/skill enable <name>` / `/skill disable <name>`. Both go through the same hot-reload path.

### Verifying changes

After enable / disable / install:

```
1. grep_files "[SKILL]" logs/<latest>.log -A 1     (confirm reload fired)
2. action: list_skills                              (returns the live list)
3. user-side: /skill list                           (same data, different UI)
4. /<skill_name>                                    (only works if user-invocable=true
                                                     AND enabled, else 404)
```

### Skill vs MCP vs action vs prompt - when to choose

```
Capability needs new code or external service                         -> MCP server (## MCP)
Capability needs new code, isolated to the agent                      -> author an action (## Actions)
Capability already exists, just needs orchestration / domain steps    -> skill (here)
Just want to nudge the LLM with a one-off instruction                 -> put it in the user message,
                                                                          NOT in a skill
```

Skills shine for: multi-step workflows ("first check X, then if Y, do Z"), domain expertise ("when generating slides, follow these design rules"), and codified procedures the LLM should follow exactly every time.

### Pitfalls

- A skill with a vague `description` will never get auto-selected. Be specific about triggers.
- A skill that declares `action-sets` it doesn't actually need bloats the prompt.
- A skill with `allowed-tools` that's too narrow will hit dead ends mid-task. Test before shipping.
- Forgetting to add the skill to `enabled_skills` after a fresh install. It stays invisible. Always verify.
- Editing a SKILL.md body of an installed skill: the change applies to the NEXT task. The currently-running task keeps the cached version.
- Body too long: skill body is injected into every prompt for the task. Keep it tight.

### Pre-shipped skills (sample)

The shipped `skills/` directory contains around 100+ entries. Most are disabled by default; flip them via `enabled_skills` in `skills_config.json` to use. Examples currently enabled in this build:

```
get-weather                  weather lookup via Playwright + BBC Weather
weather-check                similar pattern, alternative source
craftbot-skill-creator       authoring new skills
craftbot-skill-improve       refining an existing skill
predict-stock-next-week      stock prediction workflow
docx, pptx, xlsx, pdf        document generation per file format
file-format                  format normalization
playwright-mcp               browser automation steering
living-ui-creator,
living-ui-modify,
living-ui-manager            Living UI project lifecycle
compile-report-advance       multi-source report compilation
```

To enumerate the full installed set: `list_folder skills/` or `read_file app/config/skills_config.json`. To inspect a specific skill before enabling: `read_file skills/<name>/SKILL.md`.

---

## Integrations

You can help the user connect external integrations directly through chat. Most token-based integrations can be fully driven by you: collect the credential from the user, call `connect_integration` with it, and the listener auto-starts. OAuth integrations require the user to run a slash command that opens a browser — your job is to walk them through it. Treat connecting an integration like helping a non-technical friend: tell them exactly where to go, what to copy, and what to paste back.

Code: [app/external_comms/integration_settings.py](app/external_comms/integration_settings.py) (`INTEGRATION_REGISTRY`, `connect_integration_token`, `connect_integration_oauth`, `connect_integration_interactive`). Handlers: [app/credentials/handlers.py](app/credentials/handlers.py) (`INTEGRATION_HANDLERS`).

### What's wired in

11 integrations registered in `INTEGRATION_REGISTRY`. Each has an `auth_type` that determines how connection happens:

```
id                  display name        auth_type                description
─────────────────   ─────────────────   ──────────────────────   ──────────────────────────────
google              Google Workspace    oauth                    Gmail, Calendar, Drive
slack               Slack               both (oauth + token)     Team messaging
notion              Notion              both (oauth + token)     Notes and databases
linkedin            LinkedIn            oauth                    Professional network
discord             Discord             token                    Community chat
telegram            Telegram            token_with_interactive   Messaging platform
whatsapp            WhatsApp            interactive (QR scan)    Messaging via Web
whatsapp_business   WhatsApp Business   token                    WhatsApp Cloud API
jira                Jira                token                    Issue tracking
github              GitHub              token                    Repos, issues, PRs
twitter             Twitter/X           token                    Tweets, timeline
```

To enumerate at runtime: call the `list_available_integrations` action. To check what's already connected: `check_integration_status`.

### The agent's connection toolkit (actions)

```
list_available_integrations()                  → returns full registry + connected state for each
check_integration_status(integration_id)       → status of one integration
connect_integration(integration_id, ...)       → token-based connect (requires credentials)
disconnect_integration(integration_id)         → remove connection
```

`connect_integration` is the workhorse for token-based flows. The exact required fields depend on the integration. Read [app/data/action/integration_management.py](app/data/action/integration_management.py) for the action's input_schema.

### Auth-type playbook

The user just asked you to connect an integration. Here's what you do for each `auth_type`:

```
auth_type "token"
  Driven entirely from chat by you. Steps:
    1. Tell user where to obtain the credential (links + scopes below).
    2. User pastes the credential in chat.
    3. You call connect_integration(integration_id, credentials={...}).
    4. Verify with check_integration_status.

auth_type "oauth"
  Cannot be fully driven from chat. The user must run a slash command that
  opens a browser. Steps:
    1. Confirm settings.json has the right oauth.<platform> client_id and
       client_secret. If empty, tell the user to register an OAuth app at
       the platform's developer console (links below) and paste the IDs.
       You can stream_edit settings.json once they paste.
    2. Tell user: "Run /<platform> login (or /<platform> invite). It will
       open a browser. Authorize, then come back."
    3. Wait for user to confirm. Do NOT poll.
    4. Call check_integration_status to confirm connection.

auth_type "both"
  Two paths. Pick based on user preference:
    - User has CraftOS bot/app available     → /<platform> invite (OAuth)
    - User has their own bot token / app     → connect_integration with token
  Default to whichever the user already mentioned. If unclear, ask.

auth_type "interactive" (whatsapp)
  Requires a QR scan from the user's phone. Steps:
    1. Tell user: "Run /whatsapp login. A QR code will appear. Scan it with
       WhatsApp on your phone (Settings → Linked Devices → Link a Device)."
    2. Wait for user to confirm scan.
    3. Verify with check_integration_status.

auth_type "token_with_interactive" (telegram)
  Token is the primary path; the same as "token". Telegram has additional
  user-account flows (login-user) that are interactive — only invoke if the
  user explicitly wants user-account access (not bot).
```

Never invent a credential. If the user has not provided one, ask. If the user pastes something that doesn't match the expected format, point out what was expected before calling `connect_integration`.

### Required fields and where to obtain them

The fields each token integration needs (from `INTEGRATION_REGISTRY`):

```
slack
  bot_token         (required, "xoxb-..." — Bot User OAuth Token)
  workspace_name    (optional, friendly label)
  Where to get it:
    1. Go to https://api.slack.com/apps → Create New App (from scratch).
    2. OAuth & Permissions → add scopes (chat:write, channels:read,
       channels:history, users:read, etc. depending on use).
    3. Install to Workspace → copy the "Bot User OAuth Token" (xoxb-...).

notion
  token             (required, "secret_..." — Internal Integration Secret)
  Where to get it:
    1. Go to https://www.notion.so/my-integrations → New integration.
    2. Pick a workspace and a name. Submit.
    3. Copy the "Internal Integration Secret".
    4. In Notion, share the relevant pages/databases with the integration
       (the "..." menu on each page → Add connections).

discord
  bot_token         (required — Bot Token from a Discord application)
  Where to get it:
    1. Go to https://discord.com/developers/applications → New Application.
    2. Bot tab → Add Bot → "Reset Token" → copy.
    3. Enable required intents (Message Content, Server Members, etc.).
    4. OAuth2 → URL Generator → bot scope + permissions → invite bot to server.

telegram (bot)
  bot_token         (required — from @BotFather)
  Where to get it:
    1. On Telegram, message @BotFather.
    2. /newbot → set name and username (must end in "bot").
    3. @BotFather replies with the token. Copy and paste.

whatsapp_business
  access_token      (required — Meta Cloud API access token)
  phone_number_id   (required — phone number ID from Meta Business)
  Where to get it:
    1. Go to https://developers.facebook.com → My Apps → Create App
       (Business type) → Add Product → WhatsApp.
    2. From the WhatsApp config: copy the temporary access token AND the
       phone_number_id of the test number (or your own once verified).
    3. For production, generate a permanent token via System User.

jira
  domain            (required — e.g. mycompany.atlassian.net, no https)
  email             (required — your Atlassian account email)
  api_token         (required — Atlassian API token)
  Where to get it:
    1. Go to https://id.atlassian.com/manage-profile/security/api-tokens.
    2. Create API token → label it → copy.

github
  access_token      (required — Personal Access Token, "ghp_..." or "github_pat_...")
  Where to get it:
    1. Go to https://github.com/settings/tokens → Generate new token.
    2. For full repo access, classic token with repo, workflow, read:org scopes;
       fine-grained tokens work for specific repos.
    3. Copy the token (only shown once).

twitter
  api_key             (required — Consumer Key)
  api_secret          (required — Consumer Secret)
  access_token        (required)
  access_token_secret (required)
  Where to get it:
    1. Go to https://developer.twitter.com → Projects & Apps → create an app.
    2. Keys and tokens tab: regenerate Consumer Keys, then Access Token and Secret.
    3. Apps need at least Read+Write user-context permissions for posting.
```

For OAuth integrations (no fields, but client_id/client_secret in `settings.json` `oauth.<platform>`):

```
google
  client_id, client_secret in settings.json → oauth.google
  Where to get it:
    1. Go to https://console.cloud.google.com/apis/credentials.
    2. Create OAuth 2.0 Client ID → Desktop app or Web application.
    3. Copy client_id and client_secret.
    4. Enable APIs you need: Gmail API, Google Calendar API, Google Drive API.
    5. After saving keys to settings.json, user runs /google login.

linkedin
  client_id, client_secret in settings.json → oauth.linkedin
  Where to get it:
    1. Go to https://www.linkedin.com/developers/apps.
    2. Create app → set redirect URL (the CraftBot OAuth callback).
    3. Verify app, request access to required products.
    4. Copy Client ID and Client Secret.
    5. After saving keys to settings.json, user runs /linkedin login.

slack OAuth (alternate to bot token)
  client_id, client_secret in settings.json → oauth.slack
  User runs /slack invite (uses CraftOS-hosted app) or set up your own.

notion OAuth (alternate to integration token)
  client_id, client_secret in settings.json → oauth.notion
  Most users prefer the token path (simpler).
```

### End-to-end chat-driven connection example

A canonical chat-driven flow for `github`:

```
User: "connect my github"

Agent (in conversation mode):
  task_start(task_mode="simple", task_description="Connect user's GitHub")

Agent (inside the task):
  send_message: "I can connect GitHub. I'll need a Personal Access Token.
                 To create one:
                 1. Go to https://github.com/settings/tokens
                 2. Click 'Generate new token (classic)'
                 3. Pick the scopes you need (repo, workflow, read:org for full access)
                 4. Generate and copy the token (it's only shown once)
                 Paste it here when ready."

User: "ghp_abc123xyz..."

Agent:
  connect_integration(
    integration_id="github",
    credentials={"access_token": "ghp_abc123xyz..."}
  )
  → returns {status: "success", message: "..."}

Agent:
  check_integration_status(integration_id="github")
  → confirms connected, lists account name

  send_message: "Connected. You're authenticated as <username>. You can now
                 ask me to read your repos, manage issues, or open PRs."
  task_end
```

For `oauth` integrations the analogous flow:

```
User: "connect my google account"

Agent:
  Check settings.json oauth.google. If client_id/client_secret are empty,
  walk the user through registering an OAuth app at console.cloud.google.com,
  collect the IDs, stream_edit settings.json, then continue.

  send_message: "Now run `/google login` in chat. A browser will open.
                 Authorize CraftBot, then come back here and tell me when
                 you're done."

User: "done"

Agent:
  check_integration_status(integration_id="google")
  → if connected: confirm + list scopes/account
  → if not: ask user to retry, mention common issues (popup blocked,
            wrong account picked, scopes denied)
```

### Listener auto-start

After a successful `connect_integration` call, listeners auto-start for platforms that support push-style messaging. From `PLATFORM_MAP`:

```
whatsapp     → whatsapp_web listener
telegram     → telegram_bot AND telegram_user listeners
google       → google_workspace listener
jira         → jira listener
github       → github listener
twitter      → twitter listener
```

For `slack`, `notion`, `discord`, `linkedin`, `outlook`, `whatsapp_business`: connection works but listener-style auto-reply is not configured at this layer (some are handled separately via `external_comms_config.json` for telegram/whatsapp specifically).

### Verifying a connection

After any connect attempt:

```
1. check_integration_status(integration_id)         → returns success + account display
2. /cred status (user-side)                          → overview of all integrations
3. grep_files "[<platform>]" logs/<latest>.log     → look for connect / auth errors
```

If `check_integration_status` returns "Not connected" right after a successful `connect_integration` call, something is wrong. Common: the credential validated but the listener failed to start (check logs for that platform's tag).

### Disconnect

```
disconnect_integration(integration_id, account_id?)
```

`account_id` is optional. Pass it when there are multiple accounts on one platform (e.g. multiple Slack workspaces) and you want to keep the others. Omit to disconnect everything for that integration.

The user can also `/<platform> disconnect [account_id]`.

### Common failure modes

```
Symptom                                            Likely cause              Fix
─────────────────────────────────────────────────  ────────────────────────  ──────────────────────────
"Bot token is required" / "Token is required"      missing credential        ask user, retry
                                                   in connect_integration

connect succeeds, but tool calls return            scope insufficient        user re-creates token
"Forbidden" / "Insufficient scope"                                            with proper scopes

oauth connect: browser doesn't open                missing client_id/secret  walk user through
                                                   in settings.json          registering OAuth app
                                                                              and pasting IDs

oauth connect: "redirect_uri_mismatch"             redirect URL wrong in     fix redirect URL in
                                                   the developer console     developer console

whatsapp QR: timeout                               user did not scan in time tell user to retry,
                                                                              ensure phone has network

jira: 401 / 403 on tool calls                      domain or email wrong     user re-checks domain
                                                                              format and Atlassian email

twitter: invalid signature                         API tier doesn't allow    user upgrades Twitter API
                                                   the operation             tier (free is read-only)

connection works once, fails next session          token expired (some       user regenerates and
                                                   GitHub fine-grained       reconnects
                                                   tokens have short TTL)
```

When in doubt: read the action's error message in full, then check `logs/<latest>.log` for the integration's tag.

### When to use integration actions vs MCP

Some integrations have BOTH built-in actions (via this section's connection flow) AND a corresponding MCP server (e.g. `github`, `notion`, `slack`). Pick:

```
You need basic CRUD via the user's account                    → built-in integration (here)
You need rich tool surface, custom workflows, or a feature
the built-in action doesn't expose                            → MCP server (## MCP)
The user has both connected                                   → use the integration first;
                                                                 fall back to MCP if missing a verb
```

The built-in integrations cover the common 80%; MCP covers the long tail.

### Permission and disclosure

- ALWAYS tell the user what credentials you need and where to get them. Never paste a vague "give me your token".
- ALWAYS confirm the credential format roughly matches before submitting (e.g., GitHub PAT starts with `ghp_` or `github_pat_`). If it doesn't, ask the user to verify.
- ALWAYS mask tokens in your replies. Don't echo back the full credential — use a prefix or a `...` truncation.
- ALWAYS verify connection success before declaring victory.
- NEVER write the token to memory, MEMORY.md, USER.md, or chat history beyond the immediate connect step. The handler stores it under `.credentials/<platform>.json` (see `## File System` for the do-not-print rule).

---

## Models

You generate every response through an LLM. The user can ask you to change provider or model in chat, and you can drive that change. This section covers: providers, the model registry, LLM vs VLM vs embedding, the right way to switch (with a critical gotcha), per-provider caching strategy, and rate-limit handling.

Code: [agent_core/core/impl/llm/interface.py](agent_core/core/impl/llm/interface.py) (`LLMInterface`), [agent_core/core/models/model_registry.py](agent_core/core/models/model_registry.py) (`MODEL_REGISTRY`), [app/models/factory.py](app/models/factory.py) (`ModelFactory.create`), [app/ui_layer/settings/model_settings.py](app/ui_layer/settings/model_settings.py) (`PROVIDER_INFO`).

### Three interface types

The same provider serves up to three "interfaces":

```
LLM         text generation. The main chat brain. Required.
VLM         vision-language model. Used for image actions (describe_image, OCR).
EMBEDDING   text embedding. Used for memory_search semantic indexing.
```

Each interface picks its model independently. `settings.json` `model.llm_provider` and `model.vlm_provider` can point at different providers if you want (e.g., `anthropic` for text, `gemini` for vision).

### Providers and what they support

From [MODEL_REGISTRY](agent_core/core/models/model_registry.py):

```
provider     LLM default model            VLM default model           EMBEDDING default        notes
─────────    ──────────────────────       ──────────────────────      ──────────────────────   ─────────────────────────────
openai       gpt-5.2-2025-12-11           gpt-5.2-2025-12-11          text-embedding-3-small   OpenAI-hosted
anthropic    claude-sonnet-4-5-20250929   claude-sonnet-4-5-20250929  (none — no embedding)    Claude models
gemini       gemini-2.5-pro               gemini-2.5-pro              text-embedding-004       Google Gemini
byteplus     seed-1-6-250915              seed-1-6-250915             skylark-embedding-...    BytePlus-hosted
remote       llama3.2:3b                  llava:7b                    nomic-embed-text         Ollama or OpenAI-compat
deepseek     deepseek-chat                (none)                      (none)                   text only
moonshot     moonshot-v1-8k               (none)                      (none)                   text only
grok         grok-3                       grok-4-0709                 (none)                   xAI
minimax      MiniMax-Text-01              (none)                      (none)                   text only
```

If you set `model.llm_model: null` in settings.json, the default from MODEL_REGISTRY is used. Set an explicit string to override.

A provider with `(none)` for VLM cannot be used as `vlm_provider`. If the user asks for vision but only has a text-only provider configured, tell them to set a separate `vlm_provider` (or use `byteplus` / `anthropic` / `openai` / `gemini` for vision).

### Provider-name vs settings-key mismatch (gotcha)

The provider names used in code and in `model.llm_provider` are not always identical to the `api_keys.<key>` names:

```
provider name   settings.json api_keys field   /provider command alias
─────────────   ─────────────────────────       ──────────────────────
openai          api_keys.openai                 openai
anthropic       api_keys.anthropic              anthropic
gemini          api_keys.google                 gemini    (note: provider name is "gemini" but the key is stored under "google")
byteplus        api_keys.byteplus               byteplus
deepseek        api_keys.deepseek               deepseek
grok            api_keys.grok                   grok
remote          (none — uses endpoints.remote)  remote
```

When setting an API key for Gemini, edit `api_keys.google`, NOT `api_keys.gemini`. Same translation in the `api_keys_configured` block.

### Model section schema (in settings.json)

```
model:
  llm_provider:        string        e.g. "anthropic"
  vlm_provider:        string        e.g. "anthropic"  (often same as llm_provider)
  llm_model:           string|null   null = use MODEL_REGISTRY default for the provider
  vlm_model:           string|null   null = use MODEL_REGISTRY default
  slow_mode:           bool          true = throttle requests to avoid 429s
  slow_mode_tpm_limit: int           tokens per minute when slow_mode is true (e.g. 25000)
```

Full settings.json schema is in `## Configs`.

### How LLMInterface picks the model

At construction (and on `reinitialize_llm`), `ModelFactory.create(provider, interface, model_override, ...)`:

```
1. Looks up the provider in MODEL_REGISTRY[provider][interface].
2. If model_override is set, uses it. Otherwise uses the registry default.
3. Wires up the right client: OpenAI SDK, Anthropic SDK, Gemini client, BytePlus
   wrapper, or Ollama HTTP for "remote".
4. Returns ctx with provider, model, client/handles, base URL, etc.
```

The LLMInterface is constructed ONCE at startup (and reconstructed by `reinitialize_llm`). It is NOT recreated when settings.json is hot-reloaded. This is the most important gotcha in this section — see "Switching provider or model" below.

### Switching provider or model — through chat

The user asks: "switch to GPT-4" or "use Gemini" or "I'd like to try Claude".

There are TWO mutation paths. Pick the right one based on what's changing:

**Path A: Same-provider model swap (e.g. claude-sonnet-4 → claude-opus-4)**

Edit `settings.json` and the change applies on the NEXT LLM call. The cache invalidates on save; the existing client uses the new model name from the next call onward.

```
1. read_file app/config/settings.json
2. stream_edit:
     model.llm_model: "<old>" → "<new>"
     (also model.vlm_model if user wants vision swap)
3. wait ~0.5s for hot-reload
4. send_message confirming the swap took effect on next turn
```

**Path B: Provider switch (e.g. anthropic → openai)**

`stream_edit` ALONE is not enough. The LLMInterface holds the old provider's client. You must trigger `reinitialize_llm`, which is exposed only via the `/provider` slash command.

```
1. Ensure api_keys.<settings_key> for the new provider is set.
   Remember the gemini → "google" name translation.
   If empty: ask the user for a key, then stream_edit api_keys + api_keys_configured.
2. Tell the user to run:    /provider <name> [<api_key>]
   Examples:    /provider openai sk-...
                /provider anthropic
                /provider gemini AIza...
3. The slash command:
     - saves to settings.json (settings, api_keys, env)
     - calls agent.reinitialize_llm(<provider>) which rebuilds the LLMInterface
4. Verify by waiting for the next LLM-driven response; mention the new provider
   is in effect.
```

DO NOT just stream_edit `model.llm_provider` and call it done. The cache will say the new provider, but the LLMInterface will still use the old one until reinit. Symptoms of getting this wrong: replies still come from the old model, or LLMConsecutiveFailureError if the old client now lacks credentials.

If the user cannot or will not run the slash command, the alternative is restarting CraftBot. State that explicitly.

### Setting a missing API key (no provider switch)

If the user just provides a new key for the CURRENT provider (e.g., they updated their Anthropic key):

```
1. stream_edit settings.json
     api_keys.<settings_key>: "<old or empty>" → "<new>"
     api_keys_configured.<settings_key>: false → true
2. Hot-reload picks up the new key on next LLM call.
3. If unsure whether the existing client cached the old key, recommend the user
   run /provider <current> <new_key> to rebuild the client cleanly.
```

### Connection testing

Before declaring the switch worked, verify. There's a built-in test using
[app/config/connection_test_models.json](app/config/connection_test_models.json) (a tiny model + 1-token request per provider).

```
1. read_file app/config/connection_test_models.json   (see what model is used to test)
2. test_provider_connection(provider, api_key)        helper at app/models
                                                       (or wait for the user's first
                                                        response to confirm)
```

The cheapest verification is just sending a `send_message` and waiting for the reply to come back without `LLMConsecutiveFailureError`.

### Slow mode (rate-limit handling)

If the user hits 429s (provider rate limit):

```
slow_mode: true                  pace requests
slow_mode_tpm_limit: <N>         tokens per minute target. Common: 25000 for Anthropic free.
```

Set both. The throttle is internal to LLMInterface. After enabling, no further changes needed for the user — requests just take longer.

### Per-provider caching (KV cache strategy)

The harness applies different caching strategies per provider. You don't manage this directly, but knowing it helps explain cost/latency to the user:

```
provider      cache type                                managed by
─────────     ───────────────────────────────────────   ───────────────────────────
anthropic     ephemeral cache_control with extended TTL agent_core (built-in)
gemini        explicit context cache (file-based)        GeminiCacheManager
byteplus      session cache (server-side, prefix-based) BytePlusCacheManager
openai        prompt_cache_key (automatic)               provider auto
deepseek      prompt_cache_key                           provider auto
grok          prompt_cache_key                           provider auto
remote        no cross-request caching                   n/a
```

Cache TTLs come from `cache.prefix_ttl` and `cache.session_ttl` in settings.json. `cache.min_tokens` skips caching for short prompts.

### Endpoint overrides

In `settings.json` `endpoints`:

```
remote_model_url       base URL for "remote" provider (Ollama or OpenAI-compat)
remote                 alternate endpoint for remote (default http://localhost:11434)
byteplus_base_url      defaults to https://ark.ap-southeast.bytepluses.com/api/v3
google_api_base        override for Gemini API base URL
google_api_version     override for Gemini API version
```

Use these for self-hosted, regional endpoints, or non-default Gemini API versions. For most users, leave defaults.

### Consecutive-failure circuit breaker

`LLMInterface._max_consecutive_failures = 5`. After 5 consecutive failed LLM calls, `LLMConsecutiveFailureError` is raised, the active task is auto-cancelled, and `LLM_FATAL_ERROR` UI event fires. Counter resets on a successful call.

Common triggers: bad API key, expired key, model name typo, rate limit storm, network outage. See `## Errors` for the recovery rules. After fixing the cause, the user must START A NEW TASK (the cancelled one is gone).

### Picking the right model for a job

When the user is undecided:

```
Goal                                          Suggested provider
──────────────────────────────────────────    ──────────────────────────
General chat / coding / reasoning             anthropic (claude-sonnet-4-5)
                                              openai (gpt-5.2)
Vision / image understanding                  any of: anthropic, openai, gemini, byteplus, grok
Long-context document analysis                gemini (1-2M context)
                                              anthropic with extended cache
Cheap bulk reasoning                          deepseek
                                              byteplus
Air-gapped / offline                          remote (Ollama)
                                              point to local llama / qwen / mistral
Strict cost control                           gemini (free tier)
                                              deepseek (low per-token)
```

This list is opinion, not authoritative. The user has the final say.

### Pitfalls

- Editing `model.llm_provider` in settings.json without running `/provider` to reinitialize. The cache says new, the live LLM uses old. Always do Path B.
- Setting `api_keys.gemini` instead of `api_keys.google`. The Gemini provider reads from the `google` key (settings_key mismatch). Same for `api_keys_configured`.
- Choosing a `vlm_provider` whose `MODEL_REGISTRY` entry has `VLM: None`. Vision actions will fail.
- Empty `api_keys.<provider>` for a non-remote provider triggers `MSG_AUTH` on the first call. Always check before switching.
- Forgetting to update `api_keys_configured` when adding a key. UI bookkeeping breaks; LLM still works.
- Running `/provider <name>` with a key but the key is for the wrong provider (e.g., pasting Anthropic key after `/provider openai`). The error surfaces on the first call. Verify keys match.
- Switching to `remote` (Ollama) without `endpoints.remote_model_url` configured. The factory tries `http://localhost:11434` by default; if Ollama isn't running, every call fails.

### Permission and disclosure

- Always confirm with the user before switching provider. The active task may have cached state that doesn't transfer.
- Always mask API keys in chat (`sk-***...***abcd`). Echo the prefix and last 4 only.
- After a switch, send a brief confirmation: provider, model, whether vision is supported.
- Don't change models without being asked. Stick with what the user configured.

---

## Memory

Memory is your long-term recall. It is RAG-backed (semantic search over a vector index), not text-grep over MEMORY.md. Items reach MEMORY.md only after the daily memory-processing pipeline distills them from the event stream. You read memory via the `memory_search` action; you do NOT write MEMORY.md directly.

Code: [agent_core/core/impl/memory/manager.py](agent_core/core/impl/memory/manager.py) (`MemoryManager`), [agent_core/core/impl/memory/memory_file_watcher.py](agent_core/core/impl/memory/memory_file_watcher.py) (incremental re-indexing), [app/data/action/memory_search.py](app/data/action/memory_search.py) (action).

### The pipeline

```
1. Action / message / system event happens
        |
        v
2. EventStreamManager appends to EVENT.md           (full chronological log)
        |
        v
3. EventStreamManager appends filtered subset to    (memory pipeline staging
   EVENT_UNPROCESSED.md                              buffer; see filter below)
        |
        v
4. Daily 3am: scheduler fires payload.type=         (or on startup if buffer
   "memory_processing" trigger                       is non-empty)
        |
        v
5. Agent runs the memory-processor skill            (set_skip_unprocessed_logging
   reads EVENT_UNPROCESSED.md                        is True so the task's own
   scores each event with Decision Rubric            events do not loop back)
   distills passing events to MEMORY.md
        |
        v
6. EVENT_UNPROCESSED.md is cleared
        |
        v
7. memory_file_watcher detects MEMORY.md changed,
   triggers MemoryManager.update() to reindex the
   ChromaDB collection
```

EVENT_UNPROCESSED.md filter (events NOT staged): `action_start`, `action_end`, `todos`, `error`, `waiting_for_user`. The pipeline focuses on user-facing dialogue and important state changes. See `## File System` for full details.

The Decision Rubric (Impact + Risk + Cost + Urgency + Confidence, each 1-5, threshold >= 18) lives in [PROACTIVE.md](agent_file_system/PROACTIVE.md). Do NOT duplicate it elsewhere.

### MEMORY.md format

```
[YYYY-MM-DD HH:MM:SS] [type] content
```

Type values:
```
capability          a new tool, MCP server, or skill became available
project             ongoing work the user is doing
workspace           workspace contents or organization
focus               what the user is currently focused on
preference          a stable user preference (also goes to USER.md often)
analysis            distilled insight from a past task
user_complaint      something the user objected to (avoid repeating)
system_warning      a non-fatal warning the agent should remember
system_limit        a known limit (rate limit, model quota, etc.)
```

One fact per line. Multi-line entries break the parser.

### How memory_search works

`memory_search(query, top_k)` is a vector search via ChromaDB ([app/data/action/memory_search.py](app/data/action/memory_search.py)):

```
input:
  query            string. Natural-language question or topic.
  top_k            int, default 5. Maximum results to return.

output:
  status           "ok" | "error"
  results          list of memory pointers:
                     [
                       {
                         chunk_id:        "MEMORY.md_memory_3"
                         file_path:       "MEMORY.md"
                         section_path:    "Memory"
                         title:           "<section title>"
                         summary:         "<first ~150 chars of the chunk>"
                         relevance_score: 0.0-1.0 (higher = more relevant)
                       },
                       ...
                     ]
  count            int
```

Pointers are LIGHTWEIGHT references, not full content. To read the full chunk, `read_file <file_path>` and find the section, OR call the manager's `retrieve_full_content(chunk_id)` if exposed via an action.

Relevance score is normalized from ChromaDB's L2 distance: `relevance = 1.0 / (1.0 + distance)`. A score above ~0.6 is usually "highly relevant"; below ~0.3 is weak.

### Indexed files (what memory_search can find)

The MemoryManager indexes these files only ([agent_core/core/impl/memory/manager.py](agent_core/core/impl/memory/manager.py) `INDEX_TARGET_FILES`):

```
AGENT.md
PROACTIVE.md
MEMORY.md
USER.md
EVENT_UNPROCESSED.md
```

Searches over these are semantic. Files outside this list are NOT in the vector index, even if you `read_file` them often. To find content in non-indexed files, use `grep_files` directly.

### Incremental re-indexing

The watcher at [agent_core/core/impl/memory/memory_file_watcher.py](agent_core/core/impl/memory/memory_file_watcher.py) observes the indexed files. On any change:

```
1. compute MD5 of changed file
2. if hash differs from cached hash: remove old chunks, re-chunk, re-index
3. cache the new hash
```

Indexing is per-section (split by markdown headers) so one change doesn't re-process the whole file. Logs:

```
[MemoryFileWatcher] Started watching: <agent_file_system path>
Memory update complete: {'files_added': N, 'files_updated': N, 'files_removed': N, 'chunks_added': N, 'chunks_removed': N}
```

### When to use memory_search vs grep vs file read

```
Question                                         Tool
──────────────────────────────────────────       ─────────────────────────────
"What do I know about X?"                        memory_search(query="X")
"What did the user say about Y last month?"      memory_search(query="user said Y") + read CONVERSATION_HISTORY.md
"Show me all entries of a specific type"         grep_files "[type]" MEMORY.md
"What's in USER.md right now?"                   read_file USER.md
"Find specific text in PROACTIVE.md"             grep_files "<text>" PROACTIVE.md
"What past tasks involved <subject>?"            grep_files "<subject>" TASK_HISTORY.md
```

memory_search is for "what do I know about" questions. Grep is for "find this exact string". Pick the right tool.

### Memory pruning

When MEMORY.md exceeds `memory.max_items` in settings.json (default 200), pruning kicks in:

```
1. memory-processing task includes needs_pruning=True
2. processor evaluates each entry's relevance and recency
3. trims down to memory.prune_target (default 135)
4. discarded entries are dropped (not archived)
```

Pruning runs at the same time as distillation. Look for `[MEMORY] Process memory task created with pruning phase` in logs.

You can request a manual prune in chat: tell the user, then either wait for next 3am cycle or (if exposed) trigger it. The agent does NOT have a direct "prune now" action.

### Adding a fact you want remembered NOW (between cycles)

memory-processing only runs daily at 3am (or on startup with non-empty buffer). If the user wants something remembered immediately:

```
Option 1: Add to USER.md
  For stable user preferences (language, tone, approval rules, etc.)
  Use stream_edit USER.md → confirm with user → edit takes effect immediately
  USER.md is in INDEX_TARGET_FILES, so memory_search picks it up.

Option 2: Wait for next pipeline run
  Every interaction is in EVENT_UNPROCESSED.md. The 3am job will distill it.
  Tell the user: "I'll remember that — it'll be distilled into long-term
  memory in the next memory cycle."

Option 3: Manual trigger (if user requests)
  Some installs expose a way to fire memory_processing on demand
  (e.g. via a slash command). If not exposed, only the user can trigger.
  Do NOT fabricate a way.
```

### Hard rules

- You MUST NOT `stream_edit` or `write_file` MEMORY.md. Only the memory processor writes there.
- You MUST NOT edit EVENT.md, EVENT_UNPROCESSED.md, CONVERSATION_HISTORY.md, or TASK_HISTORY.md.
- You MAY edit USER.md (with user confirmation, see `## Self-Edit`).
- You MAY edit AGENT.md (with caution, see `## Self-Edit`).
- Calling `grep_files` on MEMORY.md is OK for inspection, BUT for retrieval use `memory_search`. Grep misses semantic matches and skips relevance ranking.
- The vector index lives in `chroma_db_memory/` — do NOT edit by hand.

### Settings that affect memory

In [app/config/settings.json](app/config/settings.json) `memory` block (see `## Configs`):

```
memory.enabled            bool. If false, memory_search returns empty + no
                          pipeline runs. Pipeline trigger is skipped at the
                          react level (is_memory_enabled() check).
memory.max_items          int (default 200). Trigger threshold for pruning.
memory.prune_target       int (default 135). Target size after a prune.
memory.item_word_limit    int (default 150). Soft cap on words per stored item.
```

Toggling `memory.enabled` to false does NOT delete `MEMORY.md` or `chroma_db_memory/`. It just stops the pipeline from running and `memory_search` from returning results.

### Pitfalls

- `memory_search` returns "Memory is disabled" → check `memory.enabled` in settings.json. The user may have turned it off.
- `memory_search` returns empty `results: []` with no error → the index may be empty (fresh install) or the query phrasing doesn't match the indexed content. Try rephrasing or `grep_files` as fallback.
- Editing AGENT.md, USER.md, PROACTIVE.md, MEMORY.md, or EVENT_UNPROCESSED.md re-triggers re-indexing. If you make rapid edits, the watcher debounces but still consumes some time. Don't loop edit-then-search.
- `relevance_score` is L2-distance-normalized. Don't compare scores across queries (different queries have different score distributions).
- The `chroma_db_memory/` directory is an opaque ChromaDB store. Do not try to repair or migrate it. If corrupted, the user must delete the directory and let the manager rebuild on next startup.

---

## Proactive

The proactive system lets you fire tasks on a schedule without a user prompt. Two parallel mechanisms exist: **recurring tasks** (in PROACTIVE.md, fired by the heartbeat) and **scheduled tasks** (in scheduler_config.json, fired by cron). Most user-facing automations belong in PROACTIVE.md.

Code: [app/proactive/manager.py](app/proactive/manager.py) (`ProactiveManager`), [app/proactive/parser.py](app/proactive/parser.py), [app/proactive/types.py](app/proactive/types.py). Authority on rubric and tiers: [agent_file_system/PROACTIVE.md](agent_file_system/PROACTIVE.md).

### Two mechanisms — when to use each

```
PROACTIVE.md (preferred for user automations)        scheduler_config.json (system + one-offs)
───────────────────────────────────────────────      ────────────────────────────────────────────
recurring_add / recurring_read /                     schedule_task / scheduled_task_list /
recurring_update_task / recurring_remove             schedule_task_toggle / remove_scheduled_task

Frequencies: hourly | daily | weekly | monthly       Schedule expressions: "every day at 3am",
                                                     cron "0,30 * * * *", "in 2 hours",
                                                     "tomorrow at 9am", "immediate", etc.

Heartbeat (every 30 min) checks for due tasks        Each entry has its own cron, fires
across ALL frequencies, runs each that's due,        independently. One-time entries auto-remove.
respecting time / day filters.

Decision Rubric and Permission Tiers apply.          No rubric or tier system at this level.
                                                     Scheduled tasks just fire as configured.

Use for: morning briefings, weekly reviews,          Use for: built-in schedules (memory-processing,
recurring user-facing automations, anything          heartbeat, planners), one-time reminders
with a permission_tier and conditions.               ("remind me at 3pm tomorrow"), system jobs.
```

The user wants a daily morning briefing? Use `recurring_add`. The user wants a one-time "remind me at 5pm"? Use `schedule_task`.

### When to set up a proactive task

A proactive task is justified ONLY when ALL of these are true:

```
1. The user explicitly asked for it, OR you are extending a clear recurring
   pattern they already use.
2. The work is repeatable, predictable, and useful enough to justify the
   cost of running it on schedule.
3. The output is actionable — has a clear destination (chat, file, integration).
4. The user has consented to the cadence and the permission tier.
5. There is no existing recurring task that does the same thing.
```

Reject the impulse to add proactive tasks aggressively. Each one consumes LLM turns on a schedule and clutters the user's mental model.

DO NOT auto-create a proactive task because it "sounds useful". Always offer first, get explicit consent, then create.

### When NOT to set up a proactive task

```
- One-off requests ("check the weather right now") → just do it inline.
- Tasks with vague triggers or unclear stop conditions.
- Tasks the user might forget they set up. Better to add as a one-time
  reminder via schedule_task with a fixed end date.
- Tasks that need real-time event triggers, not time-based ones (e.g. "tell
  me when X arrives in my inbox" is better solved with an integration
  listener, not a poll-every-hour proactive task).
- Tasks that overlap with an existing one. Run recurring_read first.
```

### Built-in scheduler entries (do NOT remove)

These ship pre-configured in [app/config/scheduler_config.json](app/config/scheduler_config.json) and run the system itself:

```
id                  schedule              purpose
─────────────────   ──────────────────    ─────────────────────────────────────────────────
heartbeat           0,30 * * * *          every 30 min: scan PROACTIVE.md, fire due tasks
memory-processing   every day at 3am      distill EVENT_UNPROCESSED.md into MEMORY.md (## Memory)
day-planner         every day at 7am      review yesterday + plan today's proactive priorities
week-planner        every sunday at 5pm   weekly review, update Goals/Plan/Status in PROACTIVE.md
month-planner       0 8 1 * *             1st of month 8am, monthly review
```

Removing or disabling these breaks the system. If the user wants to STOP them firing (e.g., disable proactive entirely), set `proactive.enabled: false` in `settings.json` instead.

### Planners deep-dive

Three time-horizon planners ship as separate skills, each owning one cadence:

```
day-planner       (skills/day-planner/SKILL.md)        daily 7am
week-planner      (skills/week-planner/SKILL.md)       Sunday 5pm
month-planner     (skills/month-planner/SKILL.md)      1st of month 8am
```

The fourth executor in this family is `heartbeat-processor` — not strictly a planner, but the same family pattern. It fires every 30 min and runs whatever PROACTIVE.md says is due.

All four share an important property: **silent execution**. They override standard task completion rules ([skills/day-planner/SKILL.md](skills/day-planner/SKILL.md), [skills/heartbeat-processor/SKILL.md](skills/heartbeat-processor/SKILL.md)):

```
NO acknowledgement to user on task start.
NO waiting for user confirmation before task_end.
MUST call task_end immediately after the planning/execution work is done.
MAY send_message at tier 1 (notify, no wait) when there's something user-facing.
NEVER block on a user reply (no wait_for_user_reply=true except when proposing a new task).
```

Why: planners and heartbeat run automatically. If they wait for user confirmation each cycle, tasks pile up indefinitely.

**day-planner** ([skills/day-planner/SKILL.md](skills/day-planner/SKILL.md))
- Fires daily at 7am via scheduler.
- Pre-flight reads: `scheduled_task_list`, PROACTIVE.md, TASK_HISTORY.md, MEMORY.md, USER.md, recent CONVERSATION_HISTORY.md.
- Goal: "How can I help the user get SLIGHTLY closer to their goals TODAY?"
- Output: updates the Goals / Plan / Status section in PROACTIVE.md with the day's priorities. Optionally proposes ONE new recurring or scheduled task with `wait_for_user_reply=true` and a 20-hour timeout (does NOT add the task if user doesn't reply in 20 hours).
- Action sets loaded by default: `file_operations`, `proactive`, `scheduler`, `google_calendar`, `notion`, `web`.

**week-planner** ([skills/week-planner/SKILL.md](skills/week-planner/SKILL.md))
- Fires Sunday 5pm.
- Reviews the past week's outcomes, updates the weekly section of Goals / Plan / Status, and may propose changes to recurring tasks (frequency tweaks, retiring stale tasks).

**month-planner** ([skills/month-planner/SKILL.md](skills/month-planner/SKILL.md))
- Fires 1st of month at 8am.
- Long-horizon: monthly themes, big-picture goal review, retiring or renaming PROACTIVE.md tasks that no longer serve.

**heartbeat-processor** ([skills/heartbeat-processor/SKILL.md](skills/heartbeat-processor/SKILL.md))
- Fires every 30 min via the `heartbeat` schedule.
- For each due task in PROACTIVE.md, picks one of two execution types:
  - **INLINE** (default for tier 0-1, simple actions): runs the task in this heartbeat session, sends optional tier-1 notification, records outcome via `recurring_update_task add_outcome`, moves on.
  - **SCHEDULED**: spawns a separate session via `schedule_task(schedule="immediate", ...)` when the task needs different action sets, complex multi-step work, or its own session lifecycle.
- After processing all due tasks, calls `task_end` immediately.

**Custom planners exist.** The repo also ships skills like `compliance-cert-planner` and `task-planner` for narrower cadences. They follow the same silent-execution pattern but are wired in via separate scheduler entries when needed. Read their SKILL.md to learn what they do; don't assume they're active without confirming.

**Reading the planners' output.** The Goals / Plan / Status section of PROACTIVE.md is where planners speak to you. When you start a task, scan that section for current focus and recent accomplishments — that's the cheapest way to align with the user's stated direction.

### One-time / immediate proactive tasks (fire-and-check-back)

The most underused pattern in this section. Use it when:

- The user wants something done at a SPECIFIC future moment (not on a recurring cadence).
- The user wants something done IMMEDIATELY but in a separate session that returns a result later.
- You're inside a task and want to spawn a parallel sub-task whose result you'll check on next time you wake up.
- A planner has identified a concrete one-shot action ("research X tomorrow morning at 9am").

These tasks fire ONCE, return a result via `send_message` and/or by writing to the workspace, and auto-remove themselves from `scheduler_config.json` after firing.

Use `schedule_task` with one of these expressions:

```
"immediate"              fire NOW (queues an immediate trigger; runs as soon as
                         the trigger queue picks it up, typically within seconds).
"in 30 minutes"          fire 30 minutes from now.
"in 2 hours"             fire 2 hours from now.
"at 3pm"                 fire at 3pm today (or tomorrow if 3pm has passed).
"at 3:30pm"              fire at 3:30pm today.
"at 3:30pm today"        explicit today (rejects if past).
"tomorrow at 9am"        fire 9am tomorrow.
```

Schema reminder (full table is in "Scheduled task actions" above):

```
schedule_task(
  name="<short name>",
  instruction="<what to do, in clear imperative voice>",
  schedule="<expression from list above>",
  mode="simple" | "complex",         default "simple"
  priority=<1-100>,                   default 50
  enabled=True,                       always true for one-shots
  action_sets=[<sets needed>],        if known; otherwise auto-selected
  skills=[<skills needed>],           rare for user-driven one-shots
  payload={...}                       optional extra data for the trigger
)
```

**When to set `mode="simple"` vs `mode="complex"` for a one-shot:**

```
simple    quick lookup, single output (3 actions or fewer). No user-approval gate. Auto-ends.
complex   multi-step research, document generation, multi-source compile. User approval at end.
```

Default to simple for one-shots unless the work clearly needs todos.

**Examples.**

User says: "in 30 minutes, remind me to take the laundry out"

```
schedule_task(
  name="Laundry reminder",
  instruction="Send the user a brief reminder to take the laundry out.",
  schedule="in 30 minutes",
  mode="simple",
)
```

User says: "research the new Apple Vision Pro reviews and give me a summary tomorrow morning at 8am"

```
schedule_task(
  name="Apple Vision Pro review summary",
  instruction=(
    "Search the web for the latest Apple Vision Pro reviews from credible "
    "tech publications. Compile a summary covering: hardware impressions, "
    "software/UX feedback, comparison to competitors, common complaints, "
    "common praise. Send the summary to the user via send_message."
  ),
  schedule="tomorrow at 8am",
  mode="complex",
  action_sets=["web_research", "file_operations"],
)
```

User asks you (mid-task) to "also start checking the GitHub issue I just opened" while you're doing something else:

```
schedule_task(
  name="Monitor GitHub issue #X",
  instruction="Fetch the GitHub issue at <url> right now and report the latest comments and status.",
  schedule="immediate",
  mode="simple",
  action_sets=["github"],
)
```

`schedule="immediate"` queues a trigger that fires within seconds. The agent (in a fresh task) picks it up, runs the instruction, returns. The current task is unaffected.

**Why this pattern matters.** It lets you parallelize: spawn a one-shot, keep working on the main task, and the user gets the spawned task's result asynchronously via send_message. It's also the right pattern when a planner identifies a discrete future action — the planner schedules the task, then ends silently, and the future-agent runs the actual work later.

**One-shot lifecycle.**

```
1. schedule_task(schedule="<future moment>", ...) creates entry in scheduler_config.json.
2. The scheduler holds it until fire_at is reached.
3. At fire_at, scheduler emits a trigger with payload.type="scheduled" (or as configured).
4. react() routes the trigger to the conversation/simple/complex workflow based on mode.
5. The agent runs the instruction.
6. After firing, the scheduler removes the entry (one-shots are auto-removed).
7. Final result is in EVENT.md, send_message output, or workspace files (depending on instruction).
```

**Verifying a one-shot is queued:**

```
scheduled_task_list()                              ← see all entries + next fire times
read_file app/config/scheduler_config.json         ← raw inspection
```

If a one-shot was supposed to fire but didn't, check:
- `proactive.enabled` in settings.json
- `enabled: true` on the entry
- The schedule expression parsed correctly (failed parse = entry never created — check for an error in the action's return)
- The system was running at fire time (CraftBot must be alive for the trigger to fire)

### After a proactive task fires — thinking about what's next

A proactive task that runs and disappears without follow-up wastes the work. After ANY proactive task (recurring or one-time) finishes, the executing agent should consider:

**1. Did the task fully achieve its goal?**

```
Yes  →  record the outcome with recurring_update_task add_outcome (for recurring)
        or just log via task_end summary (for one-shots).
        Move on.

Partially  →  record what was achieved AND what's outstanding.
              Decide: spawn a follow-up via schedule_task for the remainder?
              Or surface the gap to the user?

No (failed)  →  record the failure with success=false.
                Decide: was it transient (retry next cycle), approach-wrong
                (change instruction or scope), or impossible (disable task,
                surface to user)?
                See ## Errors for the failure taxonomy.
```

**2. Is there a natural follow-up the user would want?**

```
The task surfaced new information that needs action  →  schedule_task immediate
                                                         for the action; or send_message
                                                         to the user with the finding.
The task identified an emerging pattern              →  consider proposing a NEW recurring
                                                         task (with user consent) to track it.
The task confirmed nothing changed                   →  silent task_end; no follow-up needed.
The task hit a blocker that requires user input      →  send_message with a specific question;
                                                         do NOT schedule another attempt
                                                         until the user replies.
```

**3. Should the recurring task itself be adjusted?**

If the same recurring task has hit the SAME outcome multiple times in a row (visible in `outcome_history`), consider:

```
- Increase or decrease frequency (e.g., daily → weekly).
- Tighten or relax conditions (e.g., add weekdays_only).
- Update the instruction to reflect what actually works.
- Disable the task if it's no longer useful.
```

Use `recurring_update_task` with the appropriate `updates` dict. Don't make these changes silently for tasks the user set up — confirm first.

**4. Is the Goals / Plan / Status section in PROACTIVE.md still accurate?**

If a proactive task accomplished or invalidated something in the planner-maintained section:

```
- Mark a "Plan" item as completed.
- Update "Status" to reflect new state.
- Drop a stale "Goal" if the user no longer cares.
```

Planners (day, week, month) update this section automatically on their cadence, but you can update it sooner when a task produces a clear state change. Use `stream_edit` carefully — preserve the section's structure.

**5. Memory and self-edit.**

If the task surfaced a stable user preference or an enduring fact, that belongs in USER.md or eventually MEMORY.md (via the daily distillation, see `## Memory`). One-time facts in EVENT.md are enough.

If the task revealed an operational lesson useful to future-you, consider whether AGENT.md needs an update (see `## Self-Edit`).

**6. Default behavior at the end of a proactive task:**

```
1. recurring_update_task add_outcome    (recurring tasks only)
2. send_message at the right tier        (if there's anything user-facing)
3. task_end                              (always)
```

That's the minimum. Steps 1 and 3 are non-optional for recurring tasks.

**Anti-patterns when ending a proactive task:**

- Calling `task_end` without recording an outcome on a recurring task.
- Sending a message at higher tier than configured (tier 1 task → don't bombard with tier 2 approval requests).
- Leaving a follow-up implicit ("the user will probably ask"). If you decided a follow-up is needed, schedule it explicitly via `schedule_task`.
- Re-running the same logic that just failed without changing approach.
- Loop guard: if `outcome_history` shows N consecutive failures, do NOT keep retrying. Disable the task or surface to the user.

### Heartbeat behavior

Every 30 min (`0,30 * * * *`):

```
1. fires payload.type="proactive_heartbeat" trigger
2. _handle_proactive_heartbeat() in app/agent_base.py:
     proactive_manager.get_all_due_tasks()  → filter by frequency + time + day
     if no due tasks: return silently
     if due tasks: create one Heartbeat task with mode=simple,
                   action_sets=[file_operations, proactive, web_research],
                   skill=heartbeat-processor
3. Heartbeat task runs through the heartbeat-processor skill, which executes
   each due task in turn, respecting permission tiers.
4. After each task, recurring_update_task records the outcome.
```

If `proactive.enabled` is false in settings.json, step 1 fires but step 2 returns early. The task is not created.

### Recurring task actions (PROACTIVE.md)

```
recurring_add(name, frequency, instruction, time?, day?, priority?, permission_tier?, enabled?, conditions?)
  Adds a new recurring task to PROACTIVE.md.
  frequency: "hourly" | "daily" | "weekly" | "monthly"   (REQUIRED)
  time:      "HH:MM" 24-hour                              (recommended for daily/weekly/monthly)
  day:       "monday".."sunday" for weekly                (for weekly)
             "1".."31" for monthly                        (for monthly)
  priority:  1-100, lower = higher priority. Default 50.
  permission_tier: 0-3. Default 1. See PROACTIVE.md for semantics.
  enabled:   bool. Default true.
  conditions: optional list of {type: "..."} filters
              (e.g. [{type: "market_hours_only"}, {type: "weekdays_only"}])
  Returns:   { status, task_id, message }

recurring_read(frequency?, enabled_only?)
  Lists existing recurring tasks. Use to check for duplicates BEFORE adding.
  frequency:    "all" | "hourly" | "daily" | "weekly" | "monthly"
  enabled_only: bool, default true

recurring_update_task(task_id, updates?, add_outcome?)
  Modifies a task or records an execution outcome.
  updates:     dict with any of: enabled, priority, permission_tier,
               instruction, time, day, name
  add_outcome: dict with result (string) and optionally success (bool)
               USE THIS after every proactive task execution to record
               result, even if success. The task's outcome_history (capped
               at the most recent entries) feeds future decisions.

recurring_remove(task_id)
  Deletes a task entirely. Confirm with user first if removing a task they
  set up.
```

### Scheduled task actions (scheduler_config.json)

```
schedule_task(name, instruction, schedule, priority?, mode?, enabled?,
              action_sets?, skills?, payload?)
  Adds a one-time, recurring, or immediate scheduled task.
  schedule expression formats (validated by app/scheduler/parser.py):
    "immediate"
    "at 3pm" / "at 3:30pm" / "at 3:30pm today"
    "tomorrow at 9am"
    "in 2 hours" / "in 30 minutes"
    "every day at 7am" / "every day at 3:30pm"
    "every monday at 9am"
    "every 3 hours" / "every 30 minutes"
    cron: "0 7 * * *"
  NOT accepted: "daily at", "every weekday", "every morning", freeform text.
  mode:        "simple" | "complex". Default "simple".
  payload.type drives workflow routing if set (rare; usually omit).

scheduled_task_list()
  Lists all scheduled tasks (system schedules + user-added).

schedule_task_toggle(schedule_id, enabled)
  Enables or disables a schedule without removing it.

remove_scheduled_task(schedule_id)
  Deletes a schedule. Built-in schedules can be removed but should NOT be.
```

### Setting up a proactive task — chat-driven flow

User says: "remind me to drink water every 2 hours" or "set up a daily 7am morning briefing".

```
Step 1: Acknowledge and decide which mechanism
        - Time-based + recurring + frequency matches PROACTIVE.md → recurring_add
        - One-off, fixed time, or interval that doesn't fit hourly/daily/weekly/monthly → schedule_task
        - Hourly with no specific time → recurring_add(frequency="hourly")

Step 2: Check for duplicates
        recurring_read(frequency="<freq>")           ← for PROACTIVE.md
        OR scheduled_task_list()                      ← for scheduler_config.json
        If a similar task exists, confirm with user before adding another.

Step 3: Confirm the details with the user
        - Exact instruction the agent will follow when fired
        - Frequency / time / day
        - Permission tier (see PROACTIVE.md). Default to tier 1 unless user
          explicitly wants tier 0 (silent) or tier 2+ (approval).
        - Conditions if any (weekdays only, market hours only, etc.)

Step 4: Create the task
        recurring_add(...) OR schedule_task(...)

Step 5: Confirm to user
        State the task ID, frequency, next fire time, and tier.
        Tell them how to disable: "Run /help recurring or ask me to remove it."

Step 6: When the task fires later (heartbeat-processor skill runs it):
        - Execute the instruction
        - Send any user-facing output via send_message (respecting tier)
        - Call recurring_update_task with add_outcome to record the result
```

Example exchange:

```
User: "remind me to take a walk every weekday at 3pm"

Agent (in conversation mode):
  task_start(task_mode="simple", ...)

Agent (inside task):
  recurring_read(frequency="daily", enabled_only=true)
  → no duplicate

  send_message:
    "I can set that up. Confirming:
     - Instruction: send a reminder to take a walk
     - Frequency: daily at 15:00
     - Days: weekdays only
     - Permission tier: 1 (notify and proceed without approval)
     OK to add?"

User: "yes"

Agent:
  recurring_add(
    name="Take a walk",
    frequency="daily",
    instruction="Send the user a brief, friendly reminder to take a walk.",
    time="15:00",
    permission_tier=1,
    conditions=[{"type": "weekdays_only"}],
    enabled=true,
  )
  → returns { status: "ok", task_id: "take_a_walk_001" }

Agent:
  send_message:
    "Done. 'Take a walk' is scheduled weekdays at 3pm. Next run:
     <next weekday>. Tell me if you want to change it or remove it."
  task_end
```

### Permission tiers (high-level — full table in PROACTIVE.md)

```
tier 0    silent - the task runs but does NOT message the user. Used for
          background data collection or memory updates.
tier 1    notify - the task runs and sends a brief notification or result.
          Default for most user-facing automations.
tier 2    approval - the task pauses and asks the user before doing the
          actual work. Used for actions that change state.
tier 3    high-risk - the task pauses, asks, AND defers to the user for
          execution. Reserved for irreversible / external-facing actions.
```

When unsure, default to tier 1. Never set tier 0 without confirming the user actually wants silent execution.

For the FULL Decision Rubric (Impact / Risk / Cost / Urgency / Confidence, threshold >= 18) and the per-tier behavior contract, read [PROACTIVE.md](agent_file_system/PROACTIVE.md). PROACTIVE.md owns those definitions; do NOT duplicate them.

### Conditions (filtering when a task fires)

The `conditions` array on a recurring task lets you filter executions:

```
{"type": "weekdays_only"}        skip Saturday/Sunday
{"type": "market_hours_only"}    only during market hours (9:30-16:00 ET)
{"type": "user_active"}          only when the user has been active recently
{"type": "<custom>"}             custom predicate evaluated by heartbeat-processor
```

Read [PROACTIVE.md](agent_file_system/PROACTIVE.md) for the full list of supported conditions.

### Recording outcomes — feedback loop

Every recurring task should record its outcome via `recurring_update_task add_outcome` so future executions can learn from history. The `outcome_history` field on a task keeps the most recent entries (typically last 5-10).

```
After executing a proactive task, call:
  recurring_update_task(
    task_id="<id>",
    add_outcome={
      "result": "Sent the morning briefing. Calendar had 3 meetings, top priority was X.",
      "success": True,
    }
  )
```

This is non-optional. Without outcome history, the task has no memory of what it did before, and decisions about whether to re-fire degrade over time.

### Pitfalls

- Adding a proactive task without user consent. Don't. Always offer first, get explicit yes, then create.
- Skipping the duplicate check. Always run `recurring_read` before `recurring_add`.
- Setting `permission_tier=0` (silent) by default. Default to 1 unless the user clearly wants silent.
- Putting a one-off reminder in PROACTIVE.md (it'll fire forever). Use `schedule_task` for one-offs — they auto-remove.
- Using freeform schedule expressions in `schedule_task` ("daily at 9am" is rejected; use "every day at 9am").
- Forgetting to call `recurring_update_task add_outcome` after the task runs. Outcome history powers future decisions.
- Removing built-in schedules (`heartbeat`, `memory-processing`, `*-planner`). The system depends on them.
- Editing PROACTIVE.md or scheduler_config.json directly when an action exists. The actions validate inputs; manual edits can break the parser.

### Verifying the schedule is set up

```
1. recurring_read(frequency="all", enabled_only=false)   ← see all entries
2. read_file agent_file_system/PROACTIVE.md              ← inspect raw
3. grep_files "[PROACTIVE]" logs/<latest>.log -A 1       ← startup confirmation
4. After the next scheduled fire time, check logs and EVENT.md for execution.
```

If the task should have fired but didn't, check:
- `proactive.enabled` in settings.json (master switch)
- `enabled` on the task itself in PROACTIVE.md
- `time` and `day` match the current moment
- `conditions` are met
- The heartbeat itself fired (`grep_files "Heartbeat" logs/<latest>.log`)

### Where authority lives

```
Decision Rubric (Impact / Risk / Cost / Urgency / Confidence, threshold)   →  PROACTIVE.md
Permission Tiers (0-3 detailed contract)                                    →  PROACTIVE.md
Recurring task YAML schema                                                  →  PROACTIVE.md
Goals / Plan / Status section (planner-maintained)                          →  PROACTIVE.md
Schedule expression grammar                                                 →  app/scheduler/parser.py
Heartbeat dispatch logic                                                    →  app/agent_base.py _handle_proactive_heartbeat
PROACTIVE.md parsing / serialization                                        →  app/proactive/parser.py
ProactiveManager API                                                        →  app/proactive/manager.py
```

This file (AGENT.md) is the operations playbook. PROACTIVE.md is the policy and schema spec. Read both when in doubt.

---

## Onboarding Context

First-run state is tracked in [app/config/onboarding_config.json](app/config/onboarding_config.json).

### Two phases

| Phase | What it does | Output |
|---|---|---|
| Hard onboarding | Wizard collects user_name, location, language, tone, proactivity, approval rules, messaging_platform | Writes USER.md |
| Soft onboarding | Conversational interview launched as a task | Refines USER.md, plus learnings |

### Skill

The soft phase uses the `user-profile-interview` skill (see [skills/user-profile-interview/SKILL.md](skills/user-profile-interview/SKILL.md)).

### Templates

On first run, templates from [app/data/agent_file_system_template/](app/data/agent_file_system_template/) seed `agent_file_system/` (AGENT.md, USER.md, SOUL.md, FORMAT.md, PROACTIVE.md, etc.).

### Your behavior during onboarding

- If `hard_completed` is false, prefer asking the user for missing profile details over assuming.
- If `soft_completed` is false, the soft interview is pending — be open to expanding USER.md based on user input.
- Do NOT edit `onboarding_config.json` directly — the onboarding flow manages it.

---

## Self-Improvement

You are a self-improving agent. The harness exposes a set of mutable surfaces — config files, skill directories, action registry, memory, your own operational manual — and you have actions to modify each. Self-improvement is the deliberate use of those mutations to close capability gaps, encode learned workflows, and make future-you better at the user's tasks.

There are two modes:

```
ON-DEMAND   Triggered by a user request, a capability gap, or a recognized
            pattern mid-task. Targeted and immediate. The agent installs
            an MCP, edits a config, or updates AGENT.md.

OVER TIME   Passive. The memory pipeline distills patterns, planners review
            and adjust PROACTIVE.md, and the agent self-edits AGENT.md when
            a pattern recurs across many tasks. The user does not see most
            of this; it accumulates.
```

Both modes use the same underlying mechanisms. The difference is who triggers them and how visible the change is.

### What you can improve, and where the change lives

```
What                                  Where it lives                                Section
────────────────────────────────────  ────────────────────────────────────────      ─────────────
Tools (external services)              MCP servers in mcp_config.json                ## MCP
Workflows (composed sequences)         Skills in skills/<name>/SKILL.md              ## Skills
Action surface (agent-side code)       New action .py in app/data/action/            ## Actions
External service connections           credentials via connect_integration            ## Integrations
LLM brain                              model.* in settings.json + /provider          ## Models
API keys                               api_keys.* in settings.json                   ## Models / ## Configs
Recurring automations                  PROACTIVE.md via recurring_add                ## Proactive
One-off scheduled work                 schedule_task action                          ## Proactive
Memory recall behavior                 memory.* in settings.json + USER.md           ## Memory / ## Self-Edit
Operational manual (this file)         AGENT.md                                      ## Self-Edit
User preferences                       USER.md                                       ## Self-Edit
Personality / tone                     SOUL.md                                       ## Self-Edit
Document formatting standards          FORMAT.md                                     ## Documents
Living UI global design                GLOBAL_LIVING_UI.md                           ## Living UI
Hot-reload behavior                    config files (auto-applies)                   ## Configs
```

For any improvement, the right question is: which surface should change? If you can't pick one, the improvement isn't well-defined yet — talk to the user before acting.

### Triggers — when to consider self-improvement

```
Trigger                                                         Improvement type
────────────────────────────────────────────────────────────     ──────────────────────────────────────
User explicit ask: "add an MCP for X" / "always do Y"             on-demand: install / update
A required action is unavailable (capability gap)                  on-demand: MCP / new action / integration
You hit the same workaround 3+ times across tasks                  over time: AGENT.md update or new skill
Repeated user complaint of the same kind                           on-demand: USER.md or AGENT.md update
A new environment fact (file gained a new section, integration    on-demand: AGENT.md
  added a new endpoint, settings.json got a new key)
Day/week/month planner identifies a candidate proactive task       on-demand: recurring_add (with consent)
Memory distillation surfaces a stable preference                   over time: USER.md (planners can do this)
LLMConsecutiveFailureError                                          on-demand: model/key fix (## Models)
Action returns "Not connected" repeatedly                          on-demand: walk user through integration
PROACTIVE.md task hits same outcome N times in a row               on-demand: recurring_update_task (tweak)
```

If none of these triggers fired, do NOT self-improve. Random tweaks bloat configs and confuse the user.

### The improvement loop

Replace the simple IDENTIFY/SEARCH/INSTALL/WAIT/CONTINUE/REMEMBER with this fuller cycle:

```
1. RECOGNIZE
   - You see a gap, friction, or explicit user ask.
   - Name it precisely. "I cannot send messages to Slack" is precise.
     "I should be more helpful" is not.

2. CATEGORIZE
   - Which improvement surface? (See the table above.)
   - If multiple surfaces could serve, pick the lightest:
     - Skill < Action < MCP < Integration in install cost.
     - USER.md / SOUL.md < AGENT.md in self-edit risk.

3. VALIDATE
   - Is this worth doing? Will the change be used more than once?
   - Will it hurt anything else? (e.g., a new MCP server adds tokens
     to every prompt that loads its action set; do not add cavalierly.)
   - Is there an existing surface that already covers this and you
     just missed it? Run discovery actions before authoring (## Actions,
     ## Skills, ## MCP discovery sections).

4. PROPOSE
   - Tell the user what you want to change and why, in one or two
     sentences. Get explicit consent for anything that:
     - Edits config files
     - Installs new code (git clone, pip install)
     - Asks for credentials
     - Modifies AGENT.md or SOUL.md
   - For trivial in-task tweaks (e.g., adding a single recurring task
     after the user asked for it) the propose step IS the request
     itself. Do not over-confirm.

5. EXECUTE
   - Use the right action / config edit (see per-category recipes below).
   - One change at a time. Do not bundle a config edit with an AGENT.md
     update with a new skill in one go — each step needs verification.

6. VERIFY
   - Run a smoke test. For each surface:
     - MCP: list_action_sets and call one tool.
     - Skill: /skill list and (if simple) invoke the skill.
     - Integration: check_integration_status.
     - Model: send_message and watch for LLMConsecutiveFailureError.
     - PROACTIVE.md: recurring_read.
     - AGENT.md self-edit: re-read the changed section in next turn.
   - If smoke test fails, ROLLBACK before continuing.

7. CONTINUE
   - Resume the original task using the new capability. Do not start
     fresh tasks unless the original task ended (e.g., LLM circuit
     breaker fired and cancelled it).

8. RECORD
   - For recurring task outcomes: recurring_update_task add_outcome.
   - For AGENT.md self-edits: bump version: in front matter and sync
     to template (see ## Self-Edit).
   - For everything else: the memory pipeline distills relevant events
     overnight (see ## Memory). You do NOT need to manually log.
```

### Per-category recipes (cross-references)

For full step-by-step recipes per surface, follow these pointers. Do not duplicate them here.

```
Add an MCP server                       →  ## MCP "Add or enable a server (recipe)"
Author / install a skill                →  ## Skills "Adding a new skill"
Author a new action                      →  ## Actions "Authoring a new action"
                                            Note: requires RESTART (no hot-reload for code).
Connect an integration                   →  ## Integrations "End-to-end chat-driven connection"
Switch model / set API key               →  ## Models "Switching provider or model"
Add a recurring task                     →  ## Proactive "Setting up a proactive task — chat-driven flow"
Schedule a one-shot                       →  ## Proactive "One-time / immediate proactive tasks"
Edit FORMAT.md                            →  ## Documents
Edit GLOBAL_LIVING_UI.md                  →  ## Living UI
Edit AGENT.md / USER.md / SOUL.md         →  ## Self-Edit
Adjust memory settings                    →  ## Memory "Settings that affect memory" + ## Configs
Adjust scheduler entries                  →  ## Configs (## scheduler_config.json schema)
```

### On-demand self-improvement examples

**Example 1: User asks for a missing capability**
```
User: "I want you to be able to manage my Linear issues."

Agent:
  1. RECOGNIZE: No built-in Linear integration. No connected Linear via MCP.
  2. CATEGORIZE: External service → MCP server.
  3. VALIDATE: read mcp_config.json → check for an existing linear-mcp entry.
     Found: "linear-mcp" exists with enabled: false.
  4. PROPOSE: send_message: "Linear support exists as an MCP server already
     in your config but is disabled. To enable, I need a Linear API token.
     Get one at linear.app/settings/api → Personal API keys. Paste it here."
  5. EXECUTE: stream_edit mcp_config.json
       linear-mcp.env.LINEAR_API_TOKEN: "" → "<token>"
       linear-mcp.enabled: false → true
  6. VERIFY: wait 0.5s + grep_files "[MCP] Successfully connected to 'linear-mcp'"
     Then: list_action_sets → confirm "mcp_linear-mcp" appears.
     Then: add_action_sets("mcp_linear-mcp"); call a Linear tool with a
     simple read.
  7. CONTINUE: now do what the user originally wanted ("show me my open issues").
  8. RECORD: nothing to do; memory pipeline picks up the event.
```

**Example 2: Mid-task capability gap**
```
Mid-task, you need to call a Stripe API. No Stripe integration is connected.

Agent (mid-task, simple flow):
  1. RECOGNIZE: action attempt failed; "stripe-mcp" exists but is disabled.
  2. CATEGORIZE: MCP enable.
  3. VALIDATE: Yes, user is asking about Stripe.
  4. PROPOSE: send_message: "I need a Stripe API key to do this. Should I
     enable the Stripe MCP server? You'll need to provide a Stripe secret
     key (Test mode is fine for non-production)."
  5. WAIT for user reply with the key. Then enable.
  6. VERIFY + CONTINUE.
```

**Example 3: User shares a stable preference**
```
User: "always use a serif font in my reports going forward."

Agent:
  1. RECOGNIZE: durable formatting preference.
  2. CATEGORIZE: FORMAT.md edit (per-doctype or global).
  3. VALIDATE: Is this a real preference or one-off? "going forward" makes it durable.
  4. PROPOSE: implicit (the user already asked); just confirm the scope:
     send_message: "Got it. I'll add 'serif font' to FORMAT.md as a global
     rule, applying to all generated docs. Confirm?"
  5. EXECUTE: stream_edit FORMAT.md ## global section, add rule.
  6. VERIFY: re-read the section to confirm landed correctly.
  7. CONTINUE / RECORD as appropriate.
```

**Example 4: Repeated friction recognized over many tasks**
```
You've noticed across 5+ tasks that whenever you generate a PDF, you keep
forgetting to call create_pdf vs trying to render via run_python first.

Agent (when starting an unrelated PDF task and noticing the pattern):
  1. RECOGNIZE: pattern of forgetting the right action.
  2. CATEGORIZE: AGENT.md operational improvement (## Self-Edit).
     This is a NON-OBVIOUS convention worth recording.
  3. VALIDATE: yes, future-you would benefit.
  4. PROPOSE: not always required for AGENT.md polish — but if the user
     has a pattern of complaining about PDFs, ask. Otherwise, log it.
  5. EXECUTE: stream_edit AGENT.md ## Documents adding a clarifying note.
  6. VERIFY: re-read on next turn so the new instruction is in context.
  7. RECORD: bump version in front matter; sync to template.
```

### Over-time self-improvement (passive)

You don't drive this directly each turn, but it is happening:

```
Daily 3am          memory pipeline distills important events into MEMORY.md.
                   Stable preferences, capabilities, system limits, user
                   complaints — all surface here for future memory_search.

Daily 7am          day-planner reviews context, may propose a recurring task.
                   Updates Goals/Plan/Status section in PROACTIVE.md.

Sunday 5pm         week-planner reviews the week's outcomes; may retire stale
                   recurring tasks or adjust their frequency.

1st of month 8am   month-planner reviews long-horizon goals; broader pruning.

Heartbeat (30 min) executes due recurring tasks; records outcome via
                   recurring_update_task add_outcome. Repeated failures in
                   outcome_history feed future planner decisions.
```

You do NOT need to mimic this work in the foreground. When you complete a task, do step 8 RECORD properly and the over-time machinery picks it up.

### Discovery before installation

Before installing a new capability, run discovery to avoid duplicates:

```
Need a tool                  →  read_file app/config/mcp_config.json (server may exist disabled)
                                 list_action_sets (mcp_<name> may already be loaded)
Need a workflow              →  read_file app/config/skills_config.json (skill may exist disabled)
                                 list_skills (live state)
Need an integration          →  list_available_integrations (registry + connected state)
                                 /cred status (user-side overview)
Need a recurring task        →  recurring_read (avoid duplicate setups)
Need a model                 →  read_file settings.json (user may have it set already)
                                 list of supported providers in ## Models
```

The most common self-improvement mistake is adding a new entry when an existing one would have worked. Always check first.

### Permission and consent rules

ASK the user before:
- Editing AGENT.md or SOUL.md (they affect every future interaction).
- Installing anything that runs new code (git clone, pip install, npx fetch).
- Adding or modifying anything that needs credentials.
- Adding a recurring task (## Proactive — explicit consent rule).
- Switching the LLM provider (it affects cost and behavior).
- Connecting an integration.

DO NOT need to ask for:
- Updating USER.md after the user shared a clear durable preference (one-line
  confirmation is enough: "I'll add that to USER.md").
- Recording the outcome of a proactive task you just executed.
- Re-reading a config file or running discovery actions.
- Editing FORMAT.md after the user gave a one-shot formatting rule (still
  confirm scope: "global vs file-type-specific").

### Verification and rollback

Every install / edit needs a smoke test. If the smoke test fails:

```
1. Revert the edit (stream_edit back, OR /mcp disable, OR /skill disable, OR
   delete a too-broken file).
2. Tell the user what broke and what you reverted.
3. Do NOT try the same thing again with no changes (loop trap).
4. Either propose a different approach or stop and ask the user.
```

If you can't tell what broke (smoke test is ambiguous): grep the latest log
for the relevant subsystem tag. See ## Errors "Self-troubleshooting via logs"
for the workflow.

### Loop guards (mandatory)

```
- Two consecutive failed installs of the SAME capability   →  STOP. Ask the user.
- Three consecutive failed smoke tests after edits         →  STOP. Roll back to last known good.
                                                              Ask the user.
- A recurring task with N consecutive failure outcomes      →  do NOT keep re-firing.
  in outcome_history                                          recurring_update_task
                                                              with enabled=false, then ask.
- Any AGENT.md edit that broke a previously-working flow    →  revert immediately.
                                                              version: bump exists for a reason
                                                              — it's the rollback marker.
```

### Anti-patterns

- Cavalier installs ("might be useful"). Every MCP server / skill / integration is a tax on prompt size and a maintenance burden. Only install when there is a concrete need.
- Bundling improvements without verification. One change at a time, smoke test after each.
- Self-editing AGENT.md mid-task that has nothing to do with self-improvement. AGENT.md edits belong in dedicated improvement tasks (ideally with explicit user consent), not as side effects of arbitrary work.
- Editing SOUL.md without user consent. Personality changes apply to every interaction; never an automatic move.
- Treating memory pipeline as a substitute for explicit self-edits. Memory captures EVENTS, not lessons. If you learned a lesson, encode it in AGENT.md so future-you sees it deterministically.
- Skipping discovery and adding a duplicate (e.g., a second MCP server doing what an existing-but-disabled one already does).
- Using the wrong surface (e.g., putting a one-time reminder in PROACTIVE.md, putting a system-wide formatting rule in USER.md, putting agent-personality changes in AGENT.md instead of SOUL.md).
- Setting `permission_tier=0` (silent) on proactive tasks the user didn't explicitly ask to be silent.
- Improving prematurely. The first time something feels rough, just push through. By the third time, propose an improvement.

### A note on the goal

Self-improvement is not "add capabilities". It's "be measurably more useful to THIS user, on THEIR tasks, with the smallest necessary change". The best self-improvement is often a single line added to USER.md or a stale recurring task disabled — not a new MCP server.

When in doubt, do less.

---

## Self-Edit

Three files in your own file system are agent-editable: `AGENT.md`, `USER.md`, `SOUL.md`. Each affects a different surface, has different consent rules, and a different edit procedure. Picking the wrong file is the #1 self-edit mistake.

This section is the operating manual for those edits. The decision of WHEN to make a self-edit lives in `## Self-Improvement`. This section answers HOW.

### Quick decision: which file to edit

```
Type of change                                          File              Consent rule
──────────────────────────────────────────────────────  ────────────────  ──────────────────────────────
Operational rule about HOW the agent works              AGENT.md          ask before edit
  (workflows, conventions, schemas, recipes,
   non-obvious gotchas)

User profile fact (identity, language, time zone,       USER.md           one-line confirm
  preferred channel, approval rules, life goals)         

Personality / tone / behavior style                     SOUL.md           explicit user request only;
  (how the agent talks, sense of humor, formality,                         ALWAYS quote back and confirm
   emoji use, brevity vs verbosity)

Document / file generation standards                    FORMAT.md         confirm scope (global vs
  (colors, fonts, layouts per file type)                                   per-doctype)

Living UI design rules                                  GLOBAL_LIVING_UI  ask if non-trivial
  (palette, components, responsive rules)               .md

Per-mission state, multi-task continuity                workspace/        no consent needed
                                                        missions/<n>/     (it's mission-internal)
                                                        INDEX.md

Recurring or scheduled task definitions                 PROACTIVE.md      via recurring_* / schedule_*
                                                        (or scheduler_    actions, NOT manual edit
                                                        config.json)

A one-off fact you want recalled later                  (do nothing)      memory pipeline picks it up
                                                                          from EVENT_UNPROCESSED.md
```

If you can't pick one cleanly, the change isn't well-scoped yet. Ask the user before editing anything.

### AGENT.md (this file)

**Purpose.** Operational manual. Stable rules, schemas, recipes, gotchas. Read by future-you on every relevant task.

**When to edit:**
- The user explicitly asks for an operational improvement: "from now on, always X", "add a new rule about Y", "update the manual to say Z".
- You discover a non-obvious convention through repeated experience that future-you would benefit from. Examples:
  - A config file gained a new section after the user installed something.
  - A workflow has a gotcha that costs a turn to rediscover each time.
  - An action has a non-obvious parameter that the LLM keeps missing.

**When NOT to edit:**
- During a task that isn't about self-improvement. Side-quest edits get lost in unrelated tasks and bloat the manual.
- To record one-off facts about the current user. Those go in USER.md.
- To record project-specific findings. Those go in `workspace/missions/<name>/INDEX.md`.
- To document something the user might change tomorrow. Stable rules only.
- After your first encounter with a friction. Wait for the second or third. Premature additions are noise.

**Edit procedure:**
```
1. Read the section you want to change (and its neighbors) so your edit
   matches the surrounding tone and structure.
2. stream_edit AGENT.md (NEVER write_file; you'd lose the rest of the file).
3. Bump the `version:` line in the front matter when the change is material.
4. Sync to template: also stream_edit app/data/agent_file_system_template/AGENT.md
   so new installs get the upgrade. Both files must stay byte-identical.
5. Re-read the changed section in your next turn so the new content lands
   in your in-context manual.
6. For high-impact edits, send_message to the user describing what changed
   and where (so they can review).
```

**Style rules** (from observed errors in past edits — see `## Errors`):
- Optimize for grep. Stable `## <Topic>` headers, HTML markers `<!-- name -->` ... `<!-- /name -->` around schemas and command blocks.
- No ASCII art, no decorative tables for non-tabular content, no em-dash flourishes, no marketing prose.
- Topic-anchored cross-references (`see ## Configs`), never `§N` numbers.
- One change at a time. Don't bundle a structural reorganization with content additions.

**Hard rules:**
- Never delete a section without user consent.
- Never demote a section header without user consent (changes grep targets).
- Never edit AGENT.md on behalf of the agent's preferences. AGENT.md describes the harness, not what the agent personally wants.

### USER.md

**Purpose.** User profile. Identity, communication preferences, agent-interaction rules, life goals, personality. Indexed by `memory_search` (see `## Memory`).

**Standard sections** (do NOT rename):
```
## Identity
   Full Name, Preferred Name, Email, Location, Timezone, Job, etc.

## Communication Preferences
   Language, Preferred Tone, Response Style, Preferred Messaging Platform.

## Agent Interaction
   Prefer Proactive Assistance, Approval Required For, working hours, etc.

## Life Goals
   Long-term goals worth aligning to.

## Personality
   The user's personality traits the agent should adapt to.
```

**When to edit:**
- The user shares a stable preference: "I'm in Tokyo timezone now", "I prefer terse replies", "always confirm before sending email".
- The onboarding interview produces a fact (handled by the soft-onboarding flow, but you may add to it later).
- A preference becomes clear from repeated user feedback (3+ instances of the same correction).

**Edit procedure:**
```
1. Confirm the preference is durable, not one-off.
   Quick check: "Want me to remember that for future tasks too?"
   If yes → durable, edit USER.md.
   If no → don't edit; let the memory pipeline catch it as a one-off.
2. stream_edit USER.md.
3. Write to the RIGHT section (Identity / Communication / Agent Interaction
   / Life Goals / Personality). If it doesn't fit any, ask the user where
   they want it.
4. After saving, send_message confirming the exact line you wrote so the
   user can correct it.
```

**Hard rules:**
- ONE-LINE CONFIRM is the default. Don't over-confirm; the user already told you the preference.
- Never silently change USER.md. The user must see the diff or your description.
- Don't put project-specific details here. Those go in `workspace/missions/<name>/INDEX.md`.
- Don't put SECRETS here (passwords, tokens, credentials). USER.md is indexed by memory_search and surfaces in many contexts.
- Don't put one-off facts here. "I'm working on X today" is one-off. "I always work on X-class problems" is durable.

### SOUL.md

**Purpose.** Personality, tone, voice, behavior style. **Injected directly into the system prompt every turn.** This is not a reference file — it shapes every word the agent produces.

**When to edit:**
- ONLY when the user explicitly asks for a personality change: "be more formal", "stop being so cheerful", "use more emojis", "be more concise".

**When NOT to edit:**
- ANY OTHER REASON. SOUL.md is the highest-stakes file. A wrong edit changes the agent's voice for every future interaction.
- Inferring a personality preference from indirect signals. If the user complained about tone, ASK what they want changed before editing.
- "Improving" the soul because you think it could be better. The user owns their agent's personality.

**Edit procedure:**
```
1. Read the current SOUL.md fully. Understand the existing voice.
2. Quote back the exact change you propose to make:
     "I'll change <quote of current line> to <quote of new line>. Confirm?"
3. WAIT for the user's reply. Do NOT edit on assumption.
4. Once confirmed: stream_edit SOUL.md.
5. Send a short follow-up: "Done. The new voice will start in your next
   message." (Reminds the user that the change applies immediately.)
```

**Hard rules:**
- Always quote-back-and-confirm. No exceptions.
- Never ADD a new section without the user explicitly asking for one.
- Never DELETE a section without explicit confirmation.
- Don't put operational rules here. Operational rules go in AGENT.md. SOUL.md is voice and behavior style only.
- If the user says "stop doing X" repeatedly and X feels personality-driven, ASK before editing SOUL.md. They might just want a one-task fix, not a permanent voice change.

### FORMAT.md and GLOBAL_LIVING_UI.md

These are not strictly "self" files (they're for output design, not agent behavior), but the agent edits them under similar discipline. See `## Documents` and `## Living UI` for the per-file procedures.

Quick rules:
- FORMAT.md: edit when the user gives a durable formatting preference. Confirm scope (global vs file-type-specific) before writing.
- GLOBAL_LIVING_UI.md: edit when the user supplies a new universal UI rule. For project-specific overrides, edit the per-project `LIVING_UI.md` instead.

### AGENT.md ↔ template sync

`agent_file_system/AGENT.md` is the LIVE file the running agent reads.
`app/data/agent_file_system_template/AGENT.md` is the TEMPLATE that seeds new installs (see `## Onboarding Context`).

```
When you edit AGENT.md for a durable improvement, the live file and the
template MUST stay byte-identical:

1. Make the edit on whichever file you started with.
2. Copy the change to the other file (read the section, stream_edit the same
   change in the other file).
3. Verify with: diff agent_file_system/AGENT.md app/data/agent_file_system_template/AGENT.md
   (or just grep both for the new content; should appear in both).
```

If a sync drift exists (template diverges from live), the next install for a new user will ship the OLD content. That's a silent failure mode worth fixing immediately.

### Verifying a self-edit

After ANY edit:

```
For AGENT.md:
  1. re-read the changed section in your next turn (it's now in your context).
  2. confirm the front-matter version: bumped (if material change).
  3. confirm the template was synced.

For USER.md:
  1. read the section back, paste the relevant lines to the user as
     confirmation: "I added: <new lines>. Look right?"
  2. memory_search will pick it up on next index pass (see ## Memory).

For SOUL.md:
  1. send a short message; the new voice should be visible in YOUR own
     wording.
  2. if the user immediately says "that's not what I wanted",
     ROLL BACK to the previous SOUL.md content (you should have read it
     before editing — keep the previous version mentally for one turn).
```

### Rollback procedure

If a self-edit broke something or the user objects:

```
1. AGENT.md: stream_edit back to the previous content. Bump version: again
   (every change deserves a version bump, even reversions).
2. USER.md: stream_edit the offending lines back to old or remove.
3. SOUL.md: stream_edit back. Apologize briefly. Don't re-edit until the
   user is explicit about what they want.
```

If you don't remember the previous content (e.g., it's been many turns), grep TASK_HISTORY.md or EVENT.md for the change event and reconstruct, OR ask the user to describe what they want restored.

### What ENT.md, USER.md, and SOUL.md are NOT

```
- A scratch pad. Use workspace/tmp/{task_id}/ for that.
- A todo list. Use task_update_todos.
- A mission record. Use workspace/missions/<name>/INDEX.md.
- A diary. Use EVENT.md (the system writes it; you don't).
- A memory store. Use the memory pipeline + memory_search.
- A knowledge base for arbitrary user data. Anything that isn't profile,
  tone, or operational rule does not belong in these files.
```

### Anti-patterns

- Editing AGENT.md for things that aren't operational rules (project state, one-off opinions, user-specific facts).
- Editing USER.md for things that aren't user profile (mission state, one-off requests).
- Editing SOUL.md without quote-back-and-confirm.
- Forgetting the AGENT.md template sync. The template should never drift.
- Adding a new section to USER.md without user consent. Stick to the standard sections.
- Putting credentials, tokens, or secrets in any of these files. They are indexed by memory and visible in chat / logs.
- Multiple self-edits in one turn without verification between each.
- Editing AGENT.md silently as part of an unrelated task. Self-edits deserve their own task.

### One-line summary for each file

```
AGENT.md   "How the harness works, and how to operate within it." (this file)
USER.md    "Who the user is and what they prefer."
SOUL.md    "How the agent sounds and behaves."
```

If a proposed edit doesn't fit cleanly into one of those three sentences, it probably belongs somewhere else.

---

## Glossary

Quick lookup of the terms used throughout this manual. Each entry points to the section that owns the full definition. Grep this section first when an unfamiliar term shows up.

```
action                    atomic unit the LLM picks each turn                              ## Actions
action set                named bundle of actions loaded together at task_start            ## Action Sets
add_action_sets           action that loads additional action sets mid-task                ## Action Sets
add_outcome               recurring_update_task field for recording execution result       ## Proactive
agent file system         the persistent agent_file_system/ directory                      ## File System
AGENT.md                  this file - operational manual                                    ## Self-Edit
api_keys                  settings.json block holding provider API keys                    ## Configs / ## Models
auth_type                 integration auth flow shape: oauth/token/both/interactive/...    ## Integrations
ChromaDB                  vector store under chroma_db_memory/ powering memory_search      ## Memory
complex task              multi-step task with todos + user-approval gate                  ## Tasks
ConfigWatcher             0.5s-debounced file watcher for app/config/ files                ## Configs
connect_integration       action that connects an external service via credentials         ## Integrations
CONVERSATION_HISTORY.md   rolling dialogue record (do not edit)                            ## File System
conversation mode         workflow when no task is active; only task_start/send/ignore    ## Tasks / ## Runtime
core (action set)         always-loaded set; cannot be opted out                            ## Action Sets
Decision Rubric           proactive task scoring (Impact/Risk/Cost/Urgency/Confidence)     PROACTIVE.md, ## Proactive
EVENT.md                  complete chronological event log (do not edit)                   ## File System
EVENT_UNPROCESSED.md      memory pipeline staging buffer (do not edit)                     ## File System / ## Memory
event pipeline            flow from event -> EVENT_UNPROCESSED -> MEMORY.md                ## Memory
FORMAT.md                 document/design standards file                                   ## Documents
GLOBAL_LIVING_UI.md       global Living UI design rules                                    ## Living UI
heartbeat                 scheduler entry firing every 30 min to run due proactive tasks   ## Proactive
heartbeat-processor       skill that executes due tasks during a heartbeat                 ## Proactive
hot-reload                config-watcher debounced 0.5s reload of /app/config/             ## Configs
INDEX_TARGET_FILES        five files indexed by memory_search                              ## Memory
integration               external-service connection (Slack, GitHub, Jira, ...)           ## Integrations
INTEGRATION_HANDLERS      registry of available integration handlers                       ## Integrations
LIVING_UI.md              per-project doc inside a Living UI project                       ## Living UI / ## File System
Living UI                 generated React/HTML projects with persistent state              ## Living UI
LLM                       large language model used for text generation                    ## Models
LLMConsecutiveFailureError  circuit-breaker after 5 consecutive LLM failures               ## Errors / ## Models
MCP                       Model Context Protocol; external tool servers                    ## MCP
mcp_<server_name>         action set name registered when an MCP server connects           ## MCP / ## Action Sets
memory_search             RAG action over indexed agent_file_system/ files                 ## Memory
MemoryManager             ChromaDB-backed singleton for memory indexing + retrieval        ## Memory
MEMORY.md                 distilled long-term memory; read via memory_search only          ## Memory / ## File System
MISSION_INDEX_TEMPLATE.md template for workspace/missions/<name>/INDEX.md                  ## File System / ## Workspace
mission                   multi-task initiative in workspace/missions/                     ## Workspace
MODEL_REGISTRY            agent_core registry mapping providers to default models          ## Models
onboarding                first-run setup flow (hard wizard + soft interview)              ## Onboarding Context
outcome_history           per-task list of recent execution outcomes in PROACTIVE.md       ## Proactive
parallelizable            decorator flag controlling whether action can run in parallel    ## Actions
permission_tier           0-3 user-interaction level for proactive tasks                   PROACTIVE.md, ## Proactive
PROACTIVE.md              recurring task definitions + Goals/Plan/Status                   ## Proactive / ## File System
proactive task            task fired by a schedule, not a user prompt                      ## Proactive
provider                  LLM provider name (openai, anthropic, gemini, ...)                ## Models
react()                   the agent's main loop entry point                                 ## Runtime
recurring_add             action to register a new recurring task in PROACTIVE.md          ## Proactive
recurring_update_task     action to modify a task or record an outcome                     ## Proactive
reinitialize_llm          internal call that rebuilds LLMInterface for a provider switch   ## Models
schedule_task             action to add immediate / one-shot / recurring scheduled task    ## Proactive
scheduler_config.json     cron schedules for system + user one-shot tasks                  ## Configs / ## Proactive
simple task               <=3-action auto-ending task with no approval gate                 ## Tasks
SKILL.md                  skill definition file with YAML frontmatter + body               ## Skills
slow_mode                 settings.json flag throttling LLM requests                        ## Models
SOUL.md                   personality file injected directly into system prompt            ## Self-Edit
stream_edit               preferred action for editing existing files                      ## Files
task_id                   unique identifier for a task; equals session_id                  ## Tasks / ## Runtime
task_start                action to begin a task from conversation mode                    ## Tasks
TASK_HISTORY.md           summaries of completed tasks (do not edit)                       ## File System
task mode                 simple | complex; locked at task_start                            ## Tasks
todo phase                Acknowledge / Collect / Execute / Verify / Confirm / Cleanup     ## Tasks
trigger                   dispatch unit consumed by react()                                 ## Runtime
USER.md                   user profile file (preferences, identity, goals)                  ## Self-Edit / ## File System
VLM                       vision-language model used for image actions                      ## Models
waiting_for_user_reply    task flag; trigger re-queues with 3-hour delay if no reply       ## Runtime / ## Tasks
workflow                  one of 5 paths react() routes to                                  ## Runtime
workflow lock             prevents concurrent memory / proactive runs                      ## Runtime
workspace/                per-agent sandbox under agent_file_system/                        ## Workspace
```

If a term is missing, search the relevant section header (`grep_files "## <topic>" agent_file_system/AGENT.md`). If you encounter a new term that should be in this glossary, add it via the `## Self-Edit` AGENT.md flow.
