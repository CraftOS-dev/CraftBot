"""Chat entry point into the existing app setup wizard."""

from agent_core import action

@action(
    name="agent_app_scaffold",
    description=(
        "Create an Agent App from a regular chat. Opens CraftBot's existing setup "
        "wizard when requirements need clarification, then starts the framework "
        "creator in the app's side chat. Follow the returned instructions; do not "
        "start a second build in this conversation."
    ),
    default=False,
    mode="CLI",
    action_sets=["agent_app"],
    parallelizable=False,
    input_schema={
        "name": {
            "type": "string",
            "required": True,
            "example": "Stock Forecaster",
            "description": "Display name for the Agent App project.",
        },
        "description": {
            "type": "string",
            "required": True,
            "example": "A dashboard that forecasts stock performance.",
            "description": (
                "Description of what the app does. Include EVERY requirement "
                "the user has given so far — it becomes the build instruction "
                "for the project's session."
            ),
        },
        "features": {
            "type": "array",
            "required": False,
            "example": ["watchlist", "forecasts", "alerts"],
            "description": "Optional list of high-level features requested by the user.",
        },
        "chat_context": {
            "type": "string",
            "required": False,
            "example": (
                'User: "I run a small pottery studio" / User: "no existing '
                'tools, maybe a marketplace app could help"'
            ),
            "description": (
                "The user's OWN words from the conversation that led here — "
                "verbatim quotes of what they asked for, constraints they "
                "stated, and hints they dropped. The requirements interviewer "
                "reads this to avoid asking what the user already answered; "
                "your description alone is a summary and loses their intent."
            ),
        },
        "theme": {
            "type": "string",
            "required": False,
            "enum": ["light", "dark", "system"],
            "example": "system",
            "description": "UI theme. Defaults to 'system'.",
        },
        "auth_mode": {
            "type": "string",
            "required": False,
            "enum": ["none", "multi-user"],
            "example": "none",
            "description": (
                "Auth mode from the requirements: 'none' for a personal local "
                "tool (default), 'multi-user' when the app needs accounts."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "Result: 'success' or 'error'.",
        },
        "sessionId": {"type": "string", "description": "App conversation; absent while the wizard is open."},
        "path": {"type": "string", "description": "Framework app destination."},
        "message": {
            "type": "string",
            "description": "Guidance on how to use the returned path.",
        },
    },
    test_payload={
        "name": "Test App",
        "description": "A test Agent App.",
        "simulated_mode": True,
    },
)
async def agent_app_scaffold(input_data: dict) -> dict:
    """Keep chat requirements gathering; delegate the build to Agent-App."""
    if input_data.get("simulated_mode"):
        return {"status": "success", "sessionId": "simulated"}
    import uuid

    from app.agent_app import wizard
    from app.agent_app.broadcast import broadcast_agent_app_wizard_open
    from app.agent_app.framework_host import get_host

    host = get_host()
    if host is None:
        return {"status": "error", "message": "The CraftBot app host is unavailable."}
    name = str(input_data.get("name") or "").strip()
    description = str(input_data.get("description") or "").strip()
    if not name or not description:
        return {"status": "error", "message": "name and description are required"}
    config = {
        "name": name, "description": description, "layout": "free",
        "authMode": input_data.get("auth_mode", "none"),
        "uiTheme": input_data.get("theme", "system"),
        "context": f"Requested features: {input_data.get('features', [])}\n"
                   f"From the chat: {input_data.get('chat_context', '')}",
    }
    try:
        questions = await wizard.generate_interview(config, [], allow_empty=True)
        if questions and await broadcast_agent_app_wizard_open({
            "wizardId": f"chat_{uuid.uuid4().hex[:12]}",
            "config": config, "questions": questions,
            "originSessionId": input_data.get("_session_id") or "",
        }):
            return {"status": "success", "message": (
                "Setup questions opened in the user's browser. No app has been created yet. "
                "The build starts in its own app conversation after the user answers. "
                "Tell the user to answer the popup, then end your turn. Do not start another build."
            )}
        requirements = await wizard.synthesize_requirements(config, [], [])
        result = await wizard.start_framework_build(host, config, requirements)
        return {"status": "success", **result, "message": (
            "The build started in the app's side chat. Follow its progress there; "
            "do not build it again in this conversation."
        )}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
