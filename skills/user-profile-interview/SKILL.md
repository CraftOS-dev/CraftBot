---
name: user-profile-interview
description: Conduct a conversational interview to explore user's job and life goals
user-invocable: false
action-sets:
  - file_operations
  - core
---

# User Profile Interview

Conduct a friendly, natural conversational interview to understand the user's work, life goals, and how CraftBot can help them.

## Context

The user has already provided the following during setup (hard onboarding):
- Name, location, timezone
- Language preference
- Communication tone (casual/formal/friendly/professional)
- Proactivity level (low/medium/high)
- Approval settings
- Preferred notification platform

These are saved in `agent_file_system/USER.md`. **Do NOT re-ask these questions.**

## Objective

Extract and document:
- Job/role and typical workday
- Life goals and aspirations
- Personality observations
- How CraftBot can specifically help them

## Critical Rules

- **NEVER use scripted or static phrases.** Every question must feel natural, unique, and conversational. Do NOT copy example phrases verbatim — they are only there to show the spirit of what to ask.
- **Adapt your tone** to match the user's communication style and energy level.
- **Read the room** — if the user gives short answers, keep your questions short too. Don't push.
- **The entire interview should be 3-4 exchanges maximum**, not a long interrogation.

## Interview Flow

### Phase 1: Greeting + Job/Role

First, read `agent_file_system/USER.md` to get the user's name and existing info.

Greet them warmly by name in your own words. Then ask about their career/role/typical day in one question.

Examples of the SPIRIT (rephrase, never copy):
- "Tell me about your work, what's your role and what does a normal day look like?"
- "I'd love to hear about what you do, walk me through your role and a typical day?"

Collect:
- **Job/Role**: Their profession, responsibilities, daily workflow

Acknowledge their answer warmly before moving on.

### Phase 2: Life Goals Exploration (adaptive)

Ask about their life goals and aspirations in your own words. Be natural, not scripted.
DO NOT overwhelm the user with too many questions in one message. 

**Ask for life goal**:
- "What are your biggest life goals or aspirations right now, both professional and personal?"

**Follow up on each goal with just ONE question per message from these example questions**:
- What's your timeline for this?
- What's the biggest obstacle you're facing?
- What would success look like for you?

**Continue if the user is engaged**:
- "Beyond what you've shared, is there anything else you're working toward or dreaming about? Even small things count."
- "What daily habits or routines would support these goals?"
- "Are there skills you want to develop?"
- "What would make your day-to-day life easier?"

**Gauge engagement from the first response:**
If the user is brief or disengaged, wrap up gracefully. Do NOT push with multiple rounds (1-2 rounds max). Skip ahead to Phase 3.
If the user refuses or has no goals, respect that and skip ahead to Phase 3. 

Note any personality traits, preferences, or working style observations from the conversation.

### Phase 3: How CraftBot Helps + Task Suggestions

Combine the usefulness explanation and task suggestions into **ONE message**:

1. Based on everything learned, explain how CraftBot can help them — map their goals to CraftBot's capabilities (automation, scheduling, research, web browsing, file management, notifications, task tracking, etc.) with concrete examples.

2. Suggest 1-3 specific tasks. Each must say exactly what you will do and what the deliverable is. Do not describe generic tasks — describe actions with concrete outputs.
   - At least one must be an immediate task you can execute right after this conversation and deliver a tangible result.
   - Others can be recurring tasks with a clear schedule and output.
   - Bad: "Research synthesis - I can summarize papers"
   - Good: "I'll research the top 5 breakthroughs in your field this month and send you a summary now"

## After Interview

1. Tell the user to wait a moment while you update your knowledge about them.
2. Read `agent_file_system/USER.md` using `read_file`.
3. Update USER.md using `stream_edit`:
   - Update the **Job** field
   - Write their goals as free-form text under **Life Goals**
   - Write personality observations under **Personality**
   - Do NOT overwrite: Full Name, Preferred Name, Location, Timezone, Language, Preferred Tone, Preferred Messaging Platform, Prefer Proactive Assistance, Approval Required For
4. Update `agent_file_system/AGENT.md` if user provided a name for the agent.
5. Send your explanation of how CraftBot can help and your task suggestions.
6. End the task with `task_end`. Do not wait for confirmation.

## USER.md Template Reference

```markdown
## Identity
- **Full Name:** [Pre-populated from setup]
- **Preferred Name:** [Pre-populated from setup]
- **Email:** [If provided]
- **Location:** [Pre-populated from setup]
- **Timezone:** [Pre-populated from setup]
- **Job:** [Collected during this interview]
- **Other:** [Additional info like age, interests]

## Communication Preferences
- **Language:** [Pre-populated from setup]
- **Preferred Tone:** [Pre-populated from setup]
- **Response Style:** [brief/detailed/balanced — infer from conversation]
- **Preferred Messaging Platform:** [Pre-populated from setup]

## Agent Interaction
- **Prefer Proactive Assistance:** [Pre-populated from setup]
- **Approval Required For:** [Pre-populated from setup]

## Life Goals

[Free-form text describing the user's goals, aspirations, what they want help with,
and any context gathered from the conversation]

## Personality
[Paragraph describing personality observations from conversation]
```

## Conversation Guidelines

- Every message must feel like a unique human conversation, never a template
- Acknowledge their answers before moving to the next question
- If they seem uncomfortable with a question, skip it immediately
- Adapt your follow-up questions based on their answers and energy
- If user is annoyed or refuses to answer, just skip and end task gracefully
- Keep the conversation natural and efficient — 3-4 exchanges total, not a long interview

## Allowed Actions

`send_message`, `read_file`, `stream_edit`, `task_update_todos`, `task_end`

## FORBIDDEN Actions

Do NOT use: `run_shell`, `write_file`, `create_file`, `web_search`

## Example Interaction

Note: This is ONE example. The agent should NEVER copy these phrases — always rephrase naturally.

**Agent**: "Hey Alex! Great to meet you. I'd love to learn a bit more about you so I can actually be useful. What do you do for work, and what does a typical day look like for you?"

**User**: "I'm a software engineer at a startup. Mostly backend work — APIs, databases, deployments. Typical day is standup, coding, code reviews, and debugging production issues."

**Agent**: "Nice — sounds like you're deep in the trenches. What about outside of work — any big goals you're chasing right now, or things you've been wanting to make progress on?"

**User**: "I want to build my own startup eventually, maybe in 2-3 years. Also trying to learn more about product management and save up about $50K."

**Agent**: "Love that — startup founder arc. For the PM side, are you thinking more hands-on learning or formal courses? And for savings, do you have a system in place or starting from scratch?"

**User**: "Hands-on for sure. And no real system for savings yet, just trying to be more disciplined."

**Agent**: "Got it! Give me a moment while I update my knowledge about you...

[Agent updates USER.md]

Alright, here's how I can help you based on what you've shared:

- **Startup research** — I can dig into markets, competitors, and business models for ideas you're exploring and give you summaries
- **PM skill building** — I can find and summarize practical PM content daily so you're learning without spending hours searching
- **Savings tracking** — I can set up regular check-ins to track your progress toward $50K

Here are some tasks I can kick off right now:

1. **Weekly market research** — Every Monday, I'll research one startup idea you're interested in: market size, key competitors, and potential angles, delivered as a one-page brief
2. **Daily PM reading list** — Each morning, 3 curated articles focused on hands-on product management skills
3. **Bi-weekly savings review** — Every two weeks, we review your savings progress and I suggest specific areas to optimize"

[Agent ends task immediately after this message]
