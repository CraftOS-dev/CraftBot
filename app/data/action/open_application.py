from agent_core import action

@action(
        name="open_application",
        description="Launches a Windows application (executable) with optional command-line arguments.",
        mode="GUI",
        action_sets=["gui_interaction"],
        parallelizable=False,
        input_schema={
                "exe_path": {
                        "type": "string",
                        "example": "C:\\\\Program Files\\\\VideoLAN\\\\VLC\\\\vlc.exe",
                        "description": "Absolute path to the .exe file to launch (required)."
                },
                "args": {
                        "type": "array",
                        "items": {
                                "type": "string"
                        },
                        "example": [
                                "--fullscreen"
                        ],
                        "description": "Optional list of command-line arguments."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "success",
                        "description": "'success' if the application started, 'error' otherwise."
                },
                "pid": {
                        "type": "integer",
                        "example": 12345,
                        "description": "Process ID of the launched application (present on success)."
                },
                "message": {
                        "type": "string",
                        "example": "File not found.",
                        "description": "Optional error message."
                }
        },
        test_payload={
                "exe_path": "C:\\\\Program Files\\\\VideoLAN\\\\VLC\\\\vlc.exe",
                "args": [
                        "--fullscreen"
                ],
                "simulated_mode": False
        }
)
def open_application(input_data: dict) -> dict:
    import json, os, subprocess, sys

    exe_path = str(input_data.get('exe_path', '')).strip()
    args = input_data.get('args') or []

    if not exe_path:
        return {'status': 'error', 'pid': -1, 'message': 'exe_path is required.'}
        sys.exit()

    if not os.path.isfile(exe_path):
        return {'status': 'error', 'pid': -1, 'message': 'File not found.'}
        sys.exit()

    if not isinstance(args, list):
        return {'status': 'error', 'pid': -1, 'message': 'args must be an array if provided.'}
        sys.exit()

    try:
        proc = subprocess.Popen([exe_path, *args], shell=False, cwd=os.path.dirname(exe_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'status': 'success', 'pid': proc.pid, 'message': ''}
    except Exception as e:
        return {'status': 'error', 'pid': -1, 'message': str(e)}