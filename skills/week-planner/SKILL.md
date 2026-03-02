---
name: week-planner
description: Weekly planning skill that reviews the week's activities, identifies patterns, and plans proactive tasks for the coming week.
user-invocable: false
action-sets:
  - file_operations
  - proactive
---

# Week Planner

Weekly review and planning for proactive task management. This skill runs on Sundays to review the past week and plan ahead.

## Trigger Context

You receive a planner trigger with:
- `scope`: "week"
- `type`: "proactive_planner"

## Workflow

### Step 1: Weekly Review

Gather and analyze the week's data:

1. **TASK_HISTORY.md** - Tasks completed this week
2. **MEMORY.md** - Learnings and facts recorded this week
3. **PROACTIVE.md** - Proactive task execution history
4. **EVENT_UNPROCESSED.md** (if exists) - Recent interactions

### Step 2: Pattern Analysis

Identify:
- **Recurring requests**: Did the user ask for similar things multiple times?
- **Missed opportunities**: Tasks that could have been proactive
- **Successful proactive tasks**: What worked well?
- **Failed or skipped tasks**: What didn't work?

### Step 3: Evaluate Proactive Tasks

For each existing proactive task:
- Check `run_count` and `outcome_history`
- Calculate success rate
- Identify tasks with low engagement (user often dismisses)
- Identify tasks that consistently deliver value

### Step 4: Propose New Tasks

Based on patterns found:
- Identify potential new proactive tasks
- These should be based on actual user behavior, not assumptions
- New tasks should have permission_tier of at least 1 (require acknowledgment)

### Step 5: Prepare Weekly Summary

Create a summary for the user including:
- Tasks completed this week
- Key learnings or achievements
- Proactive task performance
- Recommendations for next week

### Step 6: Update Planner Output

Update PROACTIVE.md planner section:

```markdown
### Week Planner (Week N, YYYY)
- Completed tasks: X
- Proactive task success rate: Y%
- Goals for next week: [list]
- Recommended new proactive tasks: [list if any]
```

### Step 7: Present to User

Use `send_message` with star prefix to present the weekly summary:

**Message format:**
```
Weekly Review (Week N)

Completed: X tasks
Key achievements: [brief list]

Proactive Task Performance:
- Morning briefing: 5/7 days executed
- [other tasks...]

Recommendations:
- [any suggestions]

Would you like me to adjust any proactive tasks?
```

## Rules

- **Weekly presentation required** - User should see the weekly summary
- **Star emoji prefix** - Indicate this is a proactive notification
- **Ask before adding new tasks** - Never auto-add proactive tasks
- **Disable ineffective tasks** - Suggest disabling tasks with <30% engagement
- **Be data-driven** - Base recommendations on actual history

## Proactive Task Effectiveness Metrics

| Metric | Good | Needs Attention | Consider Disabling |
|--------|------|-----------------|-------------------|
| Execution rate | >80% | 50-80% | <50% |
| User engagement | High | Medium | Low/Dismissed |
| Value delivered | Clear | Unclear | None |

## Allowed Actions

`proactive_read`, `proactive_update_task`, `read_file`, `stream_read`, `stream_edit`,
`memory_search`, `send_message`, `task_update_todos`, `task_end`

## Output Format

Weekly summary message to user + planner section update in PROACTIVE.md
