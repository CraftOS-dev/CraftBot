---
name: heartbeat-processor
description: Process proactive heartbeat triggers by reading PROACTIVE.md and executing due tasks for the current frequency (hourly/daily/weekly/monthly).
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - web_research
  - scheduler
---

# Heartbeat Processor

Silent background skill for executing scheduled proactive tasks. You are activated by a heartbeat trigger (hourly, daily, weekly, or monthly).

## Trigger Context

You receive a heartbeat trigger with:
- `frequency`: The current heartbeat type (hourly, daily, weekly, monthly)
- `type`: "proactive_heartbeat"

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
  mode="complex",
  action_sets=["required", "action", "sets"],
  skills=["relevant-skills"],
  payload={"source": "proactive", "task_id": "[proactive_task_id]"}
)
```

---

## Tiered Permission Model

Use this model to determine if you need user permission to initiate a task:

```
Tier 0 - Silent Read (No Approval Required):
  - Search and summarize information
  - Detect anomalies and patterns
  - Draft recommendations internally
  - Read files and analyze data

Tier 1 - Notify Then Execute (No Approval Required):
  - Notify user with star prefix, then execute immediately
  - Send a proposed plan or draft to user
  - Share analysis results or recommendations

Tier 2 - Act on Low-Risk Tools (Pre-Approved):
  - Create tickets or issues
  - Schedule reminders
  - Open PR drafts
  - Prepare campaign drafts
  - Update internal documents

Tier 3 - High-Risk Actions (Explicit Approval Every Time):
  - Emailing customers or external parties
  - Changing configurations
  - Touching money or financial systems
  - Production deployments
  - Modifying critical systems

Tier 4 - Prohibited:
  - Anything disallowed by policy
  - Actions that could cause irreversible harm
  - Unauthorized access or modifications
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

### Step 1: Read Recurring Tasks

Use `recurring_read` action with the current frequency to get tasks that should run.

```
recurring_read(frequency="daily", enabled_only=true)
```

### Step 2: Filter by Time and Day

For each task returned, check if it should run NOW based on `time` and `day` fields:

**For tasks with a `time` field (e.g., "09:00"):**
- Compare task's `time` with current time
- If current time < task time: **Schedule for later** using `schedule_task` with the specified time, then skip to next task
- If current time >= task time: Continue to evaluate this task

**For tasks with a `day` field (weekly/monthly tasks):**
- Check if today matches the specified day (e.g., "monday", "friday")
- If today does NOT match: **Skip** this task
- If today matches: Continue to evaluate

**Scheduling for later:**
```
schedule_task(
  name="[Task Name]",
  instruction="Execute recurring task: [task_id]. [original instruction]. IMPORTANT: Before ending, call recurring_update_task(task_id='[task_id]', add_outcome={'result': '[what was done]', 'success': true/false}).",
  schedule="at [task_time]",
  mode="complex",
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

### Step 3: Check for Pending Permissions (CRITICAL)

Before evaluating tasks, check each task's `outcome_history` for pending permission requests.

**A task is "pending permission" if:**
- The most recent outcome contains `"permission_pending": true`

**If a task is pending permission:**
- **SKIP** that task entirely - do NOT ask for permission again
- Do NOT execute it
- Move on to the next task

**Example check:**
```
For task "weekly_report":
  outcome_history: [
    {"timestamp": "2024-01-15T10:00:00", "result": "Awaiting user permission", "permission_pending": true}
  ]

  → Most recent outcome has permission_pending=true, SKIP this task
