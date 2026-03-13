from agent_core import action


@action(
    name="task_start",
    description=(
        "Start a new task. Use task_mode='simple' for quick tasks completable in 2-3 actions "
        "(weather lookup, search queries, calculations). Use task_mode='complex' for multi-step "
        "work requiring planning and verification. Complex tasks use todo lists; simple tasks do not. "
        "Action sets are automatically selected based on the task description."
    ),
    default=True,
    mode="CLI",
    action_sets=["core"],
    input_schema={
        "task_name": {
            "type": "string",
            "example": "Research weather in Fukuoka",
            "description": "A short name for the task.",
        },
        "task_description": {
            "type": "string",
            "example": "Find and report the current weather conditions in Fukuoka, Japan.",
            "description": "A detailed description of what the task should accomplish.",
        },
        "task_mode": {
            "type": "string",
            "example": "simple",
            "description": "Task mode: 'simple' for quick tasks (2-3 actions, no todos), 'complex' for multi-step work (uses todos, requires user approval). Defaults to 'complex'.",
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
            "example": "task_abc123",
            "description": "The unique identifier for the created task.",
        },
        "action_sets": {
            "type": "array",
            "description": "The action sets automatically selected for this task.",
        },
        "action_count": {
            "type": "integer",
            "description": "Number of actions available for this task.",
        },
    },
    test_payload={
        "task_name": "Test Task",
        "task_description": "A test task for validation.",
        "simulated_mode": True,
    },
)
async def start_task(input_data: dict) -> dict:
    """Async action function - awaited directly by executor for true parallel execution."""
    task_name = input_data.get("task_name", "").strip()
    task_description = input_data.get("task_description", "").strip()
    task_mode = input_data.get("task_mode", "complex").strip().lower()
    simulated_mode = input_data.get("simulated_mode", False)
    # Extract session_id injected by ActionManager for stream isolation
    session_id = input_data.get("_session_id")
    # Extract original user query and platform for logging to the new task's event stream
    original_query = input_data.get("_original_query")
    original_platform = input_data.get("_original_platform")

    if not task_name:
        return {
            "status": "error",
            "message": "Task name is required.",
        }

    if not task_description:
        return {
            "status": "error",
            "message": "Task description is required.",
        }

    # Validate task_mode
    if task_mode not in ("simple", "complex"):
        task_mode = "complex"

    # In simulated mode, skip the actual interface call for testing
    if simulated_mode:
        return {
            "status": "success",
            "task_id": "test_task_id",
            "task_mode": task_mode,
            "action_sets": ["core"],
            "action_count": 10,  # Approximate for testing
        }

    import app.internal_action_interface as iai

    try:
        # Action sets are automatically selected by do_create_task based on task description
        # do_create_task is async - await directly for true parallel execution
        # Pass session_id so task_id == session_id for event stream isolation
        # Pass original_query to log user message to the new task's event stream
        result = await iai.InternalActionInterface.do_create_task(
            task_name, task_description, task_mode,
            session_id=session_id,
            original_query=original_query,
            original_platform=original_platform,
        )
        return {
            "status": "success",
            "task_id": result["task_id"],
            "task_mode": task_mode,
            "action_sets": result.get("action_sets", []),
            "action_count": result.get("action_count", 0),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
