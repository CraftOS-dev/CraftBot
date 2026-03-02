from agent_core import action

@action(
    name="ignore",
    description="If a user message requires no response or action, use ignore.",
    mode="CLI",
    action_sets=["core"],
    parallelizable=False,
    input_schema={},
    output_schema={
        "status": {
            "type": "string",
            "example": "ignored",
            "description": "Indicates the message was purposefully ignored."
        }
    },
    test_payload={
        "simulated_mode": True
    }
)
def ignore(input_data: dict) -> dict:
    import json
    
    simulated_mode = input_data.get('simulated_mode', False)
    
    if not simulated_mode:
        import app.internal_action_interface as internal_action_interface
        internal_action_interface.InternalActionInterface.do_ignore()
    return {'status': 'success', 'message': 'ignored'}