from agent_core import action


# ------------------------------------------------------------------
# Files — list / search / get / folder / upload / download / export / copy / move / delete
# ------------------------------------------------------------------


@action(
    name="list_drive_files",
    description="List files in a specific Google Drive folder.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "folder_id": {
            "type": "string",
            "description": "Google Drive folder ID. Use 'root' for the user's My Drive.",
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
    name="search_drive_files",
    description="Free-form search across all of Drive using Drive's q-query syntax (e.g. \"name contains 'report' and mimeType = 'application/pdf'\").",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Drive q-query.",
            "example": "name contains 'budget' and trashed = false",
        },
        "max_results": {
            "type": "integer",
            "description": "Max results.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_drive_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "search_drive",
        unwrap_envelope=True,
        fail_message="Failed to search files.",
        query=input_data["query"],
        max_results=input_data.get("max_results", 50),
    )


@action(
    name="get_drive_file",
    description="Get metadata for a single Drive file or folder.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "fields": {
            "type": "string",
            "description": "Comma-separated field list (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "get_drive_file",
        unwrap_envelope=True,
        fail_message="Failed to get file.",
        file_id=input_data["file_id"],
        fields=input_data.get("fields") or None,
    )


@action(
    name="create_drive_folder",
    description="Create a new folder in Google Drive.",
    action_sets=["google_drive_files", "google_drive"],
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
    parallelizable=False,
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
    name="upload_drive_file",
    description="Upload a local file to Google Drive. Reads from file_path on the agent host. MIME type is auto-detected if omitted.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "file_path": {
            "type": "string",
            "description": "Absolute path to the local file.",
            "example": "C:/Users/me/report.pdf",
        },
        "name": {
            "type": "string",
            "description": "Drive filename (defaults to local filename).",
            "example": "",
        },
        "mime_type": {
            "type": "string",
            "description": "MIME type (defaults to autodetect).",
            "example": "",
        },
        "parent_folder_id": {
            "type": "string",
            "description": "Target folder ID (defaults to root).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def upload_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "upload_drive_file",
        unwrap_envelope=True,
        fail_message="Failed to upload file.",
        file_path=input_data["file_path"],
        name=input_data.get("name") or None,
        mime_type=input_data.get("mime_type") or None,
        parent_folder_id=input_data.get("parent_folder_id") or None,
    )


