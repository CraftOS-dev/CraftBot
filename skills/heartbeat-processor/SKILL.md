---
name: heartbeat-processor
description: Run the proactive tasks from PROACTIVE.md that the scheduler hands to this run (each fires at its own set time) and report the result to the user's main chat in one message.
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - web_research
  - scheduler
---

# Heartbeat Processor

Background skill for running scheduled proactive tasks. Every task in PROACTIVE.md has its own slot (hourly at :MM, daily at HH:MM, weekly on a day at HH:MM, monthly on a date at HH:MM). The scheduler fires this run when one or more tasks reach their slot, or when a slot was missed while CraftBot was off. The heartbeat interval in Settings only sets how often CraftBot double-checks for missed tasks.

## Trigger Context

Your instruction lists exactly the tasks to run now, each with:
- its name and id, its schedule, and its tier (notify or silent)
- its instruction
- conditions to check first, if it has any
- a "Late" note when it is running well after its slot

The scheduler has ALREADY selected these tasks and recorded them as run. Do not call `recurring_read` to work out what is due, do not re-check their time or day fields, do not schedule them "for later", and do not call `recurring_update_task` to log them. CraftBot records each task's outcome from your final message.

---

## CRITICAL: Background Execution

This run happens in the background session, not in the user's chat:

- **Your run-ending `send_message` is the result.** CraftBot posts it to the user's main chat, headed with the task names. Put everything the user should see in that ONE message.
- **Progress updates are invisible.** `send_message` with `continue_work=true` is not shown to the user. Do not use it for notifications.
- **Nothing to report → `end_turn`.** If every task was silent (tier 0) or skipped and nothing needs the user's attention, end with `end_turn` and nothing is posted.
- **Never wait for the user.** Do not end on a question that needs an answer before the task can finish. If a task needs the user (a login, a decision), say so in the final message and stop that task.

---

## Two Execution Types

### INLINE Execution
Do the task directly in this run.

**Use INLINE when:**
- The task can be completed with the available actions
- No long multi-step workflow is needed
- The task is quick (notifications, searches, summaries)

### SCHEDULED Execution
Hand the task to its own background run with `schedule_task(schedule="immediate")`. It runs right after this one, in the same background session, and its own final message is posted to the main chat separately.

**Use SCHEDULED when:**
- The task needs long multi-step execution or sub-tasks
- The task needs action sets or skills this run does not have
- Running it inline would hold up the other due tasks

```
schedule_task(
  name="[Task Name]",
  instruction="Execute [task description]. End with one send_message reporting the result to the user.",
  schedule="immediate",
  action_sets=["required", "action", "sets"],
  skills=["relevant-skills"]
)
```

### Tasks That Operate a Website (Mini Browser)

