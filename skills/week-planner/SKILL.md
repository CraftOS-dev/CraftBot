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

Ask yourself: **"How can I help the user get SLIGHTLY closer to their goals THIS WEEK?"**

Focus only on what can realistically be accomplished in a single week. Leave long-term strategic planning to the month planner.

---

## CRITICAL RULES - READ BEFORE DOING ANYTHING

### Before Planning - ALWAYS Do These Checks

1. **Check existing scheduled tasks**: Use `scheduled_task_list` to see what's already scheduled
2. **Read PROACTIVE.md**: Check existing recurring tasks and the Goals, Plan, and Status section
3. **Read TASK_HISTORY.md**: See what tasks have already been completed this week
4. **Read MEMORY.md**: Understand user context, preferences, and patterns

### Duplicate Prevention (EXTREMELY IMPORTANT)

- **NEVER suggest a task the user has already performed** (check TASK_HISTORY.md)
- **NEVER suggest a task that already exists** as a recurring or scheduled task
- **NEVER add a recurring task that duplicates an existing one**
- If user performed a one-time task before and you suggest it again = **VERY BAD**

### Permission Requirements

- **Recurring tasks**: MUST get explicit user permission before adding ANY new recurring task
- **Immediate tasks**: MUST get user permission, unless it's a tier 0 task
- **Scheduled tasks**: MUST get user permission before scheduling regardless of tier

### Conservatism Principle

It MUST be **EXTREMELY HARD** for you to suggest ANYTHING:
- Add new recurring tasks → **ONLY if user explicitly said "I want this automated"**
- Suggest new tasks to the user → **ONLY if user did this 3+ times AND it's genuinely valuable**
- Schedule tasks → **ONLY if user explicitly requested scheduling**

**DO NOT annoy the user** by suggesting things they did not ask for.
**DO NOT suggest based on a single occurrence** - this is a critical mistake.
**WHEN IN DOUBT, DO NOT SUGGEST.**

---

## Guiding Principles

**Evidence over assumption**: Only act on what user has said or done, never on what you think they might want.

**Silence over noise**: Most weeks should have minimal new suggestions. Focus on the weekly summary.

**Quality over quantity**: One genuinely valuable suggestion beats five mediocre ones.

**Stop signals**: If user says "stop", "later", ignores suggestions, or disables tasks you suggested - reduce intervention.

**Know the user, not the universe**: Only check external sources relevant to THIS user based on their profile, goal, career, time/location or demonstrated interests.

---

## Determining If User Needs Proactive Assistance

**DEFAULT STANCE: DO NOT SUGGEST ANYTHING.**

Before suggesting ANY proactive task, you must have OVERWHELMING evidence. Most planner runs should result in ZERO suggestions.

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

Here are some examples:

**Calendar & Schedule** (if Google Calendar connected):
```
check_calendar_availability(start_date="[week_start]", end_date="[week_end]")
```
- Note: meeting patterns, busy days, recurring events
- Identify: heavy meeting days vs. focus time available
- Look for: upcoming deadlines, travel, important events

**Task Management** (check connected tools):
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

### When to Update MEMORY.md

Update MEMORY.md with:
- Patterns observed over the week
- User preferences discovered
- Important learnings
- Behavioral changes
- Facts that affect how you should help user

### What to Store

| Store In MEMORY.md | Do NOT Store |
|-------------------|--------------|
| User's stated preferences | Your assumptions |
| Facts user shared | Daily minutiae |
| Patterns you observed | Temporary states |
| Important deadlines | Already in TASK_HISTORY |
| Context for future help | Duplicate information |

### Format

```markdown
## [Category]

### [Date] - [Brief Title]
[Factual observation or user statement]
```

---

## Outputs

### Output 1: Weekly Summary Message (REQUIRED)

Send weekly summary to user via `send_message` with star prefix.

### Output 2: Update PROACTIVE.md

Update "Current Focus" and "Recent Accomplishments".

### Output 3: Update MEMORY.md

Record weekly patterns and observations.

### Output 4: Manage Recurring Tasks (WITH PERMISSION - RARE)

Only if ALL of these are true:
1. User explicitly requested this automation
2. Task doesn't already exist
3. Clear value proposition
4. Appropriate frequency

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
