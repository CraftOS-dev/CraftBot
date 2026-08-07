# Interfaces

CraftBot has exactly two user-facing interfaces (the **browser UI** and the **terminal CLI**) driven by one shared [UI layer](ui-layer.md). Same agent, same [commands](../commands/index.md), same state underneath. The interface only changes what you see.

<div class="grid cards" markdown>

- :material-web:{ .lg .middle } __[Browser](browser.md)__

    ---

    The default. React web UI with multi-session chat, live activity view, dashboard, workspace browser, and full settings. Requires Node.js.

- :material-console:{ .lg .middle } __[CLI](cli.md)__

    ---

    Plain terminal chat. No Node.js and no browser, just stdin, stdout, and ANSI color. Same agent, same slash commands.

- :material-layers-outline:{ .lg .middle } __[UI layer](ui-layer.md)__

    ---

    The shared core both interfaces plug into: one controller, one event bus, one command registry, two adapters.

</div>

## Choosing an interface

| | Browser | CLI |
|---|---|---|
| Launch | `python run.py` | `python run.py --cli` |
| Requirements | Python + Node.js 18+ | Python only |
| Chat | Multiple sessions, streaming, markdown, attachments | Plain text, line by line |
| Activity visibility | Live activity view with per-action inputs/outputs | Inline one-line status per action |
| Settings | Full settings pages (Model, MCPs, Skills, Integrations, ...) | Commands only (`/provider`, `/mcp`, `/skill`, `/cred`) |
| [Living UI](../../living-ui/index.md) apps | Rendered in-app, one tab per project | Not displayable |
| Best for | Daily use, watching work happen, setup | Servers, SSH, machines without Node.js |

Rule of thumb: use the browser unless you can't. Everything is configurable from either. The CLI just does it through [commands](../commands/builtin.md) instead of settings pages.

## How launching works

`run.py` is the launcher. With no flags it runs **browser mode**: it starts the Vite frontend on port `7925` and the agent backend on port `7926`, waits for both, then opens your browser. With `--cli` it runs the agent directly in your terminal.

| `run.py` flag | Effect |
|---|---|
| `--cli` | Terminal interface instead of browser |
| `--frontend-port PORT` | Frontend port (default `7925`) |
| `--backend-port PORT` | Backend port (default `7926`) |
| `--no-open-browser` | Start servers without popping a browser (service mode uses this) |
| `--conda` / `--no-conda` | Force using / not using the conda environment saved by `install.py` |

Underneath, `run.py` launches the agent driver `app/main.py` (`python -m app.main`), which accepts `--cli`, `--browser`, `--provider`, and `--api-key` and defaults to CLI when run directly. You rarely call it yourself, because `run.py` handles the frontend, ports, and environment for you.

For an always-on assistant that starts at login and survives closing the terminal, use the service manager instead: `python craftbot.py install`. That's covered end to end in [Service mode](../../start/service-mode.md), including running the service with `--cli` on headless machines.

## One brain, two skins

Both interfaces are thin adapters over `app/ui_layer/`. A single `UIController` owns the event bus, state store, and command registry; the browser and CLI adapters just render what flows through it. That's why every slash command works identically in both, and why switching interfaces never loses agent state. Memory, sessions, and settings live with the agent, not the interface. Details in [UI layer](ui-layer.md).

## Next

- [Browser](browser.md): a tour of every surface in the web UI
- [CLI](cli.md): headless usage, `NO_COLOR`, and what the terminal can and can't show
- [Commands](../commands/index.md): the slash commands available in both interfaces
- [Service mode](../../start/service-mode.md): run either interface as a background service
