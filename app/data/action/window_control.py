from agent_core import action

@action(
    name="window_control",
    description="Controls an application window. Supports focus, close, maximize, and minimize operations. If a title is provided, the matching window is targeted; otherwise the currently active window is used.",
    mode="GUI",
    action_sets=["gui_interaction"],
    parallelizable=False,
    input_schema={
        "operation": {
            "type": "string",
            "example": "focus",
            "description": "Operation to perform: 'focus', 'close', 'maximize', or 'minimize'."
        },
        "title": {
            "type": "string",
            "example": "Notepad",
            "description": "Substring (case-insensitive) of the window title to match. If omitted, the active window is used (except for 'focus' which requires a title)."
        },
        "exact": {
            "type": "boolean",
            "example": False,
            "description": "If true, match the title exactly; otherwise use substring matching (default: false)."
        },
        "index": {
            "type": "integer",
            "example": 0,
            "description": "If multiple windows match, select by zero-based index (default: 0)."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the operation succeeded, 'error' otherwise."
        },
        "matched_title": {
            "type": "string",
            "example": "Untitled - Notepad",
            "description": "The exact title of the window that was operated on (present on success)."
        },
        "message": {
            "type": "string",
            "example": "No matching window found.",
            "description": "Optional error message."
        }
    },
    requirement=["pygetwindow"],
    test_payload={
        "operation": "focus",
        "title": "Notepad",
        "exact": False,
        "index": 0,
        "simulated_mode": False
    }
)
def window_control(input_data: dict) -> dict:
    import sys, subprocess, importlib

    pkg = 'pygetwindow'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])

    import pygetwindow as gw

    operation = str(input_data.get('operation', '')).strip().lower()
    title = str(input_data.get('title', '')).strip()
    exact = bool(input_data.get('exact', False))
    index = int(input_data.get('index', 0))

    valid_operations = ('focus', 'close', 'maximize', 'minimize')
    if operation not in valid_operations:
        return {'status': 'error', 'matched_title': '', 'message': f"Invalid operation '{operation}'. Must be one of: {', '.join(valid_operations)}."}

    # Focus requires a title to be specified
    if operation == 'focus' and not title:
        return {'status': 'error', 'matched_title': '', 'message': 'title is required for focus operation.'}

    try:
        if title:
            # Match by title
            if exact:
                windows = [w for w in gw.getAllWindows() if w.title == title]
            else:
                windows = gw.getWindowsWithTitle(title)

            if not windows:
                return {'status': 'error', 'matched_title': '', 'message': 'No matching window found.'}

            if index < 0 or index >= len(windows):
                return {'status': 'error', 'matched_title': '', 'message': f'index {index} out of range (found {len(windows)} windows).'}

            win = windows[index]
        else:
            # Use active window
            win = gw.getActiveWindow()
            if win is None:
                return {'status': 'error', 'matched_title': '', 'message': f'No active window to {operation}.'}

        # Perform the operation
        if operation == 'focus':
            win.activate()
        elif operation == 'close':
            win.close()
        elif operation == 'maximize':
            win.maximize()
        elif operation == 'minimize':
            win.minimize()

        return {'status': 'success', 'matched_title': win.title, 'message': ''}

    except Exception as e:
        return {'status': 'error', 'matched_title': '', 'message': str(e)}
