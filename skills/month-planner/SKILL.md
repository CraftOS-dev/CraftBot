---
name: month-planner
description: Monthly planning skill for long-term proactive management, reviewing the month's activities, scanning external environment, setting strategic goals, and providing context for weekly and daily planners.
user-invocable: false
action-sets:
  - file_operations
  - proactive
  - scheduler
  - google_calendar
  - notion
  - web
---

# Month Planner

Monthly strategic planning for proactive agent behavior. This skill runs on the 1st of each month to review the past month, set long-term goals, and provide strategic direction for weekly and daily planners.

## Trigger Context

You receive a planner trigger with:
- `scope`: "month"
- `type`: "proactive_planner"

## Core Question

Ask yourself: **"What long-term goals should the user work toward, and how can I help them get SLIGHTLY closer THIS MONTH?"**

Focus on strategic direction and long-term thinking. Your output provides context for the weekly and daily planners to make tactical decisions.

---

## CRITICAL RULES

### Before Planning - ALWAYS Do These Checks

1. **Check existing scheduled tasks**: Use `scheduled_task_list` to see what's already scheduled
2. **Read PROACTIVE.md**: Check existing recurring tasks and the Goals, Plan, and Status section
3. **Read TASK_HISTORY.md**: See what tasks have been completed this month
4. **Read MEMORY.md**: Understand long-term patterns and user context
5. **Read USER.md**: Understand user's profile, preferences, and stated goals

### Duplicate Prevention

- **NEVER suggest a task the user has already performed** (check TASK_HISTORY.md)
- **NEVER suggest a task that already exists** as a recurring or scheduled task

### Permission Requirements

- **Recurring tasks**: MUST get explicit user permission before adding
- **Goal changes**: Should reflect what user has expressed, not your ideas

### Conservatism Principle

It should be **HARD** for you to:
- Add new recurring tasks (only if explicitly requested)
- Suggest new goals (only if user has expressed them)
- Change existing goals (only with user confirmation)

**DO NOT assume what the user wants** - only work with what they've told you.

---

## Guiding Principles

**Evidence over assumption**: Goals come from user's explicit statements or demonstrated behavior, never from your inference.

**Stability over optimization**: Goals shouldn't change frequently. Prefer stability.

**User autonomy**: Reflect user's stated priorities, don't impose new ones.

**Stop signals**: If user ignores monthly reports or dismisses suggestions - reduce intervention.

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

## Understanding User Goals

### Where Do Goals Come From?

Goals should come from these sources (in order of priority):

1. **User explicitly stated**: "I want to learn Python this year"
2. **User repeatedly works on**: User does coding exercises weekly
3. **User mentioned wanting**: "I should really organize my files"
4. **User asked for help with**: "Help me track my reading habit"

**INVALID source**: Your inference ("User might want to exercise more")

### Goal Quality

Before setting ANY long-term goal, verify:
- User explicitly stated or clearly demonstrated this goal
- Goal is something user actively works toward (evidence in TASK_HISTORY)
- Goal is within scope of what agent can help with
- Goal hasn't been abandoned by user

---

## Workflow

### Step 1: Monthly Review (Internal)

Comprehensive review of the past month:

1. **TASK_HISTORY.md** - All tasks completed this month
2. **MEMORY.md** - All learnings, patterns, and user statements
3. **PROACTIVE.md** - Recurring task performance
4. **USER.md** - User profile and stated goals
5. **scheduled_task_list** - Current scheduled tasks

### Step 2: Scan External Environment (Selective)

Based on USER.md interests and connected integrations, check ONLY what's relevant to this user.

**Calendar & Schedule** (if Google Calendar connected):
```
check_calendar_availability(start_date="[month_start]", end_date="[month_end]")
```
- Note: major events, recurring patterns, travel
- Identify: heavy periods, holidays, deadlines
- Look for: strategic planning opportunities (conferences, reviews)

**Task Management - Goal Progress** (check all connected tools):
```
IF Notion connected:
  → Review project databases for completion rates
  → Check goal-tracking databases if they exist
  → Summarize: tasks completed vs. created this month

IF Apple Reminders:
  remindctl completed
  → Review what was accomplished
```
- Analyze: goal progress across all connected tools
- Note: areas where user is making progress vs. stalling

**Long-Term External Factors** (based on user interests):
```
IF user has career goals:
  → Note relevant industry trends, opportunities

IF user has health/fitness goals:
  → Note seasonal factors (weather patterns for next month)

IF user has financial goals:
  → Note relevant market conditions (only if user has engaged before)

IF user has learning goals:
  → Check progress on connected learning platforms if any
```

**Seasonal/Calendar Factors:**
```
- Upcoming holidays in user's location
- Seasonal changes affecting user's routines
- Annual events relevant to user (tax season, reviews, renewals)
```

**Integration Usage Review:**
- Which integrations did user actually engage with this month?
- Which were connected but unused? (consider deprioritizing)
- Which delivered value vs. noise?

**SKIP if:**
- User has never engaged with the integration
- User has ignored suggestions from this domain all month
- No evidence user cares about this area

### Step 3: Evidence Gathering

For each potential goal or recommendation, document:
- **Source**: Where did this come from? (internal files OR external tools)
- **Evidence**: What proves user wants this?
- **Frequency**: How often does user work on this?
- **Explicit**: Did user state this directly?
- **External support**: What do connected tools show about progress?

If you can't fill these in → do not include.

### Step 4: Strategic Analysis

