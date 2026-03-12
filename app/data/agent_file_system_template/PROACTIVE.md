---
version: "1.0"
last_updated: null  # Auto-updated by system (format: YYYY-MM-DDTHH:MM:SSZ)
---

# Proactive Tasks

<!--
================================================================================
PROACTIVE MODULE OVERVIEW
================================================================================
This file defines scheduled autonomous tasks that the agent executes without
direct user prompts. The agent reads this file during scheduled heartbeats
and planners to determine what actions to take.

IMPORTANT: Do NOT remove the HTML comment markers (PROACTIVE_TASKS_START, etc.)
as they are used by the parser to locate sections.
================================================================================
-->

---

## How Proactive Tasks Work

You can operate proactively based on scheduled activations. Schedules can be hourly (every X hours), daily (at a specific time), weekly (on a specific day), or monthly (on a specific date).

When a schedule fires, you execute a proactive check workflow. First, read PROACTIVE.md to understand configured proactive tasks and their conditions. Then research the agent file system for relevant context - user preferences, project status, organizational priorities.

---

## Decision Rubric

Evaluate each potential proactive task using a five-dimension rubric. Score each dimension from 1 to 5:

| Dimension   | 1 (Low)        | 5 (High)      | Description                        |
|-------------|----------------|---------------|------------------------------------|
| Impact      | Negligible     | Critical      | How significant is the outcome?    |
| Risk        | High risk      | No risk       | What could go wrong?               |
| Cost        | Very high      | Negligible    | Resources and effort required?     |
| Urgency     | Not urgent     | Immediate     | How time-sensitive?                |
| Confidence  | Unlikely       | Certain       | Will the user accept this?         |

**Scoring Thresholds:**
- **18+**: Strong candidates for execution - proceed
- **13-17**: May need user input first - consider asking
- **<13**: Skip or defer - not worth doing now

---

## Permission Tiers

Each task has a permission tier that controls how it interacts with the user:

| Tier | Level | Description | User Interaction |
|------|-------|-------------|------------------|
| 0 | Silent | Searching, analyzing, drafting, internal operations | Proceed without notifying the user |
| 1 | Notify | Inform user of task execution and findings | Inform and proceed without waiting |
| 2 | Approval | Actions that modify state or create artifacts | Ask for approval before proceeding |
| 3 | High-risk | Email external parties, change configs, sensitive ops | Explicit detailed approval required |

**Note:** Tier 0 and 1 are typically used for user-created proactive tasks. Tiers 2-3 are reserved for system-level or high-impact tasks that require user oversight.

---

## Task Definitions

<!--
================================================================================
TASK FORMAT REFERENCE
================================================================================
Each task follows this structure:

### [FREQUENCY] Task Name
```yaml
id: unique_task_id              # REQUIRED: Unique identifier (snake_case)
frequency: daily                # REQUIRED: hourly | daily | weekly | monthly
time: "09:00"                   # OPTIONAL: Execution time in HH:MM (24hr format)
day: monday                     # OPTIONAL: For weekly tasks (monday-sunday)
                                #           For monthly tasks (1-31)
enabled: true                   # REQUIRED: true | false
priority: 50                    # REQUIRED: 1-100 (lower = higher priority)
permission_tier: 1              # REQUIRED: 0-4 (see Permission Tiers above)
run_count: 0                    # AUTO: Number of times executed
conditions: []                  # OPTIONAL: List of execution conditions
instruction: |                  # REQUIRED: Detailed task instruction (see below)
  Multi-line instruction
  describing the task.
outcome_history: []             # AUTO: Recent execution results (max 5)
```

FREQUENCY OPTIONS:
- hourly:  Runs every hour (time field optional)
- daily:   Runs once per day (time field recommended)
- weekly:  Runs once per week (day + time fields recommended)
- monthly: Runs once per month (day = date 1-31, time field recommended)

CONDITIONS (optional):
- market_hours_only: Only run during market hours
- user_available: Only run when user is active
- weekdays_only: Skip weekends
- Custom conditions can be added as needed

================================================================================
WRITING EFFECTIVE INSTRUCTIONS
================================================================================
The instruction field is the most critical part of a proactive task. Write
detailed, specific instructions that leave no ambiguity about what the agent
should do. Poor instructions lead to poor execution.

INSTRUCTION GUIDELINES:
1. Be specific about WHAT to do - list exact steps, not vague goals
2. Specify WHERE to find information - which files, APIs, or sources to use
3. Define the OUTPUT format - how results should be presented or stored
4. Include SUCCESS CRITERIA - how to know the task is complete
5. Handle EDGE CASES - what to do if data is missing or errors occur
6. Specify USER INTERACTION - when to notify, ask, or wait for response

BAD INSTRUCTION (too vague):
  "Check emails and summarize important ones."

GOOD INSTRUCTION (detailed):
  "1. Connect to user's email via Gmail integration
   2. Fetch unread emails from the last 24 hours
   3. Filter for emails marked as important or from contacts in CONTACTS.md
   4. For each qualifying email, extract: sender, subject, key action items
   5. Compile into a summary with sections: Urgent (needs response today),
      Important (needs response this week), FYI (informational only)
   6. Present summary to user via chat message
   7. If no qualifying emails found, send brief 'inbox clear' notification
   8. Log summary to TASK_HISTORY.md with timestamp"

================================================================================
-->

<!--
================================================================================
HOW TO ADD A NEW RECURRING PROACTIVE TASK
================================================================================
1. Add a new section between PROACTIVE_TASKS_START and PROACTIVE_TASKS_END
2. Use the format: ### [FREQUENCY] Task Name
3. Include a YAML code block with all required fields
4. Write detailed, step-by-step instructions (see WRITING EFFECTIVE INSTRUCTIONS)
5. Set enabled: true when ready to activate
6. The agent will pick up the task on the next heartbeat
================================================================================
-->

<!-- PROACTIVE_TASKS_START -->

<!-- Add your proactive tasks here following the format above -->

<!-- PROACTIVE_TASKS_END -->

---

## Goals, Plan, and Status

<!--
================================================================================
GOALS, PLAN, AND STATUS
================================================================================
This section is maintained by the day/week/month planners to track user goals,
plans, and current status. The planners update this section to help coordinate
proactive assistance across different time horizons.

- Month Planner: Sets long-term goals, strategic direction
- Week Planner: Sets weekly objectives aligned with monthly goals
- Day Planner: Sets daily priorities aligned with weekly objectives

The heartbeat processor and other planners read this section to understand
context and avoid duplicate suggestions.
================================================================================
-->

### Long-Term Goals
<!-- Updated by month planner -->
No long-term goals defined yet.

### Current Focus
<!-- Updated by week/day planner -->
No current focus defined.

### Recent Accomplishments
<!-- Updated by planners after task completion -->
None yet.

### Upcoming Priorities
<!-- Updated by day planner -->
None defined.

---

