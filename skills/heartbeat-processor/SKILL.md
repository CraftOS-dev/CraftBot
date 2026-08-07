---
name: heartbeat-processor
description: Process the unified proactive heartbeat by reading PROACTIVE.md and executing all due tasks across every frequency (hourly/daily/weekly/monthly).
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - web_research
  - scheduler
---

# Heartbeat Processor

Silent background skill for executing scheduled proactive tasks. A single unified heartbeat runs every hour and checks ALL frequencies — hourly, daily, weekly, and monthly tasks are evaluated in one pass.

## Trigger Context

You receive a single heartbeat trigger with:
- `type`: "proactive_heartbeat"
- The task instruction tells you how many due tasks were found

---

## CRITICAL: Silent Execution (Override Standard Task Rules)

**This skill overrides standard task completion rules.** Unlike regular tasks:

- **NO acknowledgement**: Do NOT acknowledge task receipt to user
- **NO confirmation**: Do NOT wait for user confirmation before ending
- **MUST end silently**: Use `end_turn` immediately after processing, without user interaction
- **Can send messages**: You can use `send_message` for tier 1 notifications — notify only, never phrase it as a question that expects an answer
- **NEVER block on user**: Do not end the run on a question at any point

**Why?** Heartbeat tasks run automatically at regular intervals. Waiting for user confirmation would cause tasks to pile up indefinitely.

---

## CRITICAL: Two Execution Types

When executing proactive tasks, you MUST choose between two execution types:

### INLINE Execution
Execute the task directly within this heartbeat session.

**Use INLINE when:**
- Permission tier is 0 or 1
- Task can be completed with available actions
- No complex multi-step workflows needed
- Task is quick (notifications, searches, summaries)

**Examples:** Send notification, search information, read and summarize files

### SCHEDULED Execution
Schedule the task as a separate session using `schedule_task`.

**Use SCHEDULED when:**
- Task requires complex multi-step execution
- Task may need to spawn sub-tasks
- Task requires action sets not available to heartbeat-processor
- Task runs extended operations that shouldn't block heartbeat

**Examples:** Comprehensive research, multi-file analysis, web scraping, code generation

**IMPORTANT for SCHEDULED tasks:** When scheduling a task, you MUST include in the instruction that the spawned task should call `recurring_update_task(task_id, add_outcome={result, success})` before ending. This ensures the proactive task outcome is recorded.

```
schedule_task(
  name="[Task Name]",
  instruction="Execute [task description]. IMPORTANT: Before ending, call recurring_update_task(task_id='[proactive_task_id]', add_outcome={'result': '[description of what was done]', 'success': true/false}) to record the outcome.",
  schedule="immediate",
  action_sets=["required", "action", "sets"],
  skills=["relevant-skills"],
  payload={"source": "proactive", "task_id": "[proactive_task_id]"}
)
```

---

## Tiered Permission Model

All recurring proactive tasks use tier 0 or tier 1. Tasks requiring user approval should not be added as recurring tasks.

```
Tier 0 - Silent (No Notification):
  - Search and summarize information
  - Detect anomalies and patterns
  - Draft recommendations internally
  - Read files and analyze data

Tier 1 - Notify Then Execute:
  - Notify user with star prefix, then execute immediately
  - Send a proposed plan or draft to user
  - Share analysis results or recommendations
```

## Evaluation Rubric

