# core/data/action/action_set_management.py
"""
Action Set Management Actions

These actions allow the agent to dynamically manage action sets during task execution.
All three actions belong to the 'core' set and are always available.
"""

from agent_core import action


@action(
    name="add_action_sets",
    description=(
        "Add additional action sets to expand available actions for the current task. "
        "Use this when you need capabilities not currently available. "
        "Use 'list_action_sets' first to see available options."
    ),
    default=False,
    mode="ALL",
    action_sets=["core"],  # Always available
    parallelizable=False,
    input_schema={
        "action_sets": {
            "type": "array",
            "items": {"type": "string"},
            "example": ["gui_interaction", "shell"],
            "description": (
                "List of action set names to add. "
                "Use 'list_action_sets' to see available options."
            ),
        },
    },
    output_schema={
        "success": {
            "type": "boolean",
            "description": "Whether the operation succeeded.",
        },
        "current_sets": {
            "type": "array",
            "description": "Updated list of active action sets for this task.",
        },
        "added_actions": {
            "type": "array",
            "description": "List of new action names now available.",
        },
        "total_actions": {
            "type": "integer",
            "description": "Total number of actions now available.",
        },
    },
    test_payload={
        "action_sets": ["file_operations"],
        "simulated_mode": True,
    },
)
def add_action_sets(input_data: dict) -> dict:
    """Add action sets and recompile the action list for the current task."""
    action_sets = input_data.get("action_sets", [])
    simulated_mode = input_data.get("simulated_mode", False)

    if not action_sets:
        return {
            "success": False,
            "error": "No action sets specified to add.",
        }

    # Ensure action_sets is a list
    if not isinstance(action_sets, list):
        action_sets = [action_sets]

    if simulated_mode:
        return {
            "success": True,
            "current_sets": ["core"] + action_sets,
            "added_actions": ["simulated_action_1", "simulated_action_2"],
            "total_actions": 10,
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.add_action_sets(action_sets)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@action(
    name="remove_action_sets",
    description=(
        "Remove action sets from the current task to reduce available actions. "
        "Use this to clean up sets that are no longer needed. "
        "The 'core' set cannot be removed."
    ),
    default=False,
    mode="ALL",
    action_sets=["core"],  # Always available
    parallelizable=False,
    input_schema={
        "action_sets": {
            "type": "array",
            "items": {"type": "string"},
            "example": ["gui_interaction"],
            "description": "List of action set names to remove. Cannot remove 'core' set.",
        },
    },
    output_schema={
        "success": {
            "type": "boolean",
            "description": "Whether the operation succeeded.",
        },
        "current_sets": {
            "type": "array",
            "description": "Updated list of active action sets for this task.",
        },
        "removed_actions": {
            "type": "array",
            "description": "List of action names that were removed.",
        },
        "total_actions": {
            "type": "integer",
            "description": "Total number of actions still available.",
        },
    },
    test_payload={
        "action_sets": ["gui_interaction"],
        "simulated_mode": True,
    },
)
def remove_action_sets(input_data: dict) -> dict:
    """Remove action sets and recompile the action list for the current task."""
    action_sets = input_data.get("action_sets", [])
    simulated_mode = input_data.get("simulated_mode", False)

    if not action_sets:
        return {
            "success": False,
            "error": "No action sets specified to remove.",
        }

    # Ensure action_sets is a list
    if not isinstance(action_sets, list):
        action_sets = [action_sets]

    # Filter out 'core' from removal request
    action_sets = [s for s in action_sets if s != "core"]

    if not action_sets:
        return {
            "success": False,
            "error": "Cannot remove 'core' set. No other sets specified.",
        }

    if simulated_mode:
        return {
            "success": True,
            "current_sets": ["core"],
            "removed_actions": ["simulated_removed_action"],
            "total_actions": 5,
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.remove_action_sets(action_sets)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@action(
    name="list_action_sets",
    description=(
        "List all available action sets and their descriptions. "
        "Also shows which sets are currently active for this task."
    ),
    default=False,
    mode="ALL",
    action_sets=["core"],  # Always available
    input_schema={},
    output_schema={
        "available_sets": {
            "type": "object",
            "description": "Dictionary of all available action sets with their descriptions.",
        },
        "current_sets": {
            "type": "array",
            "description": "List of action sets currently active for this task.",
        },
    },
    test_payload={
        "simulated_mode": True,
    },
)
def list_action_sets(input_data: dict) -> dict:
    """List all available action sets and current task's active sets."""
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "available_sets": {
                "core": "Essential actions (always included)",
                "file_operations": "File and folder manipulation",
                "web_research": "Web search and browsing",
                "document_processing": "PDF and document handling",
                "gui_interaction": "Mouse, keyboard, screen",
                "clipboard": "Clipboard operations",
                "shell": "Command line execution",
            },
            "current_sets": ["core", "file_operations"],
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.list_action_sets()
        return result
    except Exception as e:
        return {"error": str(e)}
