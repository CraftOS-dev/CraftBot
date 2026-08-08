# Browser interface

The browser interface is CraftBot's default: a React web UI where you chat with the agent, watch tasks and actions execute live, browse the agent's workspace, and configure everything without touching a config file. If you followed the [Quickstart](../../start/quickstart.md), this is what opened at `http://localhost:7925`.

## Launch

```bash
python run.py
```

Startup does four things: frees ports `7925`/`7926` from stale processes, starts the frontend dev server (Vite), starts the agent backend with `--browser`, then opens your browser once both respond. Useful flags:

```bash
python run.py --frontend-port 8925 --backend-port 8926   # different ports
python run.py --no-open-browser                          # don't pop a browser tab
```

**Requirements:** Python 3.10+ plus Node.js and npm for the frontend. `python install.py` installs the frontend dependencies (see [Install](../../start/install.md)). On Linux, `run.py` attempts to auto-install Node.js through your package manager (apt, dnf, pacman, ...) if it's missing. Packaged (frozen) builds skip Node.js entirely and serve a prebuilt static frontend from the bundled `dist/` folder.

If you can't get Node.js, use the [CLI interface](cli.md) with `python run.py --cli`.

## The layout

A sidebar on the left, the active page on the right. The sidebar (collapsible) holds:

| Sidebar item | What it opens |
|---|---|
| **Chat** | The main conversation view (the home page) |
| **Tasks** | Full-page view of every task and its actions |
| **Dashboard** | Usage metrics and agent activity |
| **Workspace** | File browser for the agent's workspace |
| One tab per [Living UI](../../living-ui/index.md) project | The running Living UI app, rendered in-page |
| **Add Living UI** | Opens the create dialog for a new Living UI project |
| **Settings** | All settings pages (pinned at the bottom) |

Above Settings sits a small toolbar with the version number, a **Playbooks** button, a light/dark theme toggle, and GitHub/Discord links.

On the very first launch you won't see any of this yet. A full-screen [onboarding wizard](../../start/onboarding.md) takes over until a model provider is configured.

## Chat

The core surface. Messages stream in with markdown rendering; you can attach files to a message (with a preview before sending) and the agent can send files back into the chat. Typing `/` opens a command autocomplete listing every [slash command](../commands/builtin.md), including one entry per enabled skill.

Beside the conversation sits a resizable panel showing active and recent tasks. From it you can reply directly into a task's session, confirm a task complete, cancel it, resume it, or delete it. An animated mascot sits above the chat and reflects what the agent is currently doing.

## Tasks

The full-screen version of the task panel. Every task expands into its action list, and every action renders as a card with its inputs and outputs. Long values are collapsible, and action-specific renderers format things like file writes and searches readably. Buttons per task: reply, complete, cancel, resume, delete.

Completed tasks have one extra feature: a **skill creator** that turns a finished task into a reusable [skill](../concepts/skills.md), or folds it into an existing one, so the agent can repeat the workflow on demand.

## Dashboard

Usage and activity metrics with a time-period selector (1H / 1D / 1W / 1M / All): task and action counts, success/failure, token usage, and your most-used tools, skills, and integrations.

## Workspace

A file browser over `agent_file_system/workspace/`, where task outputs land (see [Agent file system](../concepts/agent-file-system.md)). Upload and download files, create files and folders, rename, copy/cut/paste, delete, and search, all from the browser. Handy for grabbing a deliverable without opening a terminal.

## Settings

Eight pages, selected from a category rail:

| Page | Covers |
|---|---|
| **General** | Agent identity and general behavior |
| **Proactive** | [Proactive mode](../modes/proactive.md) configuration |
| **Memory** | The agent's memory |
| **Model** | LLM provider, API keys, model selection: the UI equivalent of `/provider` (see [LLM providers](../providers/llm.md)) |
| **MCPs** | Add, edit, enable/disable [MCP servers](../../integrations/mcp.md) |
| **Skills** | Browse and toggle [skills](../concepts/skills.md) |
| **Integrations** | Connect [external services](../../integrations/index.md): token entry and OAuth flows |
| **Living UI** | [Living UI](../../living-ui/index.md) project settings |

## Playbooks

The book icon in the sidebar toolbar opens a searchable, tag-filtered library of ready-made prompts. Picking one prefills the chat input with its prompt, a fast way to hand the agent a well-structured request without writing it from scratch.

## Living UI

Each Living UI project the agent builds appears as its own sidebar tab and renders inside the browser interface, with creation progress, clarifying-question forms, and a theme picker included. **Add Living UI** starts a new one, and you can also just ask for it in chat. Full details: [Living UI](../../living-ui/index.md).

## Ports and remote access

| Port | Serves |
|---|---|
| `7925` | Frontend (the page you open) |
| `7926` | Agent backend: WebSocket plus HTTP API, proxied through the frontend |

Both bind to **localhost** only, and the browser UI has **no built-in authentication**. Anyone who can reach the port controls your agent. Never expose these ports directly to the internet. For access from another machine, tunnel:

```bash
ssh -N -L 7925:localhost:7925 you@server    # then open http://localhost:7925 locally
```

The security notes in [Service mode](../../start/service-mode.md#security-notes) apply equally to foreground runs.

## Implementation files

`app/browser/interface.py` (`BrowserInterface`) wires the shared `UIController` to `app/ui_layer/adapters/browser_adapter.py`, which runs the backend server and speaks WebSocket to the React frontend in `app/ui_layer/browser/frontend/`. The browser adapter enables the action panel and footage display that the CLI adapter turns off. The architecture is the same, with richer rendering. See [UI layer](ui-layer.md).

## Next

- [CLI](cli.md): the no-Node.js alternative
- [Service mode](../../start/service-mode.md): keep the browser interface running in the background
- [Built-in commands](../commands/builtin.md): everything behind the `/` autocomplete
