---
hide:
  - navigation
  - toc
---

# CraftBot

CraftBot is a self-hosted AI agent that lives on your machine and works like a remote employee: it plans tasks into steps, executes them with real tools (files, shell, web, and your connected apps), remembers your preferences across sessions, and proactively initiates work it thinks you need, with your approval.

Unlike chat assistants, CraftBot can also **build and operate its own software**. Ask for a kanban board, a CRM, or a habit tracker and the agent designs, codes, tests, and launches a working web app inside its own interface, then keeps reading and writing that app's data in future tasks. This system is called [Living UI](living-ui/index.md).

Everything runs locally and you bring your own model: an API key from any of 13 supported providers, a ChatGPT or SuperGrok subscription, or a free local model through Ollama.

## Install

Requirements: Python 3.10+ · Node.js 18+ (browser interface only)

```bash
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
python craftbot.py install
```

That single command installs dependencies, registers CraftBot to start at login, launches it in the background, and opens the browser interface at `http://localhost:7925`. For manual setup, CLI-only mode, conda, and Docker, see [Install](start/install.md).

## Where to go

| I want to... | Go to |
|---|---|
| Get running and send my first task in ~10 minutes | [Quickstart](start/quickstart.md) |
| Follow a reading track for my experience level | [Learning path](start/learning-path.md) |
| Understand how the agent works | [Core](core/index.md) |
| Connect Gmail, Slack, Telegram, GitHub, ... | [Integrations](integrations/index.md) |
| Have the agent build me an app | [Living UI](living-ui/index.md) |
| Follow an end-to-end recipe | [Guides](guides/index.md) |
| Write my own skills, actions, or integrations | [Develop](develop/index.md) |
| Look up an action, setting, or error | [Reference](reference/index.md) |

## What CraftBot does

<div class="grid cards" markdown>

- :material-brain:{ .lg .middle } __Task execution in modes__

    ---

    Quick requests run as lightweight simple tasks. Bigger requests become complex tasks with a live todo list and a confirmation step before closing. You never manage sessions. CraftBot routes each message to the right conversation or running task.

    [:octicons-arrow-right-24: Task modes](core/modes/index.md)

- :material-lightning-bolt-outline:{ .lg .middle } __1,100+ built-in actions__

    ---

    File operations, shell, web research, document conversion, image and video generation, plus deep coverage per integration: 107 GitHub actions, 80 Discord, 60 Slack, 99 Stripe, and more.

    [:octicons-arrow-right-24: Actions catalogue](core/concepts/default-actions.md)

- :material-database-outline:{ .lg .middle } __Memory__

    ---

    Local RAG (vector + keyword search over markdown files) recalls relevant facts mid-task. A nightly process distills the day's events into long-term memory. Nothing leaves your machine except the model calls you configure.

    [:octicons-arrow-right-24: Memory](core/concepts/memory.md)

- :material-bell-ring-outline:{ .lg .middle } __Proactive agent__

    ---

    Learns your goals and habits, plans follow-ups, and proposes tasks on its own schedule. It acts only after you approve.

    [:octicons-arrow-right-24: Proactive mode](core/modes/proactive.md)

- :material-connection:{ .lg .middle } __Integrations__

    ---

    OAuth or bring-your-own-key connections to Google Workspace, Slack, Discord, Telegram, WhatsApp, Notion, GitHub, Jira, Stripe, HubSpot, and more, plus any MCP server.

    [:octicons-arrow-right-24: Integrations](integrations/index.md)

- :material-puzzle-outline:{ .lg .middle } __Skills__

    ---

    195 bundled skills teach the agent repeatable workflows: PDF generation, web research, code review, day planning. Invoke them with slash commands, install more, or have CraftBot create a skill from a task it just finished.

    [:octicons-arrow-right-24: Skills](core/concepts/skills.md)

- :material-account-group-outline:{ .lg .middle } __Agent profiles__

    ---

    Import prebuilt personas (CEO agent, finance agent, DevOps engineer, and 40+ others) from the [CraftBot Agent Bundles repository](https://github.com/CraftOS-dev/craftbot-agent-bundles) with one click. 120 ready-made playbooks cover common automations.

    [:octicons-arrow-right-24: Agent bundles](core/concepts/agent-bundles.md)

- :material-monitor-dashboard:{ .lg .middle } __Two interfaces__

    ---

    A browser UI for everyday use (chat, live action panel, Living UI tabs, settings) and a CLI for scripting and headless environments. Both run on Windows, macOS, and Linux, foreground or as a background service.

    [:octicons-arrow-right-24: Interfaces](core/interfaces/index.md)

</div>

## Project status

- **License:** [MIT](https://github.com/CraftOS-dev/CraftBot/blob/main/LICENSE): free to use, host, and monetize (credit required for distribution).
- **Website:** [craftbot.live](https://craftbot.live/) — product site and cloud hosting.
- **Community:** [GitHub](https://github.com/CraftOS-dev/CraftBot) · [Discord](https://discord.gg/ZN9YHc37HG) · [Living UI marketplace](https://craftos.net/marketplace)
- **Maintainers:** [CraftOS](https://craftos.net/) and contributors. Active development, weekly improvements.
