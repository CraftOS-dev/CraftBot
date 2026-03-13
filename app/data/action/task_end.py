from agent_core import action


@action(
    name="task_end",
    description=(
        "End the current task for this session with a final status. "
        "Use status='complete' when the task is fully done, or 'abort' when it "
        "should be cancelled/failed early. Always provide a reason and a detailed summary. "
        "This action can be executed in parallel with send_message, but do not use multiple task_end actions at the same time."
    ),
    default=True,
    mode="CLI",
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "status": {
            "type": "string",
            "enum": ["complete", "abort"],
            "example": "complete",
            "description": "Final status for the task: 'complete' or 'abort'.",
        },
        "reason": {
            "type": "string",
            "example": "All todos completed successfully.",
            "description": "Why the task is considered complete or why it should be aborted.",
        },
        "summary": {
            "type": "string",
            "example": "Successfully completed the user's request to update the configuration file. Modified config.json to add the new API endpoint and validated the changes.",
            "description": "A detailed summary of what was accomplished during this task, including key actions taken and outcomes.",
        },
        "errors": {
            "type": "array",
            "items": {"type": "string"},
            "example": ["Failed to connect to API on first attempt", "Permission denied for /etc/config"],
            "description": "List of any errors or issues encountered during task execution (optional).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result of the operation.",
        },
        "task_id": {
            "type": "string",
            "example": "user_request_1_abc123",
            "description": "The session/task id affected.",
        },
    },
    test_payload={
        "status": "complete",
        "reason": "All todos completed successfully.",
        "summary": "Completed the test task successfully.",
        "simulated_mode": True,
    },
)
def end_task(input_data: dict) -> dict:
    import asyncio

    status = (input_data.get("status") or "").strip().lower()
    reason = input_data.get("reason")
    summary = input_data.get("summary")
    errors = input_data.get("errors", [])
    simulated_mode = input_data.get("simulated_mode", False)
    # Extract session_id injected by ActionManager - this identifies the specific task to end
    session_id = input_data.get("_session_id")

    if status not in ("complete", "abort"):
        return {
            "status": "error",
            "message": "Invalid status for end task. Use 'complete' or 'abort'.",
        }

    # In simulated mode, skip the actual interface call for testing
    if simulated_mode:
        return {"status": "success", "task_id": "test_task_id"}

    import app.internal_action_interface as iai

    if status == "complete":
        res = asyncio.run(iai.InternalActionInterface.mark_task_completed(
            message=reason,
            summary=summary,
            errors=errors,
            task_id=session_id,  # Pass specific task ID to end
        ))
    else:
        # Map 'abort' to a cancellation by default
        res = asyncio.run(iai.InternalActionInterface.mark_task_cancel(
            reason=reason,
            summary=summary,
            errors=errors,
            task_id=session_id,  # Pass specific task ID to end
        ))

    if isinstance(res, dict) and res.get("status") == "ok":
        res["status"] = "success"

    return res