@action(
    name="update_drive_file_content",
    description="Replace an existing Drive file's binary content with a local file. Does NOT change metadata.",
    action_sets=["google_drive_files"],
    input_schema={
        "file_id": {
            "type": "string",
            "description": "Drive file ID to overwrite.",
            "example": "",
        },
        "file_path": {
            "type": "string",
            "description": "Absolute path to the new local content.",
            "example": "C:/Users/me/report_v2.pdf",
        },
        "mime_type": {
            "type": "string",
            "description": "MIME type (defaults to autodetect).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_drive_file_content(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "update_drive_file_content",
        unwrap_envelope=True,
        fail_message="Failed to update file content.",
        file_id=input_data["file_id"],
        file_path=input_data["file_path"],
        mime_type=input_data.get("mime_type") or None,
    )


@action(
    name="download_drive_file",
    description="Download a regular (non-Google-native) Drive file to a local path. For Google Docs/Sheets/Slides use export_drive_file instead.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "save_to": {
            "type": "string",
            "description": "Local path to save to. Parent directories will be created.",
            "example": "C:/Users/me/downloads/report.pdf",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def download_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "download_drive_file",
        unwrap_envelope=True,
        fail_message="Failed to download file.",
        file_id=input_data["file_id"],
        save_to=input_data["save_to"],
    )


@action(
    name="export_drive_file",
    description="Export a Google-native file (Doc/Sheet/Slide/Drawing) to a local path in another format. Common mime_type values: application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document (.docx), application/vnd.openxmlformats-officedocument.spreadsheetml.sheet (.xlsx), text/plain, text/csv. Limit: 10 MB.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "file_id": {
            "type": "string",
            "description": "Google-native file ID.",
            "example": "",
        },
        "save_to": {
            "type": "string",
            "description": "Local path to save to.",
            "example": "C:/Users/me/report.pdf",
        },
        "mime_type": {
            "type": "string",
            "description": "Target export MIME type.",
            "example": "application/pdf",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def export_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "export_drive_file",
        unwrap_envelope=True,
        fail_message="Failed to export file.",
        file_id=input_data["file_id"],
        save_to=input_data["save_to"],
        mime_type=input_data["mime_type"],
    )


@action(
    name="copy_drive_file",
    description="Duplicate a Drive file. Optionally rename and/or place in a different folder.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID to copy.", "example": ""},
        "name": {
            "type": "string",
            "description": "Name for the copy (optional).",
            "example": "",
        },
        "parent_folder_id": {
            "type": "string",
            "description": "Target folder ID (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def copy_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "copy_drive_file",
        unwrap_envelope=True,
        fail_message="Failed to copy file.",
        file_id=input_data["file_id"],
        name=input_data.get("name") or None,
        parent_folder_id=input_data.get("parent_folder_id") or None,
    )


@action(
    name="move_drive_file",
    description="Move a file to a different Google Drive folder.",
    action_sets=["google_drive_files", "google_drive"],
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
    parallelizable=False,
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
    name="update_drive_file_metadata",
    description="Rename / re-describe / star / trash a Drive file. Use trashed=true to send to trash without permanent delete.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "name": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "description": {
            "type": "string",
            "description": "New description (optional).",
            "example": "",
        },
        "starred": {
            "type": "boolean",
            "description": "Star/unstar (optional).",
            "example": False,
        },
        "trashed": {
            "type": "boolean",
            "description": "Send to trash without deleting (optional).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_drive_file_metadata(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "update_drive_file_metadata",
        unwrap_envelope=True,
        fail_message="Failed to update file.",
        file_id=input_data["file_id"],
        name=input_data.get("name") or None,
        description=input_data["description"] if "description" in input_data else None,
        starred=input_data["starred"] if "starred" in input_data else None,
        trashed=input_data["trashed"] if "trashed" in input_data else None,
    )


@action(
    name="delete_drive_file",
    description="Permanently delete a Drive file. Irreversible. To send to trash instead, use update_drive_file_metadata with trashed=true.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "delete_drive_file",
        unwrap_envelope=True,
        fail_message="Failed to delete file.",
        file_id=input_data["file_id"],
    )


@action(
    name="empty_drive_trash",
    description="Permanently delete EVERYTHING in the user's Drive trash. Irreversible.",
    action_sets=["google_drive_files"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def empty_drive_trash(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "empty_drive_trash",
        unwrap_envelope=True,
        fail_message="Failed to empty trash.",
    )


@action(
    name="get_drive_about",
    description="Get Drive account info: user, storage quota, max upload size. Set include_metadata to also get the supported export/import format maps.",
    action_sets=["google_drive_files", "google_drive"],
    input_schema={
        "include_metadata": {
            "type": "boolean",
            "description": "Include exportFormats/importFormats maps (default false).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_drive_about(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "get_drive_about",
        unwrap_envelope=True,
        fail_message="Failed to get Drive info.",
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="find_drive_folder_by_name",
    description="Find folder by name.",
    action_sets=["google_drive_files", "google_drive"],
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
    action_sets=["google_drive_files"],
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


# ------------------------------------------------------------------
# Permissions (sharing)
# ------------------------------------------------------------------


@action(
    name="list_drive_permissions",
    description="List who has access to a Drive file or folder, with their role.",
    action_sets=["google_drive_permissions", "google_drive"],
    input_schema={
        "file_id": {
            "type": "string",
            "description": "File or folder ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_drive_permissions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "list_drive_permissions",
        unwrap_envelope=True,
        fail_message="Failed to list permissions.",
        file_id=input_data["file_id"],
    )


@action(
    name="get_drive_permission",
    description="Get one specific permission by ID.",
    action_sets=["google_drive_permissions"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "permission_id": {
            "type": "string",
            "description": "Permission ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_drive_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "get_drive_permission",
        unwrap_envelope=True,
        fail_message="Failed to get permission.",
        file_id=input_data["file_id"],
        permission_id=input_data["permission_id"],
    )


@action(
    name="add_drive_permission",
    description="Share a Drive file/folder. perm_type: user|group|domain|anyone. role: reader|commenter|writer|owner.",
    action_sets=["google_drive_permissions", "google_drive"],
    input_schema={
        "file_id": {
            "type": "string",
            "description": "File or folder ID.",
            "example": "",
        },
        "role": {
            "type": "string",
            "description": "reader, commenter, writer, or owner.",
            "example": "reader",
        },
        "perm_type": {
            "type": "string",
            "description": "user, group, domain, or anyone.",
            "example": "user",
        },
        "email_address": {
            "type": "string",
            "description": "Email (for user/group types).",
            "example": "alice@example.com",
        },
        "domain": {
            "type": "string",
            "description": "Domain (for domain type).",
            "example": "",
        },
        "send_notification": {
            "type": "boolean",
            "description": "Email the grantee.",
            "example": True,
        },
        "email_message": {
            "type": "string",
            "description": "Custom notification message (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def add_drive_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "create_drive_permission",
        unwrap_envelope=True,
        fail_message="Failed to add permission.",
        file_id=input_data["file_id"],
        role=input_data["role"],
        perm_type=input_data.get("perm_type", "user"),
        email_address=input_data.get("email_address") or None,
        domain=input_data.get("domain") or None,
        send_notification=bool(input_data.get("send_notification", True)),
        email_message=input_data.get("email_message") or None,
    )


@action(
    name="update_drive_permission",
    description="Change a permission's role.",
    action_sets=["google_drive_permissions"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "permission_id": {
            "type": "string",
            "description": "Permission ID.",
            "example": "",
        },
        "role": {"type": "string", "description": "New role.", "example": "writer"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_drive_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "update_drive_permission",
        unwrap_envelope=True,
        fail_message="Failed to update permission.",
        file_id=input_data["file_id"],
        permission_id=input_data["permission_id"],
        role=input_data["role"],
    )


@action(
    name="remove_drive_permission",
    description="Revoke access by deleting a permission.",
    action_sets=["google_drive_permissions"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "permission_id": {
            "type": "string",
            "description": "Permission ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def remove_drive_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "delete_drive_permission",
        unwrap_envelope=True,
        fail_message="Failed to remove permission.",
        file_id=input_data["file_id"],
        permission_id=input_data["permission_id"],
    )


# ------------------------------------------------------------------
# Comments + replies
# ------------------------------------------------------------------


@action(
    name="list_drive_comments",
    description="List comments on a Drive file.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "include_deleted": {
            "type": "boolean",
            "description": "Include soft-deleted comments.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_drive_comments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "list_drive_comments",
        unwrap_envelope=True,
        fail_message="Failed to list comments.",
        file_id=input_data["file_id"],
        include_deleted=bool(input_data.get("include_deleted", False)),
    )


@action(
    name="get_drive_comment",
    description="Get a single comment with its replies.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_drive_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "get_drive_comment",
        unwrap_envelope=True,
        fail_message="Failed to get comment.",
        file_id=input_data["file_id"],
        comment_id=input_data["comment_id"],
    )


@action(
    name="create_drive_comment",
    description="Post a top-level comment on a Drive file. anchor is an optional region anchor (Google's structured anchor format).",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "content": {
            "type": "string",
            "description": "Comment text.",
            "example": "Please review.",
        },
        "anchor": {
            "type": "string",
            "description": "Optional anchor (structured format).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_drive_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "create_drive_comment",
        unwrap_envelope=True,
        fail_message="Failed to create comment.",
        file_id=input_data["file_id"],
        content=input_data["content"],
        anchor=input_data.get("anchor") or None,
    )


@action(
    name="update_drive_comment",
    description="Edit a comment's content or mark it resolved.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "content": {
            "type": "string",
            "description": "New content (optional).",
            "example": "",
        },
        "resolved": {
            "type": "boolean",
            "description": "Mark as resolved (optional).",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_drive_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "update_drive_comment",
        unwrap_envelope=True,
        fail_message="Failed to update comment.",
        file_id=input_data["file_id"],
        comment_id=input_data["comment_id"],
        content=input_data["content"] if "content" in input_data else None,
        resolved=input_data["resolved"] if "resolved" in input_data else None,
    )


@action(
    name="delete_drive_comment",
    description="Delete a comment.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_drive_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "delete_drive_comment",
        unwrap_envelope=True,
        fail_message="Failed to delete comment.",
        file_id=input_data["file_id"],
        comment_id=input_data["comment_id"],
    )


@action(
    name="list_drive_comment_replies",
    description="List replies on a comment.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_drive_comment_replies(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "list_drive_comment_replies",
        unwrap_envelope=True,
        fail_message="Failed to list replies.",
        file_id=input_data["file_id"],
        comment_id=input_data["comment_id"],
    )


@action(
    name="create_drive_comment_reply",
    description="Reply to a comment.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "content": {"type": "string", "description": "Reply text.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_drive_comment_reply(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "create_drive_comment_reply",
        unwrap_envelope=True,
        fail_message="Failed to create reply.",
        file_id=input_data["file_id"],
        comment_id=input_data["comment_id"],
        content=input_data["content"],
    )


@action(
    name="update_drive_comment_reply",
    description="Edit a reply.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "reply_id": {"type": "string", "description": "Reply ID.", "example": ""},
        "content": {"type": "string", "description": "New content.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_drive_comment_reply(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "update_drive_comment_reply",
        unwrap_envelope=True,
        fail_message="Failed to update reply.",
        file_id=input_data["file_id"],
        comment_id=input_data["comment_id"],
        reply_id=input_data["reply_id"],
        content=input_data["content"],
    )


@action(
    name="delete_drive_comment_reply",
    description="Delete a reply.",
    action_sets=["google_drive_comments"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "reply_id": {"type": "string", "description": "Reply ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_drive_comment_reply(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "delete_drive_comment_reply",
        unwrap_envelope=True,
        fail_message="Failed to delete reply.",
        file_id=input_data["file_id"],
        comment_id=input_data["comment_id"],
        reply_id=input_data["reply_id"],
    )


# ------------------------------------------------------------------
# Revisions (version history)
# ------------------------------------------------------------------


@action(
    name="list_drive_revisions",
    description="List revisions (version history) of a Drive file.",
    action_sets=["google_drive_revisions"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_drive_revisions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "list_drive_revisions",
        unwrap_envelope=True,
        fail_message="Failed to list revisions.",
        file_id=input_data["file_id"],
    )


@action(
    name="get_drive_revision",
    description="Get details of a specific revision.",
    action_sets=["google_drive_revisions"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "revision_id": {"type": "string", "description": "Revision ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_drive_revision(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "get_drive_revision",
        unwrap_envelope=True,
        fail_message="Failed to get revision.",
        file_id=input_data["file_id"],
        revision_id=input_data["revision_id"],
    )


@action(
    name="update_drive_revision",
    description="Mark a revision keep-forever (pin) or set publish state for Google-native files.",
    action_sets=["google_drive_revisions"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "revision_id": {"type": "string", "description": "Revision ID.", "example": ""},
        "keep_forever": {
            "type": "boolean",
            "description": "Pin this revision (otherwise Drive auto-prunes after 100 or 30 days, whichever first).",
            "example": True,
        },
        "published": {
            "type": "boolean",
            "description": "Publish state (Google-native files only).",
            "example": False,
        },
        "publish_auto": {
            "type": "boolean",
            "description": "Auto-publish subsequent revisions.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_drive_revision(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "update_drive_revision",
        unwrap_envelope=True,
        fail_message="Failed to update revision.",
        file_id=input_data["file_id"],
        revision_id=input_data["revision_id"],
        keep_forever=input_data["keep_forever"]
        if "keep_forever" in input_data
        else None,
        published=input_data["published"] if "published" in input_data else None,
        publish_auto=input_data["publish_auto"]
        if "publish_auto" in input_data
        else None,
    )


@action(
    name="delete_drive_revision",
    description="Delete a revision.",
    action_sets=["google_drive_revisions"],
    input_schema={
        "file_id": {"type": "string", "description": "File ID.", "example": ""},
        "revision_id": {"type": "string", "description": "Revision ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_drive_revision(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "delete_drive_revision",
        unwrap_envelope=True,
        fail_message="Failed to delete revision.",
        file_id=input_data["file_id"],
        revision_id=input_data["revision_id"],
    )


# ------------------------------------------------------------------
# Shared drives (formerly Team Drives)
# ------------------------------------------------------------------


@action(
    name="list_shared_drives",
    description="List shared drives the user has access to.",
    action_sets=["google_drive_shared_drives"],
    input_schema={
        "page_size": {"type": "integer", "description": "Max results.", "example": 50},
        "q": {
            "type": "string",
            "description": "Drive search query (optional).",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_shared_drives(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "list_shared_drives",
        unwrap_envelope=True,
        fail_message="Failed to list shared drives.",
        page_size=input_data.get("page_size", 50),
        q=input_data.get("q") or None,
    )


@action(
    name="get_shared_drive",
    description="Get metadata for a shared drive.",
    action_sets=["google_drive_shared_drives"],
    input_schema={
        "drive_id": {
            "type": "string",
            "description": "Shared drive ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_shared_drive(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "get_shared_drive",
        unwrap_envelope=True,
        fail_message="Failed to get shared drive.",
        drive_id=input_data["drive_id"],
    )


@action(
    name="create_shared_drive",
    description="Create a new shared drive. The user must have permission to create shared drives in their org.",
    action_sets=["google_drive_shared_drives"],
    input_schema={
        "name": {
            "type": "string",
            "description": "Shared drive name.",
            "example": "Team project",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def create_shared_drive(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "create_shared_drive",
        unwrap_envelope=True,
        fail_message="Failed to create shared drive.",
        name=input_data["name"],
    )


@action(
    name="update_shared_drive",
    description="Rename or hide/unhide a shared drive.",
    action_sets=["google_drive_shared_drives"],
    input_schema={
        "drive_id": {
            "type": "string",
            "description": "Shared drive ID.",
            "example": "",
        },
        "name": {
            "type": "string",
            "description": "New name (optional).",
            "example": "",
        },
        "hidden": {
            "type": "boolean",
            "description": "Hide from UI (optional).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def update_shared_drive(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "update_shared_drive",
        unwrap_envelope=True,
        fail_message="Failed to update shared drive.",
        drive_id=input_data["drive_id"],
        name=input_data.get("name") or None,
        hidden=input_data["hidden"] if "hidden" in input_data else None,
    )


@action(
    name="delete_shared_drive",
    description="Delete a shared drive. The drive must be empty.",
    action_sets=["google_drive_shared_drives"],
    input_schema={
        "drive_id": {
            "type": "string",
            "description": "Shared drive ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def delete_shared_drive(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_drive",
        "delete_shared_drive",
        unwrap_envelope=True,
        fail_message="Failed to delete shared drive.",
        drive_id=input_data["drive_id"],
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Changes / watch endpoints (changes.list, changes.watch, channels.stop, etc.)
#     Push notifications / incremental sync — server-side webhook plumbing,
#     not per-interaction actions.
# - generateIds
#     Pre-allocating IDs before insert. Niche; most agents just let Drive
#     mint IDs on POST.
# - Resumable upload (uploadType=resumable)
#     Used for very large uploads (>5MB) with progress tracking. The simple
#     2-step upload (metadata + uploadType=media PATCH) handles realistic
#     file sizes; resumable can be added later if needed.
# - DriveAccess proposals / members management on shared drives
#     Org-admin-level concerns, not personal-agent work.
# - Multipart/related upload (uploadType=multipart)
#     The 2-step pattern in upload_drive_file gives equivalent semantics
#     without the multipart-body construction.
