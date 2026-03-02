from agent_core import action

@action(
    name="keyboard_type",
    description="Types the given text at the current keyboard focus in any active application window.",
    mode="GUI",
    action_sets=["gui_interaction"],
    parallelizable=False,
    input_schema={
        "text": {
            "type": "string",
            "example": "Hello, world!",
            "description": "The exact text to type (required)."
        },
        "interval": {
            "type": "number",
            "example": 0.05,
            "description": "Optional delay in seconds between each keystroke. Defaults to 0 (instant)."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if typing completed, 'error' otherwise."
        },
        "message": {
            "type": "string",
            "example": "No text provided.",
            "description": "Optional error message."
        }
    },
    requirement=["pyautogui"],
    test_payload={
        "text": "Hello, world!",
        "interval": 0.05,
        "simulated_mode": False
    }
)
def keyboard_typing(input_data: dict) -> dict:
    import json, sys, subprocess, importlib
    pkg = 'pyautogui'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])
    import pyautogui
    text = input_data.get('text', '')
    interval = float(input_data.get('interval', 0))
    if not text:
        return {'status': 'error', 'message': 'No text provided.'}
    try:
        pyautogui.write(text, interval=interval)
        return {'status': 'success', 'message': ''}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}