Reading public pages works with `web_search` / `web_fetch`. A task that must USE a site (sign in, open an account page, click through, fill a form) needs the Mini Browser (action set `mini_browser`, a real browser with the user's saved logins):

- **Quick check on one page** → INLINE: `add_action_sets(["mini_browser"])` (their schemas arrive in your event stream), then the `mini_browser_*` actions next turn (`mini_browser_navigate`, then act on the numbered elements each result returns; `mini_browser_login` signs in with a saved login).
- **Multi-step work** → SCHEDULED: `schedule_task(..., schedule="immediate", action_sets=["mini_browser"], skills=["mini-browser"])`.
- A login that isn't saved, a CAPTCHA or a 2FA prompt → stop that task and say in the final message what is needed.

---

## Tiered Permission Model

Every task in your instruction is marked notify (tier 1) or silent (tier 0).

```
Tier 0 - Silent:
  - Search and summarize information
  - Detect anomalies and patterns
  - Draft recommendations internally
  - Read files and analyze data
  - Report only if the task's instruction asks for it, or something needs attention

Tier 1 - Notify:
  - Do the task, then report the result in the final message
  - Share analysis results, a proposed plan or a draft
```

Actions that send messages to other people, spend money or change external accounts are never done on a heartbeat unless the task's instruction explicitly says to.

## Evaluation Rubric

Score 1-5 for each dimension to decide whether running a task right now is worth it:

```
1. IMPACT (How significant is the outcome?)
   1 = Negligible impact
   2 = Minor improvement
   3 = Moderate benefit
   4 = Significant positive outcome
   5 = Critical/transformative impact

2. RISK (What could go wrong?)
   1 = High risk, potential for serious harm
   2 = Moderate risk, some potential issues
   3 = Low risk, manageable concerns
   4 = Very low risk, unlikely issues
   5 = No risk, completely safe

3. COST (Resources/effort required)
   1 = Very high cost/effort
   2 = Significant resources needed
   3 = Moderate effort required
   4 = Low cost/minimal effort
   5 = Negligible resources needed

4. URGENCY (How time-sensitive?)
   1 = Not urgent, can wait indefinitely
   2 = Low urgency, within weeks
   3 = Moderate urgency, within days
   4 = High urgency, within hours
   5 = Critical urgency, immediate action needed

5. CONFIDENCE (User acceptance likelihood)
   1 = Very unlikely to accept
   2 = Unlikely to accept
   3 = Uncertain/50-50
   4 = Likely to accept
   5 = Very likely/certain to accept

Decision Threshold:
- Total score >= 18: Strong candidate for execution
- Total score 13-17: Consider execution, may need user input
- Total score < 13: Skip this run (say so in the final message if the task is tier 1)
```

## Workflow

### Step 1: Read the Task List

Take the tasks from your instruction, in order. Read MEMORY.md, USER.md or other files only as far as a task needs them.

### Step 2: Check Each Task

1. **Conditions**: if a task lists conditions, check them first and skip the task if one does not hold:
   - `market_hours_only`: skip outside 9:30 AM - 4:00 PM on weekdays
   - `weekdays_only`: skip on Saturday and Sunday
   - `user_available`: skip if the user has not been active recently
   - Custom conditions as described
2. **Late note**: a task running late may no longer make sense (a "good morning" brief at 9 PM). Skip it and say so, or adapt it.
3. **Rubric**: score it; skip below 13.

### Step 3: Run Each Task

Choose INLINE or SCHEDULED, then follow the task's instruction. If a task fails, note why and continue with the next one.

### Step 4: Finish

- Something to report → ONE `send_message` (no `continue_work`) with a short section per task that has news: what was done, the findings, anything that needs the user.
- Nothing to report → `end_turn`.

## Rules

- **One final message**: everything the user should see goes into the run-ending `send_message`
- **No progress messages**: `continue_work=true` messages are never shown to the user
- **Silent on nothing**: end with `end_turn` when no task has news
- **Never wait for the user**: report what is needed instead of asking and waiting
- **Do not re-schedule or re-log**: the scheduler already recorded these tasks as run
- **Prefer INLINE execution**: use SCHEDULED only when truly necessary
- **Handle failures gracefully**: note the failure and continue with the next task

## Example Flows

### Example 1: INLINE Execution (Daily Briefing)

1. Instruction lists `daily_morning_briefing` (daily at 07:00, notify)
2. Score: Impact=4, Risk=5, Cost=4, Urgency=3, Confidence=4 = 20 (execute)
3. Gather weather, calendar and tasks
4. Final `send_message` with the briefing

### Example 2: SCHEDULED Execution (Complex Analysis)

1. Instruction lists `weekly_code_review` (weekly on Sunday at 17:00, notify)
2. Score: Impact=4, Risk=5, Cost=3, Urgency=2, Confidence=4 = 18 (execute)
3. Too long to run inline: `schedule_task(name="Weekly Code Review", instruction="Review code changes from the past week ... End with one send_message reporting the findings.", schedule="immediate", action_sets=["file_operations"])`
4. `end_turn` (the scheduled run reports its own result)

### Example 3: Silent Task

1. Instruction lists `hourly_inbox_scan` (hourly at :00, silent)
2. Nothing urgent found
3. `end_turn`

## Allowed Actions

`send_message`, `end_turn`, `memory_search`, `read_file`, `web_search`,
`web_fetch`, `schedule_task`, `update_todos`, and for website tasks
`add_action_sets` with the `mini_browser_*` actions (see "Tasks That
Operate a Website")

## Forbidden Actions

Direct file writes to PROACTIVE.md, and `recurring_update_task` /
`recurring_add` / `recurring_remove` (task changes need the user, in their
main chat)
