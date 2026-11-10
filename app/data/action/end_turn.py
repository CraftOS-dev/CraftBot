from agent_core import action


@action(
    name="end_turn",
    description=(
        "End the current run without sending any message. Use this when the "
        "incoming message or event requires no response and no further work "
        "(e.g. a third-party notification that needs nothing). The session "
        "then waits for its next input."
    ),
    mode="CLI",
    action_sets=["core"],
    parallelizable=False,
    input_schema={},
    output_schema={
        "status": {
            "type": "string",
            "example": "turn ended",
            "description": "Indicates the run was purposefully ended.",
        },
        "end_turn": {
            "type": "boolean",
            "example": True,
            "description": "Always true — this action ends the run.",
        },
    },
    test_payload={"simulated_mode": True},
)
def end_turn(input_data: dict) -> dict:

    simulated_mode = input_data.get("simulated_mode", False)

    if not simulated_mode:
        from app.agent_app.framework_host import get_host

        host = get_host()
        creation = host.store.get("creation", input_data.get("_session_id")) if host else None
        if creation and creation.get("building"):
            return {
                "status": "error", "end_turn": False,
                "message": "This app build is unfinished. Continue the framework creator workflow, "
                           "validate, independently verify and promote before reporting completion. "
                           "If blocked, explain the blocker or ask the user through send_message.",
            }

        import app.internal_action_interface as internal_action_interface

        internal_action_interface.InternalActionInterface.do_end_turn()
    return {"status": "success", "message": "turn ended", "end_turn": True}
