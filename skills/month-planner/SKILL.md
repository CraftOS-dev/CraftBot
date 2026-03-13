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

---

## CRITICAL: Silent Execution (Override Standard Task Rules)

**This skill overrides standard task completion rules.** Unlike regular tasks:

- **NO acknowledgement**: Do NOT acknowledge task receipt to user
- **NO confirmation**: Do NOT wait for user confirmation before ending
- **MUST end silently**: Use `task_end` immediately after completing planning work

**EXCEPTION - Suggesting New Tasks:**
When you want to suggest a new recurring or scheduled task:
1. Send the suggestion to user with `send_message` and `wait_for_user_reply=true`
2. If user approves → add the task, then end silently
3. If user rejects → end silently without adding
4. If user does not reply within 20 hours → end task silently WITHOUT adding the suggested task

**Why?** Planner tasks run automatically. Waiting for confirmation would cause tasks to pile up.

---

## Core Question

Ask yourself: **"What long-term goals should the user work toward, and how can I help them get SLIGHTLY closer THIS MONTH?"**

Focus on strategic direction and long-term thinking. Your output provides context for the weekly and daily planners to make tactical decisions.

---

## CRITICAL RULES - READ BEFORE DOING ANYTHING

### Before Planning - ALWAYS Do These Checks

1. **Check existing scheduled tasks**: Use `scheduled_task_list` to see what's already scheduled
2. **Read PROACTIVE.md**: Check existing recurring tasks and the Goals, Plan, and Status section
3. **Read TASK_HISTORY.md**: See what tasks have been completed this month
4. **Read MEMORY.md**: Understand long-term patterns and user context
5. **Read USER.md**: Understand user's profile, preferences, and stated goals

### Duplicate Prevention (EXTREMELY IMPORTANT)

- **NEVER suggest a task the user has already performed** (check TASK_HISTORY.md)
- **NEVER suggest a task that already exists** as a recurring or scheduled task
- **NEVER add a recurring task that duplicates an existing one**
- If user performed a one-time task before and you suggest it again = **VERY BAD**

### Permission Requirements

- **Recurring tasks**: MUST get explicit user permission before adding ANY new recurring task
- **Goal changes**: Should reflect what user has expressed, not your ideas
- **Strategic recommendations**: Must be based on evidence, not assumptions

### Conservatism Principle

It MUST be **EXTREMELY HARD** for you to suggest ANYTHING:
- Add new recurring tasks → **ONLY if user explicitly said "I want this automated"**
- Suggest new goals → **ONLY if user explicitly expressed them multiple times**
- Change existing goals → **ONLY with explicit user request**

**DO NOT assume what the user wants** - only work with what they've told you.
**DO NOT annoy the user** by suggesting things they did not ask for.
**DO NOT suggest based on a single occurrence** - this is a critical mistake.
**WHEN IN DOUBT, DO NOT SUGGEST.**

---

## Guiding Principles

**Evidence over assumption**: Goals come from user's explicit statements or demonstrated behavior, never from your inference.

**Stability over optimization**: Goals shouldn't change frequently. Prefer stability.

**User autonomy**: Reflect user's stated priorities, don't impose new ones.

**Stop signals**: If user ignores monthly reports or dismisses suggestions - reduce intervention.

**Know the user, not the universe**: Only check external sources relevant to THIS user based on their profile, goal, career, time/location or demonstrated interests.

---

## Determining If User Needs Proactive Assistance

**DEFAULT STANCE: DO NOT SUGGEST ANYTHING.**

Before suggesting ANY proactive task or goal change, you must have OVERWHELMING evidence. Most planner runs should result in ZERO suggestions.

### The 3+ Rule (MANDATORY)

**A single occurrence of ANYTHING is NEVER sufficient to suggest a task.**

- User asked for weather ONCE → **DO NOT suggest weather task**
- User checked email ONCE → **DO NOT suggest email task**
- User mentioned something ONCE → **DO NOT suggest anything**

**MINIMUM threshold for ANY suggestion:**
- User did the EXACT same task **3+ times** manually, OR
- User **explicitly said** "I want you to do X automatically/regularly"

**NO EXCEPTIONS.** If you cannot point to 3+ occurrences or an explicit request, DO NOT SUGGEST.

### Evidence-Based Need Assessment

| Question | If YES | If NO |
|----------|--------|-------|
| Did the user explicitly request this type of help? | Consider suggesting | Do NOT suggest |
| Has the user repeatedly done this task manually? | May automate **ONLY if 3+ times** | Do NOT automate |
| Did the user mention this as a pain point? | Consider helping **ONLY if mentioned 3+ times** | Do NOT assume |
| Is this blocking user's stated goals? | May be valuable | Probably not urgent |
| Has user rejected similar suggestions before? | Do NOT suggest again | N/A |

### Evidence Types (Strongest to Weakest)

