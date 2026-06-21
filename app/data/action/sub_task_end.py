from agent_core import action


@action(
    name="sub_task_end",
    description=(
        "End your sub-agent run. ONLY sub-agents may call this. Set "
        "status='completed' if you produced a useful result, or 'failed' if "
        "you could not. The `result` string is the ONLY field the spawning "
        "agent will see — make it self-contained, well-formatted, and free "
        "of self-references like 'I' or 'as requested'."
    ),
    # Empty action_sets means this action is NOT compiled into any normal
    # task's action list. It is only reachable because SubAgentRunner injects
    # it into the per-type frozen action list in SUBAGENT_TYPES.
    action_sets=[],
    mode="CLI",
    parallelizable=False,
    irreversible=False,
    input_schema={
        "status": {
            "type": "string",
            "enum": ["completed", "failed"],
            "example": "completed",
            "description": (
                "Use 'completed' when you produced a useful result. Use "
                "'failed' if you could not answer or validate."
            ),
        },
        "result": {
            "type": "string",
            "example": (
                "The latest stable Python is 3.13.1, released 2024-12-03. "
                "Source: [python.org downloads](https://www.python.org/downloads/)."
            ),
            "description": (
                "The final output the spawning agent will see. Self-contained "
                "markdown. For research: the answer with inline source links. "
                "For validation: a VERDICT line plus per-criterion bullets."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the sub-agent was marked terminal.",
        },
        "sub_id": {
            "type": "string",
            "description": "The sub-agent id that was ended.",
        },
    },
    test_payload={
        "status": "completed",
        "result": "Test result string.",
        "simulated_mode": True,
    },
)
def sub_task_end(input_data: dict) -> dict:
    # Imports inside the function — required by the action runtime model
    # (top-level imports cause NameError at executor invocation time).
    from app.internal_action_interface import InternalActionInterface

    simulated_mode = input_data.get("simulated_mode", False)
    if simulated_mode:
        return {"status": "success", "sub_id": "test_sub_id"}

    status = (input_data.get("status") or "").strip().lower()
    result = input_data.get("result") or ""
    # ActionManager injects _session_id; for a sub-agent step it equals the
    # sub-agent id (the runner passes session_id=sub.id to execute_action).
    sub_id = input_data.get("_session_id")

    if status not in ("completed", "failed"):
        return {
            "status": "error",
            "message": "Invalid status for sub_task_end. Use 'completed' or 'failed'.",
        }
    if not sub_id:
        return {
            "status": "error",
            "message": (
                "sub_task_end was called outside a sub-agent context "
                "(missing _session_id). This action is only valid inside a sub-agent."
            ),
        }

    mgr = InternalActionInterface.subagent_manager
    if mgr is None:
        return {
            "status": "error",
            "message": (
                "SubAgentManager is not initialized — cannot end sub-agent."
            ),
        }

    if mgr.get(sub_id) is None:
        return {
            "status": "error",
            "message": (
                f"No sub-agent registered with id {sub_id!r}. "
                "sub_task_end can only be used inside an active sub-agent run."
            ),
        }

    mgr.end(sub_id, status=status, result=result)
    return {"status": "success", "sub_id": sub_id}
