from agent_core import action


@action(
    name="ask_user_questions",
    irreversible=True,
    description=(
        "Ask the user one or more clarifying questions before continuing, when you genuinely "
        "cannot proceed without more information. USE THIS when you have concrete choices to put "
        "in front of the user (which connected account, which of these files, yes/no-style "
        "decisions) — buttons are faster and less ambiguous than free text. Also use it to ask "
        "SEVERAL related questions together as one batch (with a review step before submitting), "
        "even if one of those questions in the batch doesn't have natural choices. "
        "DO NOT use this for a single standalone question that has no natural choices (e.g. just "
        "'what's the recipient's email?' alone) — that is a normal conversation, not a form: use a "
        "send message action with wait_for_user_reply=true instead and let the user reply in the "
        "chat like normal. Popping a structured question card for something that's really just one "
        "plain question breaks the conversational flow and trains the user to stop paying attention "
        "to these prompts. Also use send_message/wait_for_user_reply for anything that must go out "
        "on an external platform (Telegram, WhatsApp, etc.), since this action only renders in the "
        "local CraftBot chat. Each question can offer multiple-choice buttons; the user can also "
        "always type a free-text answer or escape out of the whole batch without answering. Do NOT "
        "use this for trivial details you could reasonably infer or default — only for genuine "
        "ambiguity that would produce a wrong or unwanted result if you guessed. This action always "
        "pauses the task until the user responds; do not pair it with task_start (it would park the "
        "task before it runs). If the user escapes without answering, you will see 'The user "
        "declined to answer.' in their reply — do NOT immediately re-ask the same questions; ask in "
        "plain chat what they'd like you to do instead. During a proactive/scheduled run with "
        "nobody connected to the interface, this action refuses with an error instead of parking "
        "indefinitely — proceed with your best judgment or end the task instead."
    ),
    default=True,
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "questions": {
            "type": "array",
            "description": (
                "Array of question objects, asked together as one batch. Each object has "
                "'question' (string: the question text, REQUIRED), 'choices' (array of strings: "
                "2-6 short answers; can be an EMPTY array for one question within a multi-question "
                "batch that has no natural choices, but don't call this action with a single "
                "question that has empty choices — that's a plain conversational question, use "
                "send_message instead), and 'multi_select' (boolean, OPTIONAL, default false: true "
                "if the user may pick more than one choice, shown as checkboxes; false shows "
                "single-pick buttons). The user can always free-type an answer instead of picking a "
                "choice, or decline, so choices don't need to be exhaustive. "
                'Example single-pick: [{"question": "Which Gmail account should I use?", "choices": '
                '["alan@work.com", "alan@personal.com"]}]\n'
                'Example multi-pick: [{"question": "Which recipients should get this?", "choices": '
                '["alan@work.com", "team@work.com", "boss@work.com"], "multi_select": true}]\n'
                'Example batch mixing a choice question with an open-ended one: '
                '[{"question": "Which account?", "choices": ["work", "personal"]}, '
                '{"question": "What should the subject be?", "choices": []}]'
            ),
            "example": [
                {
                    "question": "Which Gmail account should I use to send this?",
                    "choices": ["alan@work.com", "alan@personal.com"],
                }
            ],
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
            "description": "Delay in seconds before the next follow-up action should be scheduled. Always 10800 (3 hours) — this action always pauses for a reply.",
        },
        "wait_for_user_reply": {
            "type": "boolean",
            "example": True,
            "description": "Always true — tells the agent loop to mark the task as waiting and hold off the next trigger until the user replies.",
        },
    },
    test_payload={
        "questions": [
            {
                "question": "Which Gmail account should I use to send this?",
                "choices": ["alan@work.com", "alan@personal.com"],
            }
        ],
        "simulated_mode": True,
    },
)
async def ask_user_questions(input_data: dict) -> dict:
    questions = input_data.get("questions") or []
    simulated_mode = input_data.get("simulated_mode", False)
    session_id = input_data.get("_session_id")

    if not questions:
        return {"status": "error", "message": "questions must be a non-empty array"}

    if not simulated_mode:
        import app.internal_action_interface as internal_action_interface

        ui_adapter = internal_action_interface.InternalActionInterface.ui_adapter
        ws_clients = getattr(ui_adapter, "_ws_clients", None)
        if ws_clients is not None and len(ws_clients) == 0:
            return {
                "status": "error",
                "message": (
                    "Cannot ask the user right now — no one is connected to the CraftBot "
                    "interface (this looks like a proactive/scheduled run with nobody watching). "
                    "Do not wait on a reply that may not come for hours: proceed with your best "
                    "reasonable judgment and note the assumption you made, or end the task if you "
                    "truly cannot proceed without this answer."
                ),
            }

        from app.ui_layer.components.types import ChatMessageOption, ChatMessageQuestion

        question_objs = [
            ChatMessageQuestion(
                id=f"q{i + 1}",
                text=q.get("question", ""),
                choices=[
                    ChatMessageOption(label=c, value=c)
                    for c in q.get("choices", [])
                ],
                multi_select=bool(q.get("multi_select", False)),
            )
            for i, q in enumerate(questions)
        ]
        content = "\n".join(f"{i + 1}. {q.text}" for i, q in enumerate(question_objs))

        if ui_adapter is not None:
            from app.onboarding import onboarding_manager

            agent_name = onboarding_manager.state.agent_name or "Agent"
            await ui_adapter._display_chat_message(
                agent_name,
                content,
                "agent",
                task_session_id=session_id,
                questions=question_objs,
            )

    status = "success" if simulated_mode else "ok"
    return {"status": status, "fire_at_delay": 10800, "wait_for_user_reply": True}
