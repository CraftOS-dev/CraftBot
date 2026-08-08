# Install

CraftBot runs from a git clone on Windows, macOS, and Linux. There are two ways to install it, and they end in different places:

| Path | Command | You get |
|---|---|---|
| **Automatic (recommended)** | `python craftbot.py install` | Dependencies installed, CraftBot registered to start at login, running in the background, browser open, desktop shortcut created |
| **Manual** | `python install.py`, then `python run.py` | Dependencies installed, CraftBot running in the foreground of your terminal until you stop it |

Use the automatic path if you want an assistant that's always available. Use the manual path if you're evaluating CraftBot, developing on it, or don't want anything registered to auto-start.

## Prerequisites

| Requirement | Needed for | Check |
|---|---|---|
| **Python 3.10+** | Everything. Python 3.9 and below will not work. | `python --version` |
| **git** | Cloning the repository | `git --version` |
| **Node.js 18+** | The browser interface (default mode). The launcher auto-installs Node.js on Linux; on Windows and macOS install it yourself from [nodejs.org](https://nodejs.org/) (LTS). Not needed for CLI mode. | `node --version` |
| **A model provider** | The agent needs an LLM. Have ready one of: an API key from a [supported provider](../core/providers/llm.md), a ChatGPT/SuperGrok subscription, or a running [Ollama](../core/providers/llm.md) server (free, no key). You enter this during [onboarding](onboarding.md); you don't need it to install. | (none) |
| *(optional)* **conda / mamba** | Isolated Python environment. `install.py --conda` offers to install Miniconda if missing. | `conda --version` |
| *(optional)* **Playwright Chromium** | Only the WhatsApp Web integration. Safe to skip; install later with `playwright install chromium`. | (none) |

## Path A: automatic install (background service)

```bash
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
python craftbot.py install
```

What this does, in order:

1. Installs the Python dependencies.
2. Registers CraftBot to start automatically when you log in, using Windows Task Scheduler, a systemd user service on Linux, or launchd on macOS. See [Service mode](service-mode.md) for exactly what gets registered and where.
3. Starts CraftBot in the background, detached from your terminal.
4. Waits for the agent to report ready, then opens the browser interface at `http://localhost:7925`.
5. Creates a **CraftBot desktop shortcut** and closes the terminal window.

**Checkpoint:** your browser shows the CraftBot interface with the [onboarding wizard](onboarding.md). If you close the browser tab, CraftBot keeps running. Reopen it with the desktop shortcut or by visiting `http://localhost:7925`.

Manage the service afterwards with:

```bash
python craftbot.py status     # Is it running? Is auto-start registered?
python craftbot.py stop       # Stop the background process
python craftbot.py start      # Start it again (restarts if already running)
python craftbot.py restart    # Stop + start
python craftbot.py logs       # Recent log output (-n 200 for more lines)
```

The full command reference, per-platform internals, and log locations are on the [Service mode](service-mode.md) page.

## Path B: manual install (foreground)

Install dependencies first:

=== "pip (default)"

    ```bash
    git clone https://github.com/CraftOS-dev/CraftBot.git
    cd CraftBot
    python install.py
    ```

    Installs into your current Python environment.

=== "conda environment"

    ```bash
    python install.py --conda
    ```

    Creates a dedicated `craftbot` conda environment. If conda isn't installed, the script offers to install Miniconda for you. Add `--mamba` to resolve packages with mamba instead (faster).

Then launch:

=== "Browser mode (default)"

    ```bash
    python run.py
    ```

    Starts the backend (port `7926`), builds and serves the frontend (port `7925`), and opens your browser. Requires Node.js 18+. Stop with ++ctrl+c++.

=== "CLI mode (no Node.js)"

    ```bash
    python run.py --cli
    ```

    Runs the agent as a command-line chat in your terminal. No Node.js, no browser, same agent underneath. See [CLI interface](../core/interfaces/cli.md).

### Launch flags

| Flag | Effect |
|---|---|
| `--cli` | CLI interface instead of the browser |
| `--conda` / `--no-conda` | Force using (or not using) the `craftbot` conda environment, overriding the saved setting |
| `--frontend-port PORT` | Serve the browser UI on a different port (default `7925`) |
| `--backend-port PORT` | Run the agent backend on a different port (default `7926`) |
| `--no-open-browser` | Start servers without opening a browser window (what service mode uses) |

## Docker

The repository root ships a Docker configuration with Python 3.10, the Python dependencies, and system packages including Tesseract for OCR.

```bash
docker build -t craftbot .
docker run --rm -it --env-file .env craftbot
```

The image launches `python -m app.main` by default. Pass provider keys through the env file, mount volumes with `-v` for anything that should persist (the agent's data lives in `agent_file_system/`), and publish ports with `-p` if you want the browser interface reachable from the host.

## Platform notes

=== "Windows"

    - Use PowerShell or Git Bash.
    - If `python` isn't on PATH, use the `py` launcher: `py craftbot.py install`.
    - Auto-start registers a Task Scheduler entry named `CraftBot` (with a registry-Run fallback). `python craftbot.py uninstall` removes it.

=== "macOS"

    - Auto-start registers a launchd agent (`com.craftbot.agent.plist`).
    - If Homebrew Python misbehaves during dependency install, prefer the conda path: `python install.py --conda`.

=== "Linux"

    - Auto-start registers a systemd **user** service (`craftbot.service`), so CraftBot starts at login, not boot.
    - Browser mode auto-installs Node.js if it's missing.
    - Headless server? Use `python run.py --cli`, or run browser mode with `--no-open-browser` and reach `http://<host>:7925` from another machine.

## Verify your install

Run through this list before moving on:

1. `python craftbot.py status` reports running (automatic path), or your terminal shows the startup banner without errors (manual path).
2. `http://localhost:7925` loads the interface (browser mode).
3. The onboarding wizard appears on first launch. Complete at least the provider and API-key steps. The agent can't respond without a model.
4. Send `hello` in the chat and get a reply.

If step 4 works, your install is done. Continue with the [Quickstart](quickstart.md).

## Updating

- **From the interface:** run the `/update` command in chat. `/update --check` only checks; `/update` applies.
- **From git:** `git pull`, then `python install.py` again to pick up any new dependencies, then restart (`python craftbot.py restart` or relaunch `run.py`).

## Uninstall

```bash
python craftbot.py uninstall
```

Stops CraftBot, removes the auto-start registration, uninstalls the pip packages, and purges the pip cache. Your data (conversations, memory, workspace files, Living UI apps) stays in the repository folder. Delete the clone to remove everything.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `npm not found in PATH` | Node.js missing (browser mode needs it) | Install the LTS from [nodejs.org](https://nodejs.org/), restart the terminal, run again, or use `python run.py --cli` |
| Dependency install fails | Python < 3.10, no internet, or a stale pip | `python --version`; `pip install --upgrade pip`; retry. Conda path is the most reliable: `python install.py --conda` |
| Playwright/Chromium install fails | Optional dependency | Skip it. Everything except WhatsApp Web works. Install later: `playwright install chromium` |
| Port `7925`/`7926` already in use | Another process (or an old CraftBot) owns the port | `python craftbot.py stop`, or launch with `--frontend-port` / `--backend-port` |
| Browser opens but nothing loads | Frontend still building on first launch | Wait for the first build to finish; check `python craftbot.py logs` |
| Agent doesn't reply to `hello` | No provider configured | Complete onboarding, or set a key via the `/provider` command; see [Quickstart step 2](quickstart.md#step-2-connect-a-model-provider) |

More cases: [Runtime issues](../reference/troubleshooting/runtime.md).

## Next

- [Quickstart](quickstart.md): connect a provider and complete your first task, with checkpoints
- [Service mode](service-mode.md): everything about running CraftBot as a background service
- [Interfaces](../core/interfaces/index.md): browser vs CLI in detail
