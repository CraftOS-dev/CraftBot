from agent_core import action


@action(
    name="list_drive_files",
    description="List files in a Google Drive folder.",
    action_sets=["google_workspace"],
    input_schema={
        "folder_id": {"type": "string", "description": "Google Drive folder ID.", "example": "root"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_drive_files(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.list_drive_files(folder_id=input_data["folder_id"])
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to list files.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="create_drive_folder",
    description="Create a new folder in Google Drive.",
    action_sets=["google_workspace"],
    input_schema={
        "name": {"type": "string", "description": "Folder name.", "example": "Project Files"},
        "parent_folder_id": {"type": "string", "description": "Optional parent folder ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def create_drive_folder(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.create_drive_folder(
            name=input_data["name"],
            parent_folder_id=input_data.get("parent_folder_id"),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to create folder.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="move_drive_file",
    description="Move a file to a different Google Drive folder.",
    action_sets=["google_workspace"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID to move.", "example": "abc123"},
        "destination_folder_id": {"type": "string", "description": "Destination folder ID.", "example": "def456"},
        "source_folder_id": {"type": "string", "description": "Current parent folder ID.", "example": "root"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def move_drive_file(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.move_drive_file(
            file_id=input_data["file_id"],
            add_parents=input_data["destination_folder_id"],
            remove_parents=input_data.get("source_folder_id", ""),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to move file.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="find_drive_folder_by_name",
    description="Find folder by name.",
    action_sets=["google_workspace"],
    input_schema={
        "name": {"type": "string", "description": "Name.", "example": "Folder"},
        "parent_folder_id": {"type": "string", "description": "Parent.", "example": "root"},
        "from_email": {"type": "string", "description": "Email.", "example": "me@example.com"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def find_drive_folder_by_name(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        result = client.find_drive_folder_by_name(
            name=input_data["name"],
            parent_folder_id=input_data.get("parent_folder_id"),
        )
        if result.get("ok"):
            return {"status": "success", "result": result["result"]}
        return {"status": "error", "message": result.get("error", "Failed to find folder.")}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="resolve_drive_folder_path",
    description="Resolve folder path.",
    action_sets=["google_workspace"],
    input_schema={
        "path": {"type": "string", "description": "Path.", "example": "Root/Folder"},
        "from_email": {"type": "string", "description": "Email.", "example": "me@example.com"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def resolve_drive_folder_path(input_data: dict) -> dict:
    try:
        from app.external_comms.platforms.google_workspace import GoogleWorkspaceClient
        client = GoogleWorkspaceClient()
        if not client.has_credentials():
            return {"status": "error", "message": "No Google credential. Use /google login first."}
        path = input_data["path"]

        parts = [p for p in path.split("/") if p]
        if parts and parts[0].lower() == "root":
            parts = parts[1:]

        current_folder_id = "root"

        for part in parts:
            result = client.find_drive_folder_by_name(
                name=part,
                parent_folder_id=current_folder_id,
            )

            if "error" in result:
                return {"status": "error", "reason": result.get("error", "API error")}

            folder = result.get("result")
            if not folder:
                return {
                    "status": "not_found",
                    "reason": f"Folder '{part}' not found",
                    "folder_id": None,
                }

            current_folder_id = folder["id"]

        return {"status": "success", "folder_id": current_folder_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}
