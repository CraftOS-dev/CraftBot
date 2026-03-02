from agent_core import action

@action(
    name="keyboard_hotkey",
    description="Sends arbitrary keystrokes or key-combination shortcuts to the currently focused window (e.g., 'ctrl+c', ['alt+tab', 'f5']).",
    mode="GUI",
    action_sets=["gui_interaction"],
    parallelizable=False,
    input_schema={
        "keys": {
            "type": [
                "string",
                "array"
            ],
            "example": [
                "ctrl+c",
                "alt+tab"
            ],
            "description": "A single key/combo string (\"enter\", \"ctrl+shift+t\") or a list of such strings executed in order (required)."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if all inputs were sent, 'error' otherwise."
        },
        "message": {
            "type": "string",
            "example": "Invalid key string.",
            "description": "Optional error message on failure."
        }
    },
    requirement=["pyautogui"],
    test_payload={
        "keys": [
            "ctrl+c",
            "alt+tab"
        ],
        "simulated_mode": False
    }
)
def keyboard_input(input_data: dict) -> dict:
    import json, sys, subprocess, importlib
    pkg = 'pyautogui'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])
    import pyautogui
    raw_keys = input_data.get('keys')
    if raw_keys is None or (isinstance(raw_keys, str) and not raw_keys.strip()) or (isinstance(raw_keys, list) and not raw_keys):
        return {'status': 'error', 'message': 'keys is required.'}
        exit()
    keys_seq = raw_keys if isinstance(raw_keys, list) else [raw_keys]
    try:
        for entry in keys_seq:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError('Invalid key string.')
            combo = [k.strip() for k in entry.lower().split('+') if k.strip()]
            if len(combo) == 0:
                raise ValueError('Invalid key string.')
            if len(combo) == 1:
                pyautogui.press(combo[0])
            else:
                pyautogui.hotkey(*combo)
        return {'status': 'success', 'message': ''}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}