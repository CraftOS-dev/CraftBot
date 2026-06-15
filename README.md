<div align="center">
    <img src="assets/README_banner.png" alt="CraftBot Banner" width="1280"/>
</div>

<div align="center">
    <img src="assets/craftbot_logo_text_small.png" alt="CraftBot" width="256"/>
</div>

Most agent harnesses stop at chat and tool calls. CraftBot goes further than that. It builds, evolves, and operates its own SaaS tools, then uses that tool layer to communicate and automate with you.

Beyond that, CraftBot has all the core capabilities of a general-purpose agent harness. It executes tasks the way a remote employee would, remembers your preferences and goals, and proactively helps you plan and act on what matters to you.

<p align="center">
  <img src="https://img.shields.io/badge/OS-Windows-blue?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/OS-macOS-lightgrey?logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/OS-Linux-yellow?logo=linux&logoColor=black" alt="Linux">


  <a href="https://github.com/CraftOS-dev/CraftBot">
    <img src="https://img.shields.io/github/stars/CraftOS-dev/CraftBot?style=social" alt="GitHub Repo stars">
  </a>

  <img src="https://img.shields.io/github/license/CraftOS-dev/CraftBot" alt="License">

  <a href="https://discord.gg/ZN9YHc37HG">
    <img src="https://img.shields.io/badge/Discord-Join%20the%20community-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
</p>

<div align="center">
	
