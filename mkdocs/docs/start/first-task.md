# Your first task

Everything CraftBot does for you happens inside a **task**. This page shows how tasks start, what the two task modes look like in practice, how to watch and steer a running task, and how to phrase requests so they succeed. Work through it once with the agent open next to you.

## Conversation mode vs task mode

When no task is running, the agent is in **conversation mode**. In this state it can do exactly three things: reply to you, start a task, or deliberately ignore a message that needs no response (relevant once group chats are connected). It cannot touch files, browse, or call integrations. Conversation is deliberately cheap and safe.

The moment your message asks for something actionable, the agent starts a task on its own. There is no `/task` command and nothing to manage: describing work *is* how you start work.

CraftBot picks one of two task modes based on the size of the request:

| | Simple task | Complex task |
|---|---|---|
| For | Quick, obvious work | Multi-step work that needs planning |
| Todo list | No | Yes: live, updated as it works |
| Typical length | 2–3 actions, seconds | Many actions, minutes |
| Ends | By itself when done | Only after **you confirm** the result |
| Example | "Convert this file to PDF" | "Research X, compare, write a report" |

The full mechanics are in [Task modes](../core/modes/index.md); here, you'll run one of each.

## Walkthrough 1: a simple task

Ask for something small and concrete:

```
What's the latest stable Python version? Check online, don't guess.
```

What you'll observe:

1. A task card appears. The agent decided this needs a real action (a web search), so conversation mode won't do.
2. One or two actions fire in the action panel: `web_search`, maybe a `web_fetch`.
3. The agent replies with the answer and the task ends **by itself**. Simple tasks produce no todo list and require no confirmation.

Total time: seconds. Most day-to-day requests run like this.

## Walkthrough 2: a complex task

Now give it something that requires a plan:

```
Research the three most popular Python web frameworks, compare them
by learning curve, performance, and ecosystem, and save the comparison
as frameworks.md
```

What you'll observe, stage by stage:

1. **Planning.** A task starts and a **todo list** appears. The agent breaks the work into phases you can read: acknowledging the request, collecting information, executing, verifying its own output, confirming with you, cleaning up. Todos update live, so the list shows the task's current progress.
2. **Execution.** Actions fire one after another in the action panel: searches, page fetches, then `write_file`. Every step the agent takes is visible there, with inputs and results. Nothing happens off-screen.
3. **Questions, maybe.** If the agent hits a decision it can't make (ambiguous requirement, missing credential) it messages you and **waits**. The task is paused, not stuck. Answer in chat and it resumes. Your reply routes into the waiting task automatically.
4. **Verification.** Good complex tasks check their own work before reporting completion. Expect to see the agent re-read the file it wrote.
5. **The approval gate.** The agent presents the result and asks you to confirm. This is the defining feature of complex tasks: **they do not close until you accept.** Reply "looks good" and the task ends, or say what's wrong ("too short, add benchmarks") and it keeps working in the same task, with all its context intact.

When it's done, find the output at `agent_file_system/workspace/frameworks.md`.

## Where task outputs go

| Location | What lands there |
|---|---|
| `agent_file_system/workspace/` | Final artifacts: documents, data, anything meant to persist |
| `agent_file_system/workspace/tmp/<task-id>/` | Per-task scratch files, cleaned automatically when the task ends |
| Chat attachments | Files the agent sends you directly with its reply |
| `agent_file_system/TASK_HISTORY.md` | A record of every completed task |

Tell the agent where you want things ("save it to the workspace", "send it to me here as a file") and it will comply. Details: [Agent file system](../core/concepts/agent-file-system.md).

## Steering a running task

You are not locked out while a task runs:

- **Add or change requirements mid-flight.** "Also include Flask" routes into the running task, and the agent adjusts its todos and continues.
- **Answer its questions.** Anything the agent asked, just answer in chat.
- **Stop it.** Tell it to stop or cancel. The message reaches the task and the agent winds the work down instead of finishing it.
- **Ask something unrelated.** An unrelated message does *not* interrupt the task. CraftBot's [session routing](../core/concepts/task-sessions.md) sends it to a separate conversation, and the task keeps running in parallel. You can watch and switch between them in the task panel.

That last behavior means you can queue real work: give it a research task, then immediately ask it to draft an email. Two tasks run side by side, each with its own context.

## Phrasing requests that succeed

The agent works with exactly what you give it. Requests that go well share these traits:

- **Name the deliverable.** "Write a comparison **and save it as frameworks.md**" beats "tell me about frameworks". A concrete artifact gives the task a clear completion criterion.
- **Give constraints up front.** Stating length, format, tone, and sources to prefer or avoid in the first message saves a revision cycle at the approval gate.
- **Don't pre-chunk the work.** You don't need to feed steps one at a time. That's what todos are for. Give the whole goal and let it plan.
- **Point at inputs explicitly.** Say "using the CSV in my workspace" or attach the file directly. The agent can read chat attachments and workspace files.
- **For recurring work, say so.** "Every weekday at 8am, ..." becomes a scheduled task, not a one-off. See [Scheduling](../core/concepts/scheduling.md).

## Useful commands while working with tasks

```
/help          # every command
/clear         # clear the chat display
/clear-tasks   # remove completed/failed tasks from the task panel
/skill         # manage skills            /cred           # connected integrations
/reset         # reset agent state and history (erases current context)
```

Full catalogue: [Built-in commands](../core/commands/builtin.md).

## If a task misbehaves

| Symptom | What to do |
|---|---|
| Task hangs on one action | Open the action in the action panel and read its error; most hangs are a missing credential or dependency |
| Agent misunderstood the goal | Say so in chat; course-correcting a running task is cheaper than restarting it |
| Result is wrong at the approval gate | Reject with specifics; the task continues with full context |
| Task failed outright | Check `logs/` (each run writes `main.log` + `all.log`); see [Logs](../core/concepts/logs.md) |
| Everything is confused | `/reset` clears state and history: a last resort, it erases the current context |

## Next

- [Task modes](../core/modes/index.md): simple, complex, and the special workflows behind them
- [Service mode](service-mode.md): keep the agent available when the terminal closes
- [Integrations](../integrations/index.md): day-one picks: Telegram, Gmail, Slack
- [Learning path](learning-path.md): choose your track from here
