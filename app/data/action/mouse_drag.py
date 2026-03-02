from agent_core import action

@action(
        name="mouse_drag",
        description="Performs a left-button drag from a start coordinate to an end coordinate.",
        mode="GUI",
        action_sets=["gui_interaction"],
        parallelizable=False,
        input_schema={
                "start_x": {
                        "type": "integer",
                        "example": 400,
                        "description": "Starting X-coordinate in pixels (required)."
                },
                "start_y": {
                        "type": "integer",
                        "example": 300,
                        "description": "Starting Y-coordinate in pixels (required)."
                },
                "end_x": {
                        "type": "integer",
                        "example": 800,
                        "description": "Ending X-coordinate in pixels (required)."
                },
                "end_y": {
                        "type": "integer",
                        "example": 600,
                        "description": "Ending Y-coordinate in pixels (required)."
                },
                "duration": {
                        "type": "number",
                        "example": 0.5,
                        "description": "Optional duration (seconds) for a smooth drag."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success",
                        "description": "'success' if the drag completed, 'error' otherwise."
                },
                "message": {
                        "type": "string",
                        "example": "Missing coordinates.",
                        "description": "Optional error message."
                }
        },
        requirement=["pyautogui"],
        test_payload={
                "start_x": 400,
                "start_y": 300,
                "end_x": 800,
                "end_y": 600,
                "duration": 0.5,
                "simulated_mode": False
        }
)
def mouse_drag(input_data: dict) -> dict:
    import json, sys, subprocess, importlib
    pkg = 'pyautogui'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])
    import pyautogui
    sx = input_data.get('start_x')
    sy = input_data.get('start_y')
    ex = input_data.get('end_x')
    ey = input_data.get('end_y')
    duration = float(input_data.get('duration', 0))
    if None in (sx, sy, ex, ey):
        return {'status': 'error', 'message': 'All coordinates are required.'}
        exit()
    try:
        pyautogui.moveTo(int(sx), int(sy))
        pyautogui.mouseDown(button='left')
        pyautogui.dragTo(int(ex), int(ey), duration=duration, button='left')
        pyautogui.mouseUp(button='left')
        return {'status': 'success', 'message': ''}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}