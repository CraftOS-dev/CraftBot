from agent_core import action

@action(
    name="wait",
    description="Pause execution for a specified duration. Useful for waiting for UI elements to load or introducing delays in workflows.",
    mode="ALL",
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "seconds": {
            "type": "number",
            "example": 2.0,
            "description": "Duration to wait in seconds (max 60 seconds)."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'."
        },
        "waited_seconds": {
            "type": "number",
            "description": "Actual seconds waited."
        },
        "message": {
            "type": "string",
            "description": "Error message if status is 'error'."
        }
    },
    test_payload={
        "seconds": 0.1,
        "simulated_mode": True
    }
)
def wait(input_data: dict) -> dict:
    import time

    simulated_mode = input_data.get('simulated_mode', False)
    seconds = input_data.get('seconds', 1.0)

    try:
        seconds = float(seconds)
    except (ValueError, TypeError):
        return {'status': 'error', 'waited_seconds': 0, 'message': 'seconds must be a number.'}

    if seconds < 0:
        return {'status': 'error', 'waited_seconds': 0, 'message': 'seconds must be non-negative.'}

    if seconds > 60:
        return {'status': 'error', 'waited_seconds': 0, 'message': 'Maximum wait time is 60 seconds.'}

    if simulated_mode:
        return {
            'status': 'success',
            'waited_seconds': seconds
        }

    try:
        time.sleep(seconds)
        return {
            'status': 'success',
            'waited_seconds': seconds
        }
    except Exception as e:
        return {'status': 'error', 'waited_seconds': 0, 'message': str(e)}
