---
name: day-planner
description: Daily planning skill that reviews recent interactions, scans external environment, identifies tasks for today, and updates the Goals, Plan, and Status section in PROACTIVE.md.
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - scheduler
  - google_calendar
  - notion
  - web
---

# Day Planner

Daily planning for proactive agent behavior. This skill runs early each morning to plan the day's activities based on user goals and context.

## Trigger Context

You receive a planner trigger with:
- `scope`: "day"
- `type`: "proactive_planner"

## Core Question

Ask yourself: **"How can I help the user get SLIGHTLY closer to their goals TODAY?"**

Focus only on what can realistically be accomplished in a single day. Do not over-plan.

---

## CRITICAL RULES

### Before Planning - ALWAYS Do These Checks

1. **Check existing scheduled tasks**: Use `scheduled_task_list` to see what's already scheduled
2. **Read PROACTIVE.md**: Check existing recurring tasks and the Goals, Plan, and Status section
3. **Read TASK_HISTORY.md**: See what tasks have already been completed
4. **Read MEMORY.md**: Understand user context, preferences, and past interactions

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

**Silence over noise**: Most days should have NO new suggestions. Better to do nothing than annoy.

**Quality over quantity**: One genuinely valuable suggestion per week beats five mediocre ones per day.

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

### Step 1: Gather Internal Context

Read the following files:

1. **USER.md** - User profile, preferences, location, work hours
2. **MEMORY.md** - Recent memories, learnings, user preferences
3. **TASK_HISTORY.md** - Recently completed tasks (to avoid duplicates!)
4. **PROACTIVE.md** - Current recurring tasks and Goals/Plan/Status via `recurring_read`

Also check:
- `scheduled_task_list` - What's already scheduled (to avoid duplicates!)

### Step 2: Scan External Environment (Selective)

Based on USER.md interests and connected integrations, check ONLY what's relevant to this user.

**Calendar & Schedule** (if Google Calendar connected):
```
check_calendar_availability(start_date="today", end_date="today")
```
- Note: meetings, busy times, deadlines for today
- Look for: conflicts, free blocks for focused work

**Task Management** (check what's connected):
```
IF Notion connected:
  search_notion(query="tasks")
  query_notion_database(database_id="[task_db_id]", filter={"property": "Status", "select": {"does_not_equal": "Done"}})

IF Apple Reminders (macOS):
  remindctl today
  remindctl overdue
```
- Note: overdue items, high-priority tasks due today

**Communication** (only if user engages with these):
```
IF Gmail connected AND user checks email regularly:
  → Note unread important emails, deadline mentions

IF Slack connected AND user uses actively:
  → Note urgent DMs or mentions
```

**Real-Time Context** (based on user interests from USER.md):
```
IF user has outdoor activities planned:
  → Check today's weather

IF user is traveling:
  → Check destination info relevant to today

IF user works in specific domain (tech, finance, etc.):
  → Check relevant news ONLY if they've engaged with it before
```

**SKIP if:**
- User has never mentioned or used the integration
- User has ignored suggestions from this source before
- No evidence user cares about this domain

### Step 3: Analyze Today's Context

Consider from internal files:
- What day of the week is it?
- What are the user's long-term goals? (from Goals, Plan, and Status)
- What did the user work on yesterday? (from TASK_HISTORY.md)
- Are there any recurring tasks enabled for today?
- What is the user's current focus area?

Consider from external scan:
- What meetings/events does user have today?
- Are there overdue tasks from connected tools?
- Any conflicts or scheduling issues?
- Any external factors affecting today (weather, news, etc.)?

### Step 4: Plan the Day

Create a concise day plan focusing on:
- **Daily priorities**: 1-3 key items aligned with weekly objectives
- **Recurring tasks due today**: What will run automatically
- **Context notes**: Brief notes relevant to today

---

## Updating PROACTIVE.md

Weave internal and external context naturally into the existing sections. **Do NOT create new subsections.**

### Upcoming Priorities (Primary Responsibility)

```markdown
### Upcoming Priorities
<!-- Updated by day planner -->
Today (March 12):
- Complete API review before 2pm client call
- 3 overdue Notion tasks from Project Alpha - address in morning
- PR #142 needs review (CI passing)

Today's context: 3 meetings (10am, 2pm, 4pm). Morning and late afternoon clear for focused work. Weather: rain - user's outdoor run may need indoor alternative.
```

Guidelines:
- Include external context inline (meetings, deadlines from tools)
- Note relevant environmental factors (weather, travel)
- Maximum 3-5 priorities with context
- Connect to weekly/monthly goals

### Current Focus (Secondary)

```markdown
### Current Focus
<!-- Updated by week/day planner -->
[What the user should focus on today]
```

Guidelines:
- Align with week planner's direction
- Update only if today requires different focus

### Recent Accomplishments

```markdown
### Recent Accomplishments
<!-- Updated by planners after task completion -->
- [Date]: [Accomplishment]
```

Guidelines:
- Only add if user completed something significant
- Keep last 5-7 entries

### Recording Patterns (Inline)

When you observe patterns, record them inline in existing sections:

```markdown
**Observed:** User most productive 9-11am. Prefers no interruptions during this window.
**Observed:** User engages with tech news but ignores crypto updates.
```

Do NOT create a dedicated "Patterns" or "Context Notes" subsection.

---

## Updating MEMORY.md

Update MEMORY.md when you discover:
- User preferences not previously recorded
- Important context for future tasks
- Patterns in user behavior
- Deadlines or commitments user mentioned

**Do NOT store**: Your assumptions, temporary info, trivial details, duplicates.

---

## Outputs

### Output 1: Update PROACTIVE.md

Update "Upcoming Priorities" and optionally "Current Focus" and "Recent Accomplishments".

### Output 2: Update MEMORY.md

Only if you discovered important context during analysis.

### Output 3: Manage Recurring Tasks (RARE - WITH PERMISSION)

Only if user explicitly requested automation:

```
recurring_add(
  name="Task Name",
  frequency="daily",
  instruction="...",
  time="09:00",
  permission_tier=1,
  enabled=true
)
```

### Output 4: Schedule Tasks (RARE - WITH PERMISSION)

Only if user would genuinely benefit and timing is appropriate:

```
schedule_task(
  name="Evening Reminder",
  instruction="...",
  schedule="at 8pm",
  mode="simple"
)
```

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

1. Update "Goals, Plan, and Status" section in PROACTIVE.md
2. Update MEMORY.md if relevant context discovered
3. (Rarely, with permission) Add recurring tasks if truly necessary
4. (Rarely, with permission) Schedule tasks if truly necessary
