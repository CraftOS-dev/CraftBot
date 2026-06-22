from agent_core import action

# Importing the sub-agent package triggers ``app.subagent.definitions`` to
# load, which populates the registry. We use the populated registry below
# to build the action's description and ``agent_type`` enum dynamically —
# adding a new sub-agent type then only requires editing
# ``app/subagent/definitions/<your_agent>.py``; this action file stays
# untouched.
#
# These names are referenced only at @action decoration time (module
# load), never inside the function body, so the "imports inside function
# body" rule still applies to runtime helpers (see the function body
# below).
from app.subagent import list_subagent_names, get_subagent_definition


def _build_spawn_description() -> str:
    """Render the action description from the registry.

    One short intro line, then one bullet per registered sub-agent type
    pulled from ``SubAgentDefinition.description``. Adding a sub-agent
    type with a sensible one-liner extends this list automatically.
    """
    lines = [
        "Spawn a sub-agent in an isolated context for ONE job; returns its "
        "`result`. `query` must be self-contained (sub-agent sees no parent "
        "context). Parallelizable: emit multiple calls in one decision to "
        "fan out.",
        "",
        "Available agent_types:",
    ]
    for name in list_subagent_names():
        defn = get_subagent_definition(name)
        lines.append(f"- {name}: {defn.description}")
    return "\n".join(lines)


@action(
    name="spawn_subagent",
    description=_build_spawn_description(),
    default=True,
    mode="CLI",
    action_sets=["core"],
    parallelizable=True,
    irreversible=False,
    input_schema={
        "agent_type": {
            "type": "string",
            # Enum built from the registry so new types are picked up
            # automatically. The per-type description above tells the
            # spawning agent how each one behaves.
            "enum": list_subagent_names(),
            "description": (
                "Which sub-agent type to spawn. See the per-type lines in "
                "this action's description for what each one does."
            ),
        },
        "query": {
            "type": "string",
            "description": (
                "Fully self-contained instruction for the sub-agent. NO "
                "context from your task carries over — include every file "
                "path, URL, identifier, criterion, and output-shape "
                "requirement the sub-agent needs."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "description": (
                "Terminal status of the sub-agent: 'completed', 'failed', "
                "'timeout', or 'error'."
            ),
        },
        "result": {
            "type": "string",
            "description": (
                "The sub-agent's final output. This is the only field you "
                "should act on — everything else is metadata. Shape depends "
                "on agent_type (see this action's description)."
            ),
        },
        "child_task_id": {
            "type": "string",
            "description": "The sub-agent's internal id (for logging only).",
        },
        "iterations": {
            "type": "integer",
            "description": "How many action turns the sub-agent ran.",
        },
        "agent_type": {
            "type": "string",
            "description": "Echo of the agent_type that was spawned.",
        },
        # NOTE: token usage is intentionally not surfaced here. The LLM
        # layer's task_attribution mechanism already rolls each sub-agent's
        # tokens up to the parent task at billing time, which is correct.
    },
    test_payload={
        "agent_type": "research_agent",
        "query": "What is the capital of France?",
        "simulated_mode": True,
    },
)
def spawn_subagent(input_data: dict) -> dict:
    # Imports inside the function — required by the action runtime model.
    import asyncio

    from app.internal_action_interface import InternalActionInterface
    from app.logger import logger
    from app.subagent.runner import SubAgentRunner
    from app.subagent.types import SUBAGENT_TERMINAL_STATUSES

    if input_data.get("simulated_mode"):
        return {
            "status": "completed",
            "result": "Simulated sub-agent result.",
            "child_task_id": "sub_test",
            "iterations": 0,
            "agent_type": input_data.get("agent_type", "research_agent"),
        }

    agent_type = (input_data.get("agent_type") or "").strip()
    query = (input_data.get("query") or "").strip()

    if not agent_type:
        return {"status": "error", "result": "", "message": "agent_type is required."}
    if not query:
        return {
            "status": "error",
            "result": "",
            "message": "query is required and must be self-contained.",
        }

    # ActionManager injects _session_id; for spawn_subagent this is the
    # PARENT task's id (recorded on the SubAgent for traceability).
    parent_task_id = input_data.get("_session_id")

    mgr = InternalActionInterface.subagent_manager
    action_manager = InternalActionInterface.action_manager
    action_library = InternalActionInterface.action_library
    llm = InternalActionInterface.llm_interface
    event_stream_manager = InternalActionInterface.event_stream_manager

    if (
        mgr is None
        or action_manager is None
        or action_library is None
        or llm is None
        or event_stream_manager is None
    ):
        return {
            "status": "error",
            "result": "",
            "message": "Sub-agent runtime is not initialized. Check AgentBase bootstrap.",
        }

    try:
        sub = mgr.spawn(
            agent_type=agent_type,
            query=query,
            parent_task_id=parent_task_id,
        )
    except ValueError as e:
        return {"status": "error", "result": "", "message": str(e)}

    runner = SubAgentRunner(
        subagent_manager=mgr,
        action_manager=action_manager,
        action_library=action_library,
        event_stream_manager=event_stream_manager,
        llm_interface=llm,
    )

    # The runner's ``finally`` block always calls ``mgr.release(sub.id)``,
    # which drops the per-sub-agent event stream and session caches. By the
    # time control returns here, those resources are gone — so on a crash
    # path we MUST NOT call ``mgr.end()`` (its ``subagent_end`` log would
    # have nowhere valid to go and would leak into the parent's main
    # stream). Update ``sub`` in memory instead.
    #
    # The action body runs inside ``ActionExecutor``'s thread pool — there
    # is no event loop in that thread, so ``asyncio.run`` is the correct
    # entry point (nest_asyncio compatibility is irrelevant here).
    try:
        asyncio.run(runner.run_to_completion(sub))
    except Exception as e:
        logger.exception(f"[spawn_subagent] runner crashed for {sub.id}: {e}")
        if sub.status not in SUBAGENT_TERMINAL_STATUSES:
            sub.status = "error"
            sub.result = f"(sub-agent runner crashed: {e})"

    return {
        "status": sub.status,
        "result": sub.result or "",
        "child_task_id": sub.id,
        "iterations": sub.iterations,
        "agent_type": sub.agent_type,
    }
