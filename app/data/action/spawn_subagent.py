from agent_core import action


@action(
    name="spawn_subagent",
    description=(
        "Spawn a focused sub-agent in an ISOLATED context to do ONE job, "
        "then return its `result` to you. The sub-agent has its own event "
        "stream, its own (short) system prompt, and a hard-coded small action "
        "list — it cannot see your task's context. So `query` must be fully "
        "self-contained.\n\n"
        "Available agent_types:\n"
        "- research_agent: online research. Returns a markdown answer with "
        "  inline source links.\n"
        "- validation_agent: validate an artifact, output, or claim against "
        "  criteria. Returns a VERDICT (PASS/FAIL/PARTIAL) plus per-criterion "
        "  evidence.\n\n"
        "Use this to:\n"
        "- Save tokens (fan-out heavy reads into the sub-agent's stream, not yours).\n"
        "- Parallelize (this action is parallelizable; multiple sub-agents run "
        "  concurrently).\n"
        "- Keep your event stream focused (only the `result` comes back)."
    ),
    default=True,
    mode="CLI",
    action_sets=["core"],
    parallelizable=True,
    irreversible=False,
    input_schema={
        "agent_type": {
            "type": "string",
            "enum": ["research_agent", "validation_agent"],
            "example": "research_agent",
            "description": (
                "research_agent for online research. validation_agent for "
                "checking an artifact against criteria."
            ),
        },
        "query": {
            "type": "string",
            "example": (
                "Find the current stable Python version, its release date, "
                "and a link to the official changelog. Return as a markdown "
                "bullet list with inline source links."
            ),
            "description": (
                "Fully self-contained instruction for the sub-agent. Include "
                "ALL needed context: file paths, URLs, criteria, expected output "
                "format. The sub-agent has zero context beyond this string."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "completed",
            "description": (
                "Terminal status of the sub-agent: 'completed', 'failed', "
                "'timeout', or 'error'."
            ),
        },
        "result": {
            "type": "string",
            "example": (
                "- Python 3.13.1, released 2024-12-03. "
                "Source: [python.org](https://www.python.org/downloads/)."
            ),
            "description": (
                "The sub-agent's final output. This is the only field you "
                "should act on — everything else is metadata."
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

    simulated_mode = input_data.get("simulated_mode", False)
    if simulated_mode:
        return {
            "status": "completed",
            "result": "Simulated sub-agent result.",
            "child_task_id": "sub_test",
            "iterations": 0,
            "agent_type": input_data.get("agent_type", "research_agent"),
        }

    agent_type = (input_data.get("agent_type") or "").strip()
    query = (input_data.get("query") or "").strip()
    # ActionManager injects _session_id; for spawn_subagent this is the
    # PARENT task's id (recorded on the SubAgent for traceability).
    parent_task_id = input_data.get("_session_id")

    if not agent_type:
        return {
            "status": "error",
            "result": "",
            "message": "agent_type is required.",
        }
    if not query:
        return {
            "status": "error",
            "result": "",
            "message": "query is required and must be self-contained.",
        }

    mgr = InternalActionInterface.subagent_manager
    action_manager = InternalActionInterface.action_manager
    action_library = InternalActionInterface.action_library
    llm = InternalActionInterface.llm_interface
    event_stream_manager = InternalActionInterface.event_stream_manager

    if mgr is None or action_manager is None or action_library is None or llm is None:
        return {
            "status": "error",
            "result": "",
            "message": (
                "Sub-agent runtime is not initialized "
                "(missing manager / action_manager / action_library / llm). "
                "Check AgentBase bootstrap."
            ),
        }
    if event_stream_manager is None:
        return {
            "status": "error",
            "result": "",
            "message": "Sub-agent runtime is missing event_stream_manager.",
        }

    try:
        sub = mgr.spawn(
            agent_type=agent_type,
            query=query,
            parent_task_id=parent_task_id,
        )
    except ValueError as e:
        return {
            "status": "error",
            "result": "",
            "message": str(e),
        }

    runner = SubAgentRunner(
        subagent_manager=mgr,
        action_manager=action_manager,
        action_library=action_library,
        event_stream_manager=event_stream_manager,
        llm_interface=llm,
    )

    # Runner's own ``finally`` block calls ``mgr.release(sub.id)`` so the
    # child stream and any session caches are torn down even on failure.
    # We deliberately do NOT log a fallback ``subagent_end`` event from this
    # action body — by the time we reach it the child stream is already
    # gone, and logging with task_id=sub.id would leak the event into the
    # parent's main stream (the very contamination we're trying to avoid).
    try:
        try:
            asyncio.run(runner.run_to_completion(sub))
        except RuntimeError as e:
            # asyncio.run fails if there's already a running loop — fall
            # back to scheduling on the current loop. nest_asyncio is
            # applied in agent_core.core.impl.action.manager, so this is
            # safe.
            err_msg = str(e).lower()
            if "already running" in err_msg or "cannot be called" in err_msg:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(runner.run_to_completion(sub))
            else:
                raise
    except Exception as e:
        logger.exception(f"[spawn_subagent] runner crashed for {sub.id}: {e}")
        # Update in-memory state silently. Stream is already released by
        # the runner's finally block, so we must NOT call ``mgr.end()``
        # (which would log subagent_end and leak the event to main).
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
