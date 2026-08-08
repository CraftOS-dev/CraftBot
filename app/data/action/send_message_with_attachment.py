from agent_core import action


@action(
    name="send_message_with_attachment",
    irreversible=True,
    description="Send a message to the user with one or more file attachments. Use this when you need to share files (documents, images, reports, etc.) with the user. All files must exist at the specified paths.",
    default=True,
    action_sets=["core"],
    parallelizable=True,
    input_schema={
        "message": {
            "type": "string",
            "example": "Here are the files you requested.",
            "description": "The chat message to accompany the attachments. Explain what the files are and any relevant context.",
        },
        "file_paths": {
            "type": "array",
            "items": {"type": "string"},
            "example": [
                "C:/Users/user/Desktop/agent/workspace/download/report.pdf",
                "C:/Users/user/Desktop/agent/workspace/download/summary.docx",
            ],
            "description": "List of absolute paths to the files to attach. Use full absolute paths (e.g., C:/path/to/file.pdf or /home/user/file.pdf). All files must exist at their specified locations.",
        },
        "continue_work": {
            "type": "boolean",
            "example": False,
            "description": (
                "False (default): this is your final message for now — the run ends and "
                "the session waits for the user. True: this is a progress update and you "
                "will keep working after sending it."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "ok",
            "description": "'ok' if all files sent successfully, 'error' if any files failed to send.",
        },
        "end_turn": {
            "type": "boolean",
            "example": True,
            "description": "True when this message ends the current run.",
        },
        "files_sent": {
            "type": "integer",
            "example": 2,
            "description": "Number of files successfully sent.",
        },
        "errors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of error messages for files that failed to send. Only present if status is 'error'.",
        },
    },
    test_payload={
        "message": "Here are some test files.",
        "file_paths": ["C:/test/example1.txt", "C:/test/example2.txt"],
        "continue_work": False,
        "simulated_mode": True,
    },
)
async def send_message_with_attachment(input_data: dict) -> dict:
    message = input_data["message"]
    file_paths = input_data.get("file_paths", [])
    continue_work = bool(input_data.get("continue_work", False))
    simulated_mode = input_data.get("simulated_mode", False)
    # Extract session_id injected by ActionManager for multi-session isolation
    session_id = input_data.get("_session_id")

    # Ensure file_paths is a list
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    # Validate all file paths exist before attempting to send
    import os

    errors = []
    for fp in file_paths:
        if not os.path.exists(fp):
            errors.append(f"File not found: {fp}")
        elif os.path.isdir(fp):
            errors.append(f"Cannot attach directory: {fp}")

    if errors:
        return {
            "status": "error",
            "end_turn": False,
            "files_sent": 0,
            "errors": errors,
        }

    # In simulated mode, skip the actual interface call for testing
    if simulated_mode:
        return {
            "status": "success",
            "end_turn": not continue_work,
            "files_sent": len(file_paths),
        }

    import app.internal_action_interface as internal_action_interface

    # Use the do_chat_with_attachments method which handles browser/CLI fallback
    result = await internal_action_interface.InternalActionInterface.do_chat_with_attachments(
        message, file_paths, session_id=session_id, continue_work=continue_work
    )

    files_sent = result.get("files_sent", 0)
    errors = result.get("errors")

    # Determine status based on whether all files were sent successfully
    if result.get("success", False):
        status = "ok"
    else:
        status = "error"

    response = {
        "status": status,
        "end_turn": not continue_work,
        "files_sent": files_sent,
    }

    # Include errors if any
    if errors:
        response["errors"] = errors

    return response
