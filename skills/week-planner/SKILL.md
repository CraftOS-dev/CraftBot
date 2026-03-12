---
name: week-planner
description: Weekly planning skill that reviews the week's activities, scans external environment, identifies patterns, and plans proactive tasks for the coming week.
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - scheduler
  - google_calendar
  - notion
  - web
---

# Week Planner

Weekly review and planning for proactive task management. This skill runs on Sundays to review the past week and plan ahead.

## Trigger Context

You receive a planner trigger with:
- `scope`: "week"
- `type`: "proactive_planner"

## Core Question

Ask yourself: **"How can I help the user get SLIGHTLY closer to their goals THIS WEEK?"**

Focus only on what can realistically be accomplished in a single week. Leave long-term strategic planning to the month planner.

---

## CRITICAL RULES

### Before Planning - ALWAYS Do These Checks

1. **Check existing scheduled tasks**: Use `scheduled_task_list` to see what's already scheduled
2. **Read PROACTIVE.md**: Check existing recurring tasks and the Goals, Plan, and Status section
3. **Read TASK_HISTORY.md**: See what tasks have already been completed this week
4. **Read MEMORY.md**: Understand user context, preferences, and patterns

### Duplicate Prevention

- **NEVER suggest a task the user has already performed** (check TASK_HISTORY.md)
- **NEVER suggest a task that already exists** as a recurring or scheduled task

### Permission Requirements

- **Recurring tasks**: MUST get explicit user permission before adding
- **Immediate/Scheduled tasks**: MUST get user permission unless tier 0

### Conservatism Principle

It should be **HARD** for you to suggest new tasks. Only suggest if:
- User explicitly requested it, OR
- User has done this manually multiple times, OR
- User mentioned it as a pain point

**Your assumptions about what user "might want" are NOT valid reasons to suggest.**

---

## Guiding Principles

**Evidence over assumption**: Only act on what user has said or done, never on what you think they might want.

**Silence over noise**: Most weeks should have minimal new suggestions. Focus on the weekly summary.

**Quality over quantity**: One genuinely valuable suggestion beats five mediocre ones.

**Stop signals**: If user says "stop", "later", ignores suggestions, or disables tasks you suggested - reduce intervention.

**Know the user, not the universe**: Only check external sources relevant to THIS user based on their profile and demonstrated interests.

---

## Context Layers

```
Layer 1: WHO is the user? (USER.md - static profile)
    ↓
Layer 2: WHAT's their situation? (PROACTIVE.md - dynamic context)
    ↓
Layer 3: WHAT's happening now? (External sources - selective)
```

Use Layer 1 + Layer 2 to determine which external sources to check in Layer 3.

---

## Workflow

### Step 1: Weekly Review (Internal)

Gather and analyze the week's data:

1. **TASK_HISTORY.md** - Tasks completed this week
2. **MEMORY.md** - Learnings and facts recorded this week
3. **PROACTIVE.md** - Recurring task execution history and Goals/Plan/Status
4. **USER.md** - User preferences and context
5. **scheduled_task_list** - What's currently scheduled

### Step 2: Scan External Environment (Selective)

Based on USER.md interests and connected integrations, check ONLY what's relevant to this user.

**Calendar & Schedule** (if Google Calendar connected):
```
check_calendar_availability(start_date="[week_start]", end_date="[week_end]")
```
- Note: meeting patterns, busy days, recurring events
- Identify: heavy meeting days vs. focus time available
- Look for: upcoming deadlines, travel, important events

**Task Management** (check all connected tools):
```
IF Notion connected:
  search_notion(query="tasks")
  query_notion_database(database_id="[task_db_id]")
  → Gather: all pending tasks, overdue items, upcoming deadlines

IF Apple Reminders (macOS):
  remindctl week
  remindctl overdue
```
- Summarize: task distribution across the week
- Note: any backlog building up

**Communication Patterns** (if user engages):
```
IF Gmail connected:
  → Note patterns: response times, pending threads

IF Slack connected:
  → Note: team activity patterns, recurring requests
```

**Weekly Context** (based on user interests):
```
IF user has projects with external dependencies:
  → Check project status, blockers

IF user mentioned upcoming events (conference, travel, deadline):
  → Gather relevant information

IF user works in specific domain:
  → Check relevant weekly news/updates ONLY if they've engaged before
```

**SKIP if:**
- User has never used the integration
- User ignored suggestions from this source
- No evidence user cares about this domain

