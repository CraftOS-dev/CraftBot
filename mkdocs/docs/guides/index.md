# Guides

A guide is a goal-oriented, end-to-end recipe. It starts from a working CraftBot install and walks you all the way to a finished, running outcome, using the real chat messages you type and the real configuration you set. Each guide assumes you have already completed the [Quickstart](../start/quickstart.md) and can hold a normal chat with the agent. Where a step depends on a mechanic like scheduling or a specific integration, the guide links to the reference page for the details instead of repeating them, so you can stay on the recipe.

Pick the outcome you want to build:

| Guide | What you get | Who it is for |
|---|---|---|
| [Daily briefing](daily-briefing.md) | A scheduled morning summary of your email and calendar, sent to your phone every weekday | Anyone who wants CraftBot to report to them on a fixed schedule without being asked |
| [Telegram assistant](telegram-assistant.md) | The agent running hands-free from a Telegram chat, so you can send work and get replies from your phone | People who want to drive the agent away from the desktop |
| [Automated GitHub PR reviews](github-pr-review.md) | The agent watching a repository and posting a review on each new pull request | Developers and teams who want a first-pass review on every PR |
| [Write your first skill](first-skill.md) | A reusable skill that teaches the agent a repeatable workflow you can invoke by name | Anyone who repeats the same multi-step request and wants to package it once |
| [Add an MCP server](mcp-server.md) | An external MCP server connected to the agent, adding its tools to the action surface | People who want CraftBot to reach a service that ships an MCP server |

## How to read a guide

Every guide follows the same shape, so you always know where you are:

- **The outcome** comes first, in the intro. Read it to confirm the guide builds what you want.
- **What you need** lists the prerequisites. If you are missing one, the line links to the page that sets it up. Handle these before Step 1.
- **Numbered steps** take you from nothing to the finished result. Each step names exactly what it produces, and most end with a way to check that the step worked.
- **Troubleshooting** is a table near the end. When the outcome does not appear, match your symptom to a row.
- **Next** points to related guides and the reference pages for anything you now want to go deeper on.

You do not need to read the guides in order, and they do not build on each other. Each one is self-contained. The only shared assumption is a working install.

## What guides are not

Guides are recipes, not reference. They show one good path to one outcome and skip the alternatives. When you want the full picture of a mechanic, follow the links out to the reference and concept pages:

- [Scheduling](../core/concepts/scheduling.md) for schedule expressions, one-time versus recurring tasks, and the schedule actions.
- [Task modes](../core/modes/index.md) for how simple and complex tasks differ.
- [Proactive mode](../core/modes/proactive.md) for recurring tasks the agent plans and runs on its own.
- [Integrations](../integrations/index.md) for the setup, actions, and configuration of every connector.
- [Skills](../core/concepts/skills.md) for how skills are structured, invoked, and shared.

## Suggest a guide

Missing a recipe you want? Ask for it in the [CraftBot Discord](https://discord.gg/craftbot). Guides come from real requests, so telling us the outcome you are stuck on is the fastest way to get one written. Bug reports and finished setups you want to share are welcome there too.

## Next

- [Daily briefing](daily-briefing.md): the most common first automation, and a good template for any scheduled report.
- [Quickstart](../start/quickstart.md): if you have not yet installed CraftBot or run a first task, start here.
- [Learning path](../start/learning-path.md): pick a reading track for what you want to build next.
