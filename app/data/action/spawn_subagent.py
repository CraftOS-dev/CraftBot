from agent_core import action

# Importing the sub-agent package triggers ``app.subagent.definitions`` to
# load, which populates the registry. We use the populated registry below
# to build the action's description and ``agent_type`` enum dynamically —
# adding a new sub-agent type then only requires editing
# ``app/subagent/definitions/<your_agent>.py``; this action file stays
# untouched.
#
# IMPORTANT: this action file follows the CraftBot convention that
# every top-level ``def`` is itself an ``@action``-decorated handler.
# Do NOT add a sibling top-level helper function here. The internal
# action executor (agent_core/core/impl/action/executor.py) exec()s the
# stored action source and picks the FIRST function it finds — a sibling
# helper would be picked instead of the real action. The description
# below is therefore built as an inline expression, not via a helper def.
from app.subagent import list_subagent_names, get_subagent_definition


@action(
    name="spawn_subagent",
    description="\n".join(
        [
            "Spawn a sub-agent in an isolated context for ONE FOCUSED job; "
            "returns its `result`. `query` must be self-contained (sub-agent "
            "sees no parent context). PARALLELIZABLE: emit one spawn_subagent "
            "call PER FOCUSED OBJECTIVE in the SAME decision batch. "
            "A single sub-agent covering 2+ objectives returns shallow results.",
            "",
            "Available agent_types:",
            *(
                f"- {name}: {get_subagent_definition(name).description}"
                for name in list_subagent_names()
            ),
        ]
    ),
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
    # Tag every log line emitted while this sub-agent runs with its identity.
    # contextualize sets a contextvar that asyncio.run copies into the new
    # loop, so the runner, ActionManager, LLM interface and action code all
    # log under "sub:<type>:<id>" — making it trivial to grep one agent's trace.
    short_id = sub.id[4:] if sub.id.startswith("sub_") else sub.id
    agent_tag = f"sub:{sub.agent_type}:{short_id}"
    with logger.contextualize(agent=agent_tag):
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
