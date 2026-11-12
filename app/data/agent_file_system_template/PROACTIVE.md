---
version: "1.0"
last_updated: null  # Auto-updated by system (format: YYYY-MM-DDTHH:MM:SSZ)
---

# Proactive

<!--
================================================================================
PROACTIVE MODULE OVERVIEW
================================================================================
This file drives what the agent does without a user prompt. It has three parts:
- Cron Jobs: jobs that run at their own set time.
- Heartbeat: a checklist the agent goes through on every heartbeat tick.
- Goals, Plan, and Status: kept up to date by the day/week/month planners.

IMPORTANT: Do NOT remove the HTML comment markers (CRON_JOBS_START,
HEARTBEAT_START, etc.) as they are used by the parser to locate sections.
================================================================================
-->

---

## How It Works

- **Cron Jobs** run at their own slot: hourly at :MM, daily at HH:MM, weekly on a day at HH:MM, or monthly on a date at HH:MM. When one or more jobs are due, CraftBot starts a run in the main chat whose instruction lists exactly those jobs. A slot missed while CraftBot was off runs once, late, when it is back.
- **Heartbeat**: on every heartbeat tick (every 30 minutes by default, set in Settings > Proactive), if the Heartbeat checklist below is not empty, the agent reads it, checks each item and reports only what needs attention. An empty checklist means no heartbeat runs.
- **Goals, Plan, and Status** is maintained by the planners, which also send the user a short brief.

---

## Decision Rubric

Evaluate each cron job before running it using a five-dimension rubric. Score each dimension from 1 to 5:

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

Each cron job has a permission tier that controls how it interacts with the user:

| Tier | Level | Description | User Interaction |
|------|-------|-------------|------------------|
| 0 | Silent | Searching, analyzing, drafting, internal operations | Report only when something needs attention |
| 1 | Notify | Inform user of the job's results | Report the result |

---

## Cron Jobs

<!--
================================================================================
CRON JOB FORMAT REFERENCE
================================================================================
Each cron job follows this structure:

### [FREQUENCY] Job Name
```yaml
id: unique_job_id               # REQUIRED: Unique identifier (snake_case)
frequency: daily                # REQUIRED: hourly | daily | weekly | monthly
time: "09:00"                   # OPTIONAL: Slot time HH:MM (24hr, default 00:00)
                                #           Hourly jobs use only the minute
day: monday                     # OPTIONAL: For weekly jobs (monday-sunday)
                                #           For monthly jobs (1-31)
enabled: true                   # REQUIRED: true | false
priority: 50                    # REQUIRED: 1-100 (lower = higher priority)
permission_tier: 1              # REQUIRED: 0 (silent) or 1 (notify)
run_count: 0                    # AUTO: Number of times run
active_since: ...               # AUTO: When the current schedule took effect
last_run: ...                   # AUTO: When the job last ran
conditions: []                  # OPTIONAL: List of conditions to check first
instruction: |                  # REQUIRED: Detailed job instruction (see below)
  Multi-line instruction
  describing the job.
outcome_history: []             # AUTO: Recent results (max 5)
```

FREQUENCY OPTIONS:
- hourly:  Runs once an hour, at the minute of `time` (default :00)
- daily:   Runs once a day at `time`
- weekly:  Runs once a week on `day` (default monday) at `time`
- monthly: Runs once a month on `day` (1-31, default 1; clamped to the
           month's last day) at `time`

CONDITIONS (optional):
- market_hours_only: Only run during market hours
- user_available: Only run when user is active
- weekdays_only: Skip weekends
- Custom conditions can be added as needed

================================================================================
WRITING EFFECTIVE INSTRUCTIONS
================================================================================
The instruction field is the most critical part of a cron job. Write
detailed, specific instructions that leave no ambiguity about what the agent
should do. Poor instructions lead to poor execution.

INSTRUCTION GUIDELINES:
1. Be specific about WHAT to do - list exact steps, not vague goals
2. Specify WHERE to find information - which files, APIs, or sources to use
3. Define the OUTPUT format - how results should be presented or stored
4. Include SUCCESS CRITERIA - how to know the job is complete
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
HOW TO ADD A NEW CRON JOB
================================================================================
1. Add a new section between CRON_JOBS_START and CRON_JOBS_END
2. Use the format: ### [FREQUENCY] Job Name
3. Include a YAML code block with all required fields
4. Write detailed, step-by-step instructions (see WRITING EFFECTIVE INSTRUCTIONS)
5. Set enabled: true when ready to activate
6. The job first runs at its next slot after the file was saved
================================================================================
-->

<!-- CRON_JOBS_START -->

<!-- Add your cron jobs here following the format above -->

<!-- CRON_JOBS_END -->

---

## Heartbeat

<!--
================================================================================
HEARTBEAT CHECKLIST
================================================================================
On every heartbeat tick (every 30 minutes by default, set in Settings >
Proactive), if this checklist is not empty, the agent reads it, checks each
item and reports only what needs attention. Write one item per line. Use it
for things to keep an eye on; work that must happen at a set time belongs in
Cron Jobs. Leave it empty and the heartbeat does not run.
================================================================================
-->

<!-- HEARTBEAT_START -->

<!-- Add what the heartbeat should check, one item per line, e.g.
- Check my inbox for urgent email from clients -->

<!-- HEARTBEAT_END -->

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

