"""Google Drive operations — schemas for google_drive_actions.py.

NOTE: no operation declares an ``account`` input — the host adapter
injects it on every generated action and the core resolves it centrally
(conformance-enforced). The ``from_email`` inputs on
find_drive_folder_by_name / resolve_drive_folder_path were dead
account-hint keys (never forwarded to the client) and are dropped for the
same reason.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ...contracts import Operation
from .._shared import STATUS_OUTPUT, client_op, shape_result


async def _resolve_drive_folder_path(
    client: Any, input_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Walks the path one segment at a time — custom 'not_found' shape."""
    parts = [p for p in input_data["path"].split("/") if p]
    if parts and parts[0].lower() == "root":
        parts = parts[1:]
    current_folder_id = "root"

    for part in parts:
        try:
            raw = await asyncio.to_thread(
                client.find_drive_folder_by_name,
                name=part,
                parent_folder_id=current_folder_id,
            )
        except Exception as e:
            return {"status": "error", "reason": str(e)}
        result = shape_result(
            raw,
            unwrap_envelope=True,
            fail_message=f"Failed to look up '{part}'",
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


def build_operations() -> List[Operation]:
    return [
        # ── Files — list / search / get / folder / upload / download /
        #    export / copy / move / delete ──────────────────────────────────
        client_op(
            "list_drive_files",
            "list_drive_files",
            description="List files in a specific Google Drive folder.",
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to list files.",
            input_schema={
                "folder_id": {
                    "type": "string",
                    "description": (
                        "Google Drive folder ID. Use 'root' for the user's My Drive."
                    ),
                    "example": "root",
                },
            },
            arg_map=lambda d: {"folder_id": d["folder_id"]},
        ),
        client_op(
            "search_drive_files",
            "search_drive",
            description=(
                "Free-form search across all of Drive using Drive's q-query "
                "syntax (e.g. \"name contains 'report' and mimeType = "
                "'application/pdf'\")."
            ),
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to search files.",
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
            arg_map=lambda d: {
                "query": d["query"],
                "max_results": d.get("max_results", 50),
            },
        ),
        client_op(
            "get_drive_file",
            "get_drive_file",
            description="Get metadata for a single Drive file or folder.",
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to get file.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated field list (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "fields": d.get("fields") or None,
            },
        ),
        client_op(
            "create_drive_folder",
            "create_drive_folder",
            description="Create a new folder in Google Drive.",
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to create folder.",
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
            arg_map=lambda d: {
                "name": d["name"],
                "parent_folder_id": d.get("parent_folder_id"),
            },
        ),
        client_op(
            "upload_drive_file",
            "upload_drive_file",
            description=(
                "Upload a local file to Google Drive. Reads from file_path on "
                "the agent host. MIME type is auto-detected if omitted."
            ),
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to upload file.",
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
            arg_map=lambda d: {
                "file_path": d["file_path"],
                "name": d.get("name") or None,
                "mime_type": d.get("mime_type") or None,
                "parent_folder_id": d.get("parent_folder_id") or None,
            },
        ),
        client_op(
            "update_drive_file_content",
            "update_drive_file_content",
            description=(
                "Replace an existing Drive file's binary content with a local "
                "file. Does NOT change metadata."
            ),
            parallelizable=False,
            tags=("google_drive_files",),
            unwrap_envelope=True,
            fail_message="Failed to update file content.",
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
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "file_path": d["file_path"],
                "mime_type": d.get("mime_type") or None,
            },
        ),
        client_op(
            "download_drive_file",
            "download_drive_file",
            description=(
                "Download a regular (non-Google-native) Drive file to a local "
                "path. For Google Docs/Sheets/Slides use export_drive_file "
                "instead."
            ),
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to download file.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "save_to": {
                    "type": "string",
                    "description": (
                        "Local path to save to. Parent directories will be created."
                    ),
                    "example": "C:/Users/me/downloads/report.pdf",
                },
            },
        ),
        client_op(
            "export_drive_file",
            "export_drive_file",
            description=(
                "Export a Google-native file (Doc/Sheet/Slide/Drawing) to a "
                "local path in another format. Common mime_type values: "
                "application/pdf, application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document (.docx), application/vnd."
                "openxmlformats-officedocument.spreadsheetml.sheet (.xlsx), "
                "text/plain, text/csv. Limit: 10 MB."
            ),
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to export file.",
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
        ),
        client_op(
            "copy_drive_file",
            "copy_drive_file",
            description=(
                "Duplicate a Drive file. Optionally rename and/or place in a "
                "different folder."
            ),
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to copy file.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID to copy.",
                    "example": "",
                },
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
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "name": d.get("name") or None,
                "parent_folder_id": d.get("parent_folder_id") or None,
            },
        ),
        client_op(
            "move_drive_file",
            "move_drive_file",
            description="Move a file to a different Google Drive folder.",
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to move file.",
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
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "add_parents": d["destination_folder_id"],
                "remove_parents": d.get("source_folder_id", ""),
            },
        ),
        client_op(
            "update_drive_file_metadata",
            "update_drive_file_metadata",
            description=(
                "Rename / re-describe / star / trash a Drive file. Use "
                "trashed=true to send to trash without permanent delete."
            ),
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to update file.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
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
                    "description": ("Send to trash without deleting (optional)."),
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "name": d.get("name") or None,
                "description": d["description"] if "description" in d else None,
                "starred": d["starred"] if "starred" in d else None,
                "trashed": d["trashed"] if "trashed" in d else None,
            },
        ),
        client_op(
            "delete_drive_file",
            "delete_drive_file",
            description=(
                "Permanently delete a Drive file. Irreversible. To send to "
                "trash instead, use update_drive_file_metadata with "
                "trashed=true."
            ),
            destructive=True,
            parallelizable=False,
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to delete file.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "empty_drive_trash",
            "empty_drive_trash",
            description=(
                "Permanently delete EVERYTHING in the user's Drive trash. Irreversible."
            ),
            destructive=True,
            parallelizable=False,
            tags=("google_drive_files",),
            unwrap_envelope=True,
            fail_message="Failed to empty trash.",
            input_schema={},
        ),
        client_op(
            "get_drive_about",
            "get_drive_about",
            description=(
                "Get Drive account info: user, storage quota, max upload "
                "size. Set include_metadata to also get the supported "
                "export/import format maps."
            ),
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to get Drive info.",
            input_schema={
                "include_metadata": {
                    "type": "boolean",
                    "description": (
                        "Include exportFormats/importFormats maps (default false)."
                    ),
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "include_metadata": bool(d.get("include_metadata", False)),
            },
        ),
        client_op(
            "find_drive_folder_by_name",
            "find_drive_folder_by_name",
            description="Find folder by name.",
            tags=("google_drive_files", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to find folder.",
            input_schema={
                "name": {
                    "type": "string",
                    "description": "Name.",
                    "example": "Folder",
                },
                "parent_folder_id": {
                    "type": "string",
                    "description": "Parent.",
                    "example": "root",
                },
            },
            arg_map=lambda d: {
                "name": d["name"],
                "parent_folder_id": d.get("parent_folder_id"),
            },
        ),
        Operation(
            name="resolve_drive_folder_path",
            description="Resolve folder path.",
            input_schema={
                "path": {
                    "type": "string",
                    "description": "Path.",
                    "example": "Root/Folder",
                },
            },
            output_schema=dict(STATUS_OUTPUT),
            fn=_resolve_drive_folder_path,
            tags=("google_drive_files",),
        ),
        # ── Permissions (sharing) ────────────────────────────────────────
        client_op(
            "list_drive_permissions",
            "list_drive_permissions",
            description=(
                "List who has access to a Drive file or folder, with their role."
            ),
            tags=("google_drive_permissions", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to list permissions.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File or folder ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "get_drive_permission",
            "get_drive_permission",
            description="Get one specific permission by ID.",
            tags=("google_drive_permissions",),
            unwrap_envelope=True,
            fail_message="Failed to get permission.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "permission_id": {
                    "type": "string",
                    "description": "Permission ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "add_drive_permission",
            "create_drive_permission",
            description=(
                "Share a Drive file/folder. perm_type: user|group|domain|"
                "anyone. role: reader|commenter|writer|owner."
            ),
            destructive=True,
            parallelizable=False,
            tags=("google_drive_permissions", "google_drive"),
            unwrap_envelope=True,
            fail_message="Failed to add permission.",
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
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "role": d["role"],
                "perm_type": d.get("perm_type", "user"),
                "email_address": d.get("email_address") or None,
                "domain": d.get("domain") or None,
                "send_notification": bool(d.get("send_notification", True)),
                "email_message": d.get("email_message") or None,
            },
        ),
        client_op(
            "update_drive_permission",
            "update_drive_permission",
            description="Change a permission's role.",
            destructive=True,
            parallelizable=False,
            tags=("google_drive_permissions",),
            unwrap_envelope=True,
            fail_message="Failed to update permission.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "permission_id": {
                    "type": "string",
                    "description": "Permission ID.",
                    "example": "",
                },
                "role": {
                    "type": "string",
                    "description": "New role.",
                    "example": "writer",
                },
            },
        ),
        client_op(
            "remove_drive_permission",
            "delete_drive_permission",
            description="Revoke access by deleting a permission.",
            destructive=True,
            parallelizable=False,
            tags=("google_drive_permissions",),
            unwrap_envelope=True,
            fail_message="Failed to remove permission.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "permission_id": {
                    "type": "string",
                    "description": "Permission ID.",
                    "example": "",
                },
            },
        ),
        # ── Comments + replies ───────────────────────────────────────────
        client_op(
            "list_drive_comments",
            "list_drive_comments",
            description="List comments on a Drive file.",
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to list comments.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "include_deleted": {
                    "type": "boolean",
                    "description": "Include soft-deleted comments.",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "include_deleted": bool(d.get("include_deleted", False)),
            },
        ),
        client_op(
            "get_drive_comment",
            "get_drive_comment",
            description="Get a single comment with its replies.",
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to get comment.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "comment_id": {
                    "type": "string",
                    "description": "Comment ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "create_drive_comment",
            "create_drive_comment",
            description=(
                "Post a top-level comment on a Drive file. anchor is an "
                "optional region anchor (Google's structured anchor format)."
            ),
            parallelizable=False,
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to create comment.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
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
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "content": d["content"],
                "anchor": d.get("anchor") or None,
            },
        ),
        client_op(
            "update_drive_comment",
            "update_drive_comment",
            description="Edit a comment's content or mark it resolved.",
            parallelizable=False,
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to update comment.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "comment_id": {
                    "type": "string",
                    "description": "Comment ID.",
                    "example": "",
                },
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
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "comment_id": d["comment_id"],
                "content": d["content"] if "content" in d else None,
                "resolved": d["resolved"] if "resolved" in d else None,
            },
        ),
        client_op(
            "delete_drive_comment",
            "delete_drive_comment",
            description="Delete a comment.",
            destructive=True,
            parallelizable=False,
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to delete comment.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "comment_id": {
                    "type": "string",
                    "description": "Comment ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "list_drive_comment_replies",
            "list_drive_comment_replies",
            description="List replies on a comment.",
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to list replies.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "comment_id": {
                    "type": "string",
                    "description": "Comment ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "create_drive_comment_reply",
            "create_drive_comment_reply",
            description="Reply to a comment.",
            parallelizable=False,
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to create reply.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "comment_id": {
                    "type": "string",
                    "description": "Comment ID.",
                    "example": "",
                },
                "content": {
                    "type": "string",
                    "description": "Reply text.",
                    "example": "",
                },
            },
        ),
        client_op(
            "update_drive_comment_reply",
            "update_drive_comment_reply",
            description="Edit a reply.",
            parallelizable=False,
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to update reply.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "comment_id": {
                    "type": "string",
                    "description": "Comment ID.",
                    "example": "",
                },
                "reply_id": {
                    "type": "string",
                    "description": "Reply ID.",
                    "example": "",
                },
                "content": {
                    "type": "string",
                    "description": "New content.",
                    "example": "",
                },
            },
        ),
        client_op(
            "delete_drive_comment_reply",
            "delete_drive_comment_reply",
            description="Delete a reply.",
            destructive=True,
            parallelizable=False,
            tags=("google_drive_comments",),
            unwrap_envelope=True,
            fail_message="Failed to delete reply.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "comment_id": {
                    "type": "string",
                    "description": "Comment ID.",
                    "example": "",
                },
                "reply_id": {
                    "type": "string",
                    "description": "Reply ID.",
                    "example": "",
                },
            },
        ),
        # ── Revisions (version history) ──────────────────────────────────
        client_op(
            "list_drive_revisions",
            "list_drive_revisions",
            description="List revisions (version history) of a Drive file.",
            tags=("google_drive_revisions",),
            unwrap_envelope=True,
            fail_message="Failed to list revisions.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "get_drive_revision",
            "get_drive_revision",
            description="Get details of a specific revision.",
            tags=("google_drive_revisions",),
            unwrap_envelope=True,
            fail_message="Failed to get revision.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "revision_id": {
                    "type": "string",
                    "description": "Revision ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "update_drive_revision",
            "update_drive_revision",
            description=(
                "Mark a revision keep-forever (pin) or set publish state for "
                "Google-native files."
            ),
            parallelizable=False,
            tags=("google_drive_revisions",),
            unwrap_envelope=True,
            fail_message="Failed to update revision.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "revision_id": {
                    "type": "string",
                    "description": "Revision ID.",
                    "example": "",
                },
                "keep_forever": {
                    "type": "boolean",
                    "description": (
                        "Pin this revision (otherwise Drive auto-prunes after "
                        "100 or 30 days, whichever first)."
                    ),
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
            arg_map=lambda d: {
                "file_id": d["file_id"],
                "revision_id": d["revision_id"],
                "keep_forever": d["keep_forever"] if "keep_forever" in d else None,
                "published": d["published"] if "published" in d else None,
                "publish_auto": d["publish_auto"] if "publish_auto" in d else None,
            },
        ),
        client_op(
            "delete_drive_revision",
            "delete_drive_revision",
            description="Delete a revision.",
            destructive=True,
            parallelizable=False,
            tags=("google_drive_revisions",),
            unwrap_envelope=True,
            fail_message="Failed to delete revision.",
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
                "revision_id": {
                    "type": "string",
                    "description": "Revision ID.",
                    "example": "",
                },
            },
        ),
        # ── Shared drives (formerly Team Drives) ─────────────────────────
        client_op(
            "list_shared_drives",
            "list_shared_drives",
            description="List shared drives the user has access to.",
            tags=("google_drive_shared_drives",),
            unwrap_envelope=True,
            fail_message="Failed to list shared drives.",
            input_schema={
                "page_size": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 50,
                },
                "q": {
                    "type": "string",
                    "description": "Drive search query (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "page_size": d.get("page_size", 50),
                "q": d.get("q") or None,
            },
        ),
        client_op(
            "get_shared_drive",
            "get_shared_drive",
            description="Get metadata for a shared drive.",
            tags=("google_drive_shared_drives",),
            unwrap_envelope=True,
            fail_message="Failed to get shared drive.",
            input_schema={
                "drive_id": {
                    "type": "string",
                    "description": "Shared drive ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "create_shared_drive",
            "create_shared_drive",
            description=(
                "Create a new shared drive. The user must have permission to "
                "create shared drives in their org."
            ),
            parallelizable=False,
            tags=("google_drive_shared_drives",),
            unwrap_envelope=True,
            fail_message="Failed to create shared drive.",
            input_schema={
                "name": {
                    "type": "string",
                    "description": "Shared drive name.",
                    "example": "Team project",
                },
            },
        ),
        client_op(
            "update_shared_drive",
            "update_shared_drive",
            description="Rename or hide/unhide a shared drive.",
            parallelizable=False,
            tags=("google_drive_shared_drives",),
            unwrap_envelope=True,
            fail_message="Failed to update shared drive.",
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
            arg_map=lambda d: {
                "drive_id": d["drive_id"],
                "name": d.get("name") or None,
                "hidden": d["hidden"] if "hidden" in d else None,
            },
        ),
        client_op(
            "delete_shared_drive",
            "delete_shared_drive",
            description="Delete a shared drive. The drive must be empty.",
            destructive=True,
            parallelizable=False,
            tags=("google_drive_shared_drives",),
            unwrap_envelope=True,
            fail_message="Failed to delete shared drive.",
            input_schema={
                "drive_id": {
                    "type": "string",
                    "description": "Shared drive ID.",
                    "example": "",
                },
            },
        ),
    ]


# ==================================================================
# Intentionally NOT exposed as operations
# ==================================================================
# - Changes / watch endpoints (changes.list, changes.watch, channels.stop)
#     Push notifications / incremental sync — server-side webhook plumbing,
#     not per-interaction actions.
# - generateIds, resumable upload, multipart upload, DriveAccess proposals
#     Same reasoning as the actions file: niche or org-admin-level.
