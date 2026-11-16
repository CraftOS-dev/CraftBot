from agent_core import action


@action(
    name="heartbeat_checklist_read",
    description="Read the Heartbeat checklist in PROACTIVE.md: the items the heartbeat checks every few minutes. Empty means the heartbeat does not run.",
    action_sets=["proactive"],
    input_schema={},
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise",
        },
        "checklist": {
            "type": "string",
            "description": "The checklist as markdown ('' when empty)",
        },
    },
)
def heartbeat_checklist_read(input_data: dict) -> dict:
    """Read the heartbeat checklist."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {"status": "error", "error": "Proactive manager not initialized"}
    try:
        return {"status": "ok", "checklist": manager.get_heartbeat_checklist()}
    except Exception as e:
        return {"status": "error", "error": str(e)}
