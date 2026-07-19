# Getting started

This section takes you from an empty machine to a CraftBot that runs in the background, knows who you are, and has completed its first real task. Follow the pages in order. Each one builds on the previous.

!!! tip "The fastest path"
    If you just want it running: `git clone https://github.com/CraftOS-dev/CraftBot.git && cd CraftBot && python craftbot.py install`, then follow the onboarding wizard that opens in your browser. The [Quickstart](quickstart.md) walks through exactly this, with checkpoints at every step.

<div class="grid cards" markdown>

- :material-download-outline:{ .lg .middle } __[Install](install.md)__

    ---

    Automatic install as a background service, manual foreground launch, CLI-only mode, conda, and Docker. Windows, macOS, and Linux.

- :material-timer-outline:{ .lg .middle } __[Quickstart](quickstart.md)__

    ---

    From zero to a completed first task, with a checkpoint after every step and a failure-recovery table when something doesn't work.

- :material-rocket-outline:{ .lg .middle } __[Onboarding](onboarding.md)__

    ---

    What the first-launch wizard collects (provider, API key, agent name, profile, skills, integrations), what the agent asks afterwards, and where all of it is stored.

- :material-message-text-outline:{ .lg .middle } __[Your first task](first-task.md)__

    ---

    How CraftBot decides between conversation, simple task, and complex task, plus how to watch, steer, and confirm a running task.

- :material-server:{ .lg .middle } __[Service mode](service-mode.md)__

    ---

    Run CraftBot as an always-on background service with auto-start at login, on all three platforms.

- :material-map-marker-path:{ .lg .middle } __[Learning path](learning-path.md)__

    ---

    Ordered reading tracks by experience level and by goal, so you read only what your use case needs.

</div>

## Prerequisites

| Requirement | Needed for | Check |
|---|---|---|
| Python 3.10+ | Everything | `python --version` |
| Git | Cloning the repository | `git --version` |
| Node.js 18+ | Browser interface (default). Auto-installed on Linux. | `node --version` |
| A model provider | Everything. API key from any of [13 providers](../core/providers/llm.md), a ChatGPT/SuperGrok subscription, or local [Ollama](../core/providers/llm.md#remote--ollama) (no key). | — |

## Recommended order

1. [Install](install.md): get CraftBot on your machine.
2. [Quickstart](quickstart.md): launch, connect a provider, complete a first task.
3. [Onboarding](onboarding.md): understand what the wizard set up (or redo it properly).
4. [Your first task](first-task.md): learn to work with running tasks.
5. [Service mode](service-mode.md): make it permanent.
6. [Learning path](learning-path.md): branch out based on what you want to build.

## If something goes wrong

Install and first-run problems are collected in [Troubleshooting → Runtime issues](../reference/troubleshooting/runtime.md). Provider and API-key errors are in [Troubleshooting → Provider issues](../reference/troubleshooting/providers.md). If you're stuck, ask on [Discord](https://discord.gg/ZN9YHc37HG).
