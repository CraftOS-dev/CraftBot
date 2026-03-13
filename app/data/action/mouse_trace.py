from agent_core import action

@action(
        name="mouse_trace",
        description="Moves the mouse cursor along a sequence of points, optionally with easing, per-segment duration, and pauses between segments.",
        mode="GUI",
        action_sets=["gui_interaction"],
        parallelizable=False,
        input_schema={
                "points": {
                        "type": "array",
                        "description": "Ordered list of waypoints to move through.",
                        "items": {
                                "type": "object",
                                "properties": {
                                        "x": {
                                                "type": "integer",
                                                "description": "X-coordinate in pixels (absolute unless 'relative' is true)."
                                        },
                                        "y": {
                                                "type": "integer",
                                                "description": "Y-coordinate in pixels (absolute unless 'relative' is true)."
                                        },
                                        "duration": {
                                                "type": "number",
                                                "description": "Optional duration in seconds for this segment."
                                        }
                                },
                                "required": [
                                        "x",
                                        "y"
                                ]
                        },
                        "example": [
                                {
                                        "x": 400,
                                        "y": 300,
                                        "duration": 0.2
                                },
                                {
                                        "x": 800,
                                        "y": 300,
                                        "duration": 0.15
                                },
                                {
                                        "x": 800,
                                        "y": 600,
                                        "duration": 0.25
                                }
                        ]
                },
                "relative": {
                        "type": "boolean",
                        "example": False,
                        "description": "If true, each point is treated as an offset from the current cursor position (and then from each subsequent point)."
                },
                "default_duration": {
                        "type": "number",
                        "example": 0.2,
                        "description": "Fallback duration (seconds) for any point that omits 'duration'. Defaults to 0."
                },
                "easing": {
                        "type": "string",
                        "enum": [
                                "linear",
                                "easeInQuad",
                                "easeOutQuad",
                                "easeInOutQuad",
                                "easeInCubic",
                                "easeOutCubic",
                                "easeInOutCubic"
                        ],
                        "example": "easeInOutQuad",
                        "description": "Easing function applied to each segment."
                },
                "pause": {
                        "type": "number",
                        "example": 0.05,
                        "description": "Pause in seconds between segments. Defaults to 0."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success",
                        "description": "'success' if the path was fully traced, 'error' otherwise."
                },
                "segments_executed": {
                        "type": "integer",
                        "example": 3,
                        "description": "How many segments were completed."
                },
                "message": {
                        "type": "string",
                        "example": "Coordinate out of bounds.",
                        "description": "Optional error message if the operation failed or was partial."
                }
        },
        requirement=["pyautogui"],
        test_payload={
                "points": [
                {
                        "x": 400,
                        "y": 300,
                        "duration": 0.2
                        },
                {
                        "x": 800,
                        "y": 300,
                        "duration": 0.15
                        },
                {
                        "x": 800,
                        "y": 600,
                        "duration": 0.25
                        }
                ],
                "relative": False,
                "default_duration": 0.2,
                "easing": "easeInOutQuad",
                "pause": 0.05,
                "simulated_mode": False
        }
)
def trace_mouse(input_data: dict) -> dict:
    import json, sys, subprocess, importlib, time
    pkg = 'pyautogui'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])
    import pyautogui
    points = input_data.get('points')
    relative = bool(input_data.get('relative', False))
    easing = str(input_data.get('easing', 'linear')).strip()
    pause = float(input_data.get('pause', 0))
    default_duration = float(input_data.get('default_duration', 0))
    if not isinstance(points, list) or not points:
        return {'status': 'error', 'segments_executed': 0, 'message': 'points must be a non-empty array.'}
        exit()
    def _linear(n):
        return n
    ease_map = {
        'linear': getattr(pyautogui, 'linear', _linear),
        'easeInQuad': getattr(pyautogui, 'easeInQuad', _linear),
        'easeOutQuad': getattr(pyautogui, 'easeOutQuad', _linear),
        'easeInOutQuad': getattr(pyautogui, 'easeInOutQuad', _linear),
        'easeInCubic': getattr(pyautogui, 'easeInCubic', _linear),
        'easeOutCubic': getattr(pyautogui, 'easeOutCubic', _linear),
        'easeInOutCubic': getattr(pyautogui, 'easeInOutCubic', _linear),
    }
    tween = ease_map.get(easing, ease_map['linear'])
    width, height = pyautogui.size()
    cx, cy = pyautogui.position()
    segments_executed = 0
    try:
        curx, cury = (cx, cy)
        for p in points:
            if not isinstance(p, dict) or 'x' not in p or 'y' not in p:
                raise ValueError('Each point must be an object with x and y.')
            px = int(p.get('x'))
            py = int(p.get('y'))
            dur = float(p.get('duration', default_duration))
            tx = px + curx if relative else px
            ty = py + cury if relative else py
            if tx < 0 or ty < 0 or tx >= width or ty >= height:
                raise ValueError('Coordinate out of bounds.')
            pyautogui.moveTo(tx, ty, duration=dur, tween=tween)
            curx, cury = (tx, ty)
            segments_executed += 1
            if pause > 0:
                time.sleep(pause)
        return {'status': 'success', 'segments_executed': segments_executed, 'message': ''}
    except Exception as e:
        return {'status': 'error', 'segments_executed': segments_executed, 'message': str(e)}