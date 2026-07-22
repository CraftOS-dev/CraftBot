from agent_core import action


@action(
    name="ignore",
    description=(
        "If the incoming message or event requires no response and no action "
        "(e.g. a third-party notification that needs nothing), use ignore. "
        "This ends the current run silently."
    ),
    mode="CLI",
    action_sets=["core"],
    parallelizable=False,
    input_schema={},
    output_schema={
        "status": {
            "type": "string",
            "example": "ignored",
            "description": "Indicates the message was purposefully ignored.",
        },
        "end_turn": {
            "type": "boolean",
            "example": True,
            "description": "Always true — ignoring ends the run.",
        },
    },
    test_payload={"simulated_mode": True},
)
def ignore(input_data: dict) -> dict:

    simulated_mode = input_data.get("simulated_mode", False)

    if not simulated_mode:
        import app.internal_action_interface as internal_action_interface

        internal_action_interface.InternalActionInterface.do_ignore()
    return {"status": "success", "message": "ignored", "end_turn": True}
