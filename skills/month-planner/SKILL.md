---
name: month-planner
description: Monthly planning skill for long-term proactive management, reviewing the month's activities and strategic planning.
user-invocable: false
action-sets:
  - file_operations
  - proactive
---

# Month Planner

Monthly strategic planning for proactive agent behavior. This skill runs on the 1st of each month to review the past month and plan strategically.

## Trigger Context

You receive a planner trigger with:
- `scope`: "month"
- `type`: "proactive_planner"

## Workflow

### Step 1: Monthly Review

Comprehensive review of the past month:

1. **TASK_HISTORY.md** - All tasks completed this month
2. **MEMORY.md** - All learnings and facts
3. **PROACTIVE.md** - Proactive task performance over the month
4. **USER.md** - Any changes to user profile

### Step 2: Strategic Analysis

Analyze long-term patterns:
- **Goal progress**: What long-term goals has the user been working toward?
- **Productivity trends**: Are tasks being completed more efficiently?
- **Proactive effectiveness**: Which proactive tasks delivered most value?
- **User preferences evolution**: Have preferences changed?

### Step 3: Proactive Task Audit

For each proactive task:

| Check | Action |
|-------|--------|
| No runs in 2+ months | Consider removal |
| <20% success rate | Disable and notify |
| Consistent value | Keep and optimize |
| Frequently dismissed | Lower priority or disable |

### Step 4: Archive Old Tasks

Identify and archive:
- One-time tasks that have been completed
- Tasks that have been disabled for >1 month
- Tasks with no activity for >2 months

### Step 5: Monthly Report

Prepare comprehensive monthly report:

```markdown
## Monthly Report - [Month Year]

### Productivity Summary
- Tasks completed: X
- Goals achieved: [list]
- Time saved by proactive tasks: ~Y hours

### Proactive Task Analysis
| Task | Runs | Success Rate | Recommendation |
|------|------|--------------|----------------|
| Morning briefing | 28 | 95% | Keep |
| Weekly review | 4 | 100% | Keep |

### Key Learnings
- [Insight 1]
- [Insight 2]

### Recommendations for Next Month
1. [Recommendation]
2. [Recommendation]

### Goals for Next Month
- [Goal based on user patterns]
```

### Step 6: Update Planner Output

Update PROACTIVE.md:

```markdown
### Month Planner (Month YYYY)
- Reviewed X proactive tasks
- Archived: [list if any]
- Recommendations: [brief list]
- Next month focus: [key area]
```

### Step 7: Present to User

Present the monthly report with star prefix:
- Summary of achievements
- Proactive task performance
- Recommendations
- Ask if user wants to adjust anything

## Rules

- **Monthly presentation required** - User must see the report
- **Star emoji prefix** - Proactive notification indicator
- **Don't auto-archive** - Only suggest archival, don't delete
- **Preserve history** - Keep outcome_history for analysis
- **Be strategic** - Focus on patterns, not individual events

## Monthly Health Metrics

| Aspect | Healthy | Warning | Unhealthy |
|--------|---------|---------|-----------|
| Active proactive tasks | 3-10 | 1-2 or 10-15 | 0 or >15 |
| Average task success | >70% | 50-70% | <50% |
| User engagement | Regular | Sporadic | None |
| Task diversity | Multiple frequencies | Single frequency | All same |

## Allowed Actions

`proactive_read`, `proactive_update_task`, `proactive_remove`, `read_file`,
`stream_read`, `stream_edit`, `memory_search`, `send_message`, `task_update_todos`, `task_end`

## Output Format

Monthly report message to user + planner section update in PROACTIVE.md
