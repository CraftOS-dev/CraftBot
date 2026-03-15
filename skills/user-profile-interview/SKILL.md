---
name: user-profile-interview
description: Conduct a conversational interview to build user profile and preferences
user-invocable: false
action-sets:
  - file_operations
  - core
---

# User Profile Interview

Conduct a friendly, conversational interview to learn about the user and personalize the agent experience.

## Objective

Extract and document user information for personalization:
- Personal identity (name, job, location, timezone inferred from location)
- Communication preferences (tone, response style)
- Agent interaction preferences (proactivity level, approval requirements)
- Life goals and what they want help with
- Personality observations

## Interview Flow

### 1. Warm Introduction + Identity Questions
Start with a friendly greeting and ask the first batch using a numbered list:

Example opening:
> "Hi there! I'm excited to be your new AI assistant. To personalize your experience, let me ask a few quick questions:
> 1. What should I call you?
> 2. What do you do for work?
> 3. Where are you based?"

Collect:
- **Name**: What to call them
- **Job/Role**: What they do for work
- **Location**: Where they're based (city/country)

### 2. Preference Questions (Combined)
Ask tone, proactivity, and approval together using a numbered list:

> "Great! A few more questions about how you'd like me to work with you:
> 1. Do you prefer casual or formal communication?
> 2. Should I proactively suggest things or wait for your instructions?
> 3. What types of actions should I ask your approval for first?"

Collect:
- **Communication Style**: casual/formal, brief/detailed
- **Proactivity**: low/medium/high
- **Approval Level**: what needs approval (messages, scheduling, file changes, etc.)

### 3. Messaging Platform
> "If you've connected messaging platforms like Telegram, WhatsApp, Discord, or Slack - which one should I use to send you notifications? Or would you prefer I only respond here in the CraftOS UI?"

### 4. Life Goals & Assistance
This is the most important question. Ask about their aspirations and how you can help:

> "Last question - what are your life goals or aspirations, and what would you like me to help you with generally? I want to understand what matters most to you so I can be genuinely useful."

Note any personality traits, preferences, or working style observations from the conversation.

## After Interview

1. **Read current files**: Use `stream_read` to read `agent_file_system/USER.md` and `agent_file_system/AGENT.md`

2. **Update USER.md** with extracted information using `stream_edit`:
   - Identity section: Update name, email (if provided), location, timezone (inferred from location), job
   - Communication Preferences: Update tone and response style
   - Agent Interaction: Set proactivity level (low/medium/high) and approval settings
   - Life Goals: Document their goals and what they want help with
   - Personality: Write a paragraph summarizing personality observations

3. **Update AGENT.md** if user provided a name for the agent:
   - Update the "Agent Given Name" field

4. **Suggest tasks based on life goals**: Send a message suggesting 3-5 specific tasks that CraftBot can help with to improve their life and get closer to achieving their goals. Focus on:
   - Tasks that leverage CraftBot's automation capabilities
   - Recurring tasks that save time
   - Goal-tracking or accountability tasks
   - Tasks that align with their work and personal aspirations

5. **End task immediately**: Use `task_end` right after suggesting tasks. Do NOT wait for confirmation or ask if information is accurate.

## USER.md Template Reference

```markdown
## Identity
- **Full Name:** [User's full name]
- **Preferred Name:** [What to call them]
- **Email:** [If provided]
- **Location:** [City/Country]
- **Timezone:** [Inferred from location, e.g., EST, PST, UTC+8]
- **Job:** [Their role/profession]
- **Other:** [Additional info like age, interests]

## Communication Preferences
- **Preferred Tone:** [casual/formal/friendly/professional]
- **Response Style:** [brief/detailed/balanced]
- **Preferred Messaging Platform:** [telegram/whatsapp/discord/slack/tui]

## Agent Interaction
- **Prefer Proactive Assistance:** [low/medium/high]
- **Approval Required For:** [simple/complex/proactive/all]

## Life Goals
- **Goals:** [Their life goals and aspirations, guide them to answer if needed]
- **Help Wanted:** [What they want CraftBot to help with generally]

## Personality
[Paragraph describing personality observations]
```

## Conversation Guidelines

- Be warm and conversational, not robotic or interrogative
- Ask related questions together using a **numbered list format** to reduce back-and-forth turns
- Acknowledge their answers before moving to the next batch
- If they seem uncomfortable with a question, offer to skip it
- Adapt your follow-up questions based on their answers
- Keep the interview natural and efficient - it shouldn't feel like a form
- Infer timezone from their location (e.g., San Francisco = Pacific Time)
- The life goals question is most important, ask multiple questions if necessary or goal unclear. Guide them to answer this question. Skip if user has no life or goal.
- If user is annoyed by this interview or refuse to answer, just skip, and end task.

## Allowed Actions

`send_message`, `stream_read`, `stream_edit`, `task_update_todos`, `task_end`

## FORBIDDEN Actions

Do NOT use: `run_shell`, `run_python`, `write_file`, `create_file`, `web_search`

## Example Interaction

**Agent**: "Hi there! I'm excited to be your new AI assistant. To personalize your experience, let me ask a few quick questions:
1. What should I call you?
2. What do you do for work?
3. Where are you based?"

**User**: "I'm Alex, a software engineer at a startup in San Francisco"

**Agent**: "Great to meet you, Alex! SF means you're on Pacific Time. A few more questions about how you'd like me to work with you:
1. Do you prefer casual or formal communication?
2. Should I proactively suggest things or wait for your instructions?
3. What types of actions should I ask your approval for first?"

**User**: "Casual is fine, be proactive with suggestions, but ask me before sending any messages or making external calls"

**Agent**: "Got it! If you've connected any messaging platforms like Telegram, WhatsApp, Discord, or Slack - which one should I use to send you notifications? Or would you prefer I only respond here?"

**User**: "Telegram works"

**Agent**: "Perfect! Last question - what are your life goals or aspirations, and what would you like me to help you with generally? I want to understand what matters most to you so I can be genuinely useful."

**User**: "I want to build my own startup eventually. Right now I'm trying to learn more about product management and save money for when I go independent. I'd love help staying organized and building good habits."

**Agent**: "That's exciting, Alex! I've saved your profile. Based on your goals of building a startup and learning product management, here are some ways I can help:

1. **Daily learning digest** - I can curate and summarize PM articles, podcasts, and case studies for you each morning
2. **Savings tracker** - Set up automated tracking of your savings progress toward your independence fund
3. **Side project accountability** - Weekly check-ins on any side projects or startup ideas you're exploring
4. **Habit building** - Daily reminders and tracking for habits you want to build (reading, exercise, etc.)
5. **Network building** - Reminders to reach out to people in the startup/PM space to grow your network

Let me know anytime you want to set any of these up!"

[Agent ends task immediately after this message]
