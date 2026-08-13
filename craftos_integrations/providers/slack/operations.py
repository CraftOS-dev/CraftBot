"""Slack operations — ported from the legacy slack_actions.py schemas.

Complete port of app/data/action/integrations/slack/slack_actions.py —
all 60 actions, same names/descriptions/schemas/arg mapping. No operation
declares an ``account`` input (conformance-enforced; the host injects it).

Porting notes:
- Legacy ``irreversible=True`` (send_slack_message, send_slack_ephemeral)
  → ``destructive=True``; permanent deletes/removes are also flagged
  destructive per the conformance rule (delete/remove-named operations).
- Legacy actions used ``run_client``'s default envelope handling; the
  Slack client returns either the raw Slack body (with ``ok`` alongside
  payload fields — collapsed by ``shape_result``) or ``{error, details}``
  — so ``client_op`` defaults match legacy behavior exactly.
- ``pick_result`` / lean-shaping post-processing is reproduced verbatim
  via fn-wrapping (same pattern as gmail's lean operations).

The legacy file's "intentionally NOT exposed" list carries over
unchanged: Events API/RTM/Socket Mode plumbing, views.*/interactions.*,
canvases/lists, admin.*/scim, dnd.*, deprecated surfaces (stars,
dialog.*, chat.unfurl) were never actions and stay out.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List

from ...contracts import Operation
from .._shared import client_op

_STATUS = {"status": {"type": "string", "example": "success"}}


# ────────────────────────────────────────────────────────────────────────
# Post-processing helpers (legacy pick_result / lean shaping, verbatim)
# ────────────────────────────────────────────────────────────────────────


def _with_post(
    base: Operation,
    post: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
) -> Operation:
    """Wrap an operation's fn with a (result, input_data) post-processor."""
    inner = base.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return post(await inner(client, input_data), input_data)

    return replace(base, fn=fn)


def _pick(keys: List[str]):
    """Legacy ``pick_result``: reduce a successful result to named keys."""

    def post(res: Dict[str, Any], _input: Dict[str, Any]) -> Dict[str, Any]:
        if res.get("status") == "success" and isinstance(res.get("result"), dict):
            r = res["result"]
            picked = {k: r.get(k) for k in keys if r.get(k) is not None}
            if picked:
                res = {**res, "result": picked}
        return res

    return post


def _lean_message(m: dict) -> dict:
    out = {"user": m.get("user"), "text": m.get("text"), "ts": m.get("ts")}
    if m.get("thread_ts"):
        out["thread_ts"] = m["thread_ts"]
    if m.get("reply_count") is not None:
        out["reply_count"] = m["reply_count"]
    if m.get("subtype"):
        out["subtype"] = m["subtype"]
    if m.get("reactions"):
        out["reactions"] = [
            {"name": r.get("name"), "count": r.get("count")}
            for r in m["reactions"]
            if isinstance(r, dict)
        ]
    return out


