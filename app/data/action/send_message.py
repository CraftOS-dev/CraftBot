from agent_core import action


@action(
    name="send_message",
    irreversible=True,
    description="Use this action to deliver a detailed text update that will be recorded in the conversation log and event stream. Avoid revealing internal or sensitive information and do not mention conversation identifiers. This action does not perform work; it only communicates status to the user. This action can be executed in parallel with other actions, but do not use multiple send_message actions at the same time as that is redundant - combine messages into one.",
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "message": {
            "type": "string",
            "example": "Hello, user!",
            "description": "The chat message to send. Send message in terminal friendly format and DO NOT include mark down. State only actions and results that actually happened per the event stream. If something can't be done, say so plainly (\"there's no way I can do that\" / \"this can't be done\") — never fabricate a setting, parameter, or effect you did not actually perform, and never invent a new explanation on retry if the user pushes back.",
        },
        "wait_for_user_reply": {
            "type": "boolean",
            "example": True,
            "description": "True if this action requires user's response to proceed. IMPORTANT: If set to true, you MUST (1) let the user know you are waiting for their reply, and (2) phrase the message as a question so the user has something to reply to. The agent will pause and wait for user input before continuing.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "ok",
            "description": "Indicates the action completed successfully.",
        },
        "fire_at_delay": {
            "type": "number",
            "example": 10800,
            "description": "Delay in seconds before the next follow-up action should be scheduled. 10800 seconds (3 hours) if wait_for_user_reply is true, otherwise 0.",
        },
    },
    test_payload={
        "message": "Hello, user!",
        "wait_for_user_reply": True,
        "simulated_mode": True,
    },
)
async def send_message(input_data: dict) -> dict:

    message = input_data["message"]
    wait_for_user_reply = bool(input_data.get("wait_for_user_reply", False))
    simulated_mode = input_data.get("simulated_mode", False)
    # Extract session_id injected by ActionManager for multi-task isolation
    session_id = input_data.get("_session_id")

    # In simulated mode, skip the actual interface call for testing
    if not simulated_mode:
        import app.internal_action_interface as internal_action_interface

        await internal_action_interface.InternalActionInterface.do_chat(
            message, session_id=session_id
        )

        # Mirror a "waiting for reply" question onto the Living UI creation
        # screen (no-op unless this session is a Living UI creation task) so the
        # user can answer from the Living UI page even with the chat panel closed.
        if wait_for_user_reply and session_id:
            try:
                from app.living_ui import broadcast_living_ui_question

                await broadcast_living_ui_question(session_id, message)
            except Exception:
                pass

    fire_at_delay = 10800 if wait_for_user_reply else 0
    # Return 'success' for test compatibility, but keep 'ok' in production if needed
    status = "success" if simulated_mode else "ok"
    return {
        "status": status,
        "fire_at_delay": fire_at_delay,
        "wait_for_user_reply": wait_for_user_reply,
    }
