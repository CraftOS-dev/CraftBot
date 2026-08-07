# Learning path

You don't need to read this documentation cover to cover. Find yourself below (by experience level or by what you're trying to build) and follow the links in order. Each track lists only what that goal actually requires.

## How to use this page

1. If CraftBot isn't running yet, do the [Quickstart](quickstart.md) first. Every track assumes a working install that can answer `hello`.
2. Pick **one** track and finish it before mixing in others. The tracks are ordered so each page builds on the previous one.
3. Come back when your goal changes and follow a different track. You are not expected to read every track.

## By experience level

### Beginner: a working assistant *(~1 hour)*

| # | Read | You'll be able to |
|---|---|---|
| 1 | [Quickstart](quickstart.md) | Install, connect a provider, complete a first piece of work |
| 2 | [Onboarding](onboarding.md) | Shape how the agent talks to you; understand `USER.md` |
| 3 | [Your first run](first-task.md) | Watch and steer the agent while it works |
| 4 | [Runs](../core/modes/index.md) | Know why some requests get todo lists and requirement checks |
| 5 | [Service mode](service-mode.md) | Keep it running without a terminal open |

Stop here and you have a competent daily assistant. Everything else is optional depth.

### Intermediate: integrations, schedules, and proactive mode *(~2–3 hours)*

| # | Read | You'll be able to |
|---|---|---|
| 1 | [Integrations overview](../integrations/index.md) + your platforms ([Telegram](../integrations/telegram-bot.md), [Gmail](../integrations/gmail.md), [Slack](../integrations/slack.md), ...) | Talk to the agent where you already are; let it act on your accounts |
| 2 | [Credentials](../integrations/credentials.md) | Know where tokens live and how OAuth flows work |
| 3 | [Skills](../core/concepts/skills.md) | Use slash-command skills; enable/disable what the agent knows |
| 4 | [Scheduling](../core/concepts/scheduling.md) | Recurring digests, reminders, unattended jobs |
| 5 | [Proactive mode](../core/modes/proactive.md) | Let the agent plan and propose work on its own |
| 6 | [Memory](../core/concepts/memory.md) | Understand what it remembers, and how to correct it |
| 7 | [Living UI](../living-ui/index.md) | Have it build tools for you |

### Advanced: internals and extension *(~4–6 hours)*

| # | Read | You'll be able to |
|---|---|---|
| 1 | [Agent loop](../core/concepts/agent-loop.md) → [Triggers](../core/concepts/triggers.md) → [Sessions](../core/concepts/task-sessions.md) | Trace a message from arrival to action execution |
| 2 | [Event stream](../core/concepts/event-stream.md) → [Context engine](../core/concepts/context-engine.md) → [Prompts](../core/concepts/prompts.md) | Know exactly what the model sees each turn |
| 3 | [Actions & action sets](../core/concepts/actions-and-action-sets.md) | How 1,100+ actions are registered, selected, and executed |
| 4 | [Architecture](../develop/architecture.md) | The `agent_core` / `app` split and the data flows between them |
| 5 | [Custom action](../develop/custom-action.md) / [Custom skill](../develop/skills/craftbot-skill.md) / [Custom integration](../develop/custom-integration.md) | Extend each layer |
| 6 | [Logs](../core/concepts/logs.md) | Debug from ground truth |

## By goal

**Daily personal assistant.** [Quickstart](quickstart.md) → [Onboarding](onboarding.md) → [Your first run](first-task.md) → [Service mode](service-mode.md) → one messaging integration ([Telegram](../integrations/telegram-bot.md) or [WhatsApp](../integrations/whatsapp-web.md)) → [Scheduling](../core/concepts/scheduling.md) → [Proactive](../core/modes/proactive.md).

**A bot in my team's workspace.** [Quickstart](quickstart.md) → [Slack](../integrations/slack.md) or [Discord](../integrations/discord.md) or [Telegram](../integrations/telegram-bot.md) → [Credentials](../integrations/credentials.md) → [Service mode](service-mode.md) → [Sessions](../core/concepts/task-sessions.md) (how parallel conversations stay separate).

**Email and calendar automation.** [Quickstart](quickstart.md) → [Gmail](../integrations/gmail.md) / [Outlook](../integrations/outlook.md) → [Google Calendar](../integrations/google-calendar.md) → [Scheduling](../core/concepts/scheduling.md) → [Service mode](service-mode.md).

**The agent builds my tools (Living UI).** [Quickstart](quickstart.md) → [Living UI](../living-ui/index.md) → [Agent file system](../core/concepts/agent-file-system.md) (where projects live) → [Runs](../core/modes/index.md) (how build runs behave).

**Extend CraftBot with my own capability.** [Actions & action sets](../core/concepts/actions-and-action-sets.md) → [Custom action](../develop/custom-action.md) → [Skills](../core/concepts/skills.md) → [Write a CraftBot skill](../develop/skills/craftbot-skill.md) → [MCP servers](../integrations/mcp.md) (when to plug in instead of build).

**Contribute to CraftBot itself.** [Architecture](../develop/architecture.md) → the Advanced track above → [Contributing](../develop/contributing.md).

## Feature map

When you know the feature but not the page:

| Feature | Page |
|---|---|
| Providers, models, API keys | [LLM providers](../core/providers/llm.md) |
| ChatGPT/SuperGrok subscription instead of a key | [Subscription authentication](../core/providers/subscription-auth.md) |
| Slash commands | [Built-in commands](../core/commands/builtin.md) |
| Memory and what it remembers | [Memory](../core/concepts/memory.md) |
| Recurring / scheduled work | [Scheduling](../core/concepts/scheduling.md) |
| Self-initiated work | [Proactive](../core/modes/proactive.md) |
| Sub-agents and delegation | [Sub-agents](../core/concepts/sub-agents.md) |
| Where files live | [Agent file system](../core/concepts/agent-file-system.md) |
| Every action, by category | [Actions catalogue](../core/concepts/default-actions.md) |
| Every setting | [Settings](../core/configuration/config-json.md) · [Environment variables](../reference/env-vars.md) |
| When things break | [Troubleshooting](../reference/troubleshooting/index.md) |