def _lean_messages(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    body = res.get("result")
    if not isinstance(body, dict):
        return res
    lean = {
        "messages": [
            _lean_message(m)
            for m in body.get("messages", []) or []
            if isinstance(m, dict)
        ]
    }
    if body.get("has_more"):
        lean["has_more"] = True
    return {**res, "result": lean}


def _lean_channels(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    body = res.get("result")
    if not isinstance(body, dict):
        return res

    def _lean(c: dict) -> dict:
        out = {
            "id": c.get("id"),
            "name": c.get("name"),
            "is_private": c.get("is_private"),
            "is_archived": c.get("is_archived"),
            "num_members": c.get("num_members"),
            "topic": (c.get("topic") or {}).get("value"),
            "purpose": (c.get("purpose") or {}).get("value"),
        }
        if "is_member" in c:
            out["is_member"] = c.get("is_member")
        return out

    lean = {
        "channels": [
            _lean(c) for c in body.get("channels", []) or [] if isinstance(c, dict)
        ]
    }
    cursor = (body.get("response_metadata") or {}).get("next_cursor")
    if cursor:
        lean["next_cursor"] = cursor
    return {**res, "result": lean}


def _lean_users(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    body = res.get("result")
    if not isinstance(body, dict):
        return res

    def _lean(m: dict) -> dict:
        profile = m.get("profile") or {}
        out = {
            "id": m.get("id"),
            "name": m.get("name"),
            "real_name": m.get("real_name") or profile.get("real_name"),
            "display_name": profile.get("display_name"),
            "email": profile.get("email"),
            "is_bot": m.get("is_bot"),
            "tz": m.get("tz"),
            "deleted": m.get("deleted"),
        }
        if "is_admin" in m:
            out["is_admin"] = m.get("is_admin")
        return out

    lean = {
        "members": [
            _lean(m) for m in body.get("members", []) or [] if isinstance(m, dict)
        ]
    }
    cursor = (body.get("response_metadata") or {}).get("next_cursor")
    if cursor:
        lean["next_cursor"] = cursor
    return {**res, "result": lean}


def _lean_files(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    body = res.get("result")
    if not isinstance(body, dict):
        return res
    lean = {
        "files": [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "title": f.get("title"),
                "mimetype": f.get("mimetype"),
                "size": f.get("size"),
                "created": f.get("created"),
                "user": f.get("user"),
                "permalink": f.get("permalink"),
            }
            for f in body.get("files", []) or []
            if isinstance(f, dict)
        ]
    }
    if isinstance(body.get("paging"), dict):
        lean["paging"] = body["paging"]
    return {**res, "result": lean}


def _lean_search(res: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    if input_data.get("include_metadata") or res.get("status") != "success":
        return res
    body = res.get("result")
    if not isinstance(body, dict) or not isinstance(body.get("messages"), dict):
        return res
    msgs = body["messages"]

    def _lean(m: dict) -> dict:
        ch = m.get("channel") or {}
        out = {
            "user": m.get("user"),
            "text": m.get("text"),
            "ts": m.get("ts"),
            "channel": {"id": ch.get("id"), "name": ch.get("name")},
            "permalink": m.get("permalink"),
        }
        if m.get("thread_ts"):
            out["thread_ts"] = m["thread_ts"]
        return out

    lean = {
        "total": msgs.get("total"),
        "matches": [
            _lean(m) for m in msgs.get("matches", []) or [] if isinstance(m, dict)
        ],
    }
    return {**res, "result": lean}


# ────────────────────────────────────────────────────────────────────────
# Operations
# ────────────────────────────────────────────────────────────────────────


def build_operations() -> List[Operation]:
    return [
        # ── Messages — post / update / delete / ephemeral / schedule /
        #    permalink / threads ──────────────────────────────────────────
        _with_post(
            client_op(
                "send_slack_message",
                "send_message",
                description=(
                    "Send a message to a Slack channel or DM. Pass thread_ts "
                    "to reply in a thread."
                ),
                destructive=True,  # legacy irreversible — outward-facing send
                parallelizable=False,
                tags=("slack_messages", "slack"),
                input_schema={
                    "channel": {
                        "type": "string",
                        "description": "Channel ID or name.",
                        "example": "C01234567",
                    },
                    "text": {
                        "type": "string",
                        "description": "Message text.",
                        "example": "Hello team!",
                    },
                    "thread_ts": {
                        "type": "string",
                        "description": "Optional thread timestamp for replies.",
                        "example": "",
                    },
                },
                output_schema={
                    **_STATUS,
                    "result": {
                        "type": "object",
                        "description": "{channel, ts} of the posted message.",
                    },
                },
                arg_map=lambda d: {
                    "recipient": d["channel"],
                    "text": d["text"],
                    "thread_ts": d.get("thread_ts"),
                },
            ),
            _pick(["channel", "ts"]),
        ),
        _with_post(
            client_op(
                "update_slack_message",
                "update_message",
                description=(
                    "Edit a previously-sent Slack message. ts is the "
                    "timestamp returned when posting."
                ),
                parallelizable=False,
                tags=("slack_messages", "slack"),
                input_schema={
                    "channel": {
                        "type": "string",
                        "description": "Channel ID.",
                        "example": "C01234567",
                    },
                    "ts": {
                        "type": "string",
                        "description": "Timestamp of the message to edit.",
                        "example": "1234567890.123456",
                    },
                    "text": {
                        "type": "string",
                        "description": "New text (optional).",
                        "example": "",
                    },
                    "blocks": {
                        "type": "array",
                        "description": "New Block Kit blocks (optional).",
                        "example": [],
                    },
                },
                output_schema={
                    **_STATUS,
                    "result": {
                        "type": "object",
                        "description": "{channel, ts} of the edited message.",
                    },
                },
                arg_map=lambda d: {
                    "channel": d["channel"],
                    "ts": d["ts"],
                    "text": d["text"] if "text" in d else None,
                    "blocks": d["blocks"] if "blocks" in d else None,
                },
            ),
            _pick(["channel", "ts"]),
        ),
        client_op(
            "delete_slack_message",
            "delete_message",
            description="Delete a Slack message.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("slack_messages", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "C01234567",
                },
                "ts": {
                    "type": "string",
                    "description": "Message timestamp.",
                    "example": "",
                },
            },
        ),
        _with_post(
            client_op(
                "send_slack_ephemeral",
                "post_ephemeral",
                description=(
                    "Send an ephemeral message visible only to one user in a "
                    "channel."
                ),
                destructive=True,  # legacy irreversible — outward-facing send
                parallelizable=False,
                tags=("slack_messages", "slack"),
                input_schema={
                    "channel": {
                        "type": "string",
                        "description": "Channel ID.",
                        "example": "C01234567",
                    },
                    "user": {
                        "type": "string",
                        "description": "User ID who will see the message.",
                        "example": "U12345",
                    },
                    "text": {
                        "type": "string",
                        "description": "Message text.",
                        "example": "",
                    },
                    "blocks": {
                        "type": "array",
                        "description": "Block Kit blocks (optional).",
                        "example": [],
                    },
                    "thread_ts": {
                        "type": "string",
                        "description": "Reply in a thread (optional).",
                        "example": "",
                    },
                },
                output_schema={
                    **_STATUS,
                    "result": {
                        "type": "object",
                        "description": "{message_ts} of the ephemeral message.",
                    },
                },
                arg_map=lambda d: {
                    "channel": d["channel"],
                    "user": d["user"],
                    "text": d["text"],
                    "blocks": d["blocks"] if "blocks" in d else None,
                    "thread_ts": d.get("thread_ts") or None,
                },
            ),
            _pick(["channel", "message_ts"]),
        ),
        _with_post(
            client_op(
                "schedule_slack_message",
                "schedule_message",
                description=(
                    "Schedule a Slack message to be sent at a future time. "
                    "post_at is a Unix timestamp."
                ),
                parallelizable=False,
                tags=("slack_messages", "slack"),
                input_schema={
                    "channel": {
                        "type": "string",
                        "description": "Channel ID.",
                        "example": "C01234567",
                    },
                    "post_at": {
                        "type": "integer",
                        "description": "Unix timestamp when to send.",
                        "example": 0,
                    },
                    "text": {
                        "type": "string",
                        "description": "Message text.",
                        "example": "",
                    },
                    "blocks": {
                        "type": "array",
                        "description": "Block Kit blocks (optional).",
                        "example": [],
                    },
                    "thread_ts": {
                        "type": "string",
                        "description": "Optional thread reply.",
                        "example": "",
                    },
                },
                output_schema={
                    **_STATUS,
                    "result": {
                        "type": "object",
                        "description": "{scheduled_message_id, channel, post_at}.",
                    },
                },
                arg_map=lambda d: {
                    "channel": d["channel"],
                    "post_at": d["post_at"],
                    "text": d["text"],
                    "blocks": d["blocks"] if "blocks" in d else None,
                    "thread_ts": d.get("thread_ts") or None,
                },
            ),
            _pick(["scheduled_message_id", "channel", "post_at"]),
        ),
        client_op(
            "delete_scheduled_slack_message",
            "delete_scheduled_message",
            description="Cancel a previously-scheduled Slack message.",
            destructive=True,  # cancels a pending send
            parallelizable=False,
            tags=("slack_messages",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "scheduled_message_id": {
                    "type": "string",
                    "description": (
                        "Scheduled message ID (from schedule_slack_message "
                        "response)."
                    ),
                    "example": "",
                },
            },
        ),
        client_op(
            "list_scheduled_slack_messages",
            "list_scheduled_messages",
            description="List the bot's pending scheduled messages.",
            tags=("slack_messages",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Filter to one channel (optional).",
                    "example": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 100,
                },
            },
            arg_map=lambda d: {
                "channel": d.get("channel") or None,
                "limit": d.get("limit", 100),
            },
        ),
        client_op(
            "get_slack_message_permalink",
            "get_permalink",
            description="Get a shareable permalink URL for a Slack message.",
            tags=("slack_messages", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "C01234567",
                },
                "message_ts": {
                    "type": "string",
                    "description": "Message timestamp.",
                    "example": "",
                },
            },
        ),
        _with_post(
            client_op(
                "get_slack_thread_replies",
                "get_thread_replies",
                description=(
                    "Get all messages in a Slack thread (the parent + all "
                    "replies). Lean messages (user, text, ts, thread_ts, "
                    "reply_count, reactions) by default; include_metadata=true "
                    "returns full raw messages (blocks, team, bot_profile, ...)."
                ),
                tags=("slack_messages", "slack"),
                input_schema={
                    "channel": {
                        "type": "string",
                        "description": "Channel ID.",
                        "example": "C01234567",
                    },
                    "ts": {
                        "type": "string",
                        "description": "Parent message timestamp (thread_ts).",
                        "example": "",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max messages.",
                        "example": 100,
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean messages. True: full raw.",
                        "example": False,
                    },
                },
                arg_map=lambda d: {
                    "channel": d["channel"],
                    "ts": d["ts"],
                    "limit": d.get("limit", 100),
                },
            ),
            _lean_messages,
        ),
        # ── Reactions ─────────────────────────────────────────────────────
        client_op(
            "add_slack_reaction",
            "add_reaction",
            description=(
                "Add an emoji reaction to a Slack message. name is the emoji "
                "code without colons (e.g. 'thumbsup', 'eyes')."
            ),
            parallelizable=False,
            tags=("slack_messages", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "C01234567",
                },
                "timestamp": {
                    "type": "string",
                    "description": "Message timestamp.",
                    "example": "",
                },
                "name": {
                    "type": "string",
                    "description": "Emoji name without colons.",
                    "example": "thumbsup",
                },
            },
        ),
        client_op(
            "remove_slack_reaction",
            "remove_reaction",
            description="Remove an emoji reaction from a Slack message.",
            destructive=True,  # remove-named (conformance rule)
            parallelizable=False,
            tags=("slack_messages", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "timestamp": {
                    "type": "string",
                    "description": "Message timestamp.",
                    "example": "",
                },
                "name": {
                    "type": "string",
                    "description": "Emoji name without colons.",
                    "example": "thumbsup",
                },
            },
        ),
        client_op(
            "get_slack_reactions",
            "get_reactions",
            description="Get all reactions on a Slack message.",
            tags=("slack_messages",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "timestamp": {
                    "type": "string",
                    "description": "Message timestamp.",
                    "example": "",
                },
            },
        ),
        client_op(
            "list_slack_user_reactions",
            "list_user_reactions",
            description="List messages a user has reacted to.",
            tags=("slack_messages",),
            input_schema={
                "user": {
                    "type": "string",
                    "description": "User ID (optional, defaults to auth'd user).",
                    "example": "",
                },
                "count": {
                    "type": "integer",
                    "description": "Max results.",
                    "example": 100,
                },
            },
            arg_map=lambda d: {
                "user": d.get("user") or None,
                "count": d.get("count", 100),
            },
        ),
        # ── Pins ──────────────────────────────────────────────────────────
        client_op(
            "pin_slack_message",
            "pin_message",
            description="Pin a message to a Slack channel.",
            parallelizable=False,
            tags=("slack_messages", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "timestamp": {
                    "type": "string",
                    "description": "Message timestamp.",
                    "example": "",
                },
            },
        ),
        client_op(
            "unpin_slack_message",
            "unpin_message",
            description="Unpin a message from a Slack channel.",
            parallelizable=False,
            tags=("slack_messages",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "timestamp": {
                    "type": "string",
                    "description": "Message timestamp.",
                    "example": "",
                },
            },
        ),
        client_op(
            "list_slack_pins",
            "list_pins",
            description="List pinned items in a Slack channel.",
            tags=("slack_messages",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
            },
        ),
        # ── Conversations — list/info/create/invite/open/archive/rename/
        #    topic/members ──────────────────────────────────────────────────
        _with_post(
            client_op(
                "list_slack_channels",
                "list_channels",
                description=(
                    "List channels in the Slack workspace. Lean channels (id, "
                    "name, is_private, is_archived, is_member, num_members, "
                    "topic, purpose) by default; include_metadata=true returns "
                    "full raw channel objects."
                ),
                tags=("slack_conversations", "slack"),
                input_schema={
                    "limit": {
                        "type": "integer",
                        "description": "Max channels to return.",
                        "example": 100,
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean channels. True: full raw.",
                        "example": False,
                    },
                },
                output_schema={
                    **_STATUS,
                    "channels": {"type": "array"},
                },
                arg_map=lambda d: {"limit": d.get("limit", 100)},
            ),
            _lean_channels,
        ),
        client_op(
            "get_slack_channel_info",
            "get_channel_info",
            description="Get info about a Slack channel.",
            tags=("slack_conversations", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "C1234567",
                },
            },
        ),
        _with_post(
            client_op(
                "get_slack_channel_history",
                "get_channel_history",
                description=(
                    "Get message history from a Slack channel. Lean messages "
                    "(user, text, ts, thread_ts, reply_count, reactions) by "
                    "default; include_metadata=true returns full raw messages "
                    "(blocks, team, bot_profile, ...)."
                ),
                tags=("slack_conversations", "slack"),
                input_schema={
                    "channel": {
                        "type": "string",
                        "description": "Channel ID.",
                        "example": "C01234567",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max messages.",
                        "example": 50,
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean messages. True: full raw.",
                        "example": False,
                    },
                },
                output_schema={
                    **_STATUS,
                    "messages": {"type": "array"},
                },
                arg_map=lambda d: {
                    "channel": d["channel"],
                    "limit": d.get("limit", 50),
                },
            ),
            _lean_messages,
        ),
        client_op(
            "list_slack_channel_members",
            "list_channel_members",
            description="List members of a Slack channel.",
            tags=("slack_conversations", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max members.",
                    "example": 100,
                },
                "cursor": {
                    "type": "string",
                    "description": "Pagination cursor.",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "channel": d["channel"],
                "limit": d.get("limit", 100),
                "cursor": d.get("cursor") or None,
            },
        ),
        client_op(
            "create_slack_channel",
            "create_channel",
            description="Create a new Slack channel.",
            parallelizable=False,
            tags=("slack_conversations", "slack"),
            input_schema={
                "name": {
                    "type": "string",
                    "description": "Channel name.",
                    "example": "project-alpha",
                },
                "is_private": {
                    "type": "boolean",
                    "description": "Is private?",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "name": d["name"],
                "is_private": d.get("is_private", False),
            },
        ),
        client_op(
            "invite_to_slack_channel",
            "invite_to_channel",
            description="Invite users to a Slack channel.",
            parallelizable=False,
            tags=("slack_conversations", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "C1234567",
                },
                "users": {
                    "type": "array",
                    "description": "List of user IDs.",
                    "example": ["U123"],
                },
            },
        ),
        client_op(
            "open_slack_dm",
            "open_dm",
            description="Open a DM with Slack users.",
            parallelizable=False,
            tags=("slack_conversations", "slack"),
            input_schema={
                "users": {
                    "type": "array",
                    "description": "List of user IDs.",
                    "example": ["U123"],
                },
            },
        ),
        client_op(
            "archive_slack_channel",
            "archive_channel",
            description="Archive a Slack channel.",
            parallelizable=False,
            tags=("slack_conversations", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "unarchive_slack_channel",
            "unarchive_channel",
            description="Unarchive a previously-archived Slack channel.",
            parallelizable=False,
            tags=("slack_conversations",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "rename_slack_channel",
            "rename_channel",
            description="Rename a Slack channel.",
            parallelizable=False,
            tags=("slack_conversations",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "name": {
                    "type": "string",
                    "description": "New channel name.",
                    "example": "",
                },
            },
        ),
        client_op(
            "set_slack_channel_topic",
            "set_channel_topic",
            description="Set a Slack channel's topic.",
            parallelizable=False,
            tags=("slack_conversations", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "topic": {
                    "type": "string",
                    "description": "New topic.",
                    "example": "",
                },
            },
        ),
        client_op(
            "set_slack_channel_purpose",
            "set_channel_purpose",
            description="Set a Slack channel's purpose / description.",
            parallelizable=False,
            tags=("slack_conversations",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "purpose": {
                    "type": "string",
                    "description": "New purpose.",
                    "example": "",
                },
            },
        ),
        client_op(
            "join_slack_channel",
            "join_channel",
            description="Have the bot join a Slack channel.",
            parallelizable=False,
            tags=("slack_conversations", "slack"),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "leave_slack_channel",
            "leave_channel",
            description="Have the bot leave a Slack channel.",
            parallelizable=False,
            tags=("slack_conversations",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "kick_user_from_slack_channel",
            "kick_user",
            description="Remove a user from a Slack channel.",
            parallelizable=False,
            tags=("slack_conversations",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "user": {
                    "type": "string",
                    "description": "User ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "close_slack_conversation",
            "close_conversation",
            description="Close a DM, MPDM, or private channel.",
            parallelizable=False,
            tags=("slack_conversations",),
            input_schema={
                "channel": {
                    "type": "string",
                    "description": "Conversation ID.",
                    "example": "",
                },
            },
        ),
        # ── Files ─────────────────────────────────────────────────────────
        client_op(
            "upload_slack_file",
            "upload_file_v2",
            description=(
                "Upload a local file to Slack using the modern 3-step "
                "files.getUploadURLExternal flow. Optionally share into a "
                "channel + post initial comment."
            ),
            parallelizable=False,
            tags=("slack_files", "slack"),
            input_schema={
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to local file.",
                    "example": "C:/Users/me/report.pdf",
                },
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID to share into (optional).",
                    "example": "C01234567",
                },
                "initial_comment": {
                    "type": "string",
                    "description": "Message text with the file (optional).",
                    "example": "",
                },
                "title": {
                    "type": "string",
                    "description": "File title (optional).",
                    "example": "",
                },
                "thread_ts": {
                    "type": "string",
                    "description": "Reply in a thread (optional).",
                    "example": "",
                },
                "filename": {
                    "type": "string",
                    "description": "Override filename (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "file_path": d["file_path"],
                "channel_id": d.get("channel_id") or None,
                "initial_comment": d.get("initial_comment") or None,
                "title": d.get("title") or None,
                "thread_ts": d.get("thread_ts") or None,
                "filename": d.get("filename") or None,
            },
        ),
        _with_post(
            client_op(
                "list_slack_files",
                "list_files",
                description=(
                    "List files in the workspace (optionally filter by "
                    "channel, user, or types like 'images,zips'). Lean files "
                    "(id, name, title, mimetype, size, created, user, "
                    "permalink) by default; include_metadata=true returns full "
                    "raw file objects (thumbnails, share info, ...)."
                ),
                tags=("slack_files", "slack"),
                input_schema={
                    "channel": {
                        "type": "string",
                        "description": "Filter to channel (optional).",
                        "example": "",
                    },
                    "user": {
                        "type": "string",
                        "description": "Filter to user (optional).",
                        "example": "",
                    },
                    "types": {
                        "type": "string",
                        "description": (
                            "Comma-separated types: all, spaces, snippets, "
                            "images, gdocs, zips, pdfs (optional)."
                        ),
                        "example": "",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Max results.",
                        "example": 100,
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number.",
                        "example": 1,
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean files. True: full raw.",
                        "example": False,
                    },
                },
                arg_map=lambda d: {
                    "channel": d.get("channel") or None,
                    "user": d.get("user") or None,
                    "types": d.get("types") or None,
                    "count": d.get("count", 100),
                    "page": d.get("page", 1),
                },
            ),
            _lean_files,
        ),
        client_op(
            "get_slack_file_info",
            "get_file_info",
            description=(
                "Get metadata for a Slack file (name, size, URL, channels "
                "shared into)."
            ),
            tags=("slack_files", "slack"),
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "F0123ABC",
                },
            },
        ),
        client_op(
            "delete_slack_file",
            "delete_file",
            description="Delete a Slack file. Irreversible.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("slack_files",),
            input_schema={
                "file_id": {
                    "type": "string",
                    "description": "File ID.",
                    "example": "",
                },
            },
        ),
        # ── Users + usergroups + presence ─────────────────────────────────
        _with_post(
            client_op(
                "list_slack_users",
                "list_users",
                description=(
                    "List users in the Slack workspace. Lean members (id, "
                    "name, real_name, display_name, email, is_bot, is_admin, "
                    "tz, deleted) by default; include_metadata=true returns "
                    "full raw user objects (avatar URLs, full profile, ...)."
                ),
                tags=("slack_users", "slack"),
                input_schema={
                    "limit": {
                        "type": "integer",
                        "description": "Max users to return.",
                        "example": 100,
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean members. True: full raw.",
                        "example": False,
                    },
                },
                output_schema={
                    **_STATUS,
                    "users": {"type": "array"},
                },
                arg_map=lambda d: {"limit": d.get("limit", 100)},
            ),
            _lean_users,
        ),
        client_op(
            "get_slack_user_info",
            "get_user_info",
            description="Get info about a Slack user.",
            tags=("slack_users", "slack"),
            input_schema={
                "slack_user_id": {
                    "type": "string",
                    "description": "User ID.",
                    "example": "U1234567",
                },
            },
            arg_map=lambda d: {"user_id": d["slack_user_id"]},
        ),
        client_op(
            "lookup_slack_user_by_email",
            "lookup_user_by_email",
            description="Resolve a Slack user by their email address.",
            tags=("slack_users", "slack"),
            input_schema={
                "email": {
                    "type": "string",
                    "description": "Email address.",
                    "example": "alice@example.com",
                },
            },
        ),
        client_op(
            "get_slack_user_presence",
            "get_user_presence",
            description=(
                "Check whether a Slack user is online (active) or offline "
                "(away)."
            ),
            tags=("slack_users",),
            input_schema={
                "user": {
                    "type": "string",
                    "description": "User ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "set_slack_user_presence",
            "set_user_presence",
            description=(
                "Set the authenticated user's presence (requires user token "
                "xoxp-, not bot token)."
            ),
            parallelizable=False,
            tags=("slack_users",),
            input_schema={
                "presence": {
                    "type": "string",
                    "description": "auto or away.",
                    "example": "auto",
                },
            },
        ),
        client_op(
            "list_slack_usergroups",
            "list_usergroups",
            description="List Slack usergroups (@team mentions) in the workspace.",
            tags=("slack_users", "slack"),
            input_schema={
                "include_disabled": {
                    "type": "boolean",
                    "description": "Include disabled groups.",
                    "example": False,
                },
                "include_count": {
                    "type": "boolean",
                    "description": "Include member counts.",
                    "example": False,
                },
                "include_users": {
                    "type": "boolean",
                    "description": "Include user list per group.",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "include_disabled": bool(d.get("include_disabled", False)),
                "include_count": bool(d.get("include_count", False)),
                "include_users": bool(d.get("include_users", False)),
            },
        ),
        client_op(
            "create_slack_usergroup",
            "create_usergroup",
            description="Create a new Slack usergroup.",
            parallelizable=False,
            tags=("slack_users",),
            input_schema={
                "name": {
                    "type": "string",
                    "description": "Group name (e.g. 'Marketing').",
                    "example": "",
                },
                "handle": {
                    "type": "string",
                    "description": "Handle without @ (optional).",
                    "example": "",
                },
                "description": {
                    "type": "string",
                    "description": "Description (optional).",
                    "example": "",
                },
                "channels": {
                    "type": "array",
                    "description": "Default channels (optional).",
                    "example": [],
                },
            },
            arg_map=lambda d: {
                "name": d["name"],
                "handle": d.get("handle") or None,
                "description": d.get("description") or None,
                "channels": d.get("channels") or None,
            },
        ),
        client_op(
            "update_slack_usergroup",
            "update_usergroup",
            description="Update a Slack usergroup's name/handle/description/channels.",
            parallelizable=False,
            tags=("slack_users",),
            input_schema={
                "usergroup": {
                    "type": "string",
                    "description": "Usergroup ID.",
                    "example": "",
                },
                "name": {
                    "type": "string",
                    "description": "New name (optional).",
                    "example": "",
                },
                "handle": {
                    "type": "string",
                    "description": "New handle (optional).",
                    "example": "",
                },
                "description": {
                    "type": "string",
                    "description": "New description (optional).",
                    "example": "",
                },
                "channels": {
                    "type": "array",
                    "description": "New default channels (optional).",
                    "example": [],
                },
            },
            arg_map=lambda d: {
                "usergroup": d["usergroup"],
                "name": d["name"] if "name" in d else None,
                "handle": d["handle"] if "handle" in d else None,
                "description": d["description"] if "description" in d else None,
                "channels": d["channels"] if "channels" in d else None,
            },
        ),
        client_op(
            "list_slack_usergroup_users",
            "list_usergroup_users",
            description="List the users in a Slack usergroup.",
            tags=("slack_users",),
            input_schema={
                "usergroup": {
                    "type": "string",
                    "description": "Usergroup ID.",
                    "example": "",
                },
                "include_disabled": {
                    "type": "boolean",
                    "description": "Include disabled users.",
                    "example": False,
                },
            },
            arg_map=lambda d: {
                "usergroup": d["usergroup"],
                "include_disabled": bool(d.get("include_disabled", False)),
            },
        ),
        client_op(
            "set_slack_usergroup_users",
            "update_usergroup_users",
            description="REPLACE the members of a Slack usergroup.",
            parallelizable=False,
            tags=("slack_users",),
            input_schema={
                "usergroup": {
                    "type": "string",
                    "description": "Usergroup ID.",
                    "example": "",
                },
                "users": {
                    "type": "array",
                    "description": "List of user IDs to set as members.",
                    "example": [],
                },
            },
        ),
        client_op(
            "enable_slack_usergroup",
            "enable_usergroup",
            description="Enable a previously-disabled Slack usergroup.",
            parallelizable=False,
            tags=("slack_users",),
            input_schema={
                "usergroup": {
                    "type": "string",
                    "description": "Usergroup ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "disable_slack_usergroup",
            "disable_usergroup",
            description=(
                "Disable a Slack usergroup (keeps it but hides from "
                "autocomplete)."
            ),
            parallelizable=False,
            tags=("slack_users",),
            input_schema={
                "usergroup": {
                    "type": "string",
                    "description": "Usergroup ID.",
                    "example": "",
                },
            },
        ),
        # ── Workspace: auth / team / search / bookmarks / reminders ───────
        client_op(
            "get_slack_auth_info",
            "auth_test",
            description=(
                "Get info about the authenticated Slack bot/user (team, user, "
                "bot_id)."
            ),
            tags=("slack_workspace", "slack"),
            input_schema={},
        ),
        client_op(
            "get_slack_team_info",
            "get_team_info",
            description=(
                "Get info about the Slack workspace (team name, domain, icon)."
            ),
            tags=("slack_workspace", "slack"),
            input_schema={
                "team": {
                    "type": "string",
                    "description": "Team ID (optional, defaults to current).",
                    "example": "",
                },
            },
            arg_map=lambda d: {"team": d.get("team") or None},
        ),
        _with_post(
            client_op(
                "search_slack_messages",
                "search_messages",
                description=(
                    "Search for messages in the Slack workspace (requires "
                    "user token / search:read). Lean matches (user, text, ts, "
                    "channel {id, name}, permalink) by default; "
                    "include_metadata=true returns full raw matches (blocks, "
                    "score, pagination, ...)."
                ),
                tags=("slack_workspace", "slack"),
                input_schema={
                    "query": {
                        "type": "string",
                        "description": "Search query.",
                        "example": "project update",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Max results.",
                        "example": 20,
                    },
                    "include_metadata": {
                        "type": "boolean",
                        "description": "False (default): lean matches. True: full raw.",
                        "example": False,
                    },
                },
                arg_map=lambda d: {
                    "query": d["query"],
                    "count": d.get("count", 20),
                },
            ),
            _lean_search,
        ),
        client_op(
            "list_slack_bookmarks",
            "list_bookmarks",
            description="List bookmarks pinned to a Slack channel.",
            tags=("slack_workspace", "slack"),
            input_schema={
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "add_slack_bookmark",
            "add_bookmark",
            description="Add a bookmark to a Slack channel.",
            parallelizable=False,
            tags=("slack_workspace", "slack"),
            input_schema={
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "title": {
                    "type": "string",
                    "description": "Bookmark title.",
                    "example": "Project doc",
                },
                "type": {
                    "type": "string",
                    "description": "Bookmark type (link).",
                    "example": "link",
                },
                "link": {
                    "type": "string",
                    "description": "URL (for type=link).",
                    "example": "",
                },
                "emoji": {
                    "type": "string",
                    "description": "Emoji shortcode (optional).",
                    "example": ":bookmark:",
                },
            },
            arg_map=lambda d: {
                "channel_id": d["channel_id"],
                "title": d["title"],
                "type": d.get("type", "link"),
                "link": d.get("link") or None,
                "emoji": d.get("emoji") or None,
            },
        ),
        client_op(
            "edit_slack_bookmark",
            "edit_bookmark",
            description="Edit an existing channel bookmark.",
            parallelizable=False,
            tags=("slack_workspace",),
            input_schema={
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "bookmark_id": {
                    "type": "string",
                    "description": "Bookmark ID.",
                    "example": "",
                },
                "title": {
                    "type": "string",
                    "description": "New title (optional).",
                    "example": "",
                },
                "link": {
                    "type": "string",
                    "description": "New URL (optional).",
                    "example": "",
                },
                "emoji": {
                    "type": "string",
                    "description": "New emoji (optional).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "channel_id": d["channel_id"],
                "bookmark_id": d["bookmark_id"],
                "title": d["title"] if "title" in d else None,
                "link": d["link"] if "link" in d else None,
                "emoji": d["emoji"] if "emoji" in d else None,
            },
        ),
        client_op(
            "remove_slack_bookmark",
            "remove_bookmark",
            description="Delete a channel bookmark.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("slack_workspace",),
            input_schema={
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID.",
                    "example": "",
                },
                "bookmark_id": {
                    "type": "string",
                    "description": "Bookmark ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "add_slack_reminder",
            "add_reminder",
            description=(
                "Add a Slack reminder. time can be a Unix timestamp or "
                "natural-language ('in 15 minutes'). Requires user token "
                "(xoxp-) — bot tokens can't create reminders."
            ),
            parallelizable=False,
            tags=("slack_workspace", "slack"),
            input_schema={
                "text": {
                    "type": "string",
                    "description": "Reminder text.",
                    "example": "Send the weekly report",
                },
                "time": {
                    "type": "string",
                    "description": (
                        "Unix timestamp OR natural-language ('in 15 minutes')."
                    ),
                    "example": "in 15 minutes",
                },
                "user": {
                    "type": "string",
                    "description": "User ID (optional, defaults to self).",
                    "example": "",
                },
            },
            arg_map=lambda d: {
                "text": d["text"],
                "time": d["time"],
                "user": d.get("user") or None,
            },
        ),
        client_op(
            "list_slack_reminders",
            "list_reminders",
            description="List the authenticated user's Slack reminders.",
            tags=("slack_workspace",),
            input_schema={},
        ),
        client_op(
            "get_slack_reminder",
            "get_reminder_info",
            description="Get info about a single Slack reminder.",
            tags=("slack_workspace",),
            input_schema={
                "reminder": {
                    "type": "string",
                    "description": "Reminder ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "complete_slack_reminder",
            "complete_reminder",
            description="Mark a Slack reminder as complete.",
            parallelizable=False,
            tags=("slack_workspace",),
            input_schema={
                "reminder": {
                    "type": "string",
                    "description": "Reminder ID.",
                    "example": "",
                },
            },
        ),
        client_op(
            "delete_slack_reminder",
            "delete_reminder",
            description="Delete a Slack reminder.",
            destructive=True,  # permanent delete
            parallelizable=False,
            tags=("slack_workspace",),
            input_schema={
                "reminder": {
                    "type": "string",
                    "description": "Reminder ID.",
                    "example": "",
                },
            },
        ),
    ]