[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center" style="display: inline-block">
<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer" style="display: inline-block">
	<img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509">
</a>
<a href="https://theresanaiforthat.com/ai/craftbot/?ref=featured&v=10277523" target="_blank" rel="nofollow"><img width="265" src="https://media.theresanaiforthat.com/featured-on-taaft.png?width=600"></a>
</p>

<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Highlighted Features

Aside from being an AI agent that can create and operate its own SaaS tools, CraftBot includes all the core features of an agent harness, enabling it to work as a general AI agent alongside you across your tasks, tools, memory, and daily workflows.

- **Living UI.** Build, import, or evolve custom apps that live inside CraftBot. The agent stays aware of the UI's state and can read, write, and act on its data directly.
- **Multi-tasking and session routing.** Still using `/new` command? CraftBot knows when to start a new session and when to resume a task, keeping conversation and context unified.
- **Self-hosted and BYOK.** Flexible LLM provider system supporting OpenAI, Google Gemini, Anthropic Claude, OpenRoute, and more. Or host your own model with 0 tokens spent using Ollama.
- **Memory System.** Local knowledge base built from your interaction with CraftBot via RAG + Agent File System + distillation. CraftBot dreams and consolidates events that happened throughout the day at midnight.
- **Proactive Agent.** Learn your preferences, habits, and life goals. Then, perform planning and initiate tasks (with approval, of course) to help you improve in life.
- **External Tools Integration.** Connect to Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, and Telegram (more to come!) with embedded credentials and OAuth support.
- **Skills and MCP.** 150+ MCP and 170+ Skills ready. Quick installation of new Skills and MCPs. Create/improve Skills from completed tasks with one click.
- **Cross-Platform** Full support for Windows, macOS, and Linux with platform-specific code variants and Docker containerization.
- **Browser interface and CLI support.** Use CraftBot the way it fits: through a simple browser UI for everyday interaction, or via the CLI for scripting and headless environments.

---


## 🧰 Getting Started

Requirements: Python 3.10+ · Node.js 18+ for browser mode

```bash
# 1. Clone the repository
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Install, register auto-start, and launch CraftBot
python craftbot.py install
```

That's it. The terminal closes itself, CraftBot runs in the background, and the browser opens automatically. A **desktop shortcut** is created so you can reopen the browser anytime.

**Managing the service after install:**

```bash
python craftbot.py start      # Start CraftBot in the background
python craftbot.py stop       # Stop CraftBot
python craftbot.py restart    # Restart CraftBot
python craftbot.py status     # Check if it's running and if auto-start is enabled
python craftbot.py logs       # See recent log output
python craftbot.py uninstall  # Stop, remove auto-start, and uninstall packages
```

> [!TIP]
> After `install` or `start`, a **CraftBot desktop shortcut** is created automatically. If you close the browser, just double-click the shortcut to reopen it.

---

## 🌱 Living UI

**Living UI is a system/app/dashboard that evolves with your needs.**

<div align="center">
    <img src="assets/living_ui_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- Need a kanban board with an AI co-pilot built in?
- A custom CRM shaped exactly like your workflow?
- A company dashboard that CraftBot can read and drive on your behalf?

```bash
# 1. Clone the repository
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Install into a conda environment
python install.py --conda

# 3. Run CraftBot
conda run -n craftbot python run.py

# If conda is not in PATH (Windows only):
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> Each time you want to run CraftBot, use `conda run -n craftbot python run.py`. There is no background service — you start and stop it yourself.

---

### Option 3 — Manual Install (pip)

**Use this if:** you want full control over your Python environment and prefer managing CraftBot yourself with no automatic service or background process.

`install.py` (no flags) does a standard pip install into whichever Python environment is currently active. You start and stop CraftBot manually using `run.py`.

```bash
# 1. Clone the repository
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Install dependencies into your active Python environment
python install.py

# 3. Run CraftBot
python run.py
```

The first run will guide you through setting up your API keys and preferences.

> [!NOTE]
> If Node.js is not installed, the installer will provide step-by-step instructions. You can also skip browser mode entirely and use CLI mode — no Node.js required: `python run.py --cli`

---

### What you can do right after?
- Talk to the agent naturally
- Ask it to perform complex multi-step tasks
- Type `/help` to see available commands
- Connect to Google, Slack, Notion, and more

### 🖥️ Interface Modes

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

CraftBot supports multiple UI modes. Choose based on your preference:

| Mode | Command | Requirements | Best For |
|------|---------|--------------|----------|
| **Browser** | `python run.py` | Node.js 18+ | Modern web interface, easiest to use |
| **CLI** | `python run.py --cli` | None | Command-line, lightweight |

**Browser mode** is the default and recommended. If you don't have Node.js, the installer will provide installation instructions or you can use **CLI mode** instead.

---

## 🧬 Living UI

**Living UI is a system/app/dashboard that evolve with your needs.**

Need a kanban board with an AI co-pilot built in? A custom CRM shaped exactly
like your workflow? A company dashboard that CraftBot can read and drive on
your behalf? Spin it up as a Living UI that runs alongside CraftBot and grows as your needs change.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Three ways to create a Living UI

1. **Build from scratch.** Describe what you want in plain language. CraftBot
   scaffolds the data model, backend API, and React UI, then iterates with
   you through a structured design process.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Install from the marketplace.** Browse community-built Living UIs from [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Import an existing project.** Point CraftBot at a Go, Node.js, Python,
   Rust, or static source code or github repo. It detects the runtime, configures health checks, and wraps it as a Living UI.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Keeps evolving with CraftBot inside the loop

A Living UI is never "finished." Ask the agent to add features, redesign
a view, or hook it into new data as your needs grow.

CraftBot is embedded in every Living UI and **context-aware of its state**:
it can read the current DOM and form values, query app data through the
REST API, and trigger actions on your behalf.

### Keeps Saas Tools Open and Alive

Build, customize, and evolve your own Living UI, and rely less on subscription tools that were never built to fit your needs perfectly.

| Component | Description |
|-----------|-------------|
| **Agent Base** | Core orchestration layer that manages task lifecycle, coordinates between components, and handles the main agentic loop. |
| **LLM Interface** | Unified interface supporting multiple LLM providers (OpenAI, Gemini, Anthropic, BytePlus, Ollama). |
| **Context Engine** | Generates optimized prompts with KV-cache support. |
| **Action Manager** | Retrieves and executes actions from the library. Custom action is easy to extend |
| **Action Router** | Intelligently selects the best matching action based on task requirements and resolves input parameters via LLM when needed. |
| **Event Stream** | Real-time event publishing system for task progress tracking, UI updates, and execution monitoring. |
| **Memory Manager** | RAG-based semantic memory using ChromaDB. Handles memory chunking, embedding, retrieval, and incremental updates. |
| **State Manager** | Global state management for tracking agent execution context, conversation history, and runtime configuration. |
| **Task Manager** | Manages task definitions, enable simple and complex tasks bode, create todos, and multi-step workflow tracking. |
| **Skill Manager** | Loads and injects pluggable skills into the agent context. |
| **MCP Adapter** | Model Context Protocol integration that converts MCP tools into native actions. |

---
 
# Three Living UIs to try in 5 minutes
 
- **📋 Kanban Board** — Every task, follow-up, and CTA in one place. CraftBot can operate it to perform PM work for you.
- **📊 Habit Tracker** — Develop and track your habits. Github-style activity calendar to track your habits like a developer.
- **🐦 Luolinglo** — Not Duolingo, but you can learn new languages, create flashcards, and practice with CraftBot.

**[Browse and contribute to the Living UI marketplace →](https://craftos.net/marketplace)**

---

## 📋 Command Reference

### craftbot.py — Automatic Setup (Recommended)

| Command | Description |
|---------|-------------|
| `python craftbot.py install` | Install dependencies, register auto-start on login, start CraftBot, open browser, and close the terminal automatically |
| `python craftbot.py start` | Start CraftBot in the background — auto-restarts if already running (terminal closes automatically) |
| `python craftbot.py stop` | Stop CraftBot |
| `python craftbot.py restart` | Stop and start CraftBot |
| `python craftbot.py status` | Check if CraftBot is running and if auto-start is enabled |
| `python craftbot.py logs` | Show recent log output (`-n 100` for more lines) |
| `python craftbot.py uninstall` | Stop CraftBot, remove auto-start registration, uninstall pip packages, and purge pip cache |

---

### install.py — Manual Setup

| Flag | Description |
|------|-------------|
| (none) | Standard pip install — uses your active Python environment |
| `--conda` | Install into a conda environment (auto-installs Miniconda if not found) |

```bash
# Standard pip install
python install.py

# With conda environment
python install.py --conda
```

---

### run.py — Running CraftBot (Manual Setup Only)

> If you used `craftbot.py install`, CraftBot starts automatically. Use `run.py` only when running manually.

| Flag | Description |
|------|-------------|
| (none) | Run in **Browser** mode (recommended, requires Node.js) |
| `--cli` | Run in **CLI** mode (lightweight, no Node.js required) |

**Windows (PowerShell):**
```powershell
# Browser mode (default, requires Node.js)
python run.py

# CLI mode (no Node.js required)
python run.py --cli

# With conda environment
conda run -n craftbot python run.py

# Or using full path if conda not in PATH
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
python run.py          # Browser mode
python run.py --cli    # CLI mode

# With conda environment
conda run -n craftbot python run.py
```

> [!NOTE]
> **Installation:** The installer now provides clear guidance if dependencies are missing. If Node.js is not found, you'll be prompted to install it or can switch to CLI mode. Installation automatically detects GPU availability and falls back to CPU-only mode if needed.

> [!TIP]
> **First-time setup:** CraftBot will guide you through an onboarding sequence to configure API keys, the agent's name, MCPs, and Skills.

> [!NOTE]
> **Playwright Chromium:** Optional for WhatsApp Web integration. If installation fails, the agent will still work fine for other tasks. Install manually later with: `playwright install chromium`

---

## 🔧 Troubleshooting & Common Issues

### Missing Node.js (for Browser Mode)
If you see **"npm not found in PATH"** when running `python run.py`:
1. Download from [nodejs.org](https://nodejs.org/) (choose LTS version)
2. Install and restart your terminal
3. Run `python run.py` again

**Alternative:** Use CLI mode instead (no Node.js needed):
```bash
python run.py --cli
```

### Installation Fails with Dependencies
The installer now provides detailed error messages with solutions. If installation fails:
- **Check Python version:** Make sure you have Python 3.10+ (`python --version`)
- **Check internet:** Dependencies are downloaded during installation
- **Clear pip cache:** `pip install --upgrade pip` and try again

### Playwright Installation Issues
Playwright chromium installation is optional. If it fails:
- The agent will **still work fine** for other tasks
- You can skip it or install later: `playwright install chromium`
- Only needed for WhatsApp Web integration

For detailed troubleshooting, see [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---
## 🐳 Run with Container

The repository root included a Docker configuration with Python 3.10, key system packages (including Tesseract for OCR), and all Python dependencies defined in `environment.yml`/`requirements.txt` so the agent can run consistently in isolated environments. 

Below are the setup instruction of running our agent with container.

### Build the image

From the repository root:

```bash
docker build -t craftbot .
```

### Run the container

The image is configured to launch the agent with `python -m app.main` by default. To run it interactively:

```bash
docker run --rm -it craftbot
```

If you need to supply environment variables, pass an env file (for example, based on `.env.example`):

```bash
docker run --rm -it --env-file .env craftbot
```

Mount any directories that should persist outside the container (such as data or cache folders) using `-v`, and adjust ports or additional flags as needed for your deployment. The container ships with system dependencies for OCR (`tesseract`) and common HTTP clients so the agent can work with files and network APIs inside the container.

By default the image uses Python 3.10 and bundles the Python dependencies from `environment.yml`/`requirements.txt`, so `python -m app.main` works out of the box.

---

## 🤝 How to Contribute

PRs are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow (fork → branch from `dev` → PR). All pull requests run through lint + smoke-test CI automatically. 

> [!IMPORTANT]
> **CraftBot** is under active development with weekly improvements. For questions or a faster conversation, join us on [Discord](https://discord.gg/ZN9YHc37HG) or email thamyikfoong(at)craftos.net.

---

## 🧾 License

This project is licensed under the [MIT License](LICENSE). You are free to use, host, and monetize this project (you must credit this project in case of distribution and monetization).

---

## ⭐ Acknowledgements

Developed and maintained by [CraftOS](https://craftos.net/) and contributors.  
If you find **CraftBot** useful, please ⭐ the repository and share it with others!

---

## Star History

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
