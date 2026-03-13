from agent_core import action

@action(
    name="task_update_todos",
    description=(
        "Update the todo list for the current task. The todo list follows a structured workflow:\n"
        "1. Acknowledge task receipt (send message to user)\n"
        "2. Collect information (gather what's needed before execution by asking user, search online, search from memory, search agent workspace and file system) [one or multiple steps]\n"
        "3. Execute task steps (the actual work)\n [one or multiple steps]"
        "4. Verify outcome (check if result meets requirements) [one or multiple steps]\n"
        "5. Confirm with user (get approval before ending)\n"
        "6. Clean up (delete temp files if any)\n\n"
        "Always provide the COMPLETE todo list. Mark items as 'in_progress' when starting, 'completed' when done. "
        "This action can be executed in parallel with send_message, but do not use multiple task_update_todos actions at the same time."
    ),
    mode="ALL",
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "todos": {
            "type": "array",
            "description": "Array of todo objects. Each object MUST have exactly 2 keys: 'content' (string: the task text) and 'status' (string: 'pending'|'in_progress'|'completed'). Example: [{\"content\": \"Do X\", \"status\": \"completed\"}, {\"content\": \"Do Y\", \"status\": \"in_progress\"}]",
            "required": True
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Indicates if the update was successful"
        }
    },
    test_payload={
        "todos": [
            {"content": "Acknowledge task and confirm understanding", "status": "completed"},
            {"content": "Collect: Identify required data sources", "status": "in_progress"},
            {"content": "Execute: Process the data", "status": "pending"},
            {"content": "Verify: Validate output correctness", "status": "pending"},
            {"content": "Confirm: Get user approval", "status": "pending"}
        ],
        "simulated_mode": True
    }
)
def update_todos(input_data: dict) -> dict:
    """Update the todo list for the current task."""
    todos = input_data.get("todos", [])
    simulated_mode = input_data.get("simulated_mode", False)

    if not simulated_mode:
        import app.internal_action_interface as iai
        result = iai.InternalActionInterface.update_todos(todos)
        status = "success" if result.get("status") in ("ok", "success") else "error"
        return {"status": status}

    return {"status": "success"}
