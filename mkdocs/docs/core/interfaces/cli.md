# CLI interface

The CLI runs the full agent in your terminal: plain text in, plain text out, no Node.js, no browser, no extra dependencies. It's the same agent with the same [slash commands](../commands/builtin.md). Only the rendering is thinner.

## Launch

```bash
python run.py --cli
```

You get the CraftBot logo, the version, and a prompt:

```
CraftBot v1.4.1
Type /help for commands, /exit to quit.
```

Type messages to chat, `/commands` to configure, `/exit` (or Ctrl+C / EOF) to quit. On a first run with no provider configured, the same [onboarding](../../start/onboarding.md) the browser shows runs here as a numbered-choice terminal wizard.

Alternative entry points:

```bash
python -m app.main                      # agent driver directly; CLI is its default mode
python -m app.main --provider anthropic --api-key sk-ant-...   # override settings.json for this run
python craftbot.py start --cli          # run the CLI agent as a background service
```

`run.py --cli` is the normal path. It handles the conda environment and dependency preflight, then hands off to `app/main.py`. The service variant is covered in [Service mode](../../start/service-mode.md).

## Terminal output format

The CLI renders the same event stream the browser does, inline:

- **Chat**: labeled, color-coded lines for you, the agent, and system messages.
- **Tasks and actions**: one line each as they start and finish, with ASCII status markers (`*` running, `+` completed, `x` failed) and indentation for sub-actions. Purely internal actions (message plumbing, task bookkeeping) are hidden to keep the log readable.
- **Onboarding and prompts**: when the agent asks you something, you answer on the next input line; [session routing](../concepts/task-sessions.md) sends it to the right task automatically.

What it deliberately doesn't have: the action panel and footage display are disabled in this adapter (`enable_action_panel=False`, `enable_footage=False`), so there are no per-action input/output cards, no dashboard, no workspace browser, and no in-place [Living UI](../../living-ui/index.md) rendering. Task outputs still land in `agent_file_system/workspace/` as usual, and full detail is always in [`logs/`](../concepts/logs.md).

## Commands work the same

Every command in the [built-in reference](../commands/builtin.md) works here: `/provider`, `/mcp`, `/skill`, `/cred`, the per-integration commands, and one slash command per enabled skill. Anything the browser does through a settings page, the CLI does through a command:

```
/provider anthropic sk-ant-...   # instead of Settings → Model
/mcp add myserver --transport http https://example.com/mcp
/skill enable pdf
/gmail connect                   # instead of Settings → Integrations
```

The two exceptions: `/menu` politely tells you it's browser-only, and `/clear-tasks` reports that no action panel is available.

## Colors

Output uses 24-bit ANSI color (orange for the agent, white for you, gray for actions). The formatter (`app/cli/formatter.py`) turns color off automatically when:

- stdout is **not a TTY** (piped or redirected output stays clean), or
- the standard [`NO_COLOR`](https://no-color.org) environment variable is set.

On Windows it enables ANSI via colorama when available, falling back to native VT processing on Windows 10+.

## Headless and remote usage

The CLI is the right interface when there's no display or no Node.js:

- **SSH sessions**: nothing to forward and nothing to build. Clone, install, and run `python run.py --cli`.
- **Headless servers**: `python craftbot.py start --cli` keeps the agent alive in the background with [scheduling](../concepts/scheduling.md) and [proactive mode](../modes/proactive.md) running. You talk to it through connected [integrations](../../integrations/index.md) (Telegram, Slack, email) instead of a terminal.
- **Containers and minimal environments**: Python is the only runtime requirement beyond your provider key.

Note the interactive loop reads from stdin and exits on EOF. It's built for a live terminal or a long-running service, not for one-shot scripted invocations.

## When to use the CLI

| Prefer CLI when | Prefer [browser](browser.md) when |
|---|---|
| No Node.js, or you don't want the frontend build | You want to watch actions with full inputs/outputs |
| SSH / headless / container | You're setting up integrations (OAuth flows are click-through) |
| You drive the agent through integrations anyway | You use Living UI apps, the dashboard, or the workspace browser |
| Minimal footprint matters | Day-to-day interactive use |

Switching costs nothing: agent memory, tasks, settings, and credentials live with the agent, not the interface. Run `--cli` today and `run.py` tomorrow against the same state.

## Implementation files

`app/cli/interface.py` (`CLIInterface`) creates the shared `UIController` and attaches `app/ui_layer/adapters/cli_adapter.py`, which implements chat and inline action rendering with `app/cli/formatter.py`. Same controller, same command registry, same event bus as the browser (see [UI layer](ui-layer.md)).

## Next

- [UI layer](ui-layer.md): why both interfaces behave identically
- [Built-in commands](../commands/builtin.md): your settings surface in the CLI
- [Service mode](../../start/service-mode.md): the headless always-on setup
