
<div align="center">
    <img src="assets/craftbot_readme_banner.png" alt="CraftBot Banner" width="1280"/>
</div>
<br>

<div align="center">
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
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)

<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer"><img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509"></a>

<a href="https://theresanaiforthat.com/ai/craftbot/?ref=featured&v=10277523" target="_blank" rel="nofollow"><img width="300" src="https://media.theresanaiforthat.com/featured-on-taaft.png?width=600"></a>

</div>

<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## 🚀 Overview
<h3 align="center">
CraftBot is your Personal AI Assistant that lives inside your machine and works 24/7 for you. 
</h3>

It autonomously interprets tasks, plans actions, and executes them to achieve your goals.
It learns your preferences and objectives, proactively helping you plan and initiate tasks to achieve your life goals.
MCPs and Skills, and external App integrations are supported. 

CraftBot awaits your orders. Set up your own CraftBot now.

<div align="center">
    <img src="assets/craftbot_overview.png" alt="CraftBot Overview" width="1280"/>
</div>

---

## ✨ Features

- **Bring Your Own Key (BYOK)** — Flexible LLM provider system supporting OpenAI, Google Gemini, Anthropic Claude, BytePlus, and local Ollama models. Easily switch between providers.
- **Memory System** — Distill and consolidate events that happened through the day at midnight.
- **Proactive Agent** — Learn your preferences, habits, and life goals. Then, perform planning and initiate tasks (with approval, of course) to help you improve in life.
- **Living UI** — Build, import, or evolve custom apps that live inside CraftBot. The agent stays aware of the UI's state and can read, write, and act on its data directly.
- **External Tools Integration** — Connect to Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, and Telegram (more to come!) with embedded credentials and OAuth support.
- **MCP** — Model Context Protocol integration for extending agent capabilities with external tools and services.
- **Skills** — Extensible skill framework with built-in skills for task planning, research, code review, git operations, and more.
- **Cross-Platform** — Full support for Windows, macOS, and Linux with platform-specific code variants and Docker containerization.

> [!IMPORTANT]
> **GUI mode is deprecated.** CraftBot no longer supports GUI (desktop automation) mode. Please use Browser, TUI, or CLI mode instead.

<div align="center">
    <img src="assets/craftbot_readme_features.png" alt="CraftBot Banner" width="1280"/>
	<img src="assets/craftbot_features_custom.png" alt="CraftBot Banner" width="1280"/>
</div>

---


## 🧰 Getting Started

### Prerequisites
- Python **3.10+**
- `git` (required to clone the repository)
- An API key for your chosen LLM provider (OpenAI, Gemini, or Anthropic)
- `Node.js` **18+** (optional — only required for browser interface)
- `conda` (optional — only required for the conda setup path)

---

### Which setup should I use?

> **Not sure? Use Option 1.** It handles everything for you.

| | Option 1 — Service | Option 2 — Conda | Option 3 — Manual |
|---|---|---|---|
| **Who it's for** | Most users, first-timers, testing | Conda users who want isolated envs | Power users, custom Python, full control |
| **Manages Python & env?** | ✅ Automatic | ✅ Automatic | ❌ You manage it |
| **Runs in background?** | ✅ Yes, as a service | ❌ No | ❌ No |
| **How to start** | `python craftbot.py install` | `python install.py --conda` | `python install.py` |

---

### ⭐ Option 1 — Service Install (Recommended)

**Use this if:** you want CraftBot to just work — background service, auto-start on login, desktop shortcut, no manual steps.

`craftbot.py` handles everything: Python environment, dependencies, background process management, and auto-start registration.

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

### Option 2 — Conda Install

**Use this if:** you already use conda and want CraftBot in an isolated conda environment.

`install.py --conda` sets up a dedicated `craftbot` conda environment. If Miniconda is not found on your system, it will be installed automatically.

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
> If Node.js is not installed, the installer will provide step-by-step instructions. You can also skip browser mode entirely and use TUI mode — no Node.js required: `python run.py --tui`

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
| **TUI** | `python run.py --tui` | None | Terminal UI, no dependencies needed |
| **CLI** | `python run.py --cli` | None | Command-line, lightweight |

**Browser mode** is the default and recommended. If you don't have Node.js, the installer will provide installation instructions or you can use **TUI mode** instead.

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

---

