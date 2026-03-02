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

## Tiered Permission Model

Use this model to determine if you need user permission to initiate a task:

```
Tier 0 - Silent Read (No Approval Required):
  - Search and summarize information
  - Detect anomalies and patterns
  - Draft recommendations internally
  - Read files and analyze data

Tier 1 - Suggest (Approval to Notify):
  - Send a proposed plan or draft to user
  - Notify user of findings or recommendations
  - Share analysis results

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

### Step 1: Read Proactive Tasks

Use `proactive_read` action with the current frequency to get tasks that should run.

```
proactive_read(frequency="daily", enabled_only=true)
```

### Step 2: Evaluate Each Task

For each task returned:

1. **Check Conditions**: If the task has conditions, evaluate them:
   - `market_hours_only`: Skip if outside 9:30 AM - 4:00 PM on weekdays
   - `user_available`: Check if user has responded recently
   - Custom conditions as defined

2. **Score Using Rubric**: Evaluate each dimension 1-5 as described above.

3. **Decision**:
   - Score >= 18: Execute the task
   - Score 13-17: Consider executing, may need user input
   - Score < 13: Skip for this heartbeat

### Step 3: Determine Execution Type

For each task that passes evaluation, determine HOW to execute it:

**Execute INLINE** (within this heartbeat task) if:
- Permission tier is 0 or 1
- Task instruction can be completed with available actions
- No multi-step reasoning or complex workflows needed
- Examples: send notification, search information, read and summarize

**Schedule as SEPARATE TASK** if:
- Task requires complex multi-step execution
- Task may need to spawn sub-tasks
- Task requires different action sets than heartbeat-processor has
- Task runs extended operations that shouldn't block heartbeat
- Examples: comprehensive research task, multi-file analysis, web scraping

To schedule a separate task, use:
```
schedule_add(
  name="[Task Name from PROACTIVE.md]",
  instruction="[Task instruction from PROACTIVE.md]",
  schedule="immediate",
  mode="complex",
  action_sets=["required", "action", "sets"],
  skills=["relevant-skills"],
  payload={"source": "proactive", "task_id": "[proactive_task_id]"}
)
```

### Step 4: Execute or Schedule Qualifying Tasks

For tasks you decide to execute INLINE:

1. **Check Permission Tier**:
   - **Tier 0 (silent)**: Execute without notification
   - **Tier 1 (suggest)**: Notify user with star prefix, wait for acknowledgment
   - **Tier 2 (low-risk)**: Inform user and proceed unless objected
   - **Tier 3 (high-risk)**: Request explicit approval first
   - **Tier 4 (prohibited)**: Never execute

2. **Execute the Task**: Follow the task's instruction using available actions

3. **Record Outcome**: Use `proactive_update_task` to record:
   ```
   proactive_update_task(
     task_id="task_id",
     add_outcome={"result": "Description of what was done", "success": true}
   )
   ```

For tasks you decide to SCHEDULE:

1. Use `schedule_add` with `schedule="immediate"` as shown above
2. Record outcome as "scheduled" with the session_id:
   ```
   proactive_update_task(
     task_id="task_id",
     add_outcome={"result": "Scheduled as separate task (session: xxx)", "success": true}
   )
   ```

### Step 5: Complete

After processing all tasks, end the task silently.

## Rules

- **NEVER spam users** - Batch notifications when possible
- **Respect permission tiers strictly** - Higher tiers require explicit consent
- **Star emoji prefix** - Use for proactive notifications to user
- **Silent on no tasks** - If no tasks match the frequency, end silently
- **Log outcomes** - Always record what happened for each executed task
- **Handle failures gracefully** - If a task fails, log error and continue to next
- **Prefer inline execution** - Only schedule separate tasks when truly necessary

## Permission Tier Reference

| Tier | Name | Behavior |
|------|------|----------|
| 0 | Silent | Execute without asking |
| 1 | Suggest | Notify and wait for acknowledgment |
| 2 | Low-risk | Inform and proceed unless objected |
| 3 | High-risk | Require explicit approval |
| 4 | Prohibited | Never execute |

## Example Flow

**Daily heartbeat at 7:00 AM:**

1. Read tasks: `proactive_read(frequency="daily")`
2. Find: `daily_morning_briefing` (tier 1, enabled)
3. Score: Impact=4, Risk=5, Cost=4, Urgency=3, Confidence=4 = 20 (execute)
4. Execution type: INLINE (simple notification, tier 1)
5. Permission tier 1: Send message with star prefix
6. Execute: Gather weather, calendar, tasks
7. Present briefing to user
8. Record outcome: `proactive_update_task(task_id="daily_morning_briefing", add_outcome={...})`
9. End task

**Example with scheduled task:**

1. Read tasks: `proactive_read(frequency="weekly")`
2. Find: `weekly_code_review` (tier 2, enabled, requires complex analysis)
3. Score: Impact=4, Risk=5, Cost=3, Urgency=2, Confidence=4 = 18 (execute)
4. Execution type: SCHEDULE (complex multi-step analysis)
5. Schedule: `schedule_add(name="Weekly Code Review", instruction="...", schedule="immediate", mode="complex", ...)`
6. Record outcome: `proactive_update_task(task_id="weekly_code_review", add_outcome={"result": "Scheduled as separate task", "success": true})`
7. Continue to next task or end

## Allowed Actions

`proactive_read`, `proactive_update_task`, `send_message`, `memory_search`,
`read_file`, `stream_read`, `web_search`, `web_fetch`, `schedule_add`,
`task_update_todos`, `task_end`

## Forbidden Actions

Direct file writes to PROACTIVE.md (use `proactive_update_task` instead)
