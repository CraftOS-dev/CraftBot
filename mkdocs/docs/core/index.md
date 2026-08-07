# Core

This section explains how CraftBot actually works: the concepts behind every task it runs, the interfaces you drive it from, the commands and providers it runs on, and the configuration that ties it together. Read it when you want to move from *using* the agent to *understanding* it: predicting what it will do, diagnosing what it did, and tuning how it behaves.

## How the pieces fit

A [trigger](concepts/triggers.md) (your message, a schedule firing, a Telegram DM) wakes the [agent loop](concepts/agent-loop.md), which routes it to the right [session](concepts/task-sessions.md) and runs one turn: the [context engine](concepts/context-engine.md) assembles what the model sees (profile, memory, the task's [event stream](concepts/event-stream.md)), a [prompt](concepts/prompts.md) asks the model to pick from the available [actions](concepts/actions-and-action-sets.md), the actions execute, and the loop queues the next turn until the task ([simple or complex](modes/index.md)) completes. Along the way, [skills](concepts/skills.md) supply know-how, [memory](concepts/memory.md) supplies recall, and everything the agent is and knows lives as plain files in its [file system](concepts/agent-file-system.md).

## Concepts

<div class="grid cards" markdown>

- :material-sync:{ .lg .middle } __[Agent loop](concepts/agent-loop.md)__

    ---

    The turn cycle: trigger → route → select actions → execute → continue. The page to read first.

- :material-flash-outline:{ .lg .middle } __[Triggers](concepts/triggers.md)__

    ---

    Everything that wakes the agent (messages, schedules, platform events) and the durability guarantees behind it.

- :material-identifier:{ .lg .middle } __[Sessions](concepts/task-sessions.md)__

    ---

    The lanes work runs in: chat sessions, runs, and how parallel work stays separate.

- :material-broadcast:{ .lg .middle } __[Event stream](concepts/event-stream.md)__

    ---

    The agent's working record (every message, action, and result) and how the UI renders from it.

- :material-lightning-bolt-outline:{ .lg .middle } __[Actions & action sets](concepts/actions-and-action-sets.md)__

    ---

    1,100+ registered actions, grouped in sets, selected per task. How availability is decided and execution works.

- :material-school-outline:{ .lg .middle } __[Skills](concepts/skills.md)__

    ---

    Packaged know-how the agent loads per task: 195 bundled, slash-invokable, and it can write its own.

- :material-view-column-outline:{ .lg .middle } __[Context engine](concepts/context-engine.md)__

    ---

    Exactly what the model sees each turn, and the caching strategy that keeps costs down.

- :material-format-quote-open-outline:{ .lg .middle } __[Prompts](concepts/prompts.md)__

    ---

    The prompt families behind routing and action selection, and the files (`SOUL.md`, `USER.md`, `FORMAT.md`) that let you shape them.

- :material-database-search-outline:{ .lg .middle } __[Memory](concepts/memory.md)__

    ---

    Local hybrid RAG: capture → nightly distillation → recall injected mid-task. What it remembers and how to correct it.

- :material-clock-outline:{ .lg .middle } __[Scheduling](concepts/scheduling.md)__

    ---

    One-off and recurring scheduled tasks, and how fired schedules become agent work.

- :material-account-multiple-outline:{ .lg .middle } __[Sub-agents](concepts/sub-agents.md)__

    ---

    Delegated child agents that run pieces of a task in parallel and report back.

- :material-account-box-outline:{ .lg .middle } __[Agent bundles](concepts/agent-bundles.md)__

    ---

    Portable agent profiles. Import a prebuilt persona in one click, or export your own configured agent.

- :material-folder-multiple-outline:{ .lg .middle } __[Agent file system](concepts/agent-file-system.md)__

    ---

    The markdown files that are the agent's identity, knowledge, and workspace, and which ones you should edit.

- :material-file-document-multiple-outline:{ .lg .middle } __[Logs](concepts/logs.md)__

    ---

    Per-run log directories, subsystem tags, and the grep recipes for finding out what actually happened.

</div>

## Runs & workflows

The agent scales its process to the size of the work. [Runs](modes/index.md) maps how: [quick requests](modes/simple-task.md) get direct answers, [substantial work](modes/complex-task.md) gets requirements, todos, and verification, [background workflows](modes/special-workflows.md) run system jobs like memory and planning, and [proactive](modes/proactive.md) is where the agent proposes work on its own.

## Interfaces

CraftBot has two interfaces over one shared engine: the [browser UI](interfaces/browser.md) (the default: multi-session chat, live activity view, Living UI tabs, settings) and the [CLI](interfaces/cli.md) (terminal chat for scripting and headless machines). The [UI layer](interfaces/ui-layer.md) page explains the shared architecture. Overview and comparison: [Interfaces](interfaces/index.md).

## Commands

Slash commands work identically in both interfaces: [built-in commands](commands/builtin.md) (`/help`, `/provider`, `/mcp`, `/skill`, ...), plus one command per invokable skill. [CLI-anything](commands/cli-anything.md) is the skill that lets the agent drive desktop apps (GIMP, Blender, LibreOffice, and two dozen others) without you naming them. Overview: [Commands](commands/index.md).

## Providers

The agent needs models: an LLM to think, and optionally vision, image-generation, and video-generation models. Thirteen providers are supported, switchable with one setting. See [LLM providers](providers/llm.md), [Vision & media models](providers/vlm-and-media.md), and [Subscription authentication](providers/subscription-auth.md) for running on a ChatGPT or SuperGrok subscription instead of an API key. Overview: [Providers](providers/index.md).

## Configuration

Everything above is tunable from one settings file plus a handful of purpose-specific configs. The map is at [Configuration](configuration/index.md), the full reference at [Settings](configuration/config-json.md), and agent-bundle manifests at [Agent bundle config](configuration/agent-config-yaml.md).

## Next

- New here? Do the [Quickstart](../start/quickstart.md) first: these pages assume a running agent.
- Building something? The [Learning path](../start/learning-path.md) sequences this section by goal.
- Going deeper than concepts? [Develop](../develop/index.md) covers architecture and extension points.
