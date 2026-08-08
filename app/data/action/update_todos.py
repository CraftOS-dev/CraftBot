from agent_core import action


@action(
    name="update_todos",
    description=(
        "Update the todo list for the current run of this session. Use todos whenever the work "
        "takes more than a couple of actions. The todo list follows a structured workflow:\n"
        "1. Acknowledge the request (send message to user)\n"
        "2. Collect information (gather what's needed before execution by asking user, search online, search from memory, search agent workspace and file system) [one or multiple steps]\n"
        "3. Execute the work steps [one or multiple steps]\n"
        "4. Verify outcome (check if result meets requirements) [one or multiple steps]\n"
        "5. Deliver the result to the user\n"
        "6. Clean up (delete temp files if any)\n\n"
        "Always provide the COMPLETE todo list. Mark items as 'in_progress' when starting, 'completed' when done. "
        "This action can be executed in parallel with send_message, but do not use multiple update_todos actions at the same time."
    ),
    mode="ALL",
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "todos": {
            "type": "array",
            "description": 'Array of todo objects — this payload REPLACES the whole list, so ALWAYS send the complete list (every item you want to keep, not just changes). Each object MUST have exactly 2 keys: \'content\' (string: the task text) and \'status\' (string: \'pending\'|\'in_progress\'|\'completed\'). Example: [{"content": "Do X", "status": "completed"}, {"content": "Do Y", "status": "in_progress"}]',
            "required": True,
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates if the update was successful",
        },
        "message": {
            "type": "string",
            "example": "List now has 7 todos (3 completed, 1 in progress, 3 pending).",
            "description": "Summary of the FULL merged list after this update.",
        },
    },
    test_payload={
        "todos": [
            {
                "content": "Acknowledge request and confirm understanding",
                "status": "completed",
            },
            {
                "content": "Collect: Identify required data sources",
                "status": "in_progress",
            },
            {"content": "Execute: Process the data", "status": "pending"},
            {"content": "Verify: Validate output correctness", "status": "pending"},
            {"content": "Deliver: Send the result to the user", "status": "pending"},
        ],
        "simulated_mode": True,
    },
)
def update_todos(input_data: dict) -> dict:
    """Update the todo list for the current session."""
    todos = input_data.get("todos", [])
    simulated_mode = input_data.get("simulated_mode", False)

    if not simulated_mode:
        import app.internal_action_interface as iai

        result = iai.InternalActionInterface.update_todos(
            todos, session_id=input_data.get("_session_id")
        )
        status = "success" if result.get("status") in ("ok", "success") else "error"
        # Echo the resulting list state — the payload replaces the whole list,
        # so this is the model's (and the activity feed's) immediate feedback
        # on what the list actually became after this call.
        updated = result.get("todos", []) or []
        counts = {"completed": 0, "in_progress": 0, "pending": 0}
        for t in updated:
            key = t.get("status", "pending")
            counts[key] = counts.get(key, 0) + 1
        return {
            "status": status,
            "message": (
                f"List now has {len(updated)} todos ({counts['completed']} completed, "
                f"{counts['in_progress']} in progress, {counts['pending']} pending)."
            ),
        }

    return {"status": "success"}
