from agent_core import action

@action(
    name="clipboard_read",
    description="Read the current content from the system clipboard.",
    mode="GUI",
    action_sets=["core"],
    input_schema={},
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'."
        },
        "content": {
            "type": "string",
            "description": "Text content from the clipboard."
        },
        "content_type": {
            "type": "string",
            "example": "text",
            "description": "Type of content: 'text' or 'empty'."
        },
        "message": {
            "type": "string",
            "description": "Error message if status is 'error'."
        }
    },
    requirement=["pyperclip"],
    test_payload={
        "simulated_mode": True
    }
)
def clipboard_read(input_data: dict) -> dict:
    import sys, subprocess, importlib

    simulated_mode = input_data.get('simulated_mode', False)

    if simulated_mode:
        return {
            'status': 'success',
            'content': 'Simulated clipboard content',
            'content_type': 'text'
        }

    pkg = 'pyperclip'
    try:
        importlib.import_module(pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '--quiet'])

    import pyperclip

    try:
        content = pyperclip.paste()
        if content:
            return {
                'status': 'success',
                'content': content,
                'content_type': 'text'
            }
        else:
            return {
                'status': 'success',
                'content': '',
                'content_type': 'empty'
            }
    except Exception as e:
        return {'status': 'error', 'content': '', 'content_type': '', 'message': str(e)}
