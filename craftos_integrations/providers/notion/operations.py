"""Notion operations — ported from the legacy notion_actions.py schemas.

NOTE: no operation declares an ``account`` input — the host adapter
injects it on every generated action and the core resolves it centrally
(conformance-enforced).

Complete port of app/data/action/integrations/notion/notion_actions.py.
The lean/include_metadata shaping (search results, page properties,
database schema/rows, block content) is reproduced verbatim so agents
see identical result dicts.

Destructive flags: Notion archive/trash is reversible (restore_* /
un-trash), so ported operations stay destructive=False — except
delete_notion_block, whose name trips the conformance destructive-verb
gate; it is flagged so hosts confirm before trashing blocks on an
ambiguous multi-account request.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional

from ...contracts import Operation
from .._shared import client_op

STATUS_OUTPUT = {"status": {"type": "string", "example": "success"}}


# ------------------------------------------------------------------
# Shared shaping helpers (verbatim from the legacy action bodies)
# ------------------------------------------------------------------


def _plain(rt) -> str:
    return "".join(x.get("plain_text", "") for x in (rt or []) if isinstance(x, dict))


def _prop_value(p):
    if not isinstance(p, dict):
        return p
    t = p.get("type")
    v = p.get(t)
    if t in ("title", "rich_text"):
        return _plain(v)
    if t in ("select", "status"):
        return (v or {}).get("name")
    if t == "multi_select":
        return [o.get("name") for o in (v or []) if isinstance(o, dict)]
    if t == "date":
        return (
            {"start": v.get("start"), "end": v.get("end")}
            if isinstance(v, dict)
            else None
        )
    if t == "people":
        return [u.get("name") or u.get("id") for u in (v or []) if isinstance(u, dict)]
    if t == "relation":
        return [r.get("id") for r in (v or []) if isinstance(r, dict)]
    if t in ("formula", "rollup"):
        inner = (v or {}).get("type")
        return (v or {}).get(inner)
    if t in ("created_by", "last_edited_by"):
        return (v or {}).get("name") or (v or {}).get("id")
    if t == "files":
        return [f.get("name") for f in (v or []) if isinstance(f, dict)]
    return v


def _pick(res: Dict[str, Any], keys) -> Dict[str, Any]:
    """Port of the legacy ``pick_result`` helper."""
    if res.get("status") == "success" and isinstance(res.get("result"), dict):
        r = res["result"]
        picked = {k: r.get(k) for k in keys if r.get(k) is not None}
        if picked:
            res = {**res, "result": picked}
    return res


def _shaped(
    base: Operation,
    shaper: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
) -> Operation:
    """Wrap an operation's fn with a post-shaper (mirrors the legacy
    action bodies that post-processed run_client_sync results)."""
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return shaper(await inner(client, input_data), input_data)

    return replace(base, fn=fn)


def _picked(base: Operation, keys) -> Operation:
    return _shaped(base, lambda res, _d: _pick(res, keys))


# ------------------------------------------------------------------
# Search (workspace-wide)
# ------------------------------------------------------------------


def _search_notion_op() -> Operation:
    base = client_op(
        "search_notion",
        "search",
        description=(
            "Search Notion workspace for pages and databases. Lean results "
            "({id, object, title, url}) by default; include_metadata=true "
            "returns the full raw objects (properties, timestamps, parents, ...)."
        ),
        tags=("notion",),
        input_schema={
            "query": {
                "type": "string",
                "description": "Search query.",
                "example": "meeting notes",
            },
            "filter_type": {
                "type": "string",
                "description": "Optional: 'page' or 'database'.",
                "example": "page",
            },
            "include_metadata": {
                "type": "boolean",
                "description": (
                    "False (default): lean {id, object, title, url} per result. "
                    "True: full raw."
                ),
                "example": False,
            },
        },
        arg_map=lambda d: {
            "query": d["query"],
            "filter_type": d.get("filter_type"),
        },
    )

    def shaper(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        if input_data.get("include_metadata") or res.get("status") != "success":
            return res
        items = res.get("result")
        if not isinstance(items, list):
            return res
        lean = []
        for it in items:
            if not isinstance(it, dict) or "error" in it:
                lean.append(it)
                continue
            if isinstance(it.get("title"), list):  # database object
                title = _plain(it["title"])
            else:  # page object — title lives in the title-type property
                title = ""
                for p in (it.get("properties") or {}).values():
                    if isinstance(p, dict) and p.get("type") == "title":
                        title = _plain(p.get("title"))
                        break
            lean.append(
                {
                    "id": it.get("id"),
                    "object": it.get("object"),
                    "title": title,
                    "url": it.get("url"),
                }
            )
        return {**res, "result": lean}

    return _shaped(base, shaper)


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------


def _get_notion_page_op() -> Operation:
    base = client_op(
        "get_notion_page",
        "get_page",
        description=(
            "Get a Notion page by ID (returns metadata + properties, not block "
            "content). Lean {id, url, archived, properties: {name: plain value}} "
            "by default; include_metadata=true returns the full raw page object."
        ),
        tags=("notion_pages", "notion"),
        input_schema={
            "page_id": {
                "type": "string",
                "description": "Notion page ID.",
                "example": "abc123",
            },
            "include_metadata": {
                "type": "boolean",
                "description": (
                    "False (default): lean page with plain property values. "
                    "True: full raw."
                ),
                "example": False,
            },
        },
        arg_map=lambda d: {"page_id": d["page_id"]},
    )

    def shaper(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        if input_data.get("include_metadata") or res.get("status") != "success":
            return res
        body = res.get("result")
        if not isinstance(body, dict):
            return res
        lean = {
            "id": body.get("id"),
            "url": body.get("url"),
            "archived": body.get("archived"),
            "properties": {
                name: _prop_value(p)
                for name, p in (body.get("properties") or {}).items()
            },
        }
        return {**res, "result": lean}

    return _shaped(base, shaper)


def _page_ops() -> List[Operation]:
    return [
        _get_notion_page_op(),
        _picked(
            client_op(
                "create_notion_page",
                "create_page",
                description="Create a new page in Notion.",
                tags=("notion_pages", "notion"),
                parallelizable=False,
                input_schema={
                    "parent_id": {
                        "type": "string",
                        "description": "Parent page or database ID.",
                        "example": "abc123",
                    },
                    "parent_type": {
                        "type": "string",
                        "description": "'page_id' or 'database_id'.",
                        "example": "page_id",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Page properties.",
                        "example": {"title": [{"text": {"content": "New Page"}}]},
                    },
                    "children": {
                        "type": "array",
                        "description": "Optional content blocks.",
                        "example": [],
                    },
                },
                output_schema={
                    **STATUS_OUTPUT,
                    "result": {
                        "type": "object",
                        "description": "{id, url} of the new page.",
                    },
                },
                arg_map=lambda d: {
                    "parent_id": d["parent_id"],
                    "parent_type": d["parent_type"],
                    "properties": d["properties"],
                    "children": d.get("children"),
                },
            ),
            ["id", "url"],
        ),
        _picked(
            client_op(
                "update_notion_page",
                "update_page",
                description="Update a Notion page's properties (and/or archive state).",
                tags=("notion_pages", "notion"),
                parallelizable=False,
                input_schema={
                    "page_id": {
                        "type": "string",
                        "description": "Page ID to update.",
                        "example": "abc123",
                    },
                    "properties": {
                        "type": "object",
                        "description": "Properties to update.",
                        "example": {},
                    },
                },
                output_schema={
                    **STATUS_OUTPUT,
                    "result": {
                        "type": "object",
                        "description": "{id, url} of the updated page.",
                    },
                },
            ),
            ["id", "url"],
        ),
        client_op(
            "archive_notion_page",
            "archive_page",
            description=(
                "Archive a Notion page (send to trash). Reversible via "
                "restore_notion_page."
            ),
            tags=("notion_pages", "notion"),
            parallelizable=False,
            input_schema={
                "page_id": {"type": "string", "description": "Page ID.", "example": ""},
            },
        ),
        client_op(
            "restore_notion_page",
            "restore_page",
            description="Restore a previously-archived Notion page.",
            tags=("notion_pages",),
            parallelizable=False,
            input_schema={
                "page_id": {"type": "string", "description": "Page ID.", "example": ""},
            },
        ),
        client_op(
            "get_notion_page_property",
            "get_page_property",
            description=(
                "Get a single page property's value. For rollup/relation/people "
                "properties that paginate, this returns the full list."
            ),
            tags=("notion_pages",),
            input_schema={
                "page_id": {"type": "string", "description": "Page ID.", "example": ""},
                "property_id": {
                    "type": "string",
                    "description": "Property ID (from page schema).",
                    "example": "",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Pagination size.",
                    "example": 100,
                },
            },
            arg_map=lambda d: {
                "page_id": d["page_id"],
                "property_id": d["property_id"],
                "page_size": d.get("page_size", 100),
            },
        ),
    ]


# ------------------------------------------------------------------
# Databases
# ------------------------------------------------------------------


def _get_notion_database_schema_op() -> Operation:
    base = client_op(
        "get_notion_database_schema",
        "get_database",
        description=(
            "Get a Notion database schema by ID. Lean {id, title, url, "
            "properties: {name: type (+options for select/multi_select/status)}} "
            "by default; include_metadata=true returns the full raw database object."
        ),
        tags=("notion_databases", "notion"),
        input_schema={
            "database_id": {
                "type": "string",
                "description": "Database ID.",
                "example": "abc123",
            },
            "include_metadata": {
                "type": "boolean",
                "description": (
                    "False (default): lean schema (property name -> type). "
                    "True: full raw."
                ),
                "example": False,
            },
        },
        output_schema={**STATUS_OUTPUT, "database": {"type": "object"}},
        arg_map=lambda d: {"database_id": d["database_id"]},
    )

    def shaper(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        if input_data.get("include_metadata") or res.get("status") != "success":
            return res
        body = res.get("result")
        if not isinstance(body, dict):
            return res
        props: Dict[str, Any] = {}
        for name, p in (body.get("properties") or {}).items():
            if not isinstance(p, dict):
                continue
            t = p.get("type")
            if t in ("select", "multi_select", "status"):
                options = (p.get(t) or {}).get("options") or []
                props[name] = {
                    "type": t,
                    "options": [o.get("name") for o in options if isinstance(o, dict)],
                }
            else:
                props[name] = t
        lean = {
            "id": body.get("id"),
            "title": _plain(body.get("title")),
            "url": body.get("url"),
            "properties": props,
        }
        return {**res, "result": lean}

    return _shaped(base, shaper)


def _query_notion_database_op() -> Operation:
    base = client_op(
        "query_notion_database",
        "query_database",
        description=(
            "Query a Notion database with optional filters and sorts. Lean rows "
            "({id, url, properties: {name: plain value}}) by default; "
            "include_metadata=true returns the full raw page objects."
        ),
        tags=("notion_databases", "notion"),
        input_schema={
            "database_id": {
                "type": "string",
                "description": "Database ID.",
                "example": "abc123",
            },
            "filter": {
                "type": "object",
                "description": "Optional Notion filter object.",
                "example": {},
            },
            "sorts": {
                "type": "array",
                "description": "Optional sort array.",
                "example": [],
            },
            "include_metadata": {
                "type": "boolean",
                "description": (
                    "False (default): lean rows with plain property values. "
                    "True: full raw."
                ),
                "example": False,
            },
        },
        arg_map=lambda d: {
            "database_id": d["database_id"],
            "filter_obj": d.get("filter"),
            "sorts": d.get("sorts"),
        },
    )

    def shaper(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        if input_data.get("include_metadata") or res.get("status") != "success":
            return res
        body = res.get("result")
        if not isinstance(body, dict):
            return res
        lean = {
            "results": [
                {
                    "id": row.get("id"),
                    "url": row.get("url"),
                    "properties": {
                        name: _prop_value(p)
                        for name, p in (row.get("properties") or {}).items()
                    },
                }
                for row in body.get("results", []) or []
                if isinstance(row, dict)
            ],
            "has_more": body.get("has_more"),
            "next_cursor": body.get("next_cursor"),
        }
        return {**res, "result": lean}

    return _shaped(base, shaper)


def _database_ops() -> List[Operation]:
    return [
        _get_notion_database_schema_op(),
        _query_notion_database_op(),
        _picked(
            client_op(
                "create_notion_database",
                "create_database",
                description=(
                    "Create a new database under a parent page. Schema goes in "
                    "'properties' (each value is a property type config like "
                    "{'title': {}} / {'rich_text': {}} / {'select': {'options': "
                    "[...]}})."
                ),
                tags=("notion_databases", "notion"),
                parallelizable=False,
                input_schema={
                    "parent_page_id": {
                        "type": "string",
                        "description": "Parent page ID.",
                        "example": "",
                    },
                    "title": {
                        "type": "array",
                        "description": "Title rich_text array.",
                        "example": [{"text": {"content": "Tasks"}}],
                    },
                    "description": {
                        "type": "array",
                        "description": "Description rich_text array (optional).",
                        "example": [],
                    },
                    "properties": {
                        "type": "object",
                        "description": "Property schema (column definitions). Required.",
                        "example": {"Name": {"title": {}}},
                    },
                    "is_inline": {
                        "type": "boolean",
                        "description": "Render inline.",
                        "example": False,
                    },
                    "icon": {
                        "type": "object",
                        "description": "Icon (optional). e.g. {'type':'emoji','emoji':'📋'}.",
                        "example": {},
                    },
                    "cover": {
                        "type": "object",
                        "description": "Cover (optional).",
                        "example": {},
                    },
                },
                output_schema={
                    **STATUS_OUTPUT,
                    "result": {
                        "type": "object",
                        "description": "{id, url} of the new database.",
                    },
                },
                arg_map=lambda d: {
                    "parent_page_id": d["parent_page_id"],
                    "title": d.get("title"),
                    "description": d.get("description"),
                    "properties": d.get("properties"),
                    "is_inline": bool(d.get("is_inline", False)),
                    "icon": d.get("icon") or None,
                    "cover": d.get("cover") or None,
                },
            ),
            ["id", "url"],
        ),
        _picked(
            client_op(
                "update_notion_database",
                "update_database",
                description=(
                    "Update a Notion database (title, description, schema, "
                    "inline state)."
                ),
                tags=("notion_databases", "notion"),
                parallelizable=False,
                input_schema={
                    "database_id": {
                        "type": "string",
                        "description": "Database ID.",
                        "example": "",
                    },
                    "title": {
                        "type": "array",
                        "description": "New title rich_text (optional).",
                        "example": [],
                    },
                    "description": {
                        "type": "array",
                        "description": "New description rich_text (optional).",
                        "example": [],
                    },
                    "properties": {
                        "type": "object",
                        "description": (
                            "Property updates (rename / change type / remove "
                            "with null) (optional)."
                        ),
                        "example": {},
                    },
                    "is_inline": {
                        "type": "boolean",
                        "description": "Set inline (optional).",
                        "example": False,
                    },
                },
                output_schema={
                    **STATUS_OUTPUT,
                    "result": {
                        "type": "object",
                        "description": "{id, url} of the updated database.",
                    },
                },
                arg_map=lambda d: {
                    "database_id": d["database_id"],
                    "title": d.get("title"),
                    "description": d.get("description"),
                    "properties": d.get("properties"),
                    "is_inline": d["is_inline"] if "is_inline" in d else None,
                },
            ),
            ["id", "url"],
        ),
        client_op(
            "archive_notion_database",
            "archive_database",
            description="Archive a Notion database.",
            tags=("notion_databases",),
            parallelizable=False,
            input_schema={
                "database_id": {
                    "type": "string",
                    "description": "Database ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "restore_notion_database",
            "restore_database",
            description="Restore an archived Notion database.",
            tags=("notion_databases",),
            parallelizable=False,
            input_schema={
                "database_id": {
                    "type": "string",
                    "description": "Database ID.",
                    "example": "",
                },
            },
        ),
    ]


# ------------------------------------------------------------------
# Blocks
# ------------------------------------------------------------------


def _get_notion_page_content_op() -> Operation:
    base = client_op(
        "get_notion_page_content",
        "get_block_children",
        description=(
            "Get the content blocks of a Notion page (or any block that has "
            "children). By default returns SIMPLIFIED content (each block's "
            "type + plain text) to keep the output small and readable. Set "
            "include_metadata=true to get the FULL raw blocks including block "
            "IDs, timestamps and other metadata — do this when you need block "
            "IDs to update or delete specific blocks."
        ),
        tags=("notion_blocks", "notion"),
        input_schema={
            "page_id": {
                "type": "string",
                "description": "Page ID (or block ID for nested children).",
                "example": "abc123",
            },
            "include_metadata": {
                "type": "boolean",
                "description": (
                    "False (default): return only {type, text} per block — "
                    "lean, for reading. True: return the full raw blocks with "
                    "block IDs/timestamps/etc. — needed to edit or delete "
                    "specific blocks."
                ),
                "example": False,
            },
        },
        output_schema={
            **STATUS_OUTPUT,
            "content": {
                "type": "array",
                "description": (
                    "Simplified blocks [{type, text, ...}] when "
                    "include_metadata is false; full raw blocks when true."
                ),
            },
        },
        arg_map=lambda d: {"block_id": d["page_id"]},
    )

    def shaper(result: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
        if bool(input_data.get("include_metadata", False)) or (
            result.get("status") == "error"
        ):
            return result
        raw = result.get("result", {})
        blocks = raw.get("results", []) if isinstance(raw, dict) else []

        def _simplify(b: dict) -> dict:
            t = b.get("type")
            data = b.get(t) if isinstance(b.get(t), dict) else {}
            text = "".join(
                rt.get("plain_text", "")
                for rt in data.get("rich_text", [])
                if isinstance(rt, dict)
            )
            out = {"type": t, "text": text}
            if t == "to_do":
                out["checked"] = bool(data.get("checked"))
            if b.get("has_children"):
                out["has_children"] = True
            return out

        content = [_simplify(b) for b in blocks if isinstance(b, dict)]
        out: Dict[str, Any] = {"status": "success", "content": content}
        if isinstance(raw, dict) and raw.get("has_more"):
            out["has_more"] = True
            out["next_cursor"] = raw.get("next_cursor")
        return out

    return _shaped(base, shaper)


def _append_notion_page_content_op() -> Operation:
    base = client_op(
        "append_notion_page_content",
        "append_block_children",
        description=(
            "Append content blocks to a Notion page (or any block). Returns "
            "{appended: count, ids: [block ids]}."
        ),
        tags=("notion_blocks", "notion"),
        parallelizable=False,
        input_schema={
            "page_id": {
                "type": "string",
                "description": "Page ID (or block ID).",
                "example": "abc123",
            },
            "children": {
                "type": "array",
                "description": "List of block objects.",
                "example": [],
            },
        },
        output_schema={
            **STATUS_OUTPUT,
            "result": {"type": "object", "description": "{appended, ids}."},
        },
        arg_map=lambda d: {"block_id": d["page_id"], "children": d["children"]},
    )

    def shaper(res: Dict[str, Any], _input_data: Dict[str, Any]) -> Dict[str, Any]:
        if res.get("status") != "success":
            return res
        body = res.get("result")
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            return res
        ids = [b.get("id") for b in body["results"] if isinstance(b, dict)]
        return {**res, "result": {"appended": len(ids), "ids": ids}}

    return _shaped(base, shaper)


def _block_ops() -> List[Operation]:
    return [
        _get_notion_page_content_op(),
        _append_notion_page_content_op(),
        client_op(
            "get_notion_block",
            "get_block",
            description="Get a single block (not its children) by block ID.",
            tags=("notion_blocks", "notion"),
            input_schema={
                "block_id": {
                    "type": "string",
                    "description": "Block ID.",
                    "example": "",
                },
            },
        ),
        _picked(
            client_op(
                "update_notion_block",
                "update_block",
                description=(
                    "Update a block's content. block_update has the "
                    "per-block-type key as the top-level field, e.g. {'to_do': "
                    "{'rich_text': [...], 'checked': true}} for a to-do, "
                    "{'paragraph': {'rich_text': [...]}} for a paragraph. Pass "
                    "{'in_trash': true} to soft-delete."
                ),
                tags=("notion_blocks", "notion"),
                parallelizable=False,
                input_schema={
                    "block_id": {
                        "type": "string",
                        "description": "Block ID.",
                        "example": "",
                    },
                    "block_update": {
                        "type": "object",
                        "description": "Per-block-type update object.",
                        "example": {
                            "paragraph": {
                                "rich_text": [{"text": {"content": "Updated"}}]
                            }
                        },
                    },
                },
                output_schema={
                    **STATUS_OUTPUT,
                    "result": {
                        "type": "object",
                        "description": "{id} of the updated block.",
                    },
                },
            ),
            ["id"],
        ),
        client_op(
            "delete_notion_block",
            "delete_block",
            description="Delete (soft delete, send to trash) a Notion block.",
            tags=("notion_blocks", "notion"),
            # Reversible (trash), but the "delete" verb trips the conformance
            # destructive-name gate — flagged so hosts confirm-or-clarify.
            destructive=True,
            parallelizable=False,
            input_schema={
                "block_id": {
                    "type": "string",
                    "description": "Block ID.",
                    "example": "",
                },
            },
        ),
    ]


# ------------------------------------------------------------------
# Comments / Users
# ------------------------------------------------------------------


def _comment_and_user_ops() -> List[Operation]:
    return [
        client_op(
            "list_notion_comments",
            "list_comments",
            description="List comments on a page or block.",
            tags=("notion_comments", "notion"),
            input_schema={
                "block_id": {
                    "type": "string",
                    "description": "Block or page ID.",
                    "example": "",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 100,
                },
                "start_cursor": {
                    "type": "string",
                    "description": "Pagination cursor (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "block_id": d["block_id"],
                "page_size": d.get("page_size", 100),
                "start_cursor": d.get("start_cursor") or None,
            },
        ),
        client_op(
            "create_notion_comment",
            "create_comment",
            description=(
                "Post a comment on a page/block, or reply in a discussion. "
                "Provide exactly one of parent_page_id, parent_block_id, or "
                "discussion_id."
            ),
            tags=("notion_comments", "notion"),
            parallelizable=False,
            input_schema={
                "rich_text": {
                    "type": "array",
                    "description": "Comment content as rich_text array.",
                    "example": [{"text": {"content": "Looks good!"}}],
                },
                "parent_page_id": {
                    "type": "string",
                    "description": "Page ID for a new top-level discussion (optional).",
                    "example": "",
                },
                "parent_block_id": {
                    "type": "string",
                    "description": "Block ID for a new top-level discussion (optional).",
                    "example": "",
                },
                "discussion_id": {
                    "type": "string",
                    "description": "Discussion ID to reply to (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "rich_text": d["rich_text"],
                "parent_page_id": d.get("parent_page_id") or None,
                "parent_block_id": d.get("parent_block_id") or None,
                "discussion_id": d.get("discussion_id") or None,
            },
        ),
        client_op(
            "list_notion_users",
            "list_users",
            description="List workspace members visible to the integration.",
            tags=("notion_users", "notion"),
            input_schema={
                "page_size": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 100,
                },
                "start_cursor": {
                    "type": "string",
                    "description": "Pagination cursor (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "page_size": d.get("page_size", 100),
                "start_cursor": d.get("start_cursor") or None,
            },
        ),
        client_op(
            "get_notion_user",
            "get_user",
            description="Get a single Notion user by ID.",
            tags=("notion_users", "notion"),
            input_schema={
                "user_id": {"type": "string", "description": "User ID.", "example": ""},
            },
        ),
        client_op(
            "get_notion_bot_info",
            "get_bot_info",
            description=(
                "Get info about the authenticated Notion bot (workspace_name, "
                "owner, capabilities)."
            ),
            tags=("notion_users", "notion"),
            input_schema={},
        ),
    ]


# ------------------------------------------------------------------
# File uploads
# ------------------------------------------------------------------


def _file_upload_ops() -> List[Operation]:
    return [
        client_op(
            "upload_notion_file",
            "upload_local_file",
            description=(
                "High-level: upload a local file in one call (single-part). "
                "Returns the file_upload object with id+status='uploaded'. "
                "Attach to a block via {'type':'file_upload','file_upload':"
                "{'id': <id>}}. Use multi-part flow for files >20 MB."
            ),
            tags=("notion_files", "notion"),
            parallelizable=False,
            input_schema={
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to local file.",
                    "example": "C:/Users/me/report.pdf",
                },
                "content_type": {
                    "type": "string",
                    "description": "MIME type (autodetect if omitted).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "file_path": d["file_path"],
                "content_type": d.get("content_type") or None,
            },
        ),
        client_op(
            "create_notion_file_upload",
            "create_file_upload",
            description=(
                "Step 1 of file upload: initialise a file_upload resource. "
                "Returns id + upload_url. Use mode=single_part for <20 MB, "
                "multi_part for larger, or external_url to import from a URL."
            ),
            tags=("notion_files",),
            parallelizable=False,
            input_schema={
                "mode": {
                    "type": "string",
                    "description": "single_part | multi_part | external_url.",
                    "example": "single_part",
                },
                "filename": {
                    "type": "string",
                    "description": "Required for multi_part.",
                    "example": "",
                },
                "content_type": {
                    "type": "string",
                    "description": "MIME type (recommended).",
                    "example": "",
                },
                "number_of_parts": {
                    "type": "integer",
                    "description": "Required for multi_part.",
                    "example": 0,
                },
                "external_url": {
                    "type": "string",
                    "description": "Required for external_url mode.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "mode": d.get("mode", "single_part"),
                "filename": d.get("filename") or None,
                "content_type": d.get("content_type") or None,
                "number_of_parts": d.get("number_of_parts") or None,
                "external_url": d.get("external_url") or None,
            },
        ),
        client_op(
            "send_notion_file_upload",
            "send_file_upload",
            description=(
                "Step 2: send file bytes to a pending file_upload. For "
                "multi_part uploads, repeat with each part_number."
            ),
            tags=("notion_files",),
            parallelizable=False,
            input_schema={
                "file_upload_id": {
                    "type": "string",
                    "description": "ID from create_notion_file_upload.",
                    "example": "",
                },
                "file_path": {
                    "type": "string",
                    "description": (
                        "Absolute path to local file (or one part for multi_part)."
                    ),
                    "example": "",
                },
                "part_number": {
                    "type": "integer",
                    "description": "1..1000, only for multi_part.",
                    "example": 0,
                },
            },
            arg_map=lambda d: {
                "file_upload_id": d["file_upload_id"],
                "file_path": d["file_path"],
                "part_number": d.get("part_number") or None,
            },
        ),
        client_op(
            "complete_notion_file_upload",
            "complete_file_upload",
            description=(
                "Step 3 (multi_part only): finalize a multi-part upload after "
                "all parts sent."
            ),
            tags=("notion_files",),
            parallelizable=False,
            input_schema={
                "file_upload_id": {
                    "type": "string",
                    "description": "File upload ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "get_notion_file_upload",
            "get_file_upload",
            description="Get the current status of a file upload.",
            tags=("notion_files",),
            input_schema={
                "file_upload_id": {
                    "type": "string",
                    "description": "File upload ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "list_notion_file_uploads",
            "list_file_uploads",
            description=(
                "List file uploads created by this integration. Filter by "
                "status (pending|uploaded|expired|failed)."
            ),
            tags=("notion_files",),
            input_schema={
                "status": {
                    "type": "string",
                    "description": "Filter (optional).",
                    "example": "",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 100,
                },
                "start_cursor": {
                    "type": "string",
                    "description": "Pagination cursor (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "status": d.get("status") or None,
                "page_size": d.get("page_size", 100),
                "start_cursor": d.get("start_cursor") or None,
            },
        ),
    ]


def build_operations() -> List[Operation]:
    return [
        _search_notion_op(),
        *_page_ops(),
        *_database_ops(),
        *_block_ops(),
        *_comment_and_user_ops(),
        *_file_upload_ops(),
    ]
