# Architecture

This page explains how CraftBot is built: the two code layers, where each responsibility lives on disk, how a request travels from an interface through the agent loop and back, and the properties the structure is designed to guarantee. After reading it you can locate any subsystem by name, trace an incoming message to the code that answers it, and know which layer to edit when you extend the agent.

## Two layers: the `agent_core` engine and the `app` runtime

CraftBot is split into a reusable engine and a concrete application that wires the engine to a running system.

`agent_core/` is the runtime-agnostic engine. It defines the data types (`Trigger`, `Task`, `TodoItem`, `Event`), the interfaces a host must satisfy (`agent_core/core/llm_interface.py`, `database_interface.py`, `embedding_interface.py`), the component registries (`agent_core/core/registry/`), and the default implementations under `agent_core/core/impl/` (action execution, event streams, memory, skills, MCP, settings). It knows nothing about which UI is attached or which chat platform delivered a message. `agent_core/__init__.py` re-exports the public surface, so most code imports classes such as `Task`, `ActionRegistry`, `ActionManager`, and `EventStream` directly from `agent_core`.

`app/` is the CraftBot application. It supplies a concrete runtime around the engine: the interface layer (`app/ui_layer/`), external communications (`app/external_comms/`, `craftos_integrations/`), the scheduler (`app/scheduler/`), configuration (`app/config/`), and the built-in actions and skills the agent ships with. `AgentBase` in `app/agent_base.py` is the object that holds all of this together.

Many `app/*.py` modules are thin bindings over engine classes. `app/context_engine.py` is a pure re-export of `agent_core.core.impl.context.ContextEngine`. `app/session/session_manager.py` owns session lifecycle (per-session event streams, workspace dirs, persistence for crash recovery) on top of the engine's session implementation. This is the general pattern: the engine provides behavior, the app injects the concrete dependencies.

## Directory layout

```text
CraftBot/
├── agent_core/                     reusable, runtime-agnostic engine
│   ├── __init__.py                 public API: re-exports engine classes
│   └── core/
│       ├── protocols/              typing.Protocol definitions the host satisfies
│       ├── registry/               component registries
│       ├── action_framework/       @action decorator + ActionRegistry singleton
│       ├── impl/                   default implementations of every subsystem
│       │   ├── action/             ActionExecutor, ActionManager, ActionRouter
│       │   ├── session/            session implementation
│       │   ├── event_stream/       EventStream, EventStreamManager
│       │   ├── memory/  skill/  mcp/  settings/  trigger/  context/
│       ├── prompts/                PromptRegistry + prompt string constants
│       ├── state/ trigger.py event_stream/  core data types
│       └── llm/                    provider clients and model factory
│
├── app/                            the CraftBot application (concrete runtime)
│   ├── main.py                     process entry point (--cli / --browser)
│   ├── agent_base.py               AgentBase: boot(), run(), react()
│   ├── ui_layer/                   interfaces + UIController (trigger consumer)
│   ├── triggers/                   TriggerService, sources, durable store
│   ├── scheduler/                  SchedulerManager: fires due schedules
│   ├── external_comms/             inbound platform listeners and bridges
│   ├── context_engine.py           re-export of engine ContextEngine
│   ├── session/                    SessionManager: session lifecycle + workspace dirs
│   ├── state/                      STATE singleton, StateManager
│   ├── config/                     settings.json and per-feature config files
│   └── data/
│       ├── action/                 built-in action modules + integrations/
│       └── ...                     agent profile, templates, playbooks
│
├── skills/                         installable skill packages (each has SKILL.md)
├── craftos_integrations/           integration package (clients + handlers)
│   ├── registry.py                 autoload + @register_client/@register_handler
│   └── integrations/               one subpackage per platform
├── agent_file_system/              the agent's working files (EVENT.md, MEMORY.md)
└── run.py                          launcher that starts the process
```

## Entry points and boot

`run.py` is the launcher a user invokes. It performs runtime preflight (`app/runtime_preflight.py`), then starts the process in browser or CLI mode. The process itself is `app/main.py`, which parses `--cli` and `--browser`, runs the Windows SSL bootstrap shim, constructs `AgentBase`, and calls `agent.run(interface_mode=...)`. Inside `AgentBase.run()` in `app/agent_base.py`, boot happens in one place: `boot()` starts the config watcher, registers MCP tools, loads the skills system, starts the usage reporter, boots the external-comms manager, initializes and starts the scheduler, and re-enqueues resume triggers for tasks restored from a previous session. After `boot()` returns, `run()` enters the chosen interactive interface, which starts the trigger-consuming loop described next.

