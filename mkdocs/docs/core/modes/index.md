# Runs

Every message you send (and every scheduled event that fires) wakes the agent for exactly one **run**: a stretch of work inside a **session** that starts on a trigger and continues turn by turn until the agent delivers its result or decides no reply is needed. There is one pipeline for all work, and the agent scales its process to the size of the request: a quick question gets a direct answer; a "project" gets a requirement contract, a live todo plan, and a verification pass before delivery. This page is the map; the linked pages are the full treatment.

If you haven't run anything yet, do [Your first task](../../start/first-task.md) first. It walks you through one quick request and one substantial piece of work live. These pages are the reference treatment.

## Sessions and runs

The unit of work is a **session** (main, chat, or Living UI). Each session has its own event stream, its own durable trigger queue, and a serial consumer loop: one turn at a time per session, with different sessions running independently in parallel. How sessions and reply routing work is covered in [Sessions](../concepts/task-sessions.md).

A **run** is one wake of a session:

1. A trigger fires: your message, a scheduled event, or a workflow event. Everything currently due for that session folds into a single turn, presented to the agent as a numbered checklist ([Triggers](../concepts/triggers.md)).
2. The agent works turn by turn through the same four-phase beat every time: select actions, prepare them, execute them, finalize ([Agent loop](../concepts/agent-loop.md)).
3. The run ends when the only action(s) the agent selects are **terminal**: a final `send_message` (one without `continue_work=true`) or `end_turn`. Any other turn queues a continuation trigger and the next turn follows.

You never pick a mode and neither does the agent, because there are no modes: every turn runs the same pipeline, and the agent decides how much process the work deserves.

## How the agent scales its process

| Signal in your request | What the agent does |
|---|---|
| Quick lookup, single answer, 1-3 obvious actions | Executes the action(s) and replies; the reply is the final message and ends the run |
| Input that needs no reply (an emoji ack, third-party noise) | `end_turn`: the run ends silently |
| Multi-step work, file deliverables, irreversible operations, "projects" | Locks a requirement contract (`set_requirement`), acknowledges you, plans with `update_todos`, works phase by phase, verifies, then delivers |

The two paths in detail:

- [Quick requests](simple-task.md): how small asks flow, and when the agent stays silent
- [Substantial work](complex-task.md): the requirement contract, the todo phases, verification, and delivery

## Asking you something

There is no approval gate wired into the machinery and no waiting state. When the agent needs your input (including sign-off before an irreversible step), it makes the question its **final message**: the run ends, the session sleeps, and your reply wakes a **new run in the same session**. Because the session's event stream carries the full history, the new run picks up exactly where the old one left off. A follow-up after delivery works the same way, which makes revision a continuation rather than a restart.

## Workflow runs

Some runs are never started by you. Memory processing, the proactive heartbeat, and the day/week/month planners run **in the main session** on the scheduler's clock: each run temporarily loads a dedicated skill (plus the action sets it needs), does its work silently, and unloads everything when the run ends.

- [Workflow runs](special-workflows.md): schedules, what each workflow loads, and the silent-execution rules
- [Proactive](proactive.md): the full user guide to recurring tasks, permission tiers, and the planners

## Related

- [Your first task](../../start/first-task.md): the tutorial version of this page
- [Agent loop](../concepts/agent-loop.md): the cycle every turn runs on
- [Triggers](../concepts/triggers.md): what wakes the agent and how due triggers aggregate
- [Sessions](../concepts/task-sessions.md): parallel sessions and message routing
- [Scheduling](../concepts/scheduling.md): the scheduler that fires memory and proactive triggers
