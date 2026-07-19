# Proactive

Proactive mode lets CraftBot work without being asked: a morning inbox summary, a weekly report, a daily plan for your day. These are recurring tasks the agent executes on schedule and, very conservatively, proposes on its own. It is conservative by design: the agent executes what's in its task registry and asks before adding anything to it.

## The moving parts

Three pieces, all covered mechanically in [Special workflows](special-workflows.md):

- **`agent_file_system/PROACTIVE.md`**: the registry. Recurring task definitions (as YAML blocks) plus a Goals / Plan / Status section the planners maintain.
- **The heartbeat**: fires every 30 minutes at `:00` and `:30`. Collects every due task from PROACTIVE.md and executes them in one `Heartbeat` task.
- **The planners**: a day planner (7 AM daily), week planner (Sunday 5 PM), and month planner (1st, 8 AM) that review recent activity and update the Goals / Plan / Status section. Proposing *new* recurring tasks is a rare, approval-gated side effect.

All schedules live in `app/config/scheduler_config.json` and can be edited or toggled per entry (see [Scheduling](../concepts/scheduling.md)).

## Turning it on and off

The master switch is `proactive.enabled` in `app/config/settings.json` (default: on), also exposed in the settings UI:

```json
{ "proactive": { "enabled": true } }
```

When disabled, heartbeat and planner triggers log and skip, and no tasks are created. The nightly memory run has its own `memory.enabled` toggle and is unaffected, and one-off tasks you scheduled explicitly still fire.

One hard dependency: **schedules only fire while CraftBot is running.** On a laptop that sleeps at night, a 7 AM planner never fires. For dependable proactive behavior, run the agent persistently (see [Service mode](../../start/service-mode.md)).

## Anatomy of a recurring task

Tasks live in PROACTIVE.md between the `<!-- PROACTIVE_TASKS_START -->` and `<!-- PROACTIVE_TASKS_END -->` markers. Each is a `### [FREQUENCY] Task Name` heading followed by a YAML code block:

````markdown
### [DAILY] Morning inbox summary

```yaml
id: morning_inbox_summary
frequency: daily
time: "08:30"
enabled: true
priority: 50
permission_tier: 1
run_count: 0
conditions:
  - weekdays_only
instruction: |
  1. Connect to user's email via Gmail integration
  2. Fetch unread emails from the last 24 hours
  3. Compile a summary with Urgent / Important / FYI sections
  4. Present summary to user via chat message
outcome_history: []
```
````

| Field | Required | Values |
|---|---|---|
| `id` | yes | Unique snake_case identifier |
| `frequency` | yes | `hourly` / `daily` / `weekly` / `monthly` |
| `time` | recommended for daily+ | `"HH:MM"` 24-hour |
| `day` | for weekly / monthly | Weekday name (`monday`–`sunday`) or date (`1`–`31`) |
| `enabled` | yes | `true` / `false` |
| `priority` | yes | `1`–`100`, lower = higher priority |
| `permission_tier` | yes | `0`–`3`, see below |
| `run_count` | auto | Execution counter, maintained by the system |
| `conditions` | no | e.g. `weekdays_only`, `market_hours_only`, `user_available` |
| `instruction` | yes | Multi-line, step-by-step spec — the most important field |
| `outcome_history` | auto | Last 5 run results (timestamp, result, success) |

The instruction quality determines execution quality. Write exact steps, name the sources (which integration, which file), define the output format, and say what to do when data is missing. "Check emails and summarize important ones" is a bad instruction. A numbered eight-step procedure is a good one. The template at the top of PROACTIVE.md carries a full worked example.

!!! warning "Don't remove the HTML comment markers"
    The parser locates task definitions via `<!-- PROACTIVE_TASKS_START -->` / `<!-- PROACTIVE_TASKS_END -->`. Edit the content between them; never delete the markers.

## Timing: how "due" is decided

- The heartbeat fires at `:00` and `:30`. A task with a `time` field runs on the first heartbeat at or after that time, within a **30-minute grace period**. If the agent wasn't running and the window is missed, the run is skipped until the next day/week/month. There are no catch-up runs.
- `hourly` tasks are due on **every** heartbeat.
- `daily` / `weekly` / `monthly` tasks run at most once per period. The `day` field narrows weekly tasks to a weekday and monthly tasks to a date.
- `conditions` gate execution on top of timing: `weekdays_only` skips weekends, `market_hours_only` restricts to 9:30 AM–4 PM weekdays, `user_available` checks recent user activity.