Analyze long-term patterns from internal + external sources:
- **Goal progress**: What goals has user been working toward? (evidence from both internal files AND external tools)
- **Productivity trends**: Are tasks being completed? (compare across TASK_HISTORY and connected tools)
- **Recurring task effectiveness**: Which deliver value?
- **Integration effectiveness**: Which external tools provided valuable context?
- **User feedback**: What has user said about agent's help?

### Step 5: Recurring Task Audit

For each recurring task, evaluate:
- Is it running as expected?
- Is user engaging with results?
- Has user given positive or negative feedback?

If a task is consistently ignored, recommend disabling.

---

## Updating PROACTIVE.md

Weave internal and external context naturally into the existing sections. **Do NOT create new subsections.**

### Long-Term Goals (Primary Responsibility)

```markdown
### Long-Term Goals
<!-- Updated by month planner -->
1. Complete Q1 product launch - [Evidence: user stated Jan 5, 47 tasks completed toward this in Notion]
2. Improve fitness routine - running 3x/week - [Evidence: user requested Jan 12, calendar shows 8 scheduled runs this month, 6 completed]
3. Learn Rust programming - [Evidence: user mentioned Feb 1, 12 learning sessions in TASK_HISTORY]

**Monthly context:** March is heavy with client meetings (calendar shows 15 scheduled). April lighter - good for focused learning goals. User's Q1 deadline March 31.
```

Guidelines:
- Maximum 3-5 goals
- Each goal must have evidence (from internal files AND external tools)
- Include progress metrics from connected tools where available
- Note external factors affecting goals (calendar load, seasonal factors)
- Only include goals user expressed
- Remove goals user abandoned

### Current Focus (Set Direction)

```markdown
### Current Focus
<!-- Updated by week/day planner -->
[Monthly theme based on goals above]
```

Guidelines:
- Should align with Long-Term Goals
- Provides direction for week planner
- One sentence maximum

### Recent Accomplishments

```markdown
### Recent Accomplishments
<!-- Updated by planners after task completion -->
- [Month]: [Major goal-related accomplishment]
```

Guidelines:
- Summarize month's achievements
- Include metrics from external tools (tasks completed, meetings held, etc.)
- Focus on goal progress
- Remove entries older than 3 months

### Recording Long-Term Patterns (Inline)

When you observe strategic patterns, record them inline:

```markdown
**Strategic observations:**
- User most productive in morning blocks (9-11am pattern consistent 3 months)
- Heavy meeting weeks correlate with lower goal progress - recommend protecting Thu/Fri
- User engages with tech news (clicked 80%), ignores crypto (clicked 5%) - adjust priorities
- Notion integration high-value (used daily), Apple Reminders unused - consider recommending consolidation
```

Do NOT create a dedicated "Patterns" or "Integration Status" subsection.

---

## Updating MEMORY.md

Update MEMORY.md with:
- User's explicitly stated long-term goals
- Patterns across multiple weeks
- User's feedback on agent's help
- Changes in user priorities

**Do NOT store**: Your assumptions, single-week observations, your strategic ideas.

---

## Outputs

### Output 1: Update Long-Term Goals

Update the "Long-Term Goals" section in PROACTIVE.md with evidence-based goals only.

### Output 2: Update MEMORY.md

Record monthly strategic observations.

### Output 3: Monthly Report to User

Send monthly report via `send_message` with star prefix:

```
Monthly Review - [Month Year]

Progress Toward Goals:
- [Goal 1]: [Progress summary]

Key Accomplishments:
- [Achievement related to goals]

[ONLY if truly necessary:]
Would you like to adjust any goals for next month?
```

Rules:
- Keep under 300 words
- Focus on goal progress
- Maximum 1 question
- No unsolicited suggestions

### Output 4: Audit Recurring Tasks

If a task is consistently ignored or user rejected it:

```
recurring_update_task(
  task_id="ineffective_task",
  updates={"enabled": false}
)
```

**Note:** You MUST inform user when disabling a task.

### Output 5: Manage Recurring Tasks (RARE - WITH PERMISSION)

Only if user explicitly requested automation:

```
recurring_add(
  name="Task Name",
  frequency="monthly",
  instruction="...",
  day="monday",
  time="09:00",
  permission_tier=1,
  enabled=true
)
```

---

## How Month Planner Guides Other Planners

```
Month Planner sets:
  └── Long-Term Goals (user's stated direction)
        │
        ├── Week Planner reads goals to set:
        │     └── Weekly Focus (progress toward goals)
        │
        └── Day Planner reads focus to set:
              └── Daily Priorities (specific actions)
```

Your updates to "Long-Term Goals" directly influence what the weekly and daily planners prioritize.

---

## Allowed Actions

**Core:** `recurring_read`, `recurring_add`, `recurring_update_task`, `recurring_remove`,
`scheduled_task_list`, `schedule_task`, `read_file`, `stream_read`, `stream_edit`,
`memory_search`, `send_message`, `task_update_todos`, `task_end`

**External Integrations (use selectively based on user):**
- Calendar: `check_calendar_availability`
- Notion: `search_notion`, `query_notion_database`, `get_notion_page`
- Web: `web_search`, `web_fetch`

## Output Format

1. Update "Long-Term Goals" section in PROACTIVE.md (evidence-based only)
2. Update MEMORY.md with monthly strategic review
3. Present monthly report to user
4. (Rarely) Audit and disable underperforming recurring tasks
5. (Very rarely, with permission) Add monthly recurring tasks
