# UI layer

The UI layer (`app/ui_layer/`) is the shared core both interfaces plug into. The agent never knows whether you're in the [browser](browser.md) or the [CLI](cli.md); it talks to the UI layer, and the UI layer talks to whichever adapter is active.

This page is the user-level map: enough to understand why the two interfaces behave identically and where things like commands and themes actually live. For the code-level walkthrough, see [Architecture](../../develop/architecture.md).

## The pieces

At the center sits **`UIController`** (`app/ui_layer/controller/ui_controller.py`). When an interface starts, it creates one controller and hands it the agent. The controller owns four subsystems and exactly **one active adapter at a time**:

| Piece | Role |
|---|---|
| `EventBus` | Pub/sub channel for typed UI events, with history |
| `UIStateStore` | Reactive store for UI state (agent status, panels, GUI flags) |
| `CommandRegistry` | Every slash command, with names and aliases |
| `CommandExecutor` | Parses `/command args`, resolves it in the registry, runs it |
| Active adapter | The one interface currently rendering — CLI or browser |

The adapters live in `app/ui_layer/adapters/`: `base.py` defines the `InterfaceAdapter` contract, `cli_adapter.py` renders with ANSI text, and `browser_adapter.py` runs the backend server and streams JSON over WebSocket to the React frontend. Each adapter fills in component protocols (chat, action panel, status bar, input, footage, menu from `app/ui_layer/components/protocols.py`) in its own medium. That's the entire difference between the interfaces.

## How events flow

Output travels one way, input the other:

```
render:   agent events ─→ EventTransformer ─→ EventBus ─→ active adapter
input:    adapter ─→ UIController.submit_message() ─→ CommandExecutor ─→ agent
```

**Agent → screen.** Everything the agent does (messages, task starts, action results, state changes) becomes a typed `UIEvent` on the bus: `USER_MESSAGE`, `AGENT_MESSAGE`, `TASK_START`, `TASK_END`, `ACTION_START`, `ACTION_END`, `AGENT_STATE_CHANGED`, `FOOTAGE_UPDATE`, and friends. The adapter subscribes and renders each in its own way: the CLI prints a formatted line, the browser pushes a WebSocket frame that updates the chat or task panel. This is the same [event stream](../concepts/event-stream.md) that feeds the logs.

**You → agent.** Whatever you type lands in `UIController.submit_message()`, which does one important thing first: it offers the text to the `CommandExecutor`. If the message starts with `/` it's handled as a [command](../commands/index.md) and never reaches the agent. Commands belong to the interface, not the conversation. Otherwise the controller emits the user-message event and routes the text to the agent.

Because both directions run through the same controller, feature parity is structural, not maintained by hand. A new event type or command works in both interfaces the moment it exists.

## How commands flow

The command pipeline in detail:

1. The adapter passes your input to the controller.
2. `CommandExecutor.try_execute()` checks for a leading `/`, splits off the name and args, and looks it up in the `CommandRegistry` (aliases included, so `/q` finds `/exit`).
3. The command runs and returns a result, and the executor emits it back onto the event bus as a system or error message, which the adapter renders.
4. An unknown `/name` gets an "Unknown command" error. It is **not** sent to the agent as chat.

The registry is populated at controller startup from three sources: the built-ins in `app/ui_layer/commands/builtin/`, one command per connected integration (`/gmail`, `/slack`, ...), and one command per enabled skill (`/pdf`, `/docx`, ...) which stay in sync as you enable and disable skills. The full catalogue is in [Built-in commands](../commands/builtin.md).

## What else lives here

The UI layer also owns everything that must behave the same across interfaces:

| Directory | What it is |
|---|---|
| `themes/` | Theme definitions and the per-adapter styling contract (ANSI codes for CLI, styles for browser) |
| `settings/` | The settings backends — provider, model, MCP, skill, memory, proactive, Living UI — used by both the settings pages and the `/provider`, `/mcp`, `/skill` commands |
| `onboarding/` | The shared first-run wizard flow that the browser renders as pages and the CLI as numbered prompts |
| `metrics/` | The usage collector behind the browser dashboard |
| `components/Mascot/` | The animated mascot shown on the browser chat page |
| `browser/frontend/` | The React frontend itself |
| `local_llm_setup.py` | The Ollama local-model setup helper |

Note what does *not* live here: agent memory, tasks, skills, and credentials all belong to the agent. The UI layer renders and configures. It doesn't own state you'd lose by switching interfaces.

## Practical implications

- **Commands are portable.** Anything you learn in one interface works in the other, character for character.
- **Switching is free.** Run the browser on your desktop and `--cli` on a server against identical behavior.
- **Settings pages and commands are equivalent.** Settings pages and slash commands call the same `settings/` functions, so there's no drift between what the UI and the commands can do.

## Next

- [Browser](browser.md) and [CLI](cli.md): the two adapters in practice
- [Commands](../commands/index.md): the command system this layer dispatches
- [Event stream](../concepts/event-stream.md): the events the bus carries
- [Architecture](../../develop/architecture.md): the developer-level deep dive