| Evidence Level | Description | Action |
|----------------|-------------|--------|
| **Explicit Request** | User said "I want X automated/recurring" | Safe to suggest |
| **Repeated Behavior** | User did X **3+ times** manually | May suggest with permission |
| **Stated Pain Point** | User complained about X **multiple times** | May suggest as solution |
| **Single Occurrence** | User did X once | **ABSOLUTELY DO NOT suggest** |
| **Your Assumption** | You think user might want X | **ABSOLUTELY DO NOT suggest** |

### Red Flags - DO NOT Proceed If:

- User has not interacted in 24+ hours (they may be busy)
- User dismissed similar suggestions recently
- Task would interrupt user's current focus
- No clear evidence user wants this help
- You're assuming user needs something they never mentioned
- **User only did this task 1-2 times** (NOT ENOUGH)
- **You cannot cite 3+ specific instances from TASK_HISTORY.md**

### Green Flags - May Consider If:

- User explicitly asked for proactive help with this area and it is not processed yet
- User has done this exact task **3+ times** manually (with evidence in TASK_HISTORY.md)
- User **explicitly said** "I want this automated" or "Can you do this regularly"
- Task is tier 0 (silent, no interruption)

---

## What Makes a GOOD Proactive Task

A good proactive task has ALL of these qualities:

| Quality | Description | Bad Example | Good Example |
|---------|-------------|-------------|--------------|
| **Explicit Need** | User asked for it or clearly needs it | "User might like email summaries" | "User asked me to summarize emails daily" |
| **Clear Value** | Obvious benefit to user | "Check random websites" | "Monitor competitor pricing user tracks" |
| **Appropriate Frequency** | Not too often, not too rare | "Remind user every hour" | "Weekly report on Sundays" |
| **Measurable Outcome** | You can tell if it worked | "Help user be productive" | "Compile daily standup notes by 9am" |
| **Non-Intrusive** | Respects user's attention | "Send 5 notifications daily" | "Silently prepare draft, notify once" |
| **Reversible** | User can undo or cancel | "Automatically send emails" | "Draft email for user review" |

### Task Quality Checklist

Before suggesting ANY task, it must pass ALL checks:

- [ ] User explicitly requested or clearly needs this
- [ ] Not duplicating existing task or completed work
- [ ] Frequency is appropriate (not annoying)
- [ ] Value is clear and measurable
- [ ] Tier/permission level is appropriate
- [ ] User can easily disable or modify it

---

## Annoyance Prevention

### Guiding Principles

**ASSUME THE USER DOES NOT WANT SUGGESTIONS.** You must have overwhelming evidence to override this assumption.

- **Frequency**: Suggest EXTREMELY sparingly - most months should have no new suggestions
- **Spacing**: Give user breathing room between any suggestions
- **Recurring tasks**: ALMOST NEVER suggest new recurring tasks
- **Rejection**: If user rejected something, do not suggest it again
- **Single occurrence**: NEVER suggest based on something user did only once

### Signals User is Annoyed (STOP SUGGESTING)

- User says "stop", "enough", "later", "not now"
- User ignores 2+ consecutive suggestions
- User disables a task you suggested
- User reduces notification frequency
- User mentions being "busy" or "overwhelmed"

### Quality Over Quantity

- Better to suggest **nothing** than something mediocre
- Better to **wait** than rush a suggestion
- Better to **ask once** than nag
- Better to **be silent** than be annoying
- **99% of planner runs should produce ZERO suggestions**

### The Annoyance Test

Before ANY suggestion, ask:
1. Would I be annoyed if I received this?
2. Is this genuinely helpful or just "something to do"?
3. Am I suggesting this because user needs it, or because I can?
4. Have I already suggested something similar recently?
5. **Can I cite 3+ specific instances where user did this task?**
6. **Did user EXPLICITLY ask for this to be automated?**

If you hesitate on ANY of these → DO NOT suggest.
If you cannot answer YES to question 5 or 6 → DO NOT suggest.

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

Here are some examples:

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

Weave internal and external context naturally into the existing section of "Goals, Plan, and Status". **Do NOT create new subsections.**

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

### When to Update MEMORY.md

Update MEMORY.md with:
- User's explicitly stated long-term goals
- Patterns across multiple weeks
- User's feedback on agent's help
- Changes in user priorities
- Facts that affect how you should help user

### What to Store

| Store In MEMORY.md | Do NOT Store |
|-------------------|--------------|
| User's stated preferences | Your assumptions |
| Facts user shared | Single-week observations |
| Patterns you observed | Your strategic ideas |
| Important deadlines | Already in TASK_HISTORY |
| Long-term context | Duplicate information |

### Format

```markdown
## [Category]

### [Date] - [Brief Title]
[Factual observation or user statement]
```

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

### Output 5: Manage Recurring Tasks (WITH PERMISSION - RARE)

Only if ALL of these are true:
1. User explicitly requested this automation
2. Task doesn't already exist
3. Clear value proposition
4. Appropriate frequency

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
