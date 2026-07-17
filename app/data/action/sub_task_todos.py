from agent_core import action


@action(
    name="sub_task_todos",
    description=(
        "Set or update YOUR OWN todo list for this sub-agent run. ONLY "
        "sub-agents may call this. Send the FULL list each time (it "
        "replaces the previous one). Derive it from your brief/query as "
        "your FIRST action — one item per acceptance criterion or "
        "deliverable — and keep statuses updated as you work. Exit checks "
        "may refuse sub_task_end while items are not completed."
    ),
    # Empty action_sets: not compiled into normal task action lists. Only
    # reachable for sub-agent types that list it in their definition.
    action_sets=[],
    mode="CLI",
    parallelizable=False,
    irreversible=False,
    input_schema={
        "todos": {
            "type": "array",
            "example": [
                {
                    "content": "Criterion 1: form creates a record",
                    "status": "completed",
                },
                {"content": "Tests pass", "status": "in_progress"},
            ],
            "description": (
                "The complete todo list: [{content, status}] with status one "
                "of 'pending' | 'in_progress' | 'completed'."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' when the list was stored.",
        },
        "summary": {
            "type": "string",
            "example": "3/5 completed",
            "description": "Completion summary of the stored list.",
        },
    },
    test_payload={
        "todos": [{"content": "test", "status": "pending"}],
        "simulated_mode": True,
    },
)
def sub_task_todos(input_data: dict) -> dict:
    # Imports inside the function — required by the action runtime model.
    from app.internal_action_interface import InternalActionInterface

    if input_data.get("simulated_mode"):
        return {"status": "success", "summary": "0/1 completed"}

    sub_id = input_data.get("_session_id")
    raw = input_data.get("todos")

    if not sub_id:
        return {
            "status": "error",
            "message": (
                "sub_task_todos was called outside a sub-agent context "
                "(missing _session_id)."
            ),
        }
    if not isinstance(raw, list) or not raw:
        return {
            "status": "error",
            "message": "todos must be a non-empty array of {content, status}.",
        }

    todos = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        status = str(item.get("status", "pending")).strip().lower()
        if not content:
            continue
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        todos.append({"content": content, "status": status})
    if not todos:
        return {
            "status": "error",
            "message": "No valid todo items found (each needs a content string).",
        }

    mgr = InternalActionInterface.subagent_manager
    sub = mgr.get(sub_id) if mgr else None
    if sub is None:
        return {
            "status": "error",
            "message": (
                f"No sub-agent registered with id {sub_id!r}. sub_task_todos "
                "is only valid inside an active sub-agent run."
            ),
        }

    sub.todos = todos
    done = sum(1 for t in todos if t["status"] == "completed")
    return {"status": "success", "summary": f"{done}/{len(todos)} completed"}