## Data flow: a user chat message

```text
 Browser / CLI interface
        │  user types a message
        ▼
 UIController (app/ui_layer/controller/ui_controller.py)
        │  AgentBase._handle_chat_message(payload)
        ▼
 TriggerService.emit(TriggerSpec(source=USER_MESSAGE))   ── durably stored
        │
        ▼
 UIController._consume_triggers()                         ── single consumer loop
        │  trigger = trigger_service.next()   (claims the durable record)
        ▼
 AgentBase.react(trigger)                                 ── exactly one turn
        │  route → workflow (conversation / simple / complex)
        │  select → prepare → execute → finalize
        ▼
 Actions run; each logs action_start / action_end Events
        │
        ▼
 EventStream (agent_file_system/EVENT.md + per-task stream)
        │  event_bus.emit(...) pushes updates
        ▼
 Back to the interface (live task card, todos, action panel)
        │  trigger_service.ack(trigger)   (or nack on exception)
```

A typed-in message reaches `AgentBase._handle_chat_message` through the `UIController`. That method calls `self.trigger_service.emit(TriggerSpec(source=TriggerSource.USER_MESSAGE, ...))`, which writes a durable trigger record. A separate consumer, `_consume_triggers()` in `app/ui_layer/controller/ui_controller.py`, claims the next due trigger with `trigger_service.next()`, calls `AgentBase.react(trigger)` for one turn, then `ack()`s the trigger on success or `nack()`s it on failure. `react()` routes the trigger to a workflow and runs the select, prepare, execute, and finalize phases. Actions emit `action_start` and `action_end` events onto the event stream, which the interface renders live and which is also appended to `agent_file_system/EVENT.md`. The turn ends, and multi-step work continues by enqueuing a fresh continuation trigger. See [Agent loop](../core/concepts/agent-loop.md) for the routing table and the four-phase pipeline, and [Event stream](../core/concepts/event-stream.md) for the record itself.

## Data flow: a scheduled trigger

```text
 SchedulerManager (app/scheduler/manager.py)
        │  a schedule becomes due
        ▼
 TriggerService.emit(TriggerSpec(source=SCHEDULED, dedup_key=...))
        │  scheduled_dedup_key(schedule_id, fire_target)  → one fire, one trigger
        ▼
 UIController._consume_triggers()  →  AgentBase.react(trigger)
        │  proactive / task workflow runs the scheduled work
        ▼
 Actions → Events → interface,  then ack()
```

`SchedulerManager` reads `app/config/scheduler_config.json` and fires due schedules into the same trigger path. When wired with a `TriggerService`, it emits durably with a dedup key built by `scheduled_dedup_key()` in `app/triggers/sources.py`, so a crash retry re-emits the same fire without producing a duplicate turn. The trigger carries `source=TriggerSource.SCHEDULED` (or `SCHEDULED_ONCE` / `SCHEDULED_IMMEDIATE`), and the same consumer claims it and calls `react()`. From there the flow is identical to a chat message: the workflow runs, events land on the stream, and the trigger is acknowledged. See [Scheduling](../core/concepts/scheduling.md) and [Triggers](../core/concepts/triggers.md).

## Data flow: an inbound integration message

```text
 Platform listener (craftos_integrations, e.g. GitHub poll, WhatsApp bridge)
        │  a new message / notification arrives
        ▼
 external-comms manager  →  on_message callback
        │  AgentBase._handle_external_event(payload)
        ▼
 payload normalized (source, contactId, messageBody, is_self_message, ...)
        │  wrapped as self-message or third-party notification
        ▼
 AgentBase._handle_chat_message(...)
        │  TriggerService.emit(TriggerSpec(source=USER_MESSAGE))
        ▼
 UIController._consume_triggers()  →  AgentBase.react(trigger)  →  reply on platform
```

An integration message enters through a platform listener started by the external-comms manager, which `boot()` initializes in `AgentBase._initialize_external_libraries`. That manager is created with `on_message=self._handle_external_event`. `_handle_external_event` in `app/agent_base.py` normalizes the platform payload into standard fields, maps the integration type to a platform, and wraps the text as either a direct self-message or a do-not-act third-party notification. It then routes through the same `_handle_chat_message` path a typed message uses, so the message becomes a `USER_MESSAGE` trigger and is answered by `react()` like any other. The reply goes back to the originating platform through that integration's client. See [Triggers](../core/concepts/triggers.md) for how listener events become tasks.

## Registries and self-registration

CraftBot assembles its capabilities by discovery at import and boot time rather than by a central manifest. Four registries carry this.

