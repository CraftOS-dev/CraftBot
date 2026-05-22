from agent_core import action


@action(
    name="list_drive_files",
    description="List files in a Google Drive folder.",
    action_sets=["google_drive"],
    input_schema={
        "folder_id": {
            "type": "string",
            "description": "Google Drive folder ID.",
            "example": "root",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_drive_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "list_drive_files",
        unwrap_envelope=True,
        fail_message="Failed to list files.",
        folder_id=input_data["folder_id"],
    )


@action(
    name="create_drive_folder",
    description="Create a new folder in Google Drive.",
    action_sets=["google_drive"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Folder name.",
            "example": "Project Files",
        },
        "parent_folder_id": {
            "type": "string",
            "description": "Optional parent folder ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def create_drive_folder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "create_drive_folder",
        unwrap_envelope=True,
        fail_message="Failed to create folder.",
        name=input_data["name"],
        parent_folder_id=input_data.get("parent_folder_id"),
    )


@action(
    name="move_drive_file",
    description="Move a file to a different Google Drive folder.",
    action_sets=["google_drive"],
    input_schema={
        "file_id": {
            "type": "string",
            "description": "File ID to move.",
            "example": "abc123",
        },
        "destination_folder_id": {
            "type": "string",
            "description": "Destination folder ID.",
            "example": "def456",
        },
        "source_folder_id": {
            "type": "string",
            "description": "Current parent folder ID.",
            "example": "root",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def move_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "move_drive_file",
        unwrap_envelope=True,
        fail_message="Failed to move file.",
        file_id=input_data["file_id"],
        add_parents=input_data["destination_folder_id"],
        remove_parents=input_data.get("source_folder_id", ""),
    )


@action(
    name="find_drive_folder_by_name",
    description="Find folder by name.",
    action_sets=["google_drive"],
    input_schema={
        "name": {"type": "string", "description": "Name.", "example": "Folder"},
        "parent_folder_id": {
            "type": "string",
            "description": "Parent.",
            "example": "root",
        },
        "from_email": {
            "type": "string",
            "description": "Email.",
            "example": "me@example.com",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def find_drive_folder_by_name(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "find_drive_folder_by_name",
        unwrap_envelope=True,
        fail_message="Failed to find folder.",
        name=input_data["name"],
        parent_folder_id=input_data.get("parent_folder_id"),
    )


@action(
    name="resolve_drive_folder_path",
    description="Resolve folder path.",
    action_sets=["google_drive"],
    input_schema={
        "path": {"type": "string", "description": "Path.", "example": "Root/Folder"},
        "from_email": {
            "type": "string",
            "description": "Email.",
            "example": "me@example.com",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def resolve_drive_folder_path(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    """Walks the path one segment at a time — custom 'not_found' shape."""
    parts = [p for p in input_data["path"].split("/") if p]
    if parts and parts[0].lower() == "root":
        parts = parts[1:]
    current_folder_id = "root"

    for part in parts:
        result = run_client_sync(
            "google_drive",
            "find_drive_folder_by_name",
            unwrap_envelope=True,
            fail_message=f"Failed to look up '{part}'",
            name=part,
            parent_folder_id=current_folder_id,
        )
        if result["status"] == "error":
            return {"status": "error", "reason": result.get("message", "API error")}
        folder = result.get("result")
        if not folder:
            return {
                "status": "not_found",
                "reason": f"Folder '{part}' not found",
                "folder_id": None,
            }
        current_folder_id = folder["id"]

    return {"status": "success", "folder_id": current_folder_id}