### Step 3: Pattern Analysis

Identify (with evidence only):
- **Repeated requests**: User asked for similar things multiple times
- **Manual work**: Tasks user did manually that could be automated
- **Successful automation**: Recurring tasks that delivered value
- **Failed automation**: Tasks user ignored or disabled
- **External engagement**: Which integrations did user actually use this week?
- **Information value**: What external info did user engage with vs. ignore?

### Step 4: Evaluate Recurring Tasks

For each recurring task, assess effectiveness:
- Is it being executed as expected?
- Is user engaging with the results?
- Has user given positive or negative feedback?

If a task is consistently ignored or disabled, consider suggesting to disable it.

### Step 5: Prepare Weekly Summary

Create summary including:
- Tasks completed this week (from TASK_HISTORY.md)
- Progress toward goals (from Goals section)
- Recurring task performance (if any)
- External context (calendar load, task backlog, relevant events)
- Focus for next week

---

## Updating PROACTIVE.md

Weave internal and external context naturally into the existing sections. **Do NOT create new subsections.**

### Current Focus (Primary Responsibility)

```markdown
### Current Focus
<!-- Updated by week/day planner -->
This week: Final push on Q1 launch. Calendar shows Mon-Wed heavy with meetings (6 total), Thu-Fri clear for focused work.

Key objectives:
- Complete code review backlog (3 PRs pending in GitHub)
- Finalize launch checklist (7 items remaining in Notion)

**Context:** User traveling next week - front-load deliverables. Weather clear for commute runs Mon/Tue.
```

Guidelines:
- Include external context (calendar patterns, task counts)
- Note situational factors (travel, deadlines, events)
- Connect to Long-Term Goals
- Maximum 2-3 objectives

### Recent Accomplishments

```markdown
### Recent Accomplishments
<!-- Updated by planners after task completion -->
- [Week N]: [Major accomplishment]
```

Guidelines:
- Summarize the week's achievements
- Focus on goal-related progress
- Keep last 4-5 weeks

### Recording Patterns (Inline)

When you observe patterns from internal + external analysis, record them inline:

```markdown
**Observed patterns:**
- User most active 9-11am, prefers no interruptions
- Heavy meeting days (Mon/Wed) correlate with lower task completion
- User engages with GitHub notifications within 1 hour
- User ignores LinkedIn notifications - deprioritize
```

Do NOT create a dedicated "Patterns" subsection. Weave into existing sections.

### Long-Term Goals (READ ONLY)

The week planner READS Long-Term Goals but does NOT update them. Only the month planner updates Long-Term Goals.

---

## Updating MEMORY.md

Update MEMORY.md with:
- Patterns observed over the week
- User preferences discovered
- Important learnings
- Behavioral changes

**Do NOT store**: Daily minutiae, temporary states, duplicates, your assumptions.

---

## Outputs

### Output 1: Weekly Summary Message (REQUIRED)

Send weekly summary to user via `send_message` with star prefix.

### Output 2: Update PROACTIVE.md

Update "Current Focus" and "Recent Accomplishments".

### Output 3: Update MEMORY.md

Record weekly patterns and observations.

### Output 4: Manage Recurring Tasks (RARE - WITH PERMISSION)

Only if user explicitly requested automation:

```
recurring_add(
  name="Task Name",
  frequency="weekly",
  instruction="...",
  day="monday",
  time="09:00",
  permission_tier=1,
  enabled=true
)
```

### Output 5: Audit Recurring Tasks

If a task is consistently ignored or user rejected it:

```
recurring_update_task(
  task_id="ineffective_task",
  updates={"enabled": false}
)
```

**Note:** You MUST inform user when disabling a task.

---

## Allowed Actions

**Core:** `recurring_read`, `recurring_add`, `recurring_update_task`, `scheduled_task_list`,
`schedule_task`, `read_file`, `stream_read`, `stream_edit`, `memory_search`,
`send_message`, `task_update_todos`, `task_end`

**External Integrations (use selectively based on user):**
- Calendar: `check_calendar_availability`
- Notion: `search_notion`, `query_notion_database`, `get_notion_page`
- Web: `web_search`, `web_fetch`

## Output Format

1. Weekly summary message to user (required)
2. Update "Goals, Plan, and Status" section in PROACTIVE.md
3. Update MEMORY.md with weekly observations
4. (Rarely, with permission) Add or update recurring tasks
5. (Rarely) Disable ineffective tasks with notification
