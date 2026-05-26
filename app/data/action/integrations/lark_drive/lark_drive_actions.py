from agent_core import action


# ═══════════════════════════════════════════════════════════════════════════════
# Drive — files: list / search / metadata / folder / upload / download / delete
#                + move / copy / versions / stats
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="list_lark_drive_files",
    description="List files and folders in Lark Drive. Pass an empty folder_token to list the root.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "folder_token": {"type": "string", "description": "Folder token to list inside. Empty string lists the root.", "example": ""},
        "page_size": {"type": "integer", "description": "Max items (capped at 200).", "example": 50},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_drive_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_files",
        folder_token=input_data.get("folder_token", ""),
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_drive_file_metadata",
    description="Fetch metadata for one or more Lark Drive file tokens.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "file_tokens": {"type": "array", "description": "List of file tokens.", "example": ["boxcnabcdef0123"]},
        "doc_type": {"type": "string", "description": "'file' (default), 'doc', 'docx', 'sheet', 'bitable', 'mindnote', 'slides'.", "example": "file"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_drive_file_metadata(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_file_metadata",
        file_tokens=input_data["file_tokens"],
        doc_type=input_data.get("doc_type", "file"),
    )


@action(
    name="create_lark_drive_folder",
    description="Create a new folder in Lark Drive. Empty parent_folder_token creates at the root.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "name": {"type": "string", "description": "Folder name.", "example": "Reports 2026"},
        "parent_folder_token": {"type": "string", "description": "Parent folder token. Empty=root.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_drive_folder(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_folder",
        name=input_data["name"],
        parent_folder_token=input_data.get("parent_folder_token", ""),
    )


@action(
    name="upload_lark_drive_file",
    description="Upload a local file to a Lark Drive folder (max 20MB).",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "file_path": {"type": "string", "description": "Absolute path to the local file.", "example": "/home/user/report.pdf"},
        "parent_folder_token": {"type": "string", "description": "Destination folder token.", "example": ""},
        "file_name": {"type": "string", "description": "Name in Drive (defaults to basename).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def upload_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "upload_file",
        file_path=input_data["file_path"],
        parent_folder_token=input_data["parent_folder_token"],
        file_name=input_data.get("file_name", ""),
    )


@action(
    name="download_lark_drive_file",
    description="Download a regular file from Lark Drive to a local path. For Docs/Sheets use export_lark_drive_file.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "File token.", "example": ""},
        "dest_path": {"type": "string", "description": "Local path.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def download_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "download_file",
        file_token=input_data["file_token"],
        dest_path=input_data["dest_path"],
    )


@action(
    name="delete_lark_drive_file",
    description="Delete a file/folder/doc/etc by token.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "file_type": {"type": "string", "description": "file | folder | doc | docx | sheet | bitable | mindnote | shortcut | slides.", "example": "file"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "delete_file",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "file"),
    )


@action(
    name="search_lark_drive_files",
    description="Full-text search across files in Lark Drive.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "search_key": {"type": "string", "description": "Query.", "example": "Q1 report"},
        "count": {"type": "integer", "description": "Max results (capped 50).", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_lark_drive_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "search_files",
        search_key=input_data["search_key"],
        count=input_data.get("count", 20),
    )


@action(
    name="copy_lark_drive_file",
    description="Copy a file/doc/sheet/etc into a folder.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Source token.", "example": ""},
        "name": {"type": "string", "description": "Copy name.", "example": ""},
        "folder_token": {"type": "string", "description": "Destination folder token.", "example": ""},
        "copy_type": {"type": "string", "description": "file | folder | doc | docx | sheet | bitable | mindnote | slides.", "example": "file"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def copy_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "copy_file",
        file_token=input_data["file_token"],
        name=input_data["name"],
        folder_token=input_data["folder_token"],
        copy_type=input_data.get("copy_type", "file"),
    )


@action(
    name="move_lark_drive_file",
    description="Move a file/folder/doc to another folder.",
    action_sets=["lark_drive_files", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "target_folder_token": {"type": "string", "description": "Destination folder token.", "example": ""},
        "file_type": {"type": "string", "description": "file | folder | doc | docx | sheet | bitable | mindnote | shortcut | slides.", "example": "file"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def move_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "move_file",
        file_token=input_data["file_token"],
        target_folder_token=input_data["target_folder_token"],
        file_type=input_data.get("file_type", "file"),
    )


@action(
    name="list_lark_drive_file_versions",
    description="List version history for a Doc/Sheet (Docx/Doc/Sheet only).",
    action_sets=["lark_drive_files"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "file_type": {"type": "string", "description": "docx | doc | sheet.", "example": "docx"},
        "page_size": {"type": "integer", "description": "Max (capped 50).", "example": 50},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_drive_file_versions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_file_versions",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "docx"),
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_drive_file_statistics",
    description="Get views/likes/comments stats for a file.",
    action_sets=["lark_drive_files"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "file_type": {"type": "string", "description": "docx | doc | sheet | bitable | file.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_drive_file_statistics(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "file_statistics",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "docx"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Drive — Permissions (sharing)
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="list_lark_drive_permissions",
    description="List members with access to a file/doc/etc.",
    action_sets=["lark_drive_permissions", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "file_type": {"type": "string", "description": "doc | docx | sheet | bitable | file | folder | mindnote | slides.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_drive_permissions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_permission_members",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "docx"),
    )


@action(
    name="add_lark_drive_permission",
    description="Grant access. member_type: email|openid|userid|unionid|chatid|departmentid|openchat|opendepartment|groupid. perm: view|edit|full_access. perm_type: container|single_page.",
    action_sets=["lark_drive_permissions", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "member_type": {"type": "string", "description": "Member type.", "example": "email"},
        "member_id": {"type": "string", "description": "Member identifier (email / user_id / etc.).", "example": "alice@example.com"},
        "perm": {"type": "string", "description": "view | edit | full_access.", "example": "view"},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
        "perm_type": {"type": "string", "description": "container | single_page.", "example": "container"},
        "notify_lark": {"type": "boolean", "description": "Send a Lark notification.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_lark_drive_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "add_permission_member",
        file_token=input_data["file_token"],
        member_type=input_data["member_type"],
        member_id=input_data["member_id"],
        perm=input_data["perm"],
        file_type=input_data.get("file_type", "docx"),
        perm_type=input_data.get("perm_type", "container"),
        notify_lark=bool(input_data.get("notify_lark", False)),
    )


@action(
    name="update_lark_drive_permission",
    description="Change a member's permission level.",
    action_sets=["lark_drive_permissions"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "member_id": {"type": "string", "description": "Member ID.", "example": ""},
        "member_type": {"type": "string", "description": "Member type.", "example": "email"},
        "perm": {"type": "string", "description": "view | edit | full_access.", "example": "edit"},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
        "perm_type": {"type": "string", "description": "container | single_page.", "example": "container"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_drive_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_permission_member",
        file_token=input_data["file_token"],
        member_id=input_data["member_id"],
        member_type=input_data["member_type"],
        perm=input_data["perm"],
        file_type=input_data.get("file_type", "docx"),
        perm_type=input_data.get("perm_type", "container"),
    )


@action(
    name="remove_lark_drive_permission",
    description="Revoke a member's access.",
    action_sets=["lark_drive_permissions", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "member_id": {"type": "string", "description": "Member ID.", "example": ""},
        "member_type": {"type": "string", "description": "Member type.", "example": "email"},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_lark_drive_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "delete_permission_member",
        file_token=input_data["file_token"],
        member_id=input_data["member_id"],
        member_type=input_data["member_type"],
        file_type=input_data.get("file_type", "docx"),
    )


@action(
    name="get_lark_drive_public_permission",
    description="Get public-link settings for a file.",
    action_sets=["lark_drive_permissions"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_drive_public_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_public_permission",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "docx"),
    )


@action(
    name="update_lark_drive_public_permission",
    description="Update public-link settings (sharing scope, comments, security). Values are Lark enums like 'tenant_readable' / 'anyone_readable' / 'closed' / 'anyone_editable' — see Lark docs per field.",
    action_sets=["lark_drive_permissions"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
        "link_share_entity": {"type": "string", "description": "Who can access via link (optional).", "example": "closed"},
        "share_entity": {"type": "string", "description": "Who can share (optional).", "example": ""},
        "comment_entity": {"type": "string", "description": "Who can comment (optional).", "example": ""},
        "security_entity": {"type": "string", "description": "Security setting (optional).", "example": ""},
        "external_access_entity": {"type": "string", "description": "External access (optional).", "example": ""},
        "invite_external": {"type": "boolean", "description": "Allow external invites (optional).", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_drive_public_permission(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_public_permission",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "docx"),
        link_share_entity=input_data.get("link_share_entity") or None,
        share_entity=input_data.get("share_entity") or None,
        comment_entity=input_data.get("comment_entity") or None,
        security_entity=input_data.get("security_entity") or None,
        external_access_entity=input_data.get("external_access_entity") or None,
        invite_external=input_data["invite_external"] if "invite_external" in input_data else None,
    )


@action(
    name="transfer_lark_drive_ownership",
    description="Transfer ownership of a file to another user.",
    action_sets=["lark_drive_permissions"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "member_type": {"type": "string", "description": "email|openid|userid.", "example": "email"},
        "member_id": {"type": "string", "description": "New owner's identifier.", "example": ""},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
        "remove_old_owner": {"type": "boolean", "description": "Strip old owner's access.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def transfer_lark_drive_ownership(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "transfer_owner",
        file_token=input_data["file_token"],
        member_type=input_data["member_type"],
        member_id=input_data["member_id"],
        file_type=input_data.get("file_type", "docx"),
        remove_old_owner=bool(input_data.get("remove_old_owner", False)),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Drive — Comments
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="list_lark_drive_comments",
    description="List comments on a file.",
    action_sets=["lark_drive_comments", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
        "is_whole": {"type": "boolean", "description": "Whole-doc comments (true) vs anchored (false).", "example": True},
        "page_size": {"type": "integer", "description": "Max results.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_drive_comments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_comments",
        file_token=input_data["file_token"],
        file_type=input_data.get("file_type", "docx"),
        is_whole=bool(input_data.get("is_whole", True)),
        page_size=input_data.get("page_size", 100),
    )


@action(
    name="create_lark_drive_comment",
    description="Post a comment on a file. content_elements is a rich-text array: e.g. [{type:'text_run', text_run:{text:'...'}}].",
    action_sets=["lark_drive_comments", "lark_drive"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "content_elements": {"type": "array", "description": "Rich-text elements.", "example": [{"type": "text_run", "text_run": {"text": "Looks good"}}]},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_drive_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_comment",
        file_token=input_data["file_token"],
        content_elements=input_data["content_elements"],
        file_type=input_data.get("file_type", "docx"),
    )


@action(
    name="get_lark_drive_comment",
    description="Get a single comment.",
    action_sets=["lark_drive_comments"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_drive_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_comment",
        file_token=input_data["file_token"],
        comment_id=input_data["comment_id"],
        file_type=input_data.get("file_type", "docx"),
    )


@action(
    name="resolve_lark_drive_comment",
    description="Mark a comment resolved (or unresolved).",
    action_sets=["lark_drive_comments"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "is_solved": {"type": "boolean", "description": "True=resolve, False=unresolve.", "example": True},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def resolve_lark_drive_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "resolve_comment",
        file_token=input_data["file_token"],
        comment_id=input_data["comment_id"],
        is_solved=bool(input_data.get("is_solved", True)),
        file_type=input_data.get("file_type", "docx"),
    )


@action(
    name="list_lark_drive_comment_replies",
    description="List replies on a comment.",
    action_sets=["lark_drive_comments"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
        "page_size": {"type": "integer", "description": "Max results.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_drive_comment_replies(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_comment_replies",
        file_token=input_data["file_token"],
        comment_id=input_data["comment_id"],
        file_type=input_data.get("file_type", "docx"),
        page_size=input_data.get("page_size", 100),
    )


@action(
    name="update_lark_drive_comment_reply",
    description="Edit a reply.",
    action_sets=["lark_drive_comments"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "reply_id": {"type": "string", "description": "Reply ID.", "example": ""},
        "content_elements": {"type": "array", "description": "New rich-text content.", "example": []},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_drive_comment_reply(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_comment_reply",
        file_token=input_data["file_token"],
        comment_id=input_data["comment_id"],
        reply_id=input_data["reply_id"],
        content_elements=input_data["content_elements"],
        file_type=input_data.get("file_type", "docx"),
    )


@action(
    name="delete_lark_drive_comment_reply",
    description="Delete a reply.",
    action_sets=["lark_drive_comments"],
    input_schema={
        "file_token": {"type": "string", "description": "Token.", "example": ""},
        "comment_id": {"type": "string", "description": "Comment ID.", "example": ""},
        "reply_id": {"type": "string", "description": "Reply ID.", "example": ""},
        "file_type": {"type": "string", "description": "Doc type.", "example": "docx"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_drive_comment_reply(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "delete_comment_reply",
        file_token=input_data["file_token"],
        comment_id=input_data["comment_id"],
        reply_id=input_data["reply_id"],
        file_type=input_data.get("file_type", "docx"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Drive — Import / Export tasks
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="import_lark_drive_file",
    description="Convert a regular file into a Doc/Sheet/Bitable. Step 1: upload via upload_lark_drive_file → use its file_token here. Returns a ticket; poll with get_lark_drive_import_task until done.",
    action_sets=["lark_drive_import_export"],
    input_schema={
        "file_extension": {"type": "string", "description": "docx | xlsx | csv | pdf etc.", "example": "docx"},
        "file_name": {"type": "string", "description": "Target file name.", "example": ""},
        "file_token": {"type": "string", "description": "Source file token (already uploaded).", "example": ""},
        "file_type": {"type": "string", "description": "Target type: docx | sheet | bitable.", "example": "docx"},
        "folder_token": {"type": "string", "description": "Destination folder.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def import_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_import_task",
        file_extension=input_data["file_extension"],
        file_name=input_data["file_name"],
        file_token=input_data["file_token"],
        file_type=input_data["file_type"],
        folder_token=input_data.get("folder_token", ""),
    )


@action(
    name="get_lark_drive_import_task",
    description="Poll an import task. When job_status='success' the result token is the new Doc/Sheet/Bitable.",
    action_sets=["lark_drive_import_export"],
    input_schema={
        "ticket": {"type": "string", "description": "Ticket from import_lark_drive_file.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_drive_import_task(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_import_task",
        ticket=input_data["ticket"],
    )


@action(
    name="export_lark_drive_file",
    description="Convert a Doc/Sheet/Bitable into a regular file (e.g. docx → pdf, sheet → xlsx). Returns a ticket; poll with get_lark_drive_export_task, then download_lark_drive_export.",
    action_sets=["lark_drive_import_export", "lark_drive"],
    input_schema={
        "file_extension": {"type": "string", "description": "docx | xlsx | csv | pdf.", "example": "pdf"},
        "file_token": {"type": "string", "description": "Source Doc/Sheet/Bitable token.", "example": ""},
        "file_type": {"type": "string", "description": "Source type: docx | sheet | bitable.", "example": "docx"},
        "sub_id": {"type": "string", "description": "Sub-sheet/view ID (optional, for sheets/bitable).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def export_lark_drive_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_export_task",
        file_extension=input_data["file_extension"],
        file_token=input_data["file_token"],
        file_type=input_data["file_type"],
        sub_id=input_data.get("sub_id", ""),
    )


@action(
    name="get_lark_drive_export_task",
    description="Poll an export task. When job_status='success', use the returned file_token with download_lark_drive_export.",
    action_sets=["lark_drive_import_export"],
    input_schema={
        "ticket": {"type": "string", "description": "Ticket from export_lark_drive_file.", "example": ""},
        "file_token": {"type": "string", "description": "Original source token (same as passed to export).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_drive_export_task(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_export_task",
        ticket=input_data["ticket"],
        file_token=input_data["file_token"],
    )


@action(
    name="download_lark_drive_export",
    description="Download the final blob produced by a finished export task.",
    action_sets=["lark_drive_import_export"],
    input_schema={
        "result_file_token": {"type": "string", "description": "Token from get_lark_drive_export_task response.", "example": ""},
        "dest_path": {"type": "string", "description": "Local destination path.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def download_lark_drive_export(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "download_export",
        result_file_token=input_data["result_file_token"],
        dest_path=input_data["dest_path"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Docx (new Docs) — documents + blocks
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="create_lark_doc",
    description="Create a new Lark Doc (Docx). Returns document_id.",
    action_sets=["lark_docs", "lark_drive"],
    input_schema={
        "title": {"type": "string", "description": "Doc title.", "example": "Meeting notes"},
        "folder_token": {"type": "string", "description": "Parent folder (optional, defaults to root).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_document",
        title=input_data.get("title", ""),
        folder_token=input_data.get("folder_token", ""),
    )


@action(
    name="get_lark_doc",
    description="Get a Doc's metadata (title, revision_id, etc.).",
    action_sets=["lark_docs", "lark_drive"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_doc(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_drive", "get_document", document_id=input_data["document_id"])


@action(
    name="get_lark_doc_raw_content",
    description="Get a Doc's plain-text content (for skimming/summarizing).",
    action_sets=["lark_docs", "lark_drive"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
        "lang": {"type": "integer", "description": "0=default, 1=en, 2=zh, 3=ja.", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_doc_raw_content(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_document_raw_content",
        document_id=input_data["document_id"],
        lang=input_data.get("lang", 0),
    )


@action(
    name="list_lark_doc_blocks",
    description="List a Doc's blocks (paragraphs, headings, tables, etc.).",
    action_sets=["lark_docs", "lark_drive"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
        "page_size": {"type": "integer", "description": "Max blocks (capped 500).", "example": 500},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_doc_blocks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_document_blocks",
        document_id=input_data["document_id"],
        page_size=input_data.get("page_size", 500),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_doc_block",
    description="Get a single block.",
    action_sets=["lark_docs"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
        "block_id": {"type": "string", "description": "Block ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_doc_block(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_document_block",
        document_id=input_data["document_id"],
        block_id=input_data["block_id"],
    )


@action(
    name="append_lark_doc_blocks",
    description="Append child blocks under a parent block. Pass document_id as block_id to add at top level. children is an array of block objects (paragraph / heading / bullet / etc.).",
    action_sets=["lark_docs", "lark_drive"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
        "block_id": {"type": "string", "description": "Parent block ID (or document_id for top level).", "example": ""},
        "children": {"type": "array", "description": "Block objects to insert.", "example": []},
        "index": {"type": "integer", "description": "Insert position (-1 = end).", "example": -1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def append_lark_doc_blocks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_document_block_children",
        document_id=input_data["document_id"],
        block_id=input_data["block_id"],
        children=input_data["children"],
        index=input_data.get("index", -1),
    )


@action(
    name="update_lark_doc_block",
    description="Update a block. update_payload uses Docx's update structures, e.g. {update_text_elements: {elements: [...]}} for a paragraph.",
    action_sets=["lark_docs", "lark_drive"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
        "block_id": {"type": "string", "description": "Block ID.", "example": ""},
        "update_payload": {"type": "object", "description": "Per-block-type update body.", "example": {}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_doc_block(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_document_block",
        document_id=input_data["document_id"],
        block_id=input_data["block_id"],
        update_payload=input_data["update_payload"],
    )


@action(
    name="batch_update_lark_doc_blocks",
    description="Batch-update multiple blocks in one round-trip. requests is a list of {block_id, ...update_fields}.",
    action_sets=["lark_docs"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
        "requests": {"type": "array", "description": "Update objects.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def batch_update_lark_doc_blocks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "batch_update_document_blocks",
        document_id=input_data["document_id"],
        requests=input_data["requests"],
    )


@action(
    name="delete_lark_doc_blocks",
    description="Delete a contiguous range of children of a parent block. Range is [start_index, end_index) (half-open).",
    action_sets=["lark_docs"],
    input_schema={
        "document_id": {"type": "string", "description": "Doc ID.", "example": ""},
        "block_id": {"type": "string", "description": "Parent block ID.", "example": ""},
        "start_index": {"type": "integer", "description": "Start (inclusive).", "example": 0},
        "end_index": {"type": "integer", "description": "End (exclusive).", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_doc_blocks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "delete_document_blocks",
        document_id=input_data["document_id"],
        block_id=input_data["block_id"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Sheets — spreadsheets + values
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="create_lark_sheet",
    description="Create a new Lark Spreadsheet. Returns spreadsheet_token.",
    action_sets=["lark_sheets", "lark_drive"],
    input_schema={
        "title": {"type": "string", "description": "Spreadsheet title.", "example": ""},
        "folder_token": {"type": "string", "description": "Parent folder (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_sheet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_spreadsheet",
        title=input_data.get("title", ""),
        folder_token=input_data.get("folder_token", ""),
    )


@action(
    name="get_lark_sheet",
    description="Get spreadsheet metadata (title, owner, url).",
    action_sets=["lark_sheets", "lark_drive"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Spreadsheet token.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_sheet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_spreadsheet",
        spreadsheet_token=input_data["spreadsheet_token"],
    )


@action(
    name="rename_lark_sheet",
    description="Rename a spreadsheet.",
    action_sets=["lark_sheets"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "title": {"type": "string", "description": "New title.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def rename_lark_sheet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_spreadsheet_title",
        spreadsheet_token=input_data["spreadsheet_token"],
        title=input_data["title"],
    )


@action(
    name="list_lark_sheet_tabs",
    description="List child sheets (tabs) in a spreadsheet.",
    action_sets=["lark_sheets", "lark_drive"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_sheet_tabs(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_spreadsheet_sheets",
        spreadsheet_token=input_data["spreadsheet_token"],
    )


@action(
    name="get_lark_sheet_tab",
    description="Get info about a single sheet tab (rows, cols, grid_properties).",
    action_sets=["lark_sheets"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "sheet_id": {"type": "string", "description": "Tab/sheet ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_sheet_tab(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_spreadsheet_sheet",
        spreadsheet_token=input_data["spreadsheet_token"],
        sheet_id=input_data["sheet_id"],
    )


@action(
    name="read_lark_sheet_values",
    description="Read a range of cells. range format: '<sheetId>!A1:D10'.",
    action_sets=["lark_sheets", "lark_drive"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "range": {"type": "string", "description": "Range like 'sheet1!A1:D10'.", "example": ""},
        "value_render_option": {"type": "string", "description": "ToString | FormattedValue | Formula | UnformattedValue.", "example": "ToString"},
        "date_time_render_option": {"type": "string", "description": "FormattedString or UnformattedValue.", "example": "FormattedString"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def read_lark_sheet_values(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_sheet_values",
        spreadsheet_token=input_data["spreadsheet_token"],
        range_=input_data["range"],
        value_render_option=input_data.get("value_render_option", "ToString"),
        date_time_render_option=input_data.get("date_time_render_option", "FormattedString"),
    )


@action(
    name="batch_read_lark_sheet_values",
    description="Read multiple ranges in one call.",
    action_sets=["lark_sheets"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "ranges": {"type": "array", "description": "Array of range strings.", "example": []},
        "value_render_option": {"type": "string", "description": "Render option.", "example": "ToString"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def batch_read_lark_sheet_values(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "batch_get_sheet_values",
        spreadsheet_token=input_data["spreadsheet_token"],
        ranges=input_data["ranges"],
        value_render_option=input_data.get("value_render_option", "ToString"),
    )


@action(
    name="write_lark_sheet_values",
    description="Write a 2D values array into a range (overwrites existing cells).",
    action_sets=["lark_sheets", "lark_drive"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "range": {"type": "string", "description": "Range like 'sheet1!A1'.", "example": ""},
        "values": {"type": "array", "description": "2D array of cell values.", "example": [["A1", "B1"], ["A2", "B2"]]},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def write_lark_sheet_values(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_sheet_values",
        spreadsheet_token=input_data["spreadsheet_token"],
        range_=input_data["range"],
        values=input_data["values"],
    )


@action(
    name="append_lark_sheet_values",
    description="Append rows after the last filled row. insert_data_option: OVERWRITE | INSERT_ROWS.",
    action_sets=["lark_sheets", "lark_drive"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "range": {"type": "string", "description": "Range like 'sheet1!A:D' (search range).", "example": ""},
        "values": {"type": "array", "description": "2D array of rows to append.", "example": []},
        "insert_data_option": {"type": "string", "description": "OVERWRITE | INSERT_ROWS.", "example": "OVERWRITE"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def append_lark_sheet_values(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "append_sheet_values",
        spreadsheet_token=input_data["spreadsheet_token"],
        range_=input_data["range"],
        values=input_data["values"],
        insert_data_option=input_data.get("insert_data_option", "OVERWRITE"),
    )


@action(
    name="batch_write_lark_sheet_values",
    description="Write to multiple ranges in one call. value_ranges: [{range, values}, ...].",
    action_sets=["lark_sheets"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "value_ranges": {"type": "array", "description": "[{range, values}, ...].", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def batch_write_lark_sheet_values(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "batch_update_sheet_values",
        spreadsheet_token=input_data["spreadsheet_token"],
        value_ranges=input_data["value_ranges"],
    )


@action(
    name="find_in_lark_sheet",
    description="Find cells matching a text within a range.",
    action_sets=["lark_sheets"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "sheet_id": {"type": "string", "description": "Sheet tab ID.", "example": ""},
        "find_text": {"type": "string", "description": "Text to find.", "example": ""},
        "range": {"type": "string", "description": "Search range like 'sheet1!A1:Z1000'.", "example": ""},
        "match_case": {"type": "boolean", "description": "Case sensitive.", "example": False},
        "match_entire_cell": {"type": "boolean", "description": "Match whole cell.", "example": False},
        "search_by_regex": {"type": "boolean", "description": "Regex mode.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def find_in_lark_sheet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "find_in_sheet",
        spreadsheet_token=input_data["spreadsheet_token"],
        sheet_id=input_data["sheet_id"],
        find_text=input_data["find_text"],
        range_=input_data["range"],
        match_case=bool(input_data.get("match_case", False)),
        match_entire_cell=bool(input_data.get("match_entire_cell", False)),
        search_by_regex=bool(input_data.get("search_by_regex", False)),
        include_formulas=bool(input_data.get("include_formulas", False)),
    )


@action(
    name="replace_in_lark_sheet",
    description="Find-and-replace across a range.",
    action_sets=["lark_sheets"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "sheet_id": {"type": "string", "description": "Sheet tab ID.", "example": ""},
        "find_text": {"type": "string", "description": "Text to find.", "example": ""},
        "replacement": {"type": "string", "description": "Replacement text.", "example": ""},
        "range": {"type": "string", "description": "Search range.", "example": ""},
        "match_case": {"type": "boolean", "description": "Case sensitive.", "example": False},
        "match_entire_cell": {"type": "boolean", "description": "Match whole cell.", "example": False},
        "search_by_regex": {"type": "boolean", "description": "Regex.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def replace_in_lark_sheet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "replace_in_sheet",
        spreadsheet_token=input_data["spreadsheet_token"],
        sheet_id=input_data["sheet_id"],
        find_text=input_data["find_text"],
        replacement=input_data["replacement"],
        range_=input_data["range"],
        match_case=bool(input_data.get("match_case", False)),
        match_entire_cell=bool(input_data.get("match_entire_cell", False)),
        search_by_regex=bool(input_data.get("search_by_regex", False)),
        include_formulas=bool(input_data.get("include_formulas", False)),
    )


@action(
    name="insert_lark_sheet_rows_or_cols",
    description="Insert rows or columns into a sheet tab. major_dimension: ROWS | COLUMNS.",
    action_sets=["lark_sheets"],
    input_schema={
        "spreadsheet_token": {"type": "string", "description": "Token.", "example": ""},
        "sheet_id": {"type": "string", "description": "Sheet tab ID.", "example": ""},
        "major_dimension": {"type": "string", "description": "ROWS | COLUMNS.", "example": "ROWS"},
        "start_index": {"type": "integer", "description": "Insert before this index (0-based).", "example": 0},
        "end_index": {"type": "integer", "description": "Insert up to (exclusive).", "example": 1},
        "inherit_style": {"type": "string", "description": "BEFORE | AFTER.", "example": "BEFORE"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def insert_lark_sheet_rows_or_cols(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "insert_sheet_dimension_range",
        spreadsheet_token=input_data["spreadsheet_token"],
        sheet_id=input_data["sheet_id"],
        major_dimension=input_data["major_dimension"],
        start_index=input_data["start_index"],
        end_index=input_data["end_index"],
        inherit_style=input_data.get("inherit_style", "BEFORE"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Bitable — Bases / tables / records / fields / views
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="create_lark_bitable",
    description="Create a new Bitable (multi-dimensional table). Returns app_token.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "name": {"type": "string", "description": "Bitable name.", "example": ""},
        "folder_token": {"type": "string", "description": "Parent folder (optional).", "example": ""},
        "time_zone": {"type": "string", "description": "Time zone.", "example": "Asia/Shanghai"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_bitable(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_bitable_app",
        name=input_data.get("name", ""),
        folder_token=input_data.get("folder_token", ""),
        time_zone=input_data.get("time_zone", "Asia/Shanghai"),
    )


@action(
    name="get_lark_bitable",
    description="Get a Bitable's metadata.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable app_token.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_bitable(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_drive", "get_bitable_app", app_token=input_data["app_token"])


@action(
    name="update_lark_bitable",
    description="Update a Bitable's name or is_advanced flag.",
    action_sets=["lark_bitable"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "name": {"type": "string", "description": "New name (optional).", "example": ""},
        "is_advanced": {"type": "boolean", "description": "Advanced mode (optional).", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_bitable(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_bitable_app",
        app_token=input_data["app_token"],
        name=input_data.get("name") if "name" in input_data else None,
        is_advanced=input_data["is_advanced"] if "is_advanced" in input_data else None,
    )


@action(
    name="list_lark_bitable_tables",
    description="List tables in a Bitable.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "page_size": {"type": "integer", "description": "Max (capped 100).", "example": 100},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_bitable_tables(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_bitable_tables",
        app_token=input_data["app_token"],
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="create_lark_bitable_table",
    description="Create a new table in a Bitable.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "name": {"type": "string", "description": "Table name.", "example": ""},
        "default_view_name": {"type": "string", "description": "Initial view name (optional).", "example": ""},
        "fields": {"type": "array", "description": "Initial field schema (optional).", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_bitable_table(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_bitable_table",
        app_token=input_data["app_token"],
        name=input_data["name"],
        default_view_name=input_data.get("default_view_name") or None,
        fields=input_data.get("fields") or None,
    )


@action(
    name="delete_lark_bitable_table",
    description="Delete a table from a Bitable.",
    action_sets=["lark_bitable"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_bitable_table(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "delete_bitable_table",
        app_token=input_data["app_token"], table_id=input_data["table_id"],
    )


@action(
    name="list_lark_bitable_records",
    description="List records in a table.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "view_id": {"type": "string", "description": "View ID (optional).", "example": ""},
        "page_size": {"type": "integer", "description": "Max records (capped 500).", "example": 100},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
        "field_names": {"type": "array", "description": "Specific field names to fetch.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_bitable_records(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_bitable_records",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        view_id=input_data.get("view_id", ""),
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
        field_names=input_data.get("field_names") or None,
    )


@action(
    name="get_lark_bitable_record",
    description="Get a single record.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "record_id": {"type": "string", "description": "Record ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_bitable_record(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_bitable_record",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        record_id=input_data["record_id"],
    )


@action(
    name="create_lark_bitable_record",
    description="Create a record in a table. fields is a dict mapping field name → value (per the field's type).",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "fields": {"type": "object", "description": "Field-name → value map.", "example": {"Name": "Alice"}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_bitable_record(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_bitable_record",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        fields=input_data["fields"],
    )


@action(
    name="update_lark_bitable_record",
    description="Update a record.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "record_id": {"type": "string", "description": "Record ID.", "example": ""},
        "fields": {"type": "object", "description": "Fields to update.", "example": {}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_lark_bitable_record(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "update_bitable_record",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        record_id=input_data["record_id"],
        fields=input_data["fields"],
    )


@action(
    name="delete_lark_bitable_record",
    description="Delete a record.",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "record_id": {"type": "string", "description": "Record ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_lark_bitable_record(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "delete_bitable_record",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        record_id=input_data["record_id"],
    )


@action(
    name="batch_create_lark_bitable_records",
    description="Create multiple records in one call. records: [{fields: {...}}, ...].",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "records": {"type": "array", "description": "[{fields: {...}}, ...].", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def batch_create_lark_bitable_records(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "batch_create_bitable_records",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        records=input_data["records"],
    )


@action(
    name="batch_update_lark_bitable_records",
    description="Update multiple records. records: [{record_id, fields}, ...].",
    action_sets=["lark_bitable"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "records": {"type": "array", "description": "[{record_id, fields}, ...].", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def batch_update_lark_bitable_records(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "batch_update_bitable_records",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        records=input_data["records"],
    )


@action(
    name="batch_delete_lark_bitable_records",
    description="Delete multiple records.",
    action_sets=["lark_bitable"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "record_ids": {"type": "array", "description": "Record IDs.", "example": []},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def batch_delete_lark_bitable_records(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "batch_delete_bitable_records",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        record_ids=input_data["record_ids"],
    )


@action(
    name="search_lark_bitable_records",
    description="Search records using Bitable's filter+sort syntax. filter_obj: {conjunction:'and'|'or', conditions:[{field_name, operator, value}]}. sort: [{field_name, desc}].",
    action_sets=["lark_bitable", "lark_drive"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "filter": {"type": "object", "description": "Filter spec (optional).", "example": {}},
        "sort": {"type": "array", "description": "Sort spec (optional).", "example": []},
        "field_names": {"type": "array", "description": "Field names to return (optional).", "example": []},
        "view_id": {"type": "string", "description": "View ID (optional).", "example": ""},
        "page_size": {"type": "integer", "description": "Max (capped 500).", "example": 100},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_lark_bitable_records(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "search_bitable_records",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        filter_obj=input_data.get("filter") or None,
        sort=input_data.get("sort") or None,
        field_names=input_data.get("field_names") or None,
        view_id=input_data.get("view_id", ""),
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="list_lark_bitable_fields",
    description="List fields (column definitions) in a table.",
    action_sets=["lark_bitable"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "view_id": {"type": "string", "description": "View ID (optional).", "example": ""},
        "page_size": {"type": "integer", "description": "Max (capped 100).", "example": 100},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_bitable_fields(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_bitable_fields",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        view_id=input_data.get("view_id", ""),
        page_size=input_data.get("page_size", 100),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="create_lark_bitable_field",
    description="Create a new field. field_type: 1=Text, 2=Number, 3=SingleSelect, 4=MultiSelect, 5=DateTime, 7=Checkbox, 11=User, 13=Phone, 15=URL, 17=Attachment, 18=Link, 19=Lookup, 20=Formula, 22=Location, 23=Group, 1001=CreatedTime, 1002=ModifiedTime, 1003=CreatedUser, 1004=ModifiedUser, 1005=AutoNumber.",
    action_sets=["lark_bitable"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "field_name": {"type": "string", "description": "Field name.", "example": ""},
        "field_type": {"type": "integer", "description": "Type code.", "example": 1},
        "property": {"type": "object", "description": "Field-type-specific property (e.g. options for select).", "example": {}},
        "description": {"type": "object", "description": "Description object (optional).", "example": {}},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_bitable_field(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_bitable_field",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        field_name=input_data["field_name"],
        field_type=input_data["field_type"],
        property=input_data.get("property") or None,
        description=input_data.get("description") or None,
    )


@action(
    name="list_lark_bitable_views",
    description="List views in a table.",
    action_sets=["lark_bitable"],
    input_schema={
        "app_token": {"type": "string", "description": "Bitable token.", "example": ""},
        "table_id": {"type": "string", "description": "Table ID.", "example": ""},
        "page_size": {"type": "integer", "description": "Max.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_bitable_views(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_bitable_views",
        app_token=input_data["app_token"],
        table_id=input_data["table_id"],
        page_size=input_data.get("page_size", 100),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Wiki — spaces + nodes
# ═══════════════════════════════════════════════════════════════════════════════

@action(
    name="list_lark_wiki_spaces",
    description="List Wiki spaces accessible to the bot.",
    action_sets=["lark_wiki", "lark_drive"],
    input_schema={
        "page_size": {"type": "integer", "description": "Max (capped 50).", "example": 50},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_wiki_spaces(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_wiki_spaces",
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_wiki_space",
    description="Get info about a Wiki space.",
    action_sets=["lark_wiki"],
    input_schema={
        "space_id": {"type": "string", "description": "Space ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_wiki_space(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("lark_drive", "get_wiki_space", space_id=input_data["space_id"])


@action(
    name="list_lark_wiki_nodes",
    description="List wiki nodes (pages) in a space.",
    action_sets=["lark_wiki", "lark_drive"],
    input_schema={
        "space_id": {"type": "string", "description": "Space ID.", "example": ""},
        "parent_node_token": {"type": "string", "description": "Parent node (optional, empty=top level).", "example": ""},
        "page_size": {"type": "integer", "description": "Max (capped 50).", "example": 50},
        "page_token": {"type": "string", "description": "Pagination cursor.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_lark_wiki_nodes(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "list_wiki_nodes",
        space_id=input_data["space_id"],
        parent_node_token=input_data.get("parent_node_token", ""),
        page_size=input_data.get("page_size", 50),
        page_token=input_data.get("page_token", ""),
    )


@action(
    name="get_lark_wiki_node",
    description="Resolve a wiki node token to its underlying obj_token + obj_type. ESSENTIAL when given a Wiki URL — the token in the URL isn't the doc_token of the underlying Doc/Sheet/Bitable.",
    action_sets=["lark_wiki", "lark_drive"],
    input_schema={
        "token": {"type": "string", "description": "Wiki node token (from a wiki URL).", "example": ""},
        "obj_type": {"type": "string", "description": "wiki (default) | doc | docx | sheet | bitable | mindnote | file | slides.", "example": "wiki"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_lark_wiki_node(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "get_wiki_node",
        token=input_data["token"],
        obj_type=input_data.get("obj_type", "wiki"),
    )


@action(
    name="create_lark_wiki_node",
    description="Create a new wiki node. obj_type: doc | docx | sheet | bitable | mindnote | file | slides. node_type: origin (new doc) | shortcut (link to existing).",
    action_sets=["lark_wiki"],
    input_schema={
        "space_id": {"type": "string", "description": "Space ID.", "example": ""},
        "obj_type": {"type": "string", "description": "Underlying doc type.", "example": "docx"},
        "node_type": {"type": "string", "description": "origin | shortcut.", "example": "origin"},
        "parent_node_token": {"type": "string", "description": "Parent node (optional).", "example": ""},
        "origin_node_token": {"type": "string", "description": "Source token (for shortcut).", "example": ""},
        "title": {"type": "string", "description": "Title (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_lark_wiki_node(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "create_wiki_node",
        space_id=input_data["space_id"],
        obj_type=input_data["obj_type"],
        node_type=input_data.get("node_type", "origin"),
        parent_node_token=input_data.get("parent_node_token", ""),
        origin_node_token=input_data.get("origin_node_token", ""),
        title=input_data.get("title", ""),
    )


@action(
    name="move_lark_wiki_node",
    description="Move a wiki node to another parent / space.",
    action_sets=["lark_wiki"],
    input_schema={
        "space_id": {"type": "string", "description": "Current space ID.", "example": ""},
        "node_token": {"type": "string", "description": "Node token to move.", "example": ""},
        "target_parent_token": {"type": "string", "description": "New parent (optional).", "example": ""},
        "target_space_id": {"type": "string", "description": "New space (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def move_lark_wiki_node(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client(
        "lark_drive", "move_wiki_node",
        space_id=input_data["space_id"],
        node_token=input_data["node_token"],
        target_parent_token=input_data.get("target_parent_token", ""),
        target_space_id=input_data.get("target_space_id", ""),
    )


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# - Chunked upload (upload_prepare / upload_part / upload_finish)
#     Required for files >20MB. The single-shot upload_lark_drive_file
#     covers the realistic interactive case.
# - Subscription / event webhooks (file.subscribe, file.edit, etc.)
#     Server-side push plumbing — handled by the listener if needed.
# - Bitable workflow / automation, role/perm management
#     Admin-style configuration; out of scope for daily-driver use.
# - Sheets cell formatting (border / merge_cells / cell_style)
#     Niche presentational tweaks that complicate the surface heavily.
#     Add via batch_update_sheet_values' style payload when needed.
# - Mindnote / Slides surfaces
#     Niche editors; create/move/share work via the generic Drive endpoints.
# - Docx Tables / Bitable Lookup/Formula field schemas
#     Heavy data-shape surface; the action's `property` dict accepts the
#     raw Lark shape so the agent can construct it from docs without a
#     per-field-type wrapper.
