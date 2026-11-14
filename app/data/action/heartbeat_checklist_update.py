from agent_core import action


@action(
    name="heartbeat_checklist_update",
    description="Replace the Heartbeat checklist in PROACTIVE.md. Every heartbeat tick, the agent reads this checklist, checks each item and reports only if something needs attention. Use it for things to keep an eye on (e.g. '- Check my inbox for urgent client email'); use cron_job_add for work at a set time. Read it first with heartbeat_checklist_read and pass the FULL new list. IMPORTANT: Only change it with user consent.",
    action_sets=["proactive"],
    input_schema={
        "checklist": {
            "type": "string",
            "required": True,
            "description": "The complete checklist as markdown, one item per line. An empty string clears it (the heartbeat then stops running).",
            "example": "- Check my inbox for urgent email from clients\n- If a deploy is running, tell me when it finishes",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "description": "ok if successful, error otherwise",
        },
        "message": {"type": "string", "description": "Confirmation message"},
    },
)
def heartbeat_checklist_update(input_data: dict) -> dict:
    """Replace the heartbeat checklist."""
    from app.proactive import get_proactive_manager

    manager = get_proactive_manager()
    if manager is None:
        return {"status": "error", "error": "Proactive manager not initialized"}
    checklist = input_data.get("checklist")
    if checklist is None:
        return {"status": "error", "error": "checklist is required"}
    try:
        manager.set_heartbeat_checklist(str(checklist))
        return {
            "status": "ok",
            "message": "Heartbeat checklist updated"
            if str(checklist).strip()
            else "Heartbeat checklist cleared",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
