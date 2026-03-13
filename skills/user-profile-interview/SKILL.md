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
- Personal identity (name, job, location, timezone)
- Communication preferences (tone, response style)
- Agent interaction preferences (proactivity level, approval requirements)
- Personality observations

## Interview Flow

### 1. Warm Introduction
Start with a friendly greeting. Explain that you'd like to learn about them to provide better assistance.

Example opening:
> "Hi there! I'm excited to be your new AI assistant. To help me serve you better, I'd love to learn a bit about you. Mind if I ask a few quick questions?"

### 2. Identity Questions (One at a Time)
Ask these questions conversationally, one at a time. Wait for the user's response before continuing.

- **Name**: "What would you like me to call you?"
- **Job/Role**: "What do you do for work?" or "What kind of work are you involved in?"
- **Location**: "Where are you based?" (city/country is fine)
- **Timezone**: "What timezone are you in?" (can infer from location if given)

### 3. Preference Questions
- **Communication Style**: "How would you like me to communicate with you? Do you prefer casual and friendly, or more formal and professional? Brief responses or detailed explanations?"
- **Proactivity**: "Should I proactively suggest tasks and reminders, or would you prefer I wait for your instructions?"
- **Approval Level**: "For which types of actions should I ask your approval first? (e.g., sending messages, scheduling, file changes)"
- **Preferred Messaging Platform**: "If you've connected messaging platforms like Telegram, WhatsApp, Discord, or Slack - which one should I use to send you notifications? Or would you prefer I only respond here in the terminal/TUI?"

### 4. Open-Ended Learning
- "Is there anything else you'd like me to know about you or how you prefer to work?"
- Note any personality traits, preferences, or working style observations from the conversation

## After Interview

1. **Read current files**: Use `stream_read` to read `agent_file_system/USER.md` and `agent_file_system/AGENT.md`

2. **Update USER.md** with extracted information using `stream_edit`:
   - Identity section: Update name, email (if provided), location, timezone, job
   - Communication Preferences: Update tone and response style
   - Agent Interaction: Set proactivity level (low/medium/high) and approval settings
   - Personality: Write a paragraph summarizing personality observations

3. **Update AGENT.md** if user provided a name for the agent:
   - Update the "Agent Given Name" field

4. **Confirm completion**: Send a message thanking the user and summarizing what you learned, then ASK if the information is accurate.

5. **End task**: Use `task_end` if user did not reply or confirm the information is okay

## USER.md Template Reference

```markdown
## Identity
- **Full Name:** [User's full name]
- **Preferred Name:** [What to call them]
- **Email:** [If provided]
- **Location:** [City/Country]
- **Timezone:** [e.g., EST, PST, UTC+8]
- **Job:** [Their role/profession]
- **Other:** [Additional info like age, interests]

## Communication Preferences
- **Preferred Tone:** [casual/formal/friendly/professional]
- **Response Style:** [brief/detailed/balanced]
- **Preferred Messaging Platform:** [telegram/whatsapp/discord/slack/tui]

## Agent Interaction
- **Prefer Proactive Assistance:** [low/medium/high]
- **Approval Required For:** [simple/complex/proactive/all]

## Personality
[Paragraph describing personality observations]
```

## Conversation Guidelines

- Be warm and conversational, not robotic or interrogative
- Ask ONE question at a time and wait for the response
- Acknowledge their answers before moving to the next question
- If they seem uncomfortable with a question, offer to skip it
- Adapt your follow-up questions based on their answers
- Keep the interview natural - it shouldn't feel like a form

## Allowed Actions

`send_message`, `stream_read`, `stream_edit`, `task_update_todos`, `task_end`

## FORBIDDEN Actions

Do NOT use: `run_shell`, `run_python`, `write_file`, `create_file`, `web_search`

## Example Interaction

**Agent**: "Hi there! I'm excited to be your new AI assistant. To help me serve you better, I'd love to learn a bit about you. What would you like me to call you?"

**User**: "Call me Alex"

**Agent**: "Great to meet you, Alex! What kind of work do you do?"

**User**: "I'm a software engineer at a startup"

**Agent**: "Nice! Software engineering at a startup sounds exciting. Where are you based?"

**User**: "San Francisco"

**Agent**: "Got it, SF! That means you're probably on Pacific Time. How would you like me to communicate with you - casual and brief, or more detailed and formal?"

[... continues naturally ...]

**Agent**: "Thanks for sharing all that with me, Alex! I've saved your preferences. Here's what I learned:
- You're Alex, a software engineer in San Francisco (Pacific Time)
- You prefer casual, brief communication
- You'd like me to be moderately proactive with suggestions
- I should ask before taking any actions that affect external systems

Is the information correct?"
