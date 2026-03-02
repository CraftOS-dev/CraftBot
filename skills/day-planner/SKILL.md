---
name: day-planner
description: Daily planning skill that reviews recent interactions, identifies tasks for today, and updates PROACTIVE.md planner section.
user-invocable: false
action-sets:
  - file_operations
  - proactive
---

# Day Planner

Plan the day's proactive activities based on past interactions and current context. This skill runs before the daily heartbeat to prepare the day's plan.

## Trigger Context

You receive a planner trigger with:
- `scope`: "day"
- `type`: "proactive_planner"

## Workflow

### Step 1: Gather Context

Read the following files to understand current state:

1. **USER.md** - User profile, preferences, location
2. **MEMORY.md** - Recent memories and learnings
3. **TASK_HISTORY.md** - Recently completed tasks
4. **PROACTIVE.md** - Current proactive tasks via `proactive_read`

### Step 2: Analyze Today's Context

Consider:
- What day of the week is it?
- Are there any daily tasks enabled?
- What did the user work on yesterday?
- Are there any upcoming deadlines or events from memory?
- What is the user's current focus area?

### Step 3: Prepare Day Plan

Create a concise day plan including:
- Tasks scheduled for today
- Recommended priorities based on context
- Any proactive tasks that should run

### Step 4: Update Planner Output

Use file operations to update the planner outputs section of PROACTIVE.md:

```markdown
### Day Planner (YYYY-MM-DD)
- Priority tasks: [list]
- Scheduled proactive tasks: [list]
- Context notes: [brief notes]
```

### Step 5: Prepare Morning Briefing (Optional)

If `daily_morning_briefing` task is enabled, prepare briefing content:
- Weather for user location
- Calendar/schedule summary
- Top priority items

Store this preparation for the heartbeat processor to use.

## Rules

- **Run silently** - Do not message user unless there's an important finding
- **Be concise** - Day plan should be scannable
- **Review last 3 days** - Look at recent patterns
- **Don't over-plan** - Focus on 3-5 key items max
- **Respect user preferences** - Check USER.md for work hours, preferences

## Context Sources

| Source | Purpose |
|--------|---------|
| USER.md | User profile, location, preferences |
| MEMORY.md | Recent learnings and facts |
| TASK_HISTORY.md | What was completed recently |
| PROACTIVE.md | Current proactive task configuration |

## Allowed Actions

`proactive_read`, `read_file`, `stream_read`, `stream_edit`, `memory_search`,
`task_update_todos`, `task_end`

## Output Format

Update PROACTIVE.md planner section:

```markdown
### Day Planner (2026-02-26)
- Morning briefing scheduled at 7:00 AM
- Priority: Complete quarterly report review
- Note: User mentioned deadline Friday for report
```
