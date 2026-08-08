# Sub-agents

A sub-agent is a disposable worker the main agent spawns for one focused job (gather these facts, check this source) that runs in an isolated context with a restricted toolset and reports a single result string back. Sub-agents keep bulk work (dozens of web fetches, long page contents) out of the parent task's context: the parent pays for the answer, not the search.

## When delegation happens

The `spawn_subagent` action is in the `core` [action set](actions-and-action-sets.md), so any task can use it. The main agent uses it when a step is self-contained and context-heavy. Research is the canonical case. The action is parallelizable by design: for multiple independent objectives, the agent is instructed to emit one `spawn_subagent` call *per objective* in the same decision batch, and they run concurrently. A single sub-agent given two topics is expected to refuse rather than answer both shallowly.

Two properties define the boundary:

- **No inherited context.** The sub-agent sees only its `query`: nothing from the parent task, no memory, no conversation. The parent must write a fully self-contained instruction: every URL, file path, criterion, and output-shape requirement goes into the query.
- **One field comes back.** The parent acts on the `result` string alone (plus a `status`). There is no shared state to leak through.

## Sub-agent types

Each type is a frozen definition: a system prompt, an allow-list of actions, and hard runtime caps. Types are registered at startup from `app/subagent/definitions/`. The `spawn_subagent` action builds its `agent_type` choices from that registry, so new types appear automatically.

One type ships today:

| Type | Job | Allowed actions | Caps |
|---|---|---|---|
| `research_agent` | Gather facts from external sources and return a dense, source-cited brief: verbatim numbers and quotes, no interpretation | `web_search`, `web_fetch`, `http_request`, `convert_to_markdown`, `grep_files`, `read_file`, `sub_task_end` | 30 turns, 450 s wall clock |

`sub_task_end` (the universal terminator) is auto-injected into every type's action list by the registry. A definition never lists it itself. Note what's absent from the allow-list: no messaging (a sub-agent can't talk to you), no writes beyond its working files, and no `spawn_subagent` (no nested delegation).

## Lifecycle

1. **Spawn.** The parent's `spawn_subagent` call creates the sub-agent with its own event stream and session cache, tagged with the parent task's id for traceability.
2. **Loop.** A minimal runner drives it: each turn, one LLM call over the type's system prompt + the query + the sub-agent's own event log returns exactly one action, which is executed and logged to the child stream. Anything outside the frozen allow-list is refused with a logged `action_blocked` event. The sub-agent sees the refusal and can self-correct. There is no todo planning, memory retrieval, or conversation routing. That machinery belongs to the parent.
3. **Terminate.** The run ends one of four ways, reflected in the returned `status`:

    | Status | Meaning |
    |---|---|
    | `completed` | The sub-agent called `sub_task_end` with a useful result |
    | `failed` | It called `sub_task_end` declaring failure, hit the iteration cap, or the LLM became unusable |
    | `timeout` | It ran past the type's wall-clock cap |
    | `error` | The runner itself crashed or the spawn was invalid |

4. **Return.** The parent's action result contains `status`, `result`, `child_task_id`, `iterations`, and `agent_type`. The child's event stream and caches are released. Token usage is rolled up into the parent task's accounting, so there's no separate bill to reconcile.

The parent treats the outcome like any other action observation. A `failed` research brief just becomes something the task reasons about on its next turn.

## Observing sub-agents in the logs

Each run of CraftBot writes a folder under `logs/`. Within it, sub-agents are separated two ways:

- **Own file per sub-agent.** Every line a sub-agent emits (including logs from the actions and LLM calls it triggers) is captured into `sub_<type>_<id>.log` in the run folder.
- **Tagged in the shared timeline.** `all.log` interleaves everything. Sub-agent lines carry an agent tag of the form `sub:<type>:<id>`, while the main agent's lines are tagged `main`. `main.log` stays clean of sub-agent noise.

So to follow one delegation: find the `spawn_subagent` action in the parent's stream, note the `child_task_id`, and open the matching `sub_*.log`. See [Logs](logs.md) for the full layout.

## Limits

- Sub-agents can't ask you questions, send messages, or start tasks. If a job needs user input, it belongs in the parent task.
- The caps are hard: a sub-agent that hasn't called `sub_task_end` by its iteration or wall-clock limit is terminated with `failed`/`timeout` rather than allowed to run on.
- Delegation quality depends on query quality. A vague query produces a vague `result`. The isolation that makes sub-agents cheap also means nothing is filled in implicitly.

!!! note "Implementation files"
    The action: `app/data/action/spawn_subagent.py` (terminator: `app/data/action/sub_task_end.py`). Type registry and definitions: `app/subagent/registry.py`, `app/subagent/definitions/`. The loop: `app/subagent/runner.py`. Log tagging and per-agent sinks: `app/logger.py`.

## Next

- [Agent loop](agent-loop.md): the parent cycle that decides when to delegate
- [Actions and action sets](actions-and-action-sets.md): where `spawn_subagent` lives and how allow-lists relate to sets
- [Task sessions](task-sessions.md): how parent tasks are isolated from each other
- [Logs](logs.md): the run folder layout used above