```

### Step 4: Evaluate Each Task

For each task that is NOT pending permission:

1. **Check Conditions**: If the task has conditions, evaluate them:
   - `market_hours_only`: Skip if outside 9:30 AM - 4:00 PM on weekdays
   - `user_available`: Check if user has responded recently
   - Custom conditions as defined

2. **Score Using Rubric**: Evaluate each dimension 1-5 as described above.

3. **Decision**:
   - Score >= 18: Execute the task
   - Score 13-17: Consider executing, may need user input
   - Score < 13: Skip for this heartbeat

### Step 5: Choose Execution Type (INLINE or SCHEDULED)

For each task that passes evaluation, determine HOW to execute it:

| Criteria | INLINE | SCHEDULED |
|----------|--------|-----------|
| Permission tier | 0 or 1 | Any |
| Complexity | Simple, single-step | Multi-step, complex |
| Action sets needed | Available in heartbeat | Requires different sets |
| Duration | Quick | Extended |
| Sub-tasks needed | No | Yes |

### Step 6: Execute Tasks

#### For INLINE Execution:

1. **Check Permission Tier**:
   - **Tier 0 (silent)**: Execute without notification
   - **Tier 1 (notify)**: Notify user with star prefix, then execute immediately (no approval needed)
   - **Tier 2/3 (needs approval)**: See "Requesting Permission" below
   - **Tier 4 (prohibited)**: Never execute

2. **Execute the Task**: Follow the task's instruction using available actions

3. **Record Outcome**: Use `recurring_update_task` to record:
   ```
   recurring_update_task(
     task_id="task_id",
     add_outcome={"result": "Description of what was done", "success": true}
   )
   ```

#### Requesting Permission (Tier 2/3):

When a task requires user permission:

1. **First, record that permission is being requested:**
   ```
   recurring_update_task(
     task_id="task_id",
     add_outcome={
       "result": "Awaiting user permission to execute",
       "success": true,
       "permission_pending": true
     }
   )
   ```

2. **Then ask the user for permission** using `send_message`

3. **If user approves:** Execute the task and record success outcome
4. **If user rejects:** Record rejection outcome with `permission_pending: false`
5. **If no response:** The next heartbeat will see `permission_pending: true` and SKIP (see Step 2)

#### For SCHEDULED Execution:

1. Use `schedule_task` with the instruction that includes the outcome recording requirement:
   ```
   schedule_task(
     name="Weekly Code Review",
     instruction="Perform weekly code review. IMPORTANT: Before ending this task, you MUST call recurring_update_task(task_id='weekly_code_review', add_outcome={'result': '[what was done]', 'success': true/false}) to record the outcome.",
     schedule="immediate",
     mode="complex",
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

### Step 7: Complete

After processing all tasks, end the task silently.

## Rules

- **NEVER spam users** - Batch notifications when possible
- **Respect permission tiers strictly** - Higher tiers require explicit consent
- **Star emoji prefix** - Use for proactive notifications to user
- **Silent on no tasks** - If no tasks match the frequency, end silently
- **Log outcomes** - Always record what happened for each executed task
- **Handle failures gracefully** - If a task fails, log error and continue to next
- **Prefer INLINE execution** - Only use SCHEDULED when truly necessary
- **Always include outcome recording in scheduled task instructions**
- **NEVER re-ask for permission** - If a task is pending permission (check outcome_history), SKIP it

## Permission Tier Reference

| Tier | Name | Behavior |
|------|------|----------|
| 0 | Silent | Execute without notification |
| 1 | Notify | Notify user then execute immediately |
| 2 | Low-risk | Ask permission, proceed if approved |
| 3 | High-risk | Require explicit approval every time |
| 4 | Prohibited | Never execute |

## Example Flows

### Example 1: INLINE Execution (Daily Briefing)

1. Read tasks: `recurring_read(frequency="daily")`
2. Find: `daily_morning_briefing` (tier 1, enabled)
3. Score: Impact=4, Risk=5, Cost=4, Urgency=3, Confidence=4 = 20 (execute)
4. Execution type: **INLINE** (simple notification, tier 1)
5. Permission tier 1: Send message with star prefix
6. Execute: Gather weather, calendar, tasks
7. Present briefing to user
8. Record outcome: `recurring_update_task(task_id="daily_morning_briefing", add_outcome={...})`
9. End task

### Example 2: SCHEDULED Execution (Complex Analysis)

1. Read tasks: `recurring_read(frequency="weekly")`
2. Find: `weekly_code_review` (tier 2, enabled, requires complex analysis)
3. Score: Impact=4, Risk=5, Cost=3, Urgency=2, Confidence=4 = 18 (execute)
4. Execution type: **SCHEDULED** (complex multi-step analysis, needs code_analysis action set)
5. Schedule:
   ```
   schedule_task(
     name="Weekly Code Review",
     instruction="Review code changes from the past week. Analyze for patterns, issues, and improvements. IMPORTANT: Before ending, call recurring_update_task(task_id='weekly_code_review', add_outcome={'result': '[summary of findings]', 'success': true/false}).",
     schedule="immediate",
     mode="complex",
     action_sets=["code_analysis", "file_operations"],
     payload={"source": "proactive", "task_id": "weekly_code_review"}
   )
   ```
6. Record: `recurring_update_task(task_id="weekly_code_review", add_outcome={"result": "Scheduled as separate task", "success": true})`
7. Continue to next task or end

## Allowed Actions

`recurring_read`, `recurring_update_task`, `send_message`, `memory_search`,
`read_file`, `stream_read`, `web_search`, `web_fetch`, `schedule_task`,
`task_update_todos`, `task_end`

## Forbidden Actions

Direct file writes to PROACTIVE.md (use `recurring_update_task` instead)