Score 1-5 for each dimension to determine if you should execute a proactive task:

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
- Total score < 13: Skip or defer this task
```

## Workflow

### Step 1: Read All Due Recurring Tasks

Use `recurring_read` with `frequency="all"` to get all enabled tasks, then process the ones that are due.

```
recurring_read(frequency="all", enabled_only=true)
```

The unified heartbeat checks tasks across ALL frequencies in one pass. Time and day filtering is already handled before tasks reach you — the tasks in your instruction are due now. However, you should still verify:

- **Tasks with a `time` field**: If current time < task time, schedule for later using `schedule_task` with the specified time, then skip
- **Tasks with a `day` field**: Confirm today matches (the pre-filter handles most cases, but verify edge cases)

**Scheduling a task for later:**
```
schedule_task(
  name="[Task Name]",
  instruction="Execute recurring task: [task_id]. [original instruction]. IMPORTANT: Before ending, call recurring_update_task(task_id='[task_id]', add_outcome={'result': '[what was done]', 'success': true/false}).",
  schedule="at [task_time]",
  action_sets=["proactive", "file_operations"],
  payload={"source": "proactive", "task_id": "[task_id]"}
)
```

Then record that task was scheduled:
```
recurring_update_task(
  task_id="[task_id]",
  add_outcome={"result": "Scheduled for [time]", "success": true}
)
```

### Step 3: Evaluate Each Task

For each task:

1. **Check Conditions**: If the task has conditions, evaluate them:
   - `market_hours_only`: Skip if outside 9:30 AM - 4:00 PM on weekdays
   - `user_available`: Check if user has responded recently
   - Custom conditions as defined

2. **Score Using Rubric**: Evaluate each dimension 1-5 as described above.

3. **Decision**:
   - Score >= 18: Execute the task
   - Score 13-17: Consider executing
   - Score < 13: Skip for this heartbeat

### Step 4: Choose Execution Type (INLINE or SCHEDULED)

For each task that passes evaluation, determine HOW to execute it:

| Criteria | INLINE | SCHEDULED |
|----------|--------|-----------|
| Complexity | Simple, single-step | Multi-step, complex |
| Action sets needed | Available in heartbeat | Requires different sets |
| Duration | Quick | Extended |
| Sub-tasks needed | No | Yes |

### Step 5: Execute Tasks

#### For INLINE Execution:

1. **Check Permission Tier**:
   - **Tier 0 (silent)**: Execute without notification
   - **Tier 1 (notify)**: Notify user with star prefix, then execute immediately

2. **Execute the Task**: Follow the task's instruction using available actions

3. **Record Outcome**: Use `recurring_update_task` to record:
   ```
   recurring_update_task(
     task_id="task_id",
     add_outcome={"result": "Description of what was done", "success": true}
   )
   ```

#### For SCHEDULED Execution:

1. Use `schedule_task` with the instruction that includes the outcome recording requirement:
   ```
   schedule_task(
     name="Weekly Code Review",
     instruction="Perform weekly code review. IMPORTANT: Before ending this task, you MUST call recurring_update_task(task_id='weekly_code_review', add_outcome={'result': '[what was done]', 'success': true/false}) to record the outcome.",
     schedule="immediate",
     action_sets=["code_analysis", "file_operations"],
     skills=[],
     payload={"source": "proactive", "task_id": "weekly_code_review"}
   )
   ```

2. Record that the task was scheduled:
   ```
   recurring_update_task(
     task_id="task_id",
     add_outcome={"result": "Scheduled as separate task (session: xxx)", "success": true}
   )
   ```

### Step 6: Complete

After processing all tasks, end the task silently.

## Rules

- **END SILENTLY** - Always end with `end_turn` without waiting for user confirmation
- **NEVER wait for user** - Notifications only; never end the run on a question that expects an answer
- **NEVER spam users** - Batch notifications when possible
- **Star emoji prefix** - Use for proactive notifications to user
- **Silent on no tasks** - If no tasks match the frequency, end silently
- **Log outcomes** - Always record what happened for each executed task
- **Handle failures gracefully** - If a task fails, log error and continue to next
- **Prefer INLINE execution** - Only use SCHEDULED when truly necessary
- **Always include outcome recording in scheduled task instructions**

## Permission Tier Reference

All recurring proactive tasks use tier 0 or tier 1:

| Tier | Name | Behavior |
|------|------|----------|
| 0 | Silent | Execute without notification |
| 1 | Notify | Notify user then execute immediately |

## Example Flows

### Example 1: INLINE Execution (Daily Briefing)

1. Read tasks: `recurring_read(frequency="all", enabled_only=true)`
2. Find: `daily_morning_briefing` (daily, tier 1, enabled, due now)
3. Score: Impact=4, Risk=5, Cost=4, Urgency=3, Confidence=4 = 20 (execute)
4. Execution type: **INLINE** (simple notification, tier 1)
5. Permission tier 1: Send message with star prefix
6. Execute: Gather weather, calendar, tasks
7. Present briefing to user
8. Record outcome: `recurring_update_task(task_id="daily_morning_briefing", add_outcome={...})`
9. Continue to next due task or end

### Example 2: SCHEDULED Execution (Complex Analysis)

1. Read tasks: `recurring_read(frequency="all", enabled_only=true)`
2. Find: `weekly_code_review` (weekly, tier 1, enabled, today is Sunday, due now)
3. Score: Impact=4, Risk=5, Cost=3, Urgency=2, Confidence=4 = 18 (execute)
4. Execution type: **SCHEDULED** (complex multi-step analysis, needs code_analysis action set)
5. Schedule:
   ```
   schedule_task(
     name="Weekly Code Review",
     instruction="Review code changes from the past week. Analyze for patterns, issues, and improvements. IMPORTANT: Before ending, call recurring_update_task(task_id='weekly_code_review', add_outcome={'result': '[summary of findings]', 'success': true/false}).",
     schedule="immediate",
     action_sets=["code_analysis", "file_operations"],
     payload={"source": "proactive", "task_id": "weekly_code_review"}
   )
   ```
6. Record: `recurring_update_task(task_id="weekly_code_review", add_outcome={"result": "Scheduled as separate task", "success": true})`
7. Continue to next task or end

## Allowed Actions

`recurring_read`, `recurring_update_task`, `send_message`, `memory_search`,
`read_file`, `web_search`, `web_fetch`, `schedule_task`,
`update_todos`, `end_turn`

## Forbidden Actions

Direct file writes to PROACTIVE.md (use `recurring_update_task` instead)