## Permission tiers

Each task's `permission_tier` controls how it interacts with you:

| Tier | Level | Behavior |
|---|---|---|
| 0 | Silent | Searching, analyzing, drafting — proceeds without notifying you |
| 1 | Notify | Tells you what it's doing and the findings, then proceeds without waiting |
| 2 | Approval | Asks for approval before proceeding |
| 3 | High-risk | Requires explicit, detailed approval (emailing external parties, changing configs) |

In practice, recurring tasks should be tier 0 or 1. The heartbeat executes silently and won't hold work waiting for you, so anything that genuinely needs per-run approval doesn't belong in the recurring registry. Tiers 2–3 exist for consequential, oversight-requiring work.

## What a heartbeat run actually does

When due tasks exist, the `Heartbeat` task (running the `heartbeat-processor` skill):

1. Reads all enabled recurring tasks and confirms which are due.
2. Evaluates each against its conditions and a five-dimension rubric: Impact, Risk, Cost, Urgency, Confidence, each scored 1–5. Total 18+ executes, 13–17 may warrant asking you first, and below 13 skips this round.
3. Executes each passing task **inline** if it's quick and tier 0/1, or **schedules it as a separate task** (via `schedule_task`) when it needs multi-step execution or action sets the heartbeat doesn't carry.
4. Records the outcome to the task's `outcome_history`. The history is kept to the last 5 entries, which the planners read to decide whether a task is worth keeping or tuning.
5. Ends silently. Tier-1 notifications arrive as chat messages prefixed with a star, and nothing waits for a reply.

## The approval model

The agent never quietly grants itself new recurring work. The planner skills are built around a hard conservatism rule: a new recurring task may only be suggested if you explicitly asked for the automation or demonstrably did the same thing at least three times. Most planner runs are expected to produce zero suggestions. When a planner does suggest one, it messages you and waits. On approval it adds the task, and on rejection (or ~20 hours of silence) it drops the idea and ends without adding anything.

Your broader preferences come from [onboarding](../../start/onboarding.md): a proactivity level (low waits for instructions, medium suggests when relevant, high proactively suggests) and **approval categories**, the kinds of actions the agent must always ask before taking on your behalf (sending messages, scheduling, file changes, purchases, or everything). These are written into `USER.md` under *Prefer Proactive Assistance* and *Approval Required For*, and the agent reads them when deciding how to act.

## Managing your proactive tasks

- **Ask the agent.** Say "Every weekday at 8:30, summarize my unread email" and it adds the task through the `recurring_add` action (edits via `recurring_update_task`, removal via `recurring_remove`). This is the recommended path because the actions validate the format.
- **Edit PROACTIVE.md by hand.** Follow the template, keep the markers intact, and set `enabled: true`. The next heartbeat picks it up.
- **Disable one task** by setting `enabled: false`, or reset the whole file from the template in settings.
- **Review the planner's edits.** The Goals / Plan / Status section (Long-Term Goals, Current Focus, Recent Accomplishments, Upcoming Priorities) is planner-maintained. It is worth a periodic read to see what the agent thinks you're working toward.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Task never runs | CraftBot wasn't running at the scheduled time | Run persistently — [service mode](../../start/service-mode.md) |
| Task skipped some days | Missed its 30-minute grace window (agent started late) | Pick a time the agent is reliably up, or drop the `time` field |
| Nothing proactive ever happens | `proactive.enabled` is off, or the heartbeat schedule is disabled | Check settings and `scheduler_config.json` |
| Task exists but never fires | `enabled: false`, malformed YAML, or missing/damaged markers | Validate against the template format |
| Ran but did the wrong thing | Vague `instruction` | Rewrite as numbered, specific steps; check `outcome_history` for what it actually did |

Ground truth for any run: the `Heartbeat` / planner task cards in the task panel, and `[PROACTIVE]` lines in `logs/<run>/main.log` (see [Logs](../concepts/logs.md)).

## Related

- [Special workflows](special-workflows.md): how heartbeat and planner triggers are routed and executed
- [Scheduling](../concepts/scheduling.md): the scheduler behind the heartbeat, and one-off scheduled tasks
- [Service mode](../../start/service-mode.md): keeping the agent alive so schedules fire
- [Memory](../concepts/memory.md): the other system-initiated workflow
- [Agent file system](../concepts/agent-file-system.md): where PROACTIVE.md and USER.md live
