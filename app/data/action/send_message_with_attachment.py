from agent_core import action

@action(
        name="send_message_with_attachment",
        description="Send a message to the user with one or more file attachments. Use this when you need to share files (documents, images, reports, etc.) with the user. All files must exist at the specified paths.",
        default=True,
        action_sets=["core"],
        parallelizable=False,
        input_schema={
                "message": {
                        "type": "string",
                        "example": "Here are the files you requested.",
                        "description": "The chat message to accompany the attachments. Explain what the files are and any relevant context."
                },
                "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["C:/Users/user/Desktop/agent/workspace/download/report.pdf", "C:/Users/user/Desktop/agent/workspace/download/summary.docx"],
                        "description": "List of absolute paths to the files to attach. Use full absolute paths (e.g., C:/path/to/file.pdf or /home/user/file.pdf). All files must exist at their specified locations."
                },
                "wait_for_user_reply": {
                        "type": "boolean",
                        "example": False,
                        "description": "True if this action requires user's response to proceed. If set to true, phrase the message as a question so the user has something to reply to."
                }
        },
        output_schema={
                "status": {
                        "type": "string",
                        "example": "ok",
                        "description": "'ok' if all files sent successfully, 'error' if any files failed to send."
                },
                "fire_at_delay": {
                        "type": "number",
                        "example": 10800,
                        "description": "Delay in seconds before the next follow-up action should be scheduled. 10800 seconds (3 hours) if wait_for_user_reply is true, otherwise 0."
                },
                "files_sent": {
                        "type": "integer",
                        "example": 2,
                        "description": "Number of files successfully sent."
                },
                "errors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of error messages for files that failed to send. Only present if status is 'error'."
                }
        },
        test_payload={
                "message": "Here are some test files.",
                "file_paths": ["C:/test/example1.txt", "C:/test/example2.txt"],
                "wait_for_user_reply": False,
                "simulated_mode": True
        }
)
def send_message_with_attachment(input_data: dict) -> dict:
    import asyncio

    message = input_data['message']
    file_paths = input_data.get('file_paths', [])
    wait_for_user_reply = bool(input_data.get('wait_for_user_reply', False))
    simulated_mode = input_data.get('simulated_mode', False)

    # Ensure file_paths is a list
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    # In simulated mode, skip the actual interface call for testing
    if simulated_mode:
        return {
            'status': 'success',
            'fire_at_delay': 10800 if wait_for_user_reply else 0,
            'wait_for_user_reply': wait_for_user_reply,
            'files_sent': len(file_paths)
        }

    import app.internal_action_interface as internal_action_interface

    # Use the do_chat_with_attachments method which handles browser/CLI fallback
    result = asyncio.run(internal_action_interface.InternalActionInterface.do_chat_with_attachments(
        message, file_paths
    ))

    fire_at_delay = 10800 if wait_for_user_reply else 0
    files_sent = result.get('files_sent', 0)
    errors = result.get('errors')

    # Determine status based on whether all files were sent successfully
    if result.get('success', False):
        status = 'ok'
    else:
        status = 'error'

    response = {
        'status': status,
        'fire_at_delay': fire_at_delay,
        'wait_for_user_reply': wait_for_user_reply,
        'files_sent': files_sent
    }

    # Include errors if any
    if errors:
        response['errors'] = errors

    return response
