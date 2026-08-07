# Your first run

Everything CraftBot does for you happens as a **run** inside a chat session: the agent wakes on your message, works turn by turn, and ends the run with its reply. This page shows what quick and substantial runs look like in practice, how to watch and steer a run while it works, and how to phrase requests so they succeed. Work through it once with the agent open next to you.

## Sessions and runs

The browser sidebar has a **Chats** group. **Main** is pinned at the top, and the **+** button creates additional chat sessions. Each session is its own conversation with its own context; new chats title themselves from the first exchange, and you can rename, clear, or delete any of them from the session's menu. Sessions run independently, so work in one never blocks another.

A **run** is one wake of a session. Your message starts it, the agent works through however many actions the request needs, and the agent's final reply ends it. The session then sleeps until your next message starts a new run in the same conversation, with all the context carried over. There is no `/task` command and nothing to manage: describing work *is* how you start work.

The same run mechanics scale from tiny to large:

| | Quick request | Substantial work |
|---|---|---|
| For | Questions, one-off small actions | Multi-step work that needs planning |
| Todo list | No | Yes — live, updated as it works |
| Requirements | No | Yes — a checklist of what "done" must contain |
| Typical length | 1–3 actions, seconds | Many actions, minutes |
| Ends | With the answer | With the delivered result and artifact paths |
| Example | "Convert this file to PDF" | "Research X, compare, write a report" |

The full mechanics are in [Runs](../core/modes/index.md); here, you'll watch one of each.

## Walkthrough 1: a quick run

Ask for something small and concrete:

```
What's the latest stable Python version? Check online, don't guess.
```

What you'll observe:

1. A **Working** row appears under your message: the agent decided this needs a real action (a web search), and the row ticks while it runs.
2. One or two actions fire behind it: `web_search`, maybe a `web_fetch`. Click the row to expand the agent's reasoning and each action with its result.
3. The agent replies with the answer, and that reply ends the run. Quick runs produce no todo list.

Total time: seconds. Most day-to-day requests run like this.

## Walkthrough 2: substantial work

Now give it something that requires a plan:

```
Research the three most popular Python web frameworks, compare them
by learning curve, performance, and ecosystem, and save the comparison
as frameworks.md
```

What you'll observe, stage by stage:

1. **Requirements first.** The agent records a requirements checklist — the concrete things the finished output must contain — before anything else. This is the contract it verifies against at the end.
2. **An immediate acknowledgment.** One sentence in chat confirming it has started, so you're never staring at silence.
3. **A todo list.** The agent plans the work as phase-prefixed todos (Collect, Execute, Verify, Deliver, Cleanup) and checks them off live as it works, exactly one in progress at a time.
4. **Actions fire.** The **Working** row stays visible the whole time. Expand it (or any settled "N Actions executed" row between messages) to see every search, page fetch, and `write_file` with its inputs and results. Nothing happens off-screen.
5. **Questions, maybe.** If the agent hits a decision it can't make (ambiguous requirement, missing credential), it asks you as its final message and the run ends there. Your answer wakes a new run in the same session with full context, and the work continues.
6. **Verification.** Before delivering, the agent re-checks its requirements checklist and marks each item satisfied or violated — a violated item means rework before you see the result.
7. **Delivery.** The final message summarizes what was done and lists the artifact paths. That message ends the run. If something's wrong ("too short, add benchmarks"), just say so — your reply starts a new run in the same session and the agent picks up right where it left off.

When it's done, find the output at `agent_file_system/workspace/frameworks.md`.

## Where outputs go

| Location | What lands there |
|---|---|
| `agent_file_system/workspace/` | Final artifacts — documents, data, anything meant to persist |
| `agent_file_system/workspace/sessions/<session-id>/` | Per-session scratch files — kept for the session's life, removed when the session is deleted |
| Chat attachments | Files the agent sends you directly with its reply |

Tell the agent where you want things ("save it to the workspace", "send it to me here as a file") and it will comply. Details: [Agent file system](../core/concepts/agent-file-system.md).

## Steering a running run

You are not locked out while the agent works:

- **Add or change requirements mid-flight.** "Also include Flask" folds into the run's very next turn, and the agent adjusts its todos and continues.
- **Answer its questions.** Anything the agent asked, just answer in chat. Your reply wakes the session and the work resumes with context intact.
- **Stop it.** The send button becomes a **Stop** button while a run is in flight. Stopping cancels the in-flight turn and clears the queue; your next message starts fresh.
- **Ask something unrelated.** Create a new chat with the **+** button in the sidebar's Chats group. Each session runs independently, so the research keeps going in one chat while you draft an email in another.

That last behavior means you can queue real work: give one chat a research job, open a second chat, and hand it something else. Two runs proceed side by side, each with its own context.

## Phrasing requests that succeed

The agent works with exactly what you give it. Requests that go well share these traits:

- **Name the deliverable.** "Write a comparison **and save it as frameworks.md**" beats "tell me about frameworks". A concrete artifact gives the run a clear completion criterion — it becomes the requirements checklist.
- **Give constraints up front.** Stating length, format, tone, and sources to prefer or avoid in the first message saves a revision cycle after delivery.
- **Don't pre-chunk the work.** You don't need to feed steps one at a time. That's what todos are for. Give the whole goal and let it plan.
- **Point at inputs explicitly.** Say "using the CSV in my workspace" or attach the file directly. The agent can read chat attachments and workspace files.
- **For recurring work, say so.** "Every weekday at 8am, ..." becomes a scheduled task, not a one-off. See [Scheduling](../core/concepts/scheduling.md).

## Useful commands while working

```
/help          # every command
/clear         # clear this session's conversation (alias /cls)
/tokens        # this session's token usage (input / cached / output / total)
/skill         # manage skills            /cred           # connected integrations
/reset         # delete all chat sessions and clear history (erases current context)
```

Full catalogue: [Built-in commands](../core/commands/builtin.md).

## If a run misbehaves

| Symptom | What to do |
|---|---|
| Run hangs on one action | Expand the Working row and read the action's error; most hangs are a missing credential or dependency |
| Agent misunderstood the goal | Say so in chat — course-correcting a run is cheaper than restarting it |
| Result is wrong at delivery | Reply with specifics; the next run in the session continues with full context |
| Run pauses with a Continue/Stop choice | It hit its per-run action or token budget; pick **Continue** to reset the counters and resume, or **Stop** to end it |
| Run failed outright | Check `logs/` (each app run writes `all.log` plus a `session.log` per session); see [Logs](../core/concepts/logs.md) |
| Everything is confused | `/reset` deletes all chat sessions and clears history — a last resort, it erases the current context |

## Next

- [Runs](../core/modes/index.md): quick requests, substantial work, and the background workflows behind them
- [Service mode](service-mode.md): keep the agent available when the terminal closes
- [Integrations](../integrations/index.md): day-one picks: Telegram, Gmail, Slack
- [Learning path](learning-path.md): choose your track from here
