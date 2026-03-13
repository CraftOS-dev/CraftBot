from agent_core import action

@action(
    name="clipboard_write",
    description="Write text content to the system clipboard.",
    mode="GUI",
    action_sets=["core"],
    parallelizable=False,
    input_schema={
        "content": {
            "type": "string",
            "example": "Text to copy to clipboard",
            "description": "Text content to write to the clipboard."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'."
        },
        "message": {
            "type": "string",
            "description": "Status message or error message."
        }
    },
    requirement=["pyperclip"],
    test_payload={
        "content": "Test clipboard content",
        "simulated_mode": True
    }
)
def clipboard_write(input_data: dict) -> dict:
    import sys, subprocess, importlib

    simulated_mode = input_data.get('simulated_mode', False)

    if simulated_mode:
        return {
            'status': 'success',
            'message': 'Content copied to clipboard.'
        }

    content = input_data.get('content', '')

    pkg = 'pyperclip'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])

    import pyperclip

    try:
        pyperclip.copy(content)
        return {
            'status': 'success',
            'message': 'Content copied to clipboard.'
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
