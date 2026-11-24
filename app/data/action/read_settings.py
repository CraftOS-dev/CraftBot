from agent_core import action


@action(
    name="read_settings",
    effects=[],
    description=(
        "Read CraftBot's settings (models and providers per interface, "
        "endpoints, proactive, memory, GUI and other options) with every API "
        "key and credential hidden: each one shows only whether it is set. "
        "Use this to see which provider or model the user has configured, "
        "instead of reading settings.json directly. Optional `section` returns "
        "one top-level section, e.g. 'model'."
    ),
    mode="CLI",
    action_sets=["core"],
    input_schema={
        "section": {
            "type": "string",
            "description": "One top-level section to return, e.g. 'model'. Omit for all.",
            "example": "model",
        },
    },
    output_schema={
        "status": {"type": "string", "description": "success or error"},
        "settings": {"type": "object", "description": "Settings, secrets hidden"},
        "message": {"type": "string", "description": "Error detail"},
    },
    test_payload={"section": "model", "simulated_mode": True},
    display_param="section",
    icon="Settings",
)
def read_settings(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "settings": {"model": {"llm_provider": "anthropic"}}}
    from app.config import get_settings
    from app.security.redact import hide_secrets

    settings = hide_secrets(get_settings(reload=True))
    section = (input_data.get("section") or "").strip()
    if section:
        if section not in settings:
            return {
                "status": "error",
                "settings": {},
                "message": f"No settings section '{section}'. Sections: {', '.join(sorted(settings))}.",
            }
        settings = {section: settings[section]}
    return {"status": "success", "settings": settings}
