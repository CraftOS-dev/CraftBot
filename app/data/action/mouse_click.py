from agent_core import action

@action(
    name="mouse_click",
    description="Performs a mouse click at the specified screen coordinates (or at the current cursor position if no coordinates are provided). Supports left, right, and middle buttons, as well as single and double clicks.",
    mode="GUI",
    action_sets=["gui_interaction"],
    parallelizable=False,
    input_schema={
        "x": {
            "type": "integer",
            "example": 640,
            "description": "X-coordinate in pixels. If omitted, the current cursor X is used."
        },
        "y": {
            "type": "integer",
            "example": 360,
            "description": "Y-coordinate in pixels. If omitted, the current cursor Y is used."
        },
        "button": {
            "type": "string",
            "example": "left",
            "description": "Mouse button to click: 'left', 'right', or 'middle'. Defaults to 'left'."
        },
        "click_type": {
            "type": "string",
            "example": "single",
            "description": "Click type: 'single' or 'double'. Defaults to 'single'."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the click succeeded, 'error' otherwise."
        },
        "position": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"}
            },
            "example": {"x": 640, "y": 360},
            "description": "The screen coordinates where the click was executed."
        },
        "message": {
            "type": "string",
            "example": "File not found.",
            "description": "Optional error message."
        }
    },
    requirement=["pyautogui"],
    test_payload={
        "x": 640,
        "y": 360,
        "button": "left",
        "click_type": "single",
        "simulated_mode": False
    }
)
def mouse_click(input_data: dict) -> dict:
    import sys, subprocess, importlib, time

    pkg = 'pyautogui'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])

    import pyautogui

    x = input_data.get('x')
    y = input_data.get('y')
    button = input_data.get('button', 'left').lower()
    click_type = input_data.get('click_type', 'single').lower()

    # Validate button
    if button not in ('left', 'right', 'middle'):
        return {'status': 'error', 'position': {}, 'message': f"Invalid button '{button}'. Must be 'left', 'right', or 'middle'."}

    # Validate click_type
    if click_type not in ('single', 'double'):
        return {'status': 'error', 'position': {}, 'message': f"Invalid click_type '{click_type}'. Must be 'single' or 'double'."}

    try:
        # Disable fail-safe for VM environments where cursor position detection can be unreliable
        pyautogui.FAILSAFE = False

        # Get screen size for boundary checking
        screen_width, screen_height = pyautogui.size()

        # Get position (use current if not specified)
        pos_x, pos_y = (x, y) if x is not None and y is not None else pyautogui.position()
        pos_x, pos_y = int(pos_x), int(pos_y)

        # Clamp coordinates to screen bounds with a small margin to avoid edge issues
        margin = 1
        pos_x = max(margin, min(pos_x, screen_width - margin))
        pos_y = max(margin, min(pos_y, screen_height - margin))

        # Now move to target position with visible duration
        pyautogui.moveTo(pos_x, pos_y, duration=0.1)
        time.sleep(0.1)

        # Perform click at the specified coordinates directly (don't rely on current position)
        if click_type == 'double':
            pyautogui.doubleClick(x=pos_x, y=pos_y, button=button)
        else:
            pyautogui.click(x=pos_x, y=pos_y, button=button)

        return {'status': 'success', 'position': {'x': pos_x, 'y': pos_y}, 'message': ''}
    except Exception as e:
        return {'status': 'error', 'position': {}, 'message': str(e)}
