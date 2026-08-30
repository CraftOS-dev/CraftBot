from agent_core import action

# Input schema for memory relation lookup
_INPUT_SCHEMA = {
    "name_a": {
        "type": "string",
        "example": "John",
        "description": "First entity name. Case-insensitive.",
    },
    "name_b": {
        "type": "string",
        "example": "Agent App",
        "description": "Second entity name. Case-insensitive.",
    },
}

# Output schema for memory relation lookup
_OUTPUT_SCHEMA = {
    "status": {
        "type": "string",
        "example": "ok",
        "description": "Indicates the action completed successfully.",
    },
    "connected": {
        "type": "boolean",
        "example": True,
        "description": "Whether the two entities are connected in the memory graph.",
    },
    "path": {
        "type": "array",
        "description": "Node sequence connecting the two entities: alternating entities and the memory items / files that link them.",
        "example": [
            {"kind": "entity", "id": "e:john", "label": "John"},
            {
                "kind": "item",
                "id": "i:m1a2b3c4d5e6",
                "label": "John built the Agent App dashboard",
                "category": "event",
                "superseded": False,
            },
            {"kind": "entity", "id": "e:agent app", "label": "Agent App"},
        ],
    },
}


@action(
    name="memory_related",
    description="Find how two entities (people, projects, tools, concepts) are connected in the agent's memory: returns the shortest chain of facts and files linking them. Use this to answer questions like 'what does X have to do with Y'.",
    mode="ALL",
    platforms=["linux", "windows", "darwin"],
    action_sets=["core"],
    input_schema=_INPUT_SCHEMA,
    output_schema=_OUTPUT_SCHEMA,
    test_payload={"name_a": "John", "name_b": "CraftBot", "simulated_mode": True},
)
def memory_related(input_data: dict) -> dict:
    """
    Find the shortest connection between two entities in memory.
    """
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "ok",
            "connected": True,
            "path": [
                {"kind": "entity", "id": "e:john", "label": "John"},
                {
                    "kind": "item",
                    "id": "i:m1a2b3c4d5e6",
                    "label": "John is testing CraftBot",
                    "category": "fact",
                    "superseded": False,
                },
                {"kind": "entity", "id": "e:craftbot", "label": "CraftBot"},
            ],
        }

    try:
        from app.ui_layer.settings.memory_settings import is_memory_enabled

        if not is_memory_enabled():
            return {
                "status": "ok",
                "connected": False,
                "path": [],
                "message": "Memory is disabled",
            }

        name_a = (input_data.get("name_a") or "").strip()
        name_b = (input_data.get("name_b") or "").strip()
        if not name_a or not name_b:
            return {
                "status": "error",
                "connected": False,
                "path": [],
                "error": "name_a and name_b are required",
            }

        from app.internal_action_interface import InternalActionInterface

        path = InternalActionInterface.memory_related(name_a, name_b)
        if not path:
            return {
                "status": "ok",
                "connected": False,
                "path": [],
                "message": (
                    f"No connection between '{name_a}' and '{name_b}' in memory. "
                    "One of them may not exist as an entity — try memory_entity to check."
                ),
            }

        return {"status": "ok", "connected": True, "path": path}

    except RuntimeError as e:
        return {"status": "error", "connected": False, "path": [], "error": str(e)}
    except Exception as e:
        return {"status": "error", "connected": False, "path": [], "error": str(e)}
