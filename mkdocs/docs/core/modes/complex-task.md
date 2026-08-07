# Substantial work

Substantial work is anything that needs a plan: multi-step work, file deliverables, irreversible operations, "projects". The agent locks a requirement contract before it even acknowledges you, works through a live phase-prefixed todo list, verifies its own output against the contract, and delivers with a final message that ends the run. This page is the complete behavior reference; for the guided version, see [Your first task](../../start/first-task.md).

## When the agent scales up

The agent gives a request the full treatment when any of these hold:

- The plan has more than ~3 actions.
- The output is a file or artifact you should review.
- The work touches external state: it sends messages on your behalf, makes purchases, or modifies third-party data.
- You call it a "project", or it spans multiple sessions or days.

## The shape of a substantial run

```
trigger (your message)
        │
        ▼
set_requirement(...)             ← FIRST move: lock what "done" must contain
        │
        ▼
send_message(continue_work=true) ← acknowledge you immediately, one sentence
        │
        ▼
update_todos(...)                ← the full plan, all "pending", phase-prefixed
        │
        ▼
loop {
    mark ONE todo "in_progress"
    execute actions that advance it (parallel within a todo is fine)
    mark it "completed"
    discovered missing info? → add a fresh "Collect:" todo
}
        │
        ▼
set_requirement(...)             ← Verify: re-score every item satisfied / violated
        │
        ▼
send_message                     ← final result + artifact paths; ends the run
```

### The requirement contract

Before anything else, the agent calls `set_requirement`: a list of checkable items, each with a `dimension` (content, structure, length, format, ...), a specific falsifiable `requirement`, a concrete `done_when` test, and a `status` (`pending` / `satisfied` / `violated`). This is distinct from the todo list: todos are the *steps*, requirements are the *contract* for the finished output, and substantial work needs both.

During the Verify phase the agent calls `set_requirement` again with every item re-scored. A `violated` item means rework before delivery. Each call replaces the whole list (it never appends), and the current list is pinned into the agent's context every turn, rendered with `[SAT]` / `[VIO]` / `[ ]` markers, so it survives even when older events are summarized away.

Practical upshot for you: constraints you state in the first message ("under 2 pages", "cite sources") get encoded here, which is why stating them up front beats correcting after delivery.

### Todos and phase prefixes

The plan lives in the run's todo list, updated via `update_todos`. Each todo has a `content`, a `status` (`pending` / `in_progress` / `completed`), and starts with one of five phase prefixes:

| Prefix | Meaning |
|---|---|
| `Collect:` | Gather inputs: read files, search, ask you, list integrations |
| `Execute:` | Do the work: generate, transform, send, write |
| `Verify:` | Check the output meets the goal: re-read files, run tests, smoke-test |
| `Deliver:` | Present the result to you |
| `Cleanup:` | Remove temp files, restore state, close connections |

Rules the agent is held to:

- Exactly **one** todo is `in_progress` at a time. Always.
- Todos are marked `completed` only after the actions ran, never before. There is no batch-completing.
- Verify is never skipped for todos that produce files or change external state.
- Missing information discovered mid-Execute becomes a fresh `Collect:` todo. The agent collects rather than guesses.

The plan is revisable at any time: the agent adds, reorders, rewords, or drops todos as it learns, and you can watch all of this live in the todo list.

## Delivery, and approval as a question

The final message summarizes what was done and lists artifacts with paths. Sending it ends the run: `continue_work=true` marks a progress update and keeps the run alive, while omitting it makes the message final. That flag is the run terminator; there is no separate completion action, and the agent never delivers a result and keeps working in the same message.

When the agent wants your sign-off before an irreversible step (sending an email on your behalf, purchasing, deleting), it makes the question its final message. The run ends, and your reply wakes a **new run in the same session** with the full event-stream context, so "yes, send it" continues seamlessly. The same pattern covers revision: reply with what's wrong and the new run picks the work back up with everything it knew before. There is no timeout and nothing is left running while you decide.

## Steering and parallel work

- **Steering.** Messages you send while a run is working fold into its next turn (all due triggers for a session aggregate into one checklist), so new requirements adjust the todos and "stop" winds the work down. You can also force-stop a run from the UI at any time.
- **Unrelated work** belongs in another session: sessions run independently in parallel, one turn at a time each. See [Sessions](../concepts/task-sessions.md).
- **Spin-offs.** Independent side-work gets deferred or parallelized with `schedule_task`: `schedule="immediate"` starts a separate run within seconds, and expressions like `"tomorrow at 9am"` or `"every day at 7am"` defer it. See [Scheduling](../concepts/scheduling.md).

## Action and token limits

Every run carries per-run counters (`action_count`, `token_count`) checked each turn against `max_actions_per_task` and `max_tokens_per_task`. Defaults live in `agent_core/core/state/types.py`: **150 actions** and **6,000,000 tokens** per run.

At 100% of either limit the run pauses: you get a chat message with **Continue** / **Stop** options, no continuation is queued, and the session sits idle until you pick one (or send a new message). Choosing **Continue** resets both counters to zero and the run resumes; while paused, the agent issues no actions. There is no advance warning before the gate.

Token accounting bills only **uncached** tokens: each turn adds `tokens_used - cached_tokens` to the counter, so warm-cache runs stretch much further than raw usage suggests. See [Context engine](../concepts/context-engine.md).

## Failure paths

- **Recoverable errors.** Failed actions return `status: "error"`. The agent retries transient failures once, changes approach on semantic failures, and escalates to you with one specific question when blocked.
- **Impossible work.** When the work can't be done (missing access, contradictory requirements), the agent's final message summarizes what it tried, includes any salvageable partial result, and ends the run. It never fabricates success.
- **Fatal LLM failures.** Repeated consecutive LLM call failures halt the run and surface an error message. Fix the provider configuration, then send any chat message (for example "continue") to resume. See [LLM providers](../providers/llm.md).

## Where the output goes

- Files you should keep land in `agent_file_system/workspace/`.
- Drafts and intermediate state go to the session's scratch directory, `agent_file_system/workspace/sessions/<session-id>/`, which persists for the session's life and is removed when the session is deleted.
- Multi-run initiatives get a **mission**: a directory at `agent_file_system/workspace/missions/<name>/` anchored by an `INDEX.md` (goal, status, key findings, next steps) that lets any future run restore context and pick up where the last one stopped. The agent scans the missions directory at the start of every substantial run. See [Agent file system](../concepts/agent-file-system.md).

## Caching

Substantial runs benefit most from prompt caching: the loop can span dozens of turns, and each one reuses the cached context prefix, appending only the new events. Combined with uncached-only token billing, this is what keeps long runs affordable. See [Context engine](../concepts/context-engine.md).

## Observing a substantial run

| Where | What you see |
|---|---|
| Todo list | The live plan with phase prefixes and per-todo status |
| Action panel | Every action with inputs and results, including `update_todos` and `set_requirement` calls |
| Chat | Acknowledgement, milestone updates, questions, the delivery message, limit dialogs |
| `agent_file_system/EVENT.md` | The main session's full event log |
| `logs/<run>/all.log` | Grep `[REACT]` for the run flow, `[ACTION]` for execution, `[LIMIT]` for limit events |

More on logs in [Logs](../concepts/logs.md).

## Related

- [Quick requests](simple-task.md): the path for 1-3 action work
- [Runs overview](index.md): how the agent scales its process
- [Sessions](../concepts/task-sessions.md): reply routing and parallel sessions
- [Triggers](../concepts/triggers.md): aggregation and the continuation machinery underneath runs
