"""Figma REST and optional browser canvas operations, grouped by workflow."""

from __future__ import annotations

from .._shared import client_op


def _s(description, example=""):
    return {"type": "string", "description": description, "example": example}


def _i(description, example=30):
    return {"type": "integer", "description": description, "example": example}


FILE = _s(
    "Figma file key or https://www.figma.com/design/<key>/… URL. Omit only if a default file is configured.",
    "AbCdEf123",
)
TEAM = _s(
    "Numeric team id or Figma team URL; omit only if a default team is configured. Team ids cannot be discovered by API.",
    "123456",
)
NODES = {
    "type": "array",
    "description": "Node ids such as 12:34. Omit when the file URL includes node-id. Maximum 100.",
    "example": ["12:34"],
}
DEPTH = _i("Tree depth, 1–10; default 2. Results also obey the configured node cap.", 2)
LIMIT = _i("Maximum items, 1–100, default 30.")
OFFSET = _i(
    "Local list offset. Follow pagination.next_offset; this does not reduce the API's response size.",
    0,
)
VERSION = _s("Optional historical version id; omit for the current version.")
COMMENT = _s(
    "Comment id returned by list_figma_comments. Reply operations require a root comment id.",
    "123",
)
FORMAT = _s("Export format: png, jpg, svg or pdf. Default png.", "png")
SCALE = {
    "type": "number",
    "description": "Render scale, 0.01–4, default 1.",
    "example": 1,
}


def _op(
    name,
    method,
    description,
    group,
    schema,
    *,
    core=False,
    write=False,
    destructive=False,
):
    return client_op(
        name,
        method,
        description=description,
        input_schema=schema,
        tags=(f"figma_{group}", "figma") if core else (f"figma_{group}",),
        parallelizable=not write,
        destructive=destructive,
    )


