# Task modes

Every message you send (and every scheduled event that fires) becomes exactly one kind of turn: a **conversation**, a **simple task**, a **complex task**, or one of two system-initiated **special workflows**. This page is the decision map: how CraftBot picks, what each mode is for, and where to read the full behavior of each.

If you haven't run a task yet, do [Your first task](../../start/first-task.md) first. It walks you through one simple and one complex task live. These pages are the reference treatment.

## How a message becomes a mode

Routing happens at the top of the agent loop (`react()` in `app/agent_base.py`), in a fixed order:

1. **Memory trigger?** A scheduled memory-processing event short-circuits everything else and runs the [memory workflow](special-workflows.md#the-memory-workflow).
2. **Proactive trigger?** A heartbeat or planner event runs the [proactive workflow](special-workflows.md#the-proactive-workflow).
3. **Is a task already running for this session?** If yes, the message routes into that task: the complex-task workflow if the task's mode is `complex`, the simple-task workflow if `simple`.
4. **Otherwise: conversation mode.**

Two things follow from this order. Special workflows never compete with your messages. They are separate turns with their own trigger types. And *you* never pick a mode: the routing is decided by session state, and the task mode itself is decided by the agent when it calls `task_start` with `task_mode: "simple"` or `"complex"` (default `complex`). How triggers and sessions drive this is covered in [Agent loop](../concepts/agent-loop.md), [Triggers](../concepts/triggers.md), and [Task sessions](../concepts/task-sessions.md).

## The three user-facing modes

| | Conversation | Simple task | Complex task |
|---|---|---|---|
| Exists when | No task running | `task_start` with `simple` | `task_start` with `complex` |
| For | Chat, routing, clarification | Quick, obvious work | Multi-step work needing a plan |
| Can do | Reply, start tasks, ignore | Full action surface of its action sets | Full action surface of its action sets |
| Todo list | — | No | Yes — live, phase-prefixed |
| Typical length | One turn | 2–3 actions | Many actions, many turns |
| Ends | n/a | By itself, after delivering the result | Only after **you approve** the result |
| Prompt caching | Prefix caching only | Session caching | Session caching |

Conversation mode is deliberately narrow: the agent can reply (`send_message`), start one or more tasks with `task_start` (several in parallel is allowed, so "research A and B" becomes two tasks at once), or deliberately `ignore` a message that needs no response (mostly relevant for group-chat integrations, where not every message is addressed to the agent). It cannot touch files, browse, or call integrations. All of that requires a task.

## Which task mode does the agent pick?

The agent decides at `task_start` based on the size of the request:

| Signal in your request | Mode picked |
|---|---|
| Quick lookup, single answer, one obvious action | Simple |
| Result is the reply itself — nothing for you to review | Simple |
| More than ~3 actions, research, planning | Complex |
| Output is a file or artifact you should approve | Complex |
| Irreversible external effects (sends, purchases, config changes) | Complex |
| "Project"-scale or multi-session work | Complex |

The mode is fixed for the task's lifetime. If a simple task turns out to be bigger than expected, the agent doesn't silently keep going. It ends the simple task with the partial result and schedules a complex follow-up. Details on both pages:

- [Simple task](simple-task.md): lifecycle, auto-completion, what happens when the work grows
- [Complex task](complex-task.md): the todo state machine, requirement contract, approval gate, limits

## The special workflows

Two turns are never started by you:

- **Memory**: a nightly (3 AM) distillation run that turns the day's events into long-term memory. See [Special workflows](special-workflows.md) and [Memory](../concepts/memory.md).
- **Proactive**: heartbeats every 30 minutes and day/week/month planners that let the agent execute and plan recurring work on its own. See [Special workflows](special-workflows.md) for the mechanics and [Proactive](proactive.md) for the full user guide.

Both workflows do little themselves: they check their enable switch, then create an ordinary simple task loaded with a dedicated skill. The work itself runs through the same simple-task machinery described above.

## Related

- [Your first task](../../start/first-task.md): the tutorial version of this page
- [Agent loop](../concepts/agent-loop.md): the cycle every mode runs on
- [Triggers](../concepts/triggers.md): what wakes the agent and carries the routing type
- [Task sessions](../concepts/task-sessions.md): how parallel tasks and message routing work
- [Scheduling](../concepts/scheduling.md): the scheduler that fires memory and proactive triggers
