# Actions and action sets

An **action** is one concrete thing the agent can do: write a file, search the web, send a Slack message, run a shell command. The action registry is the agent's entire vocabulary: if no action exists for something, the agent cannot do it. Action **sets** group related actions so each task carries only the vocabulary it needs.

## Overview
Three layers, each answering a different question:

| Layer | Question it answers | When it's decided |
|---|---|---|
| **Registry** | What can this agent do at all? | At startup (import time), plus whenever MCP servers connect |
| **Action sets** | What can *this task* do? | Once, at task creation (adjustable mid-task) |
| **Router** | What happens *this turn*? | Every iteration of the [agent loop](agent-loop.md) |

CraftBot ships 1,176 actions: 56 core actions (task management, files, web, documents, media, shell, scheduling, memory, messaging) and 1,120 integration actions under `app/data/action/integrations/<service>/`. The full catalogue is in the [actions reference](default-actions.md).

## Anatomy of an action

An action is a Python function with an `@action` decorator that registers it at import time. The metadata (not the implementation) is what the selection LLM sees, so the `description` field does most of the work:

| Field | What it does |
|---|---|
| `name` | Unique identifier, e.g. `web_search` |
| `description` | What the LLM reads to decide when to pick this action |
| `input_schema` / `output_schema` | Parameter and result contracts, shown to the LLM |
| `action_sets` | Which sets contain this action (an action can be in several) |
| `mode` | Interface visibility — which interface contexts offer the action; `"ALL"` means everywhere |
| `execution_mode` | `"internal"` (in-process) or `"sandboxed"` (isolated venv) |
| `platforms` | `windows` / `linux` / `darwin` / `all` — see platform dispatch below |
| `requirement` | pip packages the action needs; installed automatically before it runs |
| `parallelizable` | Whether it may run alongside other actions in one turn (`False` for writes, state changes, `send_message`) |
| `irreversible` | Marks side effects that can't be undone once they reach the outside world (send email, post publicly) |
| `default`, `test_payload` | Always-available flag (legacy; prefer `action_sets`), and data for simulated test runs |

**Irreversible actions get a crash guard.** Before an `irreversible=True` action executes, its intent is durably recorded in an activity ledger. After execution the outcome is recorded too. If CraftBot crashes between the send and the record, the guard refuses a blind re-execution and surfaces a warning instead. The agent verifies or asks you rather than sending your email twice.

**Platform dispatch.** The registry stores implementations per platform. One logical name like `run_shell` can have Windows, macOS, and Linux variants. Lookup picks the current platform's implementation and falls back to the generic `all` one.

## Action sets

Sets are labels declared in each action's metadata. The registry discovers them dynamically by scanning, so a custom action declaring `action_sets=["my_tools"]` creates the `my_tools` set with no other registration step. The built-in sets:

| Set | Contains |
|---|---|
| `core` | 35 always-included actions: messaging, task control, file operations, search, web research, shell and HTTP, clipboard, scheduling, integration management, skill and set management, memory search, and sub-agent spawning |
| `document_processing` | PDF reading, editing, and conversion, markdown conversion, OCR, image description, video understanding |
| `image` | `describe_image`, `generate_image`, `perform_ocr`, `understand_video` |
| `video` | `generate_video`, `perform_ocr`, `understand_video` |
| `content_creation` | `generate_image`, `generate_video` |
| `scheduler` | Schedule management actions (also present in `core`) |
| `proactive` | Recurring-task management for `PROACTIVE.md` plus schedule management |
| `living_ui` | The 7 Living UI lifecycle actions (scaffold, launch, restart, import, data access) |

Connected integrations contribute their own sets, and each connected [MCP server](../../integrations/mcp.md) becomes a set named `mcp_<server>` (see below).

## How a task gets its actions

When a task starts, one LLM call selects both the [skills](skills.md) and the action sets for it, based on the task description: a report-writing task gets `document_processing`, a Living UI build gets `living_ui`. Sets recommended by the selected skill are merged in automatically, `core` is always included, and the union is compiled into a static action list that the task carries for its lifetime.

This compile-once design is deliberate: during execution there is no retrieval step and no searching for tools. The task's vocabulary is a fixed list the router reads directly.

The list can still change, though. Mid-task, the agent can call `list_action_sets`, `add_action_sets`, and `remove_action_sets` (all in `core`, so always available) to expand or trim its own vocabulary when it discovers it needs something. These calls appear in the action panel when a task discovers mid-way that it needs another capability.

## Per-turn selection

Every iteration of the [agent loop](agent-loop.md), the router makes **one LLM call** that returns reasoning plus a list of one *or more* actions:

```json
{"reasoning": "...", "actions": [{"action_name": "web_search", "parameters": {...}},
                                 {"action_name": "task_update_todos", "parameters": {...}}]}
```

Rules applied to that list before execution:

- **Parallel execution.** Multiple actions in one decision run concurrently, up to 10 per batch.
- **Non-parallelizable wins alone.** If any selected action has `parallelizable=False`, it runs by itself and the rest are dropped with an error the agent sees next turn.
- **Format errors retry, then abort.** Malformed LLM output gets up to 3 retries with the parse error fed back. After that the task aborts rather than wasting tokens.
- **Conversation mode is narrow.** Outside a task, the candidates are only `send_message`, `task_start`, `ignore`, plus messaging actions for connected platforms. Real work requires a task.

Each execution logs `action_start` / `action_end` events to the task's [event stream](event-stream.md), which is what the action panel in the browser renders live.

## Internal vs sandboxed execution

`execution_mode` decides where the function body runs:

- **`internal`** runs in the CraftBot process. Used by actions that touch agent state (task management, messaging, memory) and by MCP tools. Declared `requirement` packages are pip-installed into the main environment before the first run.
- **`sandboxed`** runs in a separate process using a persistent virtual environment (`~/.craftbot/sandbox_venv`, created lazily on first use and reused). Requirements install into the sandbox venv once and persist across calls. A timeout kills runaway executions.

Either way, the action returns a dict that flows back into the event stream as the observation for the next turn.

## MCP tools join the same registry

Servers configured in `app/config/mcp_config.json` (or managed via the `/mcp` command and **Settings**) expose tools that are converted into ordinary actions at connect time: each tool becomes an action named `mcp_<server>_<tool>`, its JSON Schema becomes the `input_schema`, and all of a server's tools land in an action set named `mcp_<server>` (configurable per server). From that point nothing downstream knows the difference: MCP sets appear in task-creation selection, MCP actions appear in the router's candidates, and disabling a server unregisters its actions. Details and server setup: [MCP](../../integrations/mcp.md).

!!! note "Implementation files"
    Registry and decorator: `agent_core/core/action_framework/registry.py`. Set compilation: `app/action/action_set.py`. Set/skill selection at task creation: `app/internal_action_interface.py`. Per-turn routing: `agent_core/core/impl/action/router.py`. Execution: `agent_core/core/impl/action/manager.py` and `executor.py`. MCP conversion: `agent_core/core/impl/mcp/adapter.py`.

## Next

- [Actions reference](default-actions.md): the full catalogue, action by action
- [Write a custom action](../../develop/custom-action.md): one file, one decorator
- [Skills](skills.md): strategy injected on top of the action vocabulary
- [Agent loop](agent-loop.md): where selection and execution sit in the cycle
- [MCP](../../integrations/mcp.md): connecting external tool servers