def build_operations():
    ops = [
        _op(
            "parse_figma_url",
            "parse_url",
            "Extract a file key and optional normalized node id from a Figma link. Does not fetch the file.",
            "files",
            {"file_key": FILE},
            core=True,
        ),
        _op(
            "get_figma_file",
            "get_file",
            "Read a bounded Figma document tree. Check truncated/children_truncated; request specific nodes for further detail.",
            "files",
            {"file_key": FILE, "depth": DEPTH, "version": VERSION},
            core=True,
        ),
        _op(
            "get_figma_file_metadata",
            "get_file_metadata",
            "Read lightweight file metadata before requesting expensive document contents.",
            "files",
            {"file_key": FILE},
            core=True,
        ),
        _op(
            "get_figma_nodes",
            "get_nodes",
            "Read selected node subtrees, preserving layout, text and style data. A node URL supplies the node id automatically.",
            "files",
            {"file_key": FILE, "node_ids": NODES, "depth": DEPTH, "version": VERSION},
            core=True,
        ),
        _op(
            "find_figma_nodes",
            "find_nodes",
            "Search names/types in a bounded, fetched document tree. This is not global file search; use returned ids with get_figma_nodes.",
            "files",
            {
                "file_key": FILE,
                "name": _s("Case-insensitive node-name substring."),
                "node_type": _s("Optional node type, e.g. FRAME or COMPONENT."),
                "depth": _i(
                    "Tree depth, 1–10; default 4. Results also obey the configured node cap.",
                    4,
                ),
                "limit": LIMIT,
                "offset": OFFSET,
            },
            core=True,
        ),
        _op(
            "list_figma_versions",
            "list_versions",
            "List file version history. Pass pagination.prev_page to before or pagination.next_page to after; returned URLs preserve secondary cursors.",
            "files",
            {
                "file_key": FILE,
                "limit": LIMIT,
                "before": _s(
                    "Previous-page cursor or returned pagination.prev_page URL."
                ),
                "after": _s("Next-page cursor or returned pagination.next_page URL."),
            },
        ),
        _op(
            "export_figma_images",
            "export_images",
            "Render nodes to temporary asset URLs. Check failed_node_ids; download images when permanent local files are needed.",
            "assets",
            {
                "file_key": FILE,
                "node_ids": NODES,
                "format": FORMAT,
                "scale": SCALE,
                "version": VERSION,
            },
            core=True,
        ),
        _op(
            "get_figma_image_fills",
            "get_image_fills",
            "Get temporary URLs for image fills embedded in a design, keyed by imageRef.",
            "assets",
            {"file_key": FILE},
            core=True,
        ),
        _op(
            "download_figma_images",
            "download_images",
            "Render and save exported nodes to unique local files. Does not overwrite existing files. Reports partial failures; maximum 50 MiB per asset.",
            "assets",
            {
                "file_key": FILE,
                "output_dir": _s("Required absolute local output directory."),
                "node_ids": NODES,
                "format": FORMAT,
                "scale": SCALE,
                "version": VERSION,
            },
            core=True,
            write=True,
        ),
        _op(
            "list_figma_comments",
            "list_comments",
            "List file comments with root/reply ids. Uses local pagination over the API response.",
            "comments",
            {"file_key": FILE, "limit": LIMIT, "offset": OFFSET},
            core=True,
        ),
        _op(
            "post_figma_comment",
            "post_comment",
            "Post a new root comment, optionally anchored with client_meta. Posting requires file_comments:write.",
            "comments",
            {
                "file_key": FILE,
                "message": _s("Required non-empty comment text."),
                "client_meta": {
                    "type": "object",
                    "description": "Optional Figma comment position, e.g. node_id and node_offset.",
                    "example": {"node_id": "12:34", "node_offset": {"x": 0, "y": 0}},
                },
            },
            core=True,
            write=True,
            destructive=True,  # Outward-facing post: enable the host replay guard.
        ),
        _op(
            "reply_figma_comment",
            "reply_comment",
            "Reply to a root comment; replies cannot be parents of other replies.",
            "comments",
            {
                "file_key": FILE,
                "comment_id": COMMENT,
                "message": _s("Required non-empty reply text."),
            },
            core=True,
            write=True,
            destructive=True,
        ),
        _op(
            "delete_figma_comment",
            "delete_comment",
            "Delete a comment authored by the connected user. Figma does not allow deleting another user's comment.",
            "comments",
            {"file_key": FILE, "comment_id": COMMENT},
            core=True,
            write=True,
            destructive=True,
        ),
        _op(
            "list_figma_comment_reactions",
            "list_comment_reactions",
            "List reactions to a comment. Follow pagination.next_page with cursor.",
            "comments",
            {
                "file_key": FILE,
                "comment_id": COMMENT,
                "cursor": _s("Pagination cursor."),
            },
        ),
        _op(
            "add_figma_comment_reaction",
            "add_comment_reaction",
            "React to a comment using a Figma emoji shortcode, e.g. :heart:.",
            "comments",
            {
                "file_key": FILE,
                "comment_id": COMMENT,
                "emoji": _s("Required emoji shortcode.", ":heart:"),
            },
            write=True,
        ),
        _op(
            "delete_figma_comment_reaction",
            "delete_comment_reaction",
            "Remove the connected user's reaction from a comment.",
            "comments",
            {
                "file_key": FILE,
                "comment_id": COMMENT,
                "emoji": _s("Emoji shortcode to remove.", ":heart:"),
            },
            write=True,
            destructive=True,
        ),
        _op(
            "get_figma_current_user",
            "get_current_user",
            "Get the connected Figma user's identity and profile.",
            "discovery",
            {},
            core=True,
        ),
        _op(
            "list_figma_team_folders",
            "list_team_folders",
            "List top-level folders for a supplied team. Requires folders:read and PAT/private OAuth; unavailable to public OAuth apps.",
            "discovery",
            {"team_id": TEAM, "limit": LIMIT, "offset": OFFSET},
            core=True,
        ),
        _op(
            "list_figma_subfolders",
            "list_subfolders",
            "List direct subfolders. Requires folders:read and PAT/private OAuth; uses local pagination.",
            "discovery",
            {"folder_id": _s("Required folder id."), "limit": LIMIT, "offset": OFFSET},
        ),
        _op(
            "list_figma_folder_files",
            "list_folder_files",
            "List files in a folder. Requires folders:read and PAT/private OAuth; uses local pagination.",
            "discovery",
            {"folder_id": _s("Required folder id."), "limit": LIMIT, "offset": OFFSET},
            core=True,
        ),
        _op(
            "get_figma_folder_metadata",
            "get_folder_metadata",
            "Get folder metadata using folder_metadata:read (OAuth), or explicitly partial id/name metadata using folders:read with a personal token.",
            "discovery",
            {"folder_id": _s("Required folder id.")},
        ),
    ]
    # Published library endpoints share identical paging and identifier rules.
    for resource, singular, label in (
        ("components", "component", "components"),
        ("component_sets", "component_set", "component sets"),
        ("styles", "style", "styles"),
    ):
        ops.extend(
            [
                _op(
                    f"list_figma_team_{resource}",
                    f"list_team_{resource}",
                    f"List published {label} in a supplied team. Server pagination uses before/after; requires team_library_content:read.",
                    "library",
                    {
                        "team_id": TEAM,
                        "limit": LIMIT,
                        "before": _s("Previous-page cursor."),
                        "after": _s("Next-page cursor."),
                    },
                ),
                _op(
                    f"list_figma_file_{resource}",
                    f"list_file_{resource}",
                    f"List published {label} from a file using local pagination. Requires library_content:read; unpublished nodes are accessible through get_figma_nodes.",
                    "library",
                    {"file_key": FILE, "limit": LIMIT, "offset": OFFSET},
                    core=True,
                ),
                _op(
                    f"get_figma_{singular}",
                    f"get_{singular}",
                    f"Get a published {singular.replace('_', ' ')} by its library key, not its node id. Requires library_assets:read.",
                    "library",
                    {
                        f"{singular}_key": _s(
                            "Required published library key; not a node id."
                        )
                    },
                ),
            ]
        )
    ops.extend(
        [
            _op(
                "start_figma_canvas",
                "start_canvas",
                "Start CraftBot's local canvas bridge on port 3055 and return the published plugin setup instructions. Requires the Figma plugin open in the user's browser for design creation.",
                "canvas",
                {},
                core=True,
                write=True,
            ),
            _op(
                "connect_figma_canvas",
                "connect_canvas",
                "Pair the channel shown by Talk To Figma MCP Plugin with this account session. Canvas edits target that open document/page; a REST default file does not choose the target.",
                "canvas",
                {
                    "channel": _s(
                        "Required channel string visibly shown by the connected Figma plugin."
                    )
                },
                core=True,
                write=True,
            ),
            _op(
                "get_figma_canvas_status",
                "canvas_status",
                "Check this account's canvas connection, or inspect a request_id after a timeout without replaying a write.",
                "canvas",
                {
                    "request_id": _s(
                        "Optional request id returned in a canvas error; history lasts for this session, up to 128 commands."
                    )
                },
                core=True,
            ),
            _op(
                "read_figma_canvas",
                "read_canvas",
                "Read the live plugin page/selection or specific canvas nodes before and after editing. This sees unsaved canvas changes immediately.",
                "canvas",
                {
                    "node_ids": {
                        "type": "array",
                        "description": "Optional 1–20 canvas node ids; omit for current page overview/selection.",
                        "example": ["12:34"],
                    }
                },
                core=True,
                write=True,
            ),
            _op(
                "create_figma_design",
                "create_design",
                "Create editable native Figma nodes in the paired browser canvas. Provide one root FRAME with nested FRAME, RECTANGLE and TEXT nodes. Validate setup with get_figma_canvas_status. Reports created ids and partial writes; never blindly retry a timeout.",
                "canvas",
                {
                    "design": {
                        "type": "object",
                        "description": "Required tree: type, name, x/y, width/height, fill (#RRGGBB), corner_radius, children. TEXT: text, font_size (Inter, 1–512), font_weight (100–900 steps of 100). FRAME: layout NONE/HORIZONTAL/VERTICAL, padding, gap. Max 100 nodes, 8 levels, 128 KiB. Coordinates are parent-local. Root must be FRAME.",
                        "example": {
                            "type": "FRAME",
                            "name": "Landing page",
                            "width": 1200,
                            "height": 800,
                            "fill": "#FFFFFF",
                            "children": [
                                {
                                    "type": "TEXT",
                                    "text": "Hello",
                                    "x": 40,
                                    "y": 40,
                                    "font_size": 48,
                                }
                            ],
                        },
                    }
                },
                core=True,
                write=True,
                destructive=True,
            ),
            _op(
                "update_figma_canvas_node",
                "update_canvas_node",
                "Update an existing native canvas node. Read the node first. Properties: name, x/y (both required together), width/height (both required together), fill (#RRGGBB), corner_radius, text (TEXT only). Partial updates are reported and never replayed automatically.",
                "canvas",
                {
                    "node_id": _s("Required canvas node id."),
                    "properties": {
                        "type": "object",
                        "description": "Required non-empty object of supported properties.",
                        "example": {"text": "Updated heading", "fill": "#2563EB"},
                    },
                },
                write=True,
                destructive=True,
            ),
            _op(
                "delete_figma_canvas_node",
                "delete_canvas_node",
                "Delete an explicitly identified canvas node and its children in the paired document. Read first; pages/documents cannot be deleted. Uses the host mutation replay guard.",
                "canvas",
                {"node_id": _s("Required canvas node id selected for deletion.")},
                write=True,
                destructive=True,
            ),
            _op(
                "stop_figma_canvas",
                "stop_canvas",
                "Disconnect this account's plugin session. Stop the local bridge when no account sessions remain.",
                "canvas",
                {},
                write=True,
            ),
            _op(
                "get_figma_canvas_capabilities",
                "canvas_capabilities",
                "Discover supported live plugin read/edit commands and their exact parameter schemas before advanced canvas work.",
                "canvas",
                {},
                core=True,
            ),
            _op(
                "read_figma_canvas_details",
                "canvas_details",
                "Inspect live styles, local components, selected design, text nodes, annotations, instance overrides or prototype reactions. Get command schemas from get_figma_canvas_capabilities. Results report truncation.",
                "canvas",
                {
                    "command": _s(
                        "Required read command from get_figma_canvas_capabilities."
                    ),
                    "params": {
                        "type": "object",
                        "description": "Optional upstream camelCase parameters; defaults to an empty object.",
                    },
                },
                write=True,
            ),
            _op(
                "edit_figma_canvas",
                "edit_canvas",
                "Apply 1–30 validated native canvas actions: creation, cloning, reparenting, layout, styling, text, component instances/overrides, annotations and selection. Discover exact command schemas first. Returns partial progress on error; never blindly retry a write.",
                "canvas",
                {
                    "actions": {
                        "type": "array",
                        "description": "Required ordered actions with command, params, optional as alias on creation/clone. Later node-id fields can use $alias. Max 30 actions/128 KiB. No scripts or delete commands.",
                        "example": [
                            {
                                "command": "clone_node",
                                "params": {"nodeId": "12:34", "x": 700, "y": 0},
                                "as": "copy",
                            },
                            {
                                "command": "set_stroke_color",
                                "params": {
                                    "nodeId": "$copy",
                                    "color": {"r": 0, "g": 0, "b": 1},
                                    "weight": 2,
                                },
                            },
                        ],
                    }
                },
                core=True,
                write=True,
                destructive=True,
            ),
            _op(
                "set_figma_canvas_image",
                "set_canvas_image",
                "Apply an existing local PNG/JPG/GIF/WebP file as an image fill on a canvas node. Transfers image bytes to the paired plugin only; max 5 MiB. Does not fetch remote URLs.",
                "canvas",
                {
                    "node_id": _s("Required canvas node id."),
                    "image_path": _s("Required absolute local image path."),
                    "scale_mode": _s("FILL (default), FIT, CROP or TILE.", "FILL"),
                },
                write=True,
                destructive=True,
            ),
            _op(
                "export_figma_canvas_image",
                "export_canvas_image",
                "Export an unsaved live canvas node as PNG to a unique local file. Requires an absolute output directory; max 5 MiB. Use REST export for JPG/SVG/PDF after file synchronization.",
                "canvas",
                {
                    "node_id": _s("Required canvas node id."),
                    "output_dir": _s("Required absolute local output directory."),
                    "scale": SCALE,
                },
                write=True,
            ),
        ]
    )
    return ops


# Canvas writes use the published plugin protocol, not the REST API.
# Intentionally excluded:
# variables and library analytics (Enterprise), webhooks (need public receiver),
# organization/admin logs, AI metering, billing, deprecated project endpoints.