**Actions.** `agent_core/core/action_framework/registry.py` defines the `@action` decorator and a single `ActionRegistry` instance, `registry_instance`. The decorator runs at import time: it builds an `ActionMetadata` from its arguments (including `action_sets`, `parallelizable`, and `irreversible`), wraps the function in a `RegisteredAction`, and calls `registry_instance.register(...)`. `load_actions_from_directories()` imports every module under the action directories (`app/data/action/`, including `app/data/action/integrations/`), which triggers those decorators. Adding an action is dropping a decorated function into a module the loader scans.

**Skills.** `SkillLoader.discover_skills()` in `agent_core/core/impl/skill/loader.py` walks skill directories and parses each `SKILL.md` (frontmatter plus body). `SkillManager` holds the loaded skills and exposes them for selection. Installable skill packages live in the top-level `skills/` directory.

**Prompts.** `agent_core/core/prompts/registry.py` defines `PromptRegistry` and the `prompt_registry` singleton, with `register_prompt(name, prompt)` and `get_prompt(name)`. Prompt constants are registered at import and referenced by name, which keeps the static prompt prefix identical across turns.

**Integrations.** `craftos_integrations/registry.py` keeps two parallel registries, one for runtime platform clients and one for auth handlers, populated by the `@register_client` and `@register_handler` decorators. `autoload_integrations()` walks the `craftos_integrations/integrations/` subpackage and imports every module, firing those decorators. Adding an integration is one file drop with no edits to the registry, and `boot()` calls the autoload during external-library setup.

Concrete subsystems are resolved through the component registries in `agent_core/core/registry/`. Code calls accessors such as `get_task_manager()`, `get_action_manager()`, `get_event_stream_manager()`, and `get_context_engine()` instead of constructing dependencies directly, so the app can register its own implementations once at boot and the engine stays decoupled from them.

## Design principles

Each property below is enforced by a specific mechanism in the code.

| Property | How it is enforced | Why it matters |
|---|---|---|
| Durable, at-least-once triggers | `TriggerService.emit/next/ack/nack` back a persistent store (`app/triggers/store.py`); a claimed-but-unsettled trigger is re-delivered on next boot | Work in flight survives a crash or restart instead of being silently lost |
| One trigger, one turn | The consumer runs `react()` once per claimed trigger; continuation is a new trigger, not an in-memory loop | Tasks interleave fairly and the agent is idle between steps |
| No duplicate fires on retry | Dedup keys from `app/triggers/sources.py` (`scheduled_dedup_key`, `resume_dedup_key`) bucket a fire by identity | A crash-retry of a schedule or resume cannot mint a second turn |
| Irreversible actions run once | `@action(irreversible=True)` metadata plus the activity ledger (`app/triggers/activity_log.py`) record intent before execution | An external side effect (send, post) is not replayed after a crash |
| KV-cache-stable prompts | Prompt constants registered once in `PromptRegistry`; a static prefix precedes per-turn content | The provider reuses cached prefix tokens, cutting cost and latency |
| Observable execution | Every action logs `action_start` / `action_end` to the `EventStream`, mirrored to `agent_file_system/EVENT.md` | The UI and logs render the loop live and a restart can replay state |
| Compile-once action lists | Actions carry `action_sets`; a task loads its sets rather than retrieving actions per call | The action menu is stable and deterministic within a task |
| Engine / runtime separation | `agent_core` depends on protocols and registries; `app` injects concrete implementations (see `app/task/task_manager.py`) | The engine is reusable and testable without a UI or network |

## Recommended reading order

For a new contributor, read in this order:

1. [Agent loop](../core/concepts/agent-loop.md): the single cycle every trigger runs through.
2. [Triggers](../core/concepts/triggers.md): what wakes the loop and what survives a restart.
3. [Sessions](../core/concepts/task-sessions.md): the lanes work runs in.
4. [Event stream](../core/concepts/event-stream.md): the record each turn reads and writes.
5. [Actions and action sets](../core/concepts/actions-and-action-sets.md): the unit of work the LLM selects.
6. [Custom action](custom-action.md): write and register your first action.
7. [Custom integration](custom-integration.md): add a platform client and handler.
8. [Skills](skills/index.md): package reusable capability as a skill.
9. [Custom agent](custom-agent.md): assemble the engine into a new runtime.
10. [Contributing](contributing.md): repository conventions and how to submit changes.

## Next

- [Custom action](custom-action.md): the `@action` decorator, action sets, and testing
- [Custom integration](custom-integration.md): the `craftos_integrations` client and handler recipe
- [Agent loop](../core/concepts/agent-loop.md): the turn pipeline in depth
