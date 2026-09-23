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
        # STRUCTURAL GUARD: a Agent App build must never be silently
        # abandoned mid-creation. Ending the run leaves the session asleep
        # forever (nothing re-wakes it), stranding the user on the creation
        # screen. Refuse and keep the run alive.
        session_id = input_data.get("_session_id")
        if session_id:
            try:
                from app.agent_app import get_agent_app_manager

                manager = get_agent_app_manager()
                project = (
                    manager.get_project_by_session_id(session_id) if manager else None
                )
                if project is not None and project.status == "creating":
                    return {
                        "status": "error",
                        "message": (
                            "REFUSED: this Agent App build is not finished — ending "
                            "the run now would strand it forever (nothing wakes the "
                            "session again). Valid ways to stop working: (1) keep "
                            "building the remaining features, (2) ask the user a "
                            "question via send_message with wait_for_user_reply=true, "
                            "or (3) finish with agent_app_notify_ready(project_id="
                            f"'{project.id}') and report the result. There is no "
                            "'continue in a later turn' — this run IS the build."
                        ),
                        "end_turn": False,
                    }
            except Exception:
                pass  # never let the guard itself break turn-ending

        import app.internal_action_interface as internal_action_interface

        internal_action_interface.InternalActionInterface.do_end_turn()
    return {"status": "success", "message": "turn ended", "end_turn": True}
