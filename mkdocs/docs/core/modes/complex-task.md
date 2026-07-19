# Complex task mode

Complex task mode is how CraftBot handles anything that needs a plan: multi-step work, file deliverables, irreversible operations, "projects". The agent locks a requirement contract, works through a live phase-prefixed todo list, verifies its own output, and (the defining feature) **does not close the task until you approve the result**.

For the guided version, see [Your first task](../../start/first-task.md#walkthrough-2-a-complex-task). This page is the complete behavior reference.

## When the agent picks complex

The agent chooses `task_mode: "complex"` at `task_start` (it's also the default) when any of these hold:

- The plan has more than ~3 actions.
- The output is a file or artifact you should review and approve.
- The work touches external state: it sends messages on your behalf, makes purchases, or modifies third-party data.
- The work spans multiple sessions or days.

## The state machine

A well-run complex task moves through a fixed sequence:

```
task_start(task_mode="complex")
        │
        ▼
set_requirement(...)        ← FIRST move: lock what "done" must contain
        │
        ▼
send_message                ← acknowledge you immediately
        │
        ▼
task_update_todos(...)      ← the full plan, all "pending", phase-prefixed
        │
        ▼
loop {
    mark ONE todo "in_progress"
    execute actions that advance it (parallel within a todo is fine)
    mark it "completed"
    discovered missing info? → add a "Collect:" todo, revert
}
        │
        ▼
send_message                ← final result + explicit approval request
        │
        ▼
wait for your reply         ← task pauses; nothing blocks
        │
        ▼
task_end                    ← only after your explicit approval
```

### The requirement contract

Before anything else, the agent calls `set_requirement`, a list of checkable items, each with a `dimension` (content, structure, length, format, ...), a specific falsifiable `requirement`, a concrete `done_when` test, and a `status` (`pending` / `satisfied` / `violated`). This is distinct from the todo list: todos are the *steps*, requirements are the *contract* for the finished output. During the Verify phase the agent re-scores every item. A `violated` item means rework before it asks for your approval. The list is pinned into the agent's context every turn, so it survives even when older events are summarized away.

Practical upshot for you: constraints you state in the first message ("under 2 pages", "cite sources") get encoded here, which is why stating them up front beats correcting at the approval gate.

### Todos and phase prefixes

The plan lives in the task's todo list, updated via `task_update_todos`. Each todo has a `content`, a `status` (`pending` / `in_progress` / `completed`), and must start with one of six mandatory phase prefixes:

| Prefix | Meaning |
|---|---|
| `Acknowledge:` | Restate your goal in the agent's own words |
| `Collect:` | Gather inputs — read files, search, ask you, list integrations |
| `Execute:` | Do the work — generate, transform, send, write |
| `Verify:` | Check the output meets the goal — re-read files, run tests |
| `Confirm:` | Present the result to you for approval |
| `Cleanup:` | Remove temp files, restore state, close connections |

Rules the agent is held to:

- Exactly **one** todo is `in_progress` at a time. Each turn works the current in-progress todo (or the first pending one if none is in progress).
- Todos are marked `in_progress` before the work and `completed` right after. There is no batch-completing.
- Verify is never skipped for todos that produce files or change external state.
- Cleanup never happens before you've signed off at Confirm.
- Missing information discovered mid-Execute becomes a fresh `Collect:` todo. The agent reverts rather than guesses.

The plan is revisable at any time: the agent adds, reorders, rewords, or drops todos as it learns. You can watch all of this live in the todo list on the task card, which shows the current progress.

## The approval gate

Complex tasks do not close themselves. The final message summarizes what was done, lists artifacts with paths, and explicitly asks for approval. Reply "looks good" and the agent runs Cleanup and calls `task_end(status="complete")`. Point out what's wrong and it keeps working *in the same task* with full context. Rejection is a revision loop, not a restart. There is no timeout that auto-approves. An unanswered task just waits (see below).

## Waiting, steering, and parallel work

- **Pauses.** When the agent asks you something with `wait_for_user_reply=true`, the task's `waiting_for_user_reply` flag pauses trigger scheduling. Your reply routes back into the task automatically. If nothing arrives, a silent wait trigger re-queues every 3 hours, so the task idles indefinitely without consuming tokens.
- **Steering.** Messages you send about the running task route into it: new requirements adjust the todos, and "stop" winds the work down.
- **Unrelated messages** don't interrupt, because [session routing](../concepts/task-sessions.md) sends them to a fresh conversation, and multiple tasks run side by side.

## Action and token limits

Every task carries per-task counters (`action_count`, `token_count`) checked after each turn. Defaults live in `app/config.py`: **500 actions** and **12,000,000 tokens** per task.

| Threshold | What happens |
|---|---|
| 80% of either limit | A warning event tells the agent to wrap up, deliver the best partial result, or ask you whether to abort |
| 100% of either limit | The task **pauses**: you get a chat message with **Continue** / **Abort** buttons, the task card shows *paused*, and a long-delay trigger keeps the task alive while it waits |

Choosing **Continue** resets both counters to zero and resumes the task, and **Abort** ends it. While paused, the agent issues no actions. The decision is entirely yours.

## Failure paths

- **Recoverable errors.** Failed actions return `status: "error"`. The agent retries transient failures once, changes approach on semantic failures, and escalates to you with one specific question when blocked.
- **Deliberate abort.** When the work is impossible (missing access, contradictory requirements), the agent summarizes what it tried, sends any salvageable partial result, and calls `task_end(status="abort")`.
- **Fatal LLM failures.** Repeated consecutive LLM call failures cancel the task automatically and surface an error dialog. Fix the provider configuration, then retry. See [LLM providers](../providers/llm.md).

## What happens at the end

On `task_end`:

- A record is appended to `agent_file_system/TASK_HISTORY.md` with the task name, ID, status (`completed` / `cancelled` / `failed`), timestamps, a one-paragraph summary, the original instruction, and the skills and action sets used.
- The task's scratch directory `agent_file_system/workspace/tmp/<task-id>/` is cleaned automatically. Deliverables saved to `agent_file_system/workspace/` persist. See [Agent file system](../concepts/agent-file-system.md).

## Mode is fixed

A task never changes mode after it starts. Simple work discovered inside a complex task just gets done. Complex work discovered inside a simple task ends the simple task and spawns a complex one (see [Simple task](simple-task.md#when-the-work-grows-mid-task)). There is no demotion from complex to simple.

## Caching

Complex tasks benefit most from **session-level prompt caching**: the loop can span dozens of turns, and each one reuses the cached context prefix, appending only the new events. See [Context engine](../concepts/context-engine.md).

## Observing a complex task

| Where | What you see |
|---|---|
| Task panel | The task card with its live todo list and status (running / paused / completed) |
| Action panel | Every action with inputs and results, including `task_update_todos` and `set_requirement` calls |
| Chat | Acknowledgement, milestone updates, questions, the approval request, limit dialogs |
| `agent_file_system/TASK_HISTORY.md` | The end-of-task record |
| `logs/<run>/main.log` | Grep `[TASK]` for lifecycle, `[ACTION]` for execution, `[LIMIT]` for limit events |

More on logs in [Logs](../concepts/logs.md).

## Related

- [Simple task](simple-task.md): the mode for 2–3 action work
- [Task modes overview](index.md): how the mode gets picked
- [Task sessions](../concepts/task-sessions.md): reply routing and parallel tasks
- [Triggers](../concepts/triggers.md): the wait/re-queue machinery underneath pauses
