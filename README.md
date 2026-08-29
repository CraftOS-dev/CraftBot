<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
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

  <a href="https://deepwiki.com/CraftOS-dev/CraftBot">
    <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki">
  </a>
</p>

<div align="center">
	
[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Highlighted Features

Aside from being an AI agent that can create and operate its own SaaS tools, CraftBot includes all the core features of an agent harness, enabling it to work as a general AI agent alongside you across your tasks, tools, memory, and daily workflows.

- **Agent Profiles** 40+ Agent Profiles (CEO agent, Finance agent, marketing lead agent, devops engineer, video producer agent, or 37 others) ready to work for you. Find the desire roles from **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** and import them with one-click.
- **Playbook catalogue** Not sure how to automate with AI agent? CraftBot has 120 playbooks ready for use (across 19 categories). Open the playbook picker from the top bar, pick a playbook, and it start running task for you.
- **Living UI.** Build, import, or evolve custom apps that live inside CraftBot. The agent stays aware of the UI's state and can read, write, and act on its data directly.
- **Multi-tasking and session routing.** Still using `/new` command? CraftBot knows when to start a new session and when to resume a task, keeping conversation and context unified.
- **Self-hosted and BYOK.** Flexible LLM provider system supporting OpenAI, Google Gemini, Anthropic Claude, OpenRoute, and more. Or host your own model with 0 tokens spent using Ollama.
- **Memory System.** A second brain built from your interactions with CraftBot. Hybrid approach: RAG + knowledge graph + Agent File System. CraftBot dreams and consolidates events that happened throughout the day at midnight.
- **Proactive Agent.** Learn your preferences, habits, and life goals. Then, perform planning and initiate tasks (with approval, of course) to help you improve in life.
- **External Tools Integration.** Connect to your apps like Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, Telegram and more (more to come!) with OAuth support or your own key. You can connect multiple accounts to each integration.
- **Skills and MCP.** 150+ MCP and 170+ Skills ready. Quick installation of new Skills and MCPs. Create/improve Skills from completed tasks with one click.
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

Spin it up as a Living UI that runs alongside CraftBot and grows as your needs change.

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

---
 
# Three Living UIs to try in 5 minutes
 
- **📋 Kanban Board** — Every task, follow-up, and CTA in one place. CraftBot can operate it to perform PM work for you.
- **📊 Habit Tracker** — Develop and track your habits. Github-style activity calendar to track your habits like a developer.
- **🐦 Luolinglo** — Not Duolingo, but you can learn new languages, create flashcards, and practice with CraftBot.

**[Browse and contribute to the Living UI marketplace →](https://craftos.net/marketplace)**

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
