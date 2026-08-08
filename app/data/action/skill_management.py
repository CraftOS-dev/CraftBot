# core/data/action/skill_management.py
"""
Skill Management Actions

These actions allow the agent to dynamically load and unload skills in its
session. All belong to the 'core' set and are always available.
"""

from agent_core import action


@action(
    name="list_skills",
    description=(
        "List all enabled skills with their names and descriptions. "
        "Use this to discover available skills before using 'use_skill'."
    ),
    default=False,
    mode="ALL",
    action_sets=["core"],
    input_schema={},
    output_schema={
        "skills": {
            "type": "object",
            "description": "Dictionary of enabled skill names to their descriptions.",
        },
    },
    test_payload={
        "simulated_mode": True,
    },
)
def list_skills(input_data: dict) -> dict:
    """List all enabled skills with their names and descriptions."""
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "skills": {
                "pdf": "Read and create PDF documents",
                "docx": "Read and create Word documents",
            },
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.list_skills()
        return result
    except Exception as e:
        return {"error": str(e)}


@action(
    name="use_skill",
    description=(
        "Load a skill into this session: its instructions are injected into "
        "your context and its recommended action sets are loaded. Skills are "
        "additive — loading one keeps the others. Unload skills you no longer "
        "need with 'unload_skill' to keep your context small. The capability "
        "catalog in your system prompt lists every available skill. If you "
        "only need to read a skill's instructions once, use 'read_file' on "
        "its SKILL.md instead."
    ),
    default=False,
    mode="ALL",
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "skill_name": {
            "type": "string",
            "description": "Name of the skill to load.",
            "example": "pdf",
        },
    },
    output_schema={
        "success": {
            "type": "boolean",
            "description": "Whether the skill was loaded successfully.",
        },
        "active_skills": {
            "type": "array",
            "description": "All skills now loaded in this session.",
        },
        "skill_description": {
            "type": "string",
            "description": "Description of the loaded skill.",
        },
        "added_action_sets": {
            "type": "array",
            "description": "Action sets that were added as recommended by the skill.",
        },
    },
    test_payload={
        "skill_name": "pdf",
        "simulated_mode": True,
    },
)
def use_skill(input_data: dict) -> dict:
    """Load a skill into the session (additive)."""
    skill_name = input_data.get("skill_name", "")
    simulated_mode = input_data.get("simulated_mode", False)

    if not skill_name:
        return {
            "success": False,
            "error": "No skill_name specified.",
        }

    if simulated_mode:
        return {
            "success": True,
            "active_skills": [skill_name],
            "skill_description": "Simulated skill description",
            "added_action_sets": [],
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.use_skill(
            skill_name, session_id=input_data.get("_session_id")
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@action(
    name="unload_skill",
    description=(
        "Unload a previously loaded skill from this session, removing its "
        "instructions from your context. Use this when a skill's work is done "
        "to keep your context focused."
    ),
    default=False,
    mode="ALL",
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "skill_name": {
            "type": "string",
            "description": "Name of the skill to unload.",
            "example": "pdf",
        },
    },
    output_schema={
        "success": {
            "type": "boolean",
            "description": "Whether the skill was unloaded successfully.",
        },
        "active_skills": {
            "type": "array",
            "description": "Skills still loaded in this session.",
        },
    },
    test_payload={
        "skill_name": "pdf",
        "simulated_mode": True,
    },
)
def unload_skill(input_data: dict) -> dict:
    """Unload a skill from the session."""
    skill_name = input_data.get("skill_name", "")
    simulated_mode = input_data.get("simulated_mode", False)

    if not skill_name:
        return {
            "success": False,
            "error": "No skill_name specified.",
        }

    if simulated_mode:
        return {
            "success": True,
            "active_skills": [],
        }

    import app.internal_action_interface as iai

    try:
        result = iai.InternalActionInterface.unload_skill(
            skill_name, session_id=input_data.get("_session_id")
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}