## 🧩 Architecture Overview

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
| **TUI Interface** | Terminal user interface built with Textual framework for interactive command-line operation. |

---

## 🔜 Roadmap

- [X] **Memory Module** — Done.
- [ ] **External Tool integration** — Still adding more!
- [X] **MCP Layer** — Done.
- [X] **Skill Layer** — Done.
- [ ] **Proactive Behaviour** — Pending

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
| `--tui` | Run in **Terminal UI** mode (no dependencies needed) |
| `--cli` | Run in **CLI** mode (lightweight) |

**Windows (PowerShell):**
```powershell
# Browser mode (default, requires Node.js)
python run.py

# TUI mode (no Node.js required)
python run.py --tui

# CLI mode (lightweight)
python run.py --cli

# With conda environment
conda run -n craftbot python run.py

# Or using full path if conda not in PATH
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
python run.py          # Browser mode
python run.py --tui    # TUI mode
python run.py --cli    # CLI mode

# With conda environment
conda run -n craftbot python run.py
```

> [!NOTE]
> **Installation:** The installer now provides clear guidance if dependencies are missing. If Node.js is not found, you'll be prompted to install it or can switch to TUI mode. Installation automatically detects GPU availability and falls back to CPU-only mode if needed.

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

**Alternative:** Use TUI mode instead (no Node.js needed):
```bash
python run.py --tui
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

## 🔌 External Service Integration

The agent can connect to various services using OAuth. Release builds come with embedded credentials, but you can also use your own.

### Quick Start

For release builds with embedded credentials:
```
/google login    # Connect Google Workspace
/zoom login      # Connect Zoom
/slack invite    # Connect Slack
/notion invite   # Connect Notion
/linkedin login  # Connect LinkedIn
```

### Service Details

| Service | Auth Type | Command | Requires Secret? |
|---------|-----------|---------|------------------|
| Google | PKCE | `/google login` | No (PKCE) |
| Zoom | PKCE | `/zoom login` | No (PKCE) |
| Slack | OAuth 2.0 | `/slack invite` | Yes |
| Notion | OAuth 2.0 | `/notion invite` | Yes |
| LinkedIn | OAuth 2.0 | `/linkedin login` | Yes |

### Using Your Own Credentials

If you prefer to use your own OAuth credentials, add them to your `.env` file:

#### Google (PKCE - only Client ID needed)
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Gmail, Calendar, Drive, and People APIs
3. Create OAuth credentials as **Desktop app** type
4. Copy the Client ID (secret not required for PKCE)

#### Zoom (PKCE - only Client ID needed)
```bash
ZOOM_CLIENT_ID=your-zoom-client-id
```
1. Go to [Zoom Marketplace](https://marketplace.zoom.us/)
2. Create an OAuth app
3. Copy the Client ID

#### Slack (Requires both)
```bash
SLACK_SHARED_CLIENT_ID=your-slack-client-id
SLACK_SHARED_CLIENT_SECRET=your-slack-client-secret
```
1. Go to [Slack API](https://api.slack.com/apps)
2. Create a new app
3. Add OAuth scopes: `chat:write`, `channels:read`, `users:read`, etc.
4. Copy Client ID and Client Secret

#### Notion (Requires both)
```bash
NOTION_SHARED_CLIENT_ID=your-notion-client-id
NOTION_SHARED_CLIENT_SECRET=your-notion-client-secret
```
1. Go to [Notion Developers](https://developers.notion.com/)
2. Create a new integration (Public integration)
3. Copy OAuth Client ID and Secret

#### LinkedIn (Requires both)
```bash
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret
```
1. Go to [LinkedIn Developers](https://developer.linkedin.com/)
2. Create an app
3. Add OAuth 2.0 scopes
4. Copy Client ID and Client Secret

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

PRs are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow (fork → branch from `dev` → PR). All pull requests run through lint + smoke-test CI automatically. For questions or a faster conversation, join us on [Discord](https://discord.gg/ZN9YHc37HG) or email thamyikfoong(at)craftos.net.

## 🧾 License

This project is licensed under the [MIT License](LICENSE). You are free to use, host, and monetize this project (you must credit this project in case of distribution and monetization).

---

## ⭐ Acknowledgements

Developed and maintained by [CraftOS](https://craftos.net/) and contributors [@zfoong](https://github.com/zfoong) and [@ahmad-ajmal](https://github.com/ahmad-ajmal).  
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
