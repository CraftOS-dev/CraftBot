from agent_core import action

# Input schema for memory entity lookup
_INPUT_SCHEMA = {
    "name": {
        "type": "string",
        "example": "Living UI",
        "description": "The entity to look up (a person, project, tool, or concept). Case-insensitive.",
    },
}

# Output schema for memory entity lookup
_OUTPUT_SCHEMA = {
    "status": {
        "type": "string",
        "example": "ok",
        "description": "Indicates the action completed successfully.",
    },
    "found": {
        "type": "boolean",
        "example": True,
        "description": "Whether the entity exists in the memory graph.",
    },
    "entity": {
        "type": "object",
        "description": "Entity overview: name, mention_count, items (facts about it), related_entities, and files that mention it.",
        "example": {
            "entity": "Living UI",
            "mention_count": 4,
            "items": [
                {
                    "item_id": "m1a2b3c4d5e6",
                    "timestamp": "2026-08-11 03:00:00",
                    "category": "project",
                    "content": "Living UI projects are managed from the sidebar",
                    "superseded": False,
                }
            ],
            "related_entities": [{"name": "CraftBot", "shared_items": 2}],
            "files": ["AGENT.md"],
        },
    },
}


@action(
    name="memory_entity",
    description="Look up everything the agent's memory knows about one entity (a person, project, tool, or concept): all facts mentioning it, related entities, and indexed files that reference it. Use this instead of memory_search when the subject is a specific named thing.",
    mode="ALL",
    platforms=["linux", "windows", "darwin"],
    action_sets=["core"],
    input_schema=_INPUT_SCHEMA,
    output_schema=_OUTPUT_SCHEMA,
    test_payload={"name": "CraftBot", "simulated_mode": True},
)
def memory_entity(input_data: dict) -> dict:
    """
    Look up an entity in the agent's memory graph.

    Returns the entity's facts, related entities, and source files.
    """
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "ok",
            "found": True,
            "entity": {
                "entity": "CraftBot",
                "mention_count": 3,
                "items": [
                    {
                        "item_id": "m1a2b3c4d5e6",
                        "timestamp": "2026-08-11 03:00:00",
                        "category": "fact",
                        "content": "CraftBot is the local agent application",
                        "superseded": False,
                    }
                ],
                "related_entities": [{"name": "Living UI", "shared_items": 1}],
                "files": ["AGENT.md"],
            },
        }

    try:
        from app.ui_layer.settings.memory_settings import is_memory_enabled

        if not is_memory_enabled():
            return {
                "status": "ok",
                "found": False,
                "entity": None,
                "message": "Memory is disabled",
            }

        name = (input_data.get("name") or "").strip()
        if not name:
            return {"status": "error", "found": False, "error": "name is required"}

        from app.internal_action_interface import InternalActionInterface

        overview = InternalActionInterface.memory_entity(name)
        if overview is None:
            return {
                "status": "ok",
                "found": False,
                "entity": None,
                "message": f"No entity named '{name}' in memory. Try memory_search for a broader semantic lookup.",
            }

        return {"status": "ok", "found": True, "entity": overview}

    except RuntimeError as e:
        return {"status": "error", "found": False, "error": str(e)}
    except Exception as e:
        return {"status": "error", "found": False, "error": str(e)}
