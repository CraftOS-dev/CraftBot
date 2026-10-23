# core/data/action/action_set_management.py
"""
Action Set Management Actions

A session's <actions> list is fixed by its type. These actions read the rest
of the action registry: add_action_sets delivers the schemas of extra sets
into the session's event stream, list_action_sets lists every set. Both
belong to the 'core' set and are always available.
"""

from agent_core import action


@action(
    name="add_action_sets",
    description=(
        "Get the schemas of action sets from the capability catalog that are "
        "not in <actions> (e.g. document_processing, image, mini_browser for "
        "using websites, an integration). The schemas, plus workflow guidance "
        "for any integration among them, arrive in your event stream as an "
        "action_schemas event; then call those actions by name like any action "
        "in <actions>. Your <actions> list itself does not change. Unknown "
        "names are reported back, not loaded."
    ),
    default=False,
    mode="ALL",
    action_sets=["core"],  # Always available
    input_schema={
        "action_sets": {
            "type": "array",
            "items": {"type": "string"},
            "example": ["mini_browser"],
            "description": (
                "List of action set names, exactly as in the capability "
                "catalog. Use 'list_action_sets' to see available options."
            ),
        },
    },
    output_schema={
        "success": {
            "type": "boolean",
            "description": "False only when none of the requested sets exist.",
        },
        "loaded_sets": {
            "type": "array",
            "description": "The requested sets that exist.",
        },
        "actions": {
            "type": "array",
            "description": (
                "Actions whose schemas were added to the event stream. Actions "
                "already in <actions> or in an earlier action_schemas event are "
                "not repeated."
            ),
        },
        "unknown_sets": {
            "type": "array",
            "description": "Requested names that are not action sets (nothing was loaded for them).",
        },
        "hint": {
            "type": "string",
            "description": "How to fix unknown set names (closest matches, skills to load with use_skill).",
        },
    },
    test_payload={
        "action_sets": ["file_operations"],
        "simulated_mode": True,
    },
)
def add_action_sets(input_data: dict) -> dict:
    """Deliver the schemas of action sets into the session's event stream."""
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
            "loaded_sets": action_sets,
            "actions": ["simulated_action_1", "simulated_action_2"],
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.load_action_sets(
            action_sets, session_id=input_data.get("_session_id")
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@action(
    name="list_action_sets",
    description=(
        "List all available action sets and their descriptions. "
        "Also shows which sets this session's <actions> list holds."
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
            "description": (
                "Action sets in this session's <actions> list. Fixed by the "
                "session type; add_action_sets does not change it."
            ),
        },
    },
    test_payload={
        "simulated_mode": True,
    },
)
def list_action_sets(input_data: dict) -> dict:
    """List all available action sets and the session's <actions> sets."""
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "available_sets": {
                "core": "Essential actions (always included)",
                "file_operations": "File and folder manipulation",
                "document_processing": "PDF and document handling",
                "image": "Image viewing, analysis, and OCR",
                "mini_browser": "Mini Browser: operate websites in a live Chromium",
            },
            "current_sets": ["core", "file_operations"],
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.list_action_sets(
            session_id=input_data.get("_session_id")
        )
        return result
    except Exception as e:
        return {"error": str(e)}
