# Task sessions

CraftBot has no "new chat" button and no command to switch between conversations. Every message you send is routed to the right place automatically. A **session** is one lane of work. A **task** is the work object that lives in that lane. This page explains how routing decides where your message goes, how several tasks run in parallel without stepping on each other, and what a task's life looks like from creation to the entry in its history file.

## Overview
- A **session** starts as just an id. When your message asks for real work, the agent calls `task_start` and the session becomes a **task**. The task's id *is* the session id, so [triggers](triggers.md), the [event stream](event-stream.md), and the temp workspace all key off the same identifier.
- A session with no running task is in **conversation mode**: the agent can only reply, start a task, or deliberately ignore the message.
- Multiple sessions run in parallel. Each has its own trigger, its own event stream, and its own scratch directory, so tasks never leak context into each other.

You never manage any of this. You type, and routing decides.

## How your message finds its session

When a message arrives, CraftBot tries cheap deterministic rules first and asks an LLM only when it has to:

| Rule | Condition | Destination |
|---|---|---|
| 1 | Someone *else* messaged on a connected platform (not you) | No session at all — posted to chat as a notification for you to act on |
| 2 | You clicked **reply** on a specific task's message in the UI | That task, immediately — no LLM call |
| 3 | Reply marker present but the target task is gone | A fresh session (the quoted context travels inside the message) |
| 4 | At least one task is currently active | The routing LLM decides: continue/modify/cancel/answer one of them, or open a new session |
| 5 | Nothing matched | A fresh session |

The rule-4 router sees real context for each running task (name, original instruction, mode, todo progress, the last 10 events, whether it's waiting for your reply, and its platform) plus the recent cross-session conversation. It is deliberately conservative: **when in doubt, it opens a new session** rather than derailing a running task. Even if exactly one task is waiting for a reply, your next message isn't blindly assumed to be the answer. Tasks often park on a final "anything else?", and your next message may be an unrelated request that deserves its own lane.

Before any of this runs, the message is durably parked in the trigger store, so a crash mid-routing can't lose it (see [Triggers](triggers.md)).

!!! note "Implementation files"
    The rule ladder is `_handle_chat_message()` in `app/agent_base.py`. The LLM decision and its context formatting are `SessionRouter` in `app/triggers/router.py`, driven by the `ROUTE_TO_SESSION_PROMPT` template (see [Prompts](prompts.md)).

## Waiting for your reply

When a task asks you something, it flips its `waiting_for_user_reply` flag and stops consuming resources:

- Its trigger re-arms itself in 3-hour hops. Each hop is checked and re-scheduled by the [agent loop](agent-loop.md) without any LLM call. A task can wait for days at zero token cost.
- The moment your answer routes to it (rule 2 or rule 4), the trigger is pulled forward to *now* and the task resumes on the spot, with your message injected into its event stream.
- The router explicitly sees `WAITING FOR REPLY` status, which is a strong signal that a short answer like "yes, go ahead" belongs to that task.

The flag is persisted immediately, so a restart can't accidentally resume a waiting task behind your back.

## Parallel tasks

Ask for two things at once ("research topic A and topic B") and the agent may start two tasks from a single turn. Each gets:

| Per-task resource | Why it matters |
|---|---|
| Its own event stream | Task A's actions never appear in task B's context |
| Its own continuation triggers | The [agent loop](agent-loop.md) interleaves turns fairly, ordered by time and priority |
| Its own temp directory | `agent_file_system/workspace/tmp/<task_id>/`, auto-cleaned at task end |
| Its own counters | Actions and tokens are budgeted per task, not globally |

Your messages keep flowing while tasks run: an unrelated question becomes a new conversation. A steering comment routes into the task it's about.

## The task object

A task is a small record you can reason about:

| Field | Meaning |
|---|---|
| `id` | Session id — shared by triggers, events, temp dir |
| `name` / `instruction` | Short label + the original request |
| `mode` | `simple` or `complex` — picked by the LLM at creation; see [Task modes](../modes/index.md) |
| `status` | `running`, `completed`, `error`, `paused`, or `cancelled` |
| `todos` | The visible checklist (complex tasks only) |
| `action_sets` | Which action groups this task may use ([Actions & action sets](actions-and-action-sets.md)) |
| `selected_skills` | [Skills](skills.md) whose instructions are injected into the task's prompts |
| `waiting_for_user_reply` | The pause flag described above |
| `source_platform` | Where the task was started from — replies go back there (Telegram, Slack, the browser…) |
| `action_count` / `token_count` | Per-task budget counters |
| `final_summary` | Written when the task ends |

Action sets and skills are locked in at `task_start`. The LLM selects them from your request, which is why a research task can search the web but not, say, touch your clipboard.

## Lifecycle

1. **Created.** `task_start` (from conversation) or the scheduler creates the task with `status: running`, builds its temp dir, opens its event stream, and logs a `task_start` event. Your original message is copied into the new stream so the task has full context.
2. **Running.** Turns advance it, todos get checked off, and it may flip in and out of waiting-for-reply. Hitting an action or token budget pauses it behind a Continue/Abort prompt.
3. **Ended.** `task_end` sets the final status and summary, closes the stream, releases the temp dir, and appends a record to `agent_file_system/TASK_HISTORY.md`: name, id, status, timestamps, summary, original instruction, skills and action sets used.

Tasks are persisted on every change, and running tasks are restored at boot. Their `resume` triggers re-queue automatically (deduplicated so a double boot can't double-resume). `TASK_HISTORY.md` is also how the agent itself recalls past outcomes when you ask "didn't you do something like this last week?".

!!! note "Implementation files"
    The task dataclass is `agent_core/core/task/task.py`. Creation, per-task event streams, temp dirs, and the `TASK_HISTORY.md` writer live in `TaskManager` at `agent_core/core/impl/task/manager.py`.

## Where sessions appear in the UI

- **Task cards** in the browser are sessions: one card per task, with status, todos, and actions.
- **Routing decisions** are logged. Send a message while a task runs and grep:

```bash
grep -E "\[CHAT\]|\[TASK" logs/<latest>.log
```

```text
[CHAT RECEIVED] use the cheaper flight option
[CHAT] LLM routed to 4f2c1a: user is answering the task's flight question
```

- **On disk.** `agent_file_system/TASK_HISTORY.md` for finished work, `agent_file_system/workspace/tmp/<task_id>/` for a running task's scratch files. See [Agent file system](agent-file-system.md).

## Limits

- Routing is only as good as its context: a bare "yes" days later, after the task's trigger went stale, may open a new conversation instead. Clicking reply on the task's message (rule 2) is always unambiguous.
- Mode is fixed at creation. A simple task that discovers it's actually big ends itself and spawns a complex successor rather than silently growing.
- Per-task action and token budgets pause runaway tasks. You decide whether they continue.

## Next

- [Task modes](../modes/index.md): what simple and complex tasks do differently
- [Your first task](../../start/first-task.md): watch routing and parallel tasks in practice
- [Agent loop](agent-loop.md): how a task's turns actually execute
- [Event stream](event-stream.md): the per-task record everything above writes to
