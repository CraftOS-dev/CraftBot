from agent_core import action


@action(
    name="send_message",
    irreversible=True,
    description=(
        "Use this action to deliver a text update to the user; it is recorded in the "
        "conversation log and event stream. Avoid revealing internal or sensitive "
        "information and do not mention session identifiers. By default this ENDS the "
        "current run: send your message as the only action when you are done (or when "
        "you need the user's answer before you can continue), and the session will wait "
        "for the user's next input. Set continue_work=true ONLY for progress updates "
        "sent while you still have more work to do. Do not use multiple send_message "
        "actions at the same time - combine messages into one."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "message": {
            "type": "string",
            "example": "Hello, user!",
            "description": "The chat message to send. Send message in terminal friendly format and DO NOT include mark down.",
        },
        "continue_work": {
            "type": "boolean",
            "example": False,
            "description": (
                "False (default): this is your final message for now — the run ends and "
                "the session waits for the user. True: this is a progress update and you "
                "will keep working after sending it."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "ok",
            "description": "Indicates the action completed successfully.",
        },
        "end_turn": {
            "type": "boolean",
            "example": True,
            "description": "True when this message ends the current run.",
        },
    },
    test_payload={
        "message": "Hello, user!",
        "continue_work": False,
        "simulated_mode": True,
    },
)
async def send_message(input_data: dict) -> dict:

    message = input_data["message"]
    continue_work = bool(input_data.get("continue_work", False))
    simulated_mode = input_data.get("simulated_mode", False)
    # Extract session_id injected by ActionManager for multi-session isolation
    session_id = input_data.get("_session_id")

    # In simulated mode, skip the actual interface call for testing
    if not simulated_mode:
        import app.internal_action_interface as internal_action_interface

        await internal_action_interface.InternalActionInterface.do_chat(
            message, session_id=session_id
        )

        # Mirror a final question onto the Living UI creation screen (no-op
        # unless this session belongs to a Living UI project) so the user can
        # answer from the Living UI page even with the chat panel closed.
        if not continue_work and session_id:
            try:
                from app.living_ui import broadcast_living_ui_question

                await broadcast_living_ui_question(session_id, message)
            except Exception:
                pass

    # Return 'success' for test compatibility, but keep 'ok' in production if needed
    status = "success" if simulated_mode else "ok"
    return {
        "status": status,
        "end_turn": not continue_work,
    }
