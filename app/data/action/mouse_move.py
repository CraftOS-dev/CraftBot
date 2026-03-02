from agent_core import action

@action(
        name="mouse_move",
        description="Moves the mouse cursor to a specific screen coordinate.",
        mode="GUI",
        action_sets=["gui_interaction"],
        parallelizable=False,
        input_schema={
                "x": {
                        "type": "integer",
                        "example": 640,
                        "description": "Target X-coordinate in pixels (required)."
                },
                "y": {
                        "type": "integer",
                        "example": 360,
                        "description": "Target Y-coordinate in pixels (required)."
                },
                "duration": {
                        "type": "number",
                        "example": 0.25,
                        "description": "Optional duration in seconds for a smooth move. Defaults to instant."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success",
                        "description": "'success' if the cursor moved, 'error' otherwise."
                },
                "position": {
                        "type": "object",
                        "properties": {
                                "x": {"type": "integer"},
                                "y": {"type": "integer"}
                        },
                        "description": "The final cursor coordinates."
                },
                "message": {
                        "type": "string",
                        "description": "Error message if operation failed."
                }
        },
        # We assume these are pre-installed in the Docker image now
        requirement=["pyautogui"], 
        test_payload={
                "x": 640,
                "y": 360,
                "duration": 0.25,
        }
)
def mouse_move(input_data: dict) -> dict:
    import sys
    import os

    # 1. Basic Input Validation
    x = input_data.get('x')
    y = input_data.get('y')
    duration = float(input_data.get('duration', 0))

    if x is None or y is None:
        return {'status': 'error', 'position': {}, 'message': 'Both x and y coordinates are required.'}

    # 2. Environment Check (Crucial for Linux Docker)
    # PyAutoGUI needs a DISPLAY environment variable to know where to send events.
    if sys.platform == 'linux' and 'DISPLAY' not in os.environ:
         return {
             'status': 'error', 
             'position': {}, 
             'message': 'Linux environment detected but DISPLAY environment variable is not set. GUI actions require a display (e.g., Xvfb).'
         }

    try:
        # 3. Import PyAutoGUI correctly
        # We assume it's pre-installed via Dockerfile. Removing the runtime pip install
        # makes the action faster and more reliable.
        import pyautogui
        
        # Fail fast if safety feature gets in the way (optional, but good practice for bots)
        pyautogui.FAILSAFE = False 

        # 4. Attempt the move
        pyautogui.moveTo(int(x), int(y), duration=duration)
        
        # 5. Return success
        return {
            'status': 'success', 
            # Note: pyautogui.position() gets actual current pos, better than just returning input x,y
            'position': {'x': pyautogui.position()[0], 'y': pyautogui.position()[1]}, 
            'message': 'Cursor moved successfully.'
        }

    except AttributeError as e:
        # This catches the specific error: "module 'pyautogui' has no attribute 'moveTo'"
        if "'moveTo'" in str(e):
             msg = ("PyAutoGUI failed to initialize properly. This usually means system-level "
                    "X11 dependencies are missing in the Linux Docker container (e.g., libX11, libXtst). "
                    "Please update your Dockerfile to install these packages.")
        else:
             msg = f"PyAutoGUI attribute error: {e}"
        return {'status': 'error', 'position': {}, 'message': msg}
        
    except ImportError:
         return {
             'status': 'error', 
             'position': {}, 
             'message': "The 'pyautogui' Python package is not installed in the container. Please add 'pip install pyautogui' to your Dockerfile."
         }
    except Exception as e:
        # Catch-all for other issues (like coordinates out of screen bounds)
        return {'status': 'error', 'position': {}, 'message': f"An unexpected error occurred: {str(e)}"}