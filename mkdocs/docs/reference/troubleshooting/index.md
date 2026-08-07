# Troubleshooting

This section holds the broad, symptom-organized diagnostics for CraftBot. Each individual page (install, quickstart, every integration, and each provider) already carries its own troubleshooting table for issues specific to that feature. The three reference pages here group problems by what you observe, so you can start from a symptom when you do not yet know which feature is at fault.

Work through the first diagnostics below before you open a specific page. They apply to every kind of problem and often tell you where to look next.

## First diagnostics

Run these four checks in order. They resolve most problems on their own, and they tell you which reference page to read for the rest.

1. **Check status.** Run `python craftbot.py status`. It reports whether CraftBot is running and whether auto-start is registered. If the process is not running, start it with `python craftbot.py start` and retry the action that failed.

2. **Read the logs.** Every run writes a timestamped folder under `logs/`. Open `logs/<run>/all.log` for the full picture across every session and sub-agent, or `logs/<run>/main/session.log` for the main session alone. Restarting begins a fresh folder, so a problem from earlier is in an older folder, not the current one. Search for `ERROR` first, then read upward from the match. See [Logs](../../core/concepts/logs.md) for the file layout, the subsystem tags, and grep recipes.

3. **Check the activity view.** When a single action fails, the activity view in the interface shows the run and its status. A run parked behind a Continue/Stop choice is waiting for your decision, not stuck. An error names the action that broke, which you can then trace in the logs.

4. **Restart.** Run `python craftbot.py restart`. A restart re-reads settings, re-scans the memory index, and clears a stale lock left by a previous crash. If a restart fixes the problem, the logs from before it explain why.

## Symptom router

Find your symptom, then open the page in the right column.

| Symptom | Go to |
|---|---|
| CraftBot will not install, launch, or build the interface | [Install](../../start/install.md), then [Runtime issues](runtime.md) |
| A port is already in use, or the service will not auto-start | [Runtime issues](runtime.md) |
| The agent does not reply, or a task hangs | [Runtime issues](runtime.md) |
| A task stops early or asks whether to continue | [Runtime issues](runtime.md) |
| The agent does not recall something you told it | [Runtime issues](runtime.md) |
| A schedule did not fire | [Runtime issues](runtime.md) |
| Connecting an integration fails at the OAuth step | [Integration issues](connections.md) |
| A connected integration stops delivering messages | [Integration issues](connections.md) |
| An MCP server will not start, or its tools are missing | [Integration issues](connections.md) |
| A problem specific to one service (a scope, a rate limit) | The integration's own page, from [Integrations](../../integrations/index.md) |
| The agent errors with `401`, `invalid key`, or `model not found` | [Provider issues](providers.md) |
| The agent is rate limited, or slow | [Provider issues](providers.md) |
| A ChatGPT or SuperGrok subscription will not sign in | [Provider issues](providers.md) |
| An image or video action fails | [Provider issues](providers.md) |

## Where to get help

If the logs do not explain the failure and none of the pages match, ask for help. Include the relevant lines from `logs/<run>/all.log`, your provider, and your platform.

- **Discord:** [discord.gg/ZN9YHc37HG](https://discord.gg/ZN9YHc37HG) for questions and quick answers.
- **GitHub issues:** [github.com/CraftOS-dev/CraftBot/issues](https://github.com/CraftOS-dev/CraftBot/issues) for bugs and feature requests. Search existing issues first.

## Next

- [Runtime issues](runtime.md): startup, launch, the agent not responding, tasks, memory, and scheduling
- [Integration issues](connections.md): connecting, listeners, and MCP servers
- [Provider issues](providers.md): authentication, models, rate limits, and media
