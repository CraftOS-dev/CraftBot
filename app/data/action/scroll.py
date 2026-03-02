from agent_core import action

@action(
    name="scroll",
    description="Scrolls the active window one viewport up or down (≈90 % of the screen height, leaving ~10 % overlap).",
    mode="GUI",
    action_sets=["gui_interaction"],
    parallelizable=False,
    input_schema={
        "direction": {
            "type": "string",
            "enum": [
                "up",
                "down"
            ],
            "example": "down",
            "description": "Scroll direction."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if scrolling succeeded, 'error' otherwise."
        },
        "message": {
            "type": "string",
            "example": "Invalid direction.",
            "description": "Optional error message if the operation failed."
        }
    },
    requirement=["pyautogui"],
    test_payload={
        "direction": "down",
        "simulated_mode": False
    }
)
def scroll(input_data: dict) -> dict:
    import json, sys, subprocess, importlib
    pkg = 'pyautogui'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])
    import pyautogui

    direction = str(input_data.get('direction', '')).lower()
    if direction not in {'up', 'down'}:
        return {'status': 'error', 'message': 'direction must be "up" or "down".'}