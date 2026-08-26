"""YouTube operations — schemas for google_youtube_actions.py.

NOTE: no operation declares an ``account`` input — the host adapter
injects it on every generated action and the core resolves it centrally
(conformance-enforced).

Several actions shape raw API resources into lean results unless
``include_metadata`` is set; ``_lean_op`` reproduces that post-processing
on top of ``client_op`` so ported operations return identical dicts.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List

from ...contracts import Operation
from .._shared import client_op

_INCLUDE_METADATA_SCHEMA = {
    "type": "boolean",
    "description": "Return raw search results (default false = lean).",
    "example": False,
}


def _lean_op(op: Operation, lean: Callable[[List[Any]], List[Any]]) -> Operation:
    """Wrap an Operation so a successful list result is reduced to its lean
    shape unless the caller sets ``include_metadata`` (client default)."""
    inner = op.fn

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        res = await inner(client, input_data)
        if not input_data.get("include_metadata") and res.get("status") == "success":
            items = res.get("result")
            if isinstance(items, list):
                res = {**res, "result": lean(items)}
        return res

    return replace(op, fn=fn)


def _lean_search(items: List[Any]) -> List[Any]:
    lean = []
    for it in items:
        if not isinstance(it, dict):
            continue
        snippet = it.get("snippet") or {}
        rid = it.get("id") or {}
        entry: Dict[str, Any] = {}
        for key in ("videoId", "channelId", "playlistId"):
            if isinstance(rid, dict) and rid.get(key):
                entry[key] = rid[key]
        entry.update(
            {
                "title": snippet.get("title"),
                "channelTitle": snippet.get("channelTitle"),
                "publishedAt": snippet.get("publishedAt"),
                "description": snippet.get("description"),
            }
        )
        lean.append(entry)
    return lean


def _lean_subscriptions(items: List[Any]) -> List[Any]:
    lean = []
    for it in items:
        if not isinstance(it, dict):
            continue
        snippet = it.get("snippet") or {}
        entry = {
            "channelId": (snippet.get("resourceId") or {}).get("channelId"),
            "title": snippet.get("title"),
        }
        if snippet.get("description"):
            entry["description"] = snippet["description"]
        lean.append(entry)
    return lean


def _lean_playlists(items: List[Any]) -> List[Any]:
    return [
        {
            "id": it.get("id"),
            "title": (it.get("snippet") or {}).get("title"),
            "itemCount": (it.get("contentDetails") or {}).get("itemCount"),
        }
        for it in items
        if isinstance(it, dict)
    ]


def _lean_playlist_items(items: List[Any]) -> List[Any]:
    lean = []
    for it in items:
        if not isinstance(it, dict):
            continue
        snippet = it.get("snippet") or {}
        lean.append(
            {
                "videoId": (snippet.get("resourceId") or {}).get("videoId"),
                "title": snippet.get("title"),
                "position": snippet.get("position"),
                "publishedAt": snippet.get("publishedAt"),
            }
        )
    return lean


def _lean_comments(items: List[Any]) -> List[Any]:
    lean = []
    for it in items:
        if not isinstance(it, dict):
            continue
        thread = it.get("snippet") or {}
        comment = (thread.get("topLevelComment") or {}).get("snippet") or {}
        lean.append(
            {
                "author": comment.get("authorDisplayName"),
                "text": comment.get("textOriginal") or comment.get("textDisplay"),
                "likeCount": comment.get("likeCount"),
                "publishedAt": comment.get("publishedAt"),
                "totalReplyCount": thread.get("totalReplyCount"),
            }
        )
    return lean


def build_operations() -> List[Operation]:
    return [
        client_op(
            "get_my_youtube_channel",
            "get_my_channel",
            description=(
                "Return the authenticated user's YouTube channel info "
                "(id, title, subscriber/view counts)."
            ),
            tags=("google_youtube",),
            unwrap_envelope=True,
            fail_message="Failed to fetch channel.",
            input_schema={},
        ),
        _lean_op(
            client_op(
                "search_youtube",
                "search",
                description=(
                    "Search YouTube for videos, channels, or playlists. Lean "
                    "results by default ({videoId/channelId/playlistId, title, "
                    "channelTitle, publishedAt, description}); set "
                    "include_metadata for raw results."
                ),
                tags=("google_youtube",),
                unwrap_envelope=True,
                fail_message="YouTube search failed.",
                input_schema={
                    "query": {
                        "type": "string",
                        "description": "Search terms.",
                        "example": "claude code tutorial",
                    },
                    "type": {
                        "type": "string",
                        "description": "What to search for: video, channel, or playlist.",
                        "example": "video",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of results.",
                        "example": 25,
                    },
                    "include_metadata": dict(_INCLUDE_METADATA_SCHEMA),
                },
                arg_map=lambda d: {
                    "query": d["query"],
                    "type_filter": d.get("type", "video"),
                    "max_results": d.get("max_results", 25),
                },
            ),
            _lean_search,
        ),
        client_op(
            "get_youtube_video",
            "get_video",
            description=(
                "Get full metadata for a YouTube video (snippet, statistics, "
                "content details)."
            ),
            tags=("google_youtube",),
            unwrap_envelope=True,
            fail_message="Failed to fetch video.",
            input_schema={
                "video_id": {
                    "type": "string",
                    "description": "The YouTube video ID.",
                    "example": "dQw4w9WgXcQ",
                },
            },
        ),
        _lean_op(
            client_op(
                "list_my_youtube_subscriptions",
                "list_my_subscriptions",
                description=(
                    "List the channels the authenticated user is subscribed to. "
                    "Lean results by default ({channelId, title, description}); "
                    "set include_metadata for raw results (needed for the "
                    "subscription ID used by unsubscribe)."
                ),
                tags=("google_youtube",),
                unwrap_envelope=True,
                fail_message="Failed to list subscriptions.",
                input_schema={
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of subscriptions to return.",
                        "example": 50,
                    },
                    "include_metadata": {
                        **_INCLUDE_METADATA_SCHEMA,
                        "description": (
                            "Return raw subscription resources (default false = lean)."
                        ),
                    },
                },
                arg_map=lambda d: {"max_results": d.get("max_results", 50)},
            ),
            _lean_subscriptions,
        ),
        _lean_op(
            client_op(
                "list_my_youtube_playlists",
                "list_my_playlists",
                description=(
                    "List playlists owned by the authenticated user. Lean "
                    "results by default ({id, title, itemCount}); set "
                    "include_metadata for raw results."
                ),
                tags=("google_youtube",),
                unwrap_envelope=True,
                fail_message="Failed to list playlists.",
                input_schema={
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of playlists to return.",
                        "example": 50,
                    },
                    "include_metadata": {
                        **_INCLUDE_METADATA_SCHEMA,
                        "description": (
                            "Return raw playlist resources (default false = lean)."
                        ),
                    },
                },
                arg_map=lambda d: {"max_results": d.get("max_results", 50)},
            ),
            _lean_playlists,
        ),
        _lean_op(
            client_op(
                "list_youtube_playlist_items",
                "list_playlist_items",
                description=(
                    "List videos in a YouTube playlist. Lean results by default "
                    "({videoId, title, position, publishedAt}); set "
                    "include_metadata for raw results."
                ),
                tags=("google_youtube",),
                unwrap_envelope=True,
                fail_message="Failed to list playlist items.",
                input_schema={
                    "playlist_id": {
                        "type": "string",
                        "description": "The playlist ID.",
                        "example": "PLrAXt...",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of items to return.",
                        "example": 50,
                    },
                    "include_metadata": {
                        **_INCLUDE_METADATA_SCHEMA,
                        "description": (
                            "Return raw playlistItem resources (default false = lean)."
                        ),
                    },
                },
                arg_map=lambda d: {
                    "playlist_id": d["playlist_id"],
                    "max_results": d.get("max_results", 50),
                },
            ),
            _lean_playlist_items,
        ),
        client_op(
            "subscribe_to_youtube_channel",
            "subscribe",
            description="Subscribe the authenticated user to a YouTube channel.",
            tags=("google_youtube",),
            unwrap_envelope=True,
            success_message="Subscribed.",
            fail_message="Failed to subscribe.",
            input_schema={
                "channel_id": {
                    "type": "string",
                    "description": "The channel ID to subscribe to.",
                    "example": "UC...",
                },
            },
        ),
        client_op(
            "unsubscribe_from_youtube_channel",
            "unsubscribe",
            description=(
                "Remove a YouTube subscription. Takes the subscription ID "
                "(from list_my_youtube_subscriptions), not the channel ID."
            ),
            tags=("google_youtube",),
            unwrap_envelope=True,
            success_message="Unsubscribed.",
            fail_message="Failed to unsubscribe.",
            input_schema={
                "subscription_id": {
                    "type": "string",
                    "description": "The subscription record ID.",
                    "example": "abc123...",
                },
            },
        ),
        client_op(
            "rate_youtube_video",
            "rate_video",
            description="Like, dislike, or clear your rating on a YouTube video.",
            tags=("google_youtube",),
            unwrap_envelope=True,
            fail_message="Failed to rate video.",
            input_schema={
                "video_id": {
                    "type": "string",
                    "description": "The YouTube video ID.",
                    "example": "dQw4w9WgXcQ",
                },
                "rating": {
                    "type": "string",
                    "description": "One of: like, dislike, none.",
                    "example": "like",
                },
            },
        ),
        client_op(
            "post_youtube_comment",
            "post_comment",
            description="Post a top-level comment on a YouTube video.",
            destructive=True,  # public, can't unsay
            parallelizable=False,
            tags=("google_youtube",),
            unwrap_envelope=True,
            success_message="Comment posted.",
            fail_message="Failed to post comment.",
            input_schema={
                "video_id": {
                    "type": "string",
                    "description": "The YouTube video ID.",
                    "example": "dQw4w9WgXcQ",
                },
                "text": {
                    "type": "string",
                    "description": "Comment text.",
                    "example": "Great video!",
                },
            },
        ),
        _lean_op(
            client_op(
                "get_youtube_video_comments",
                "get_video_comments",
                description=(
                    "Get top-level comments on a YouTube video, most recent "
                    "first. Lean results by default ({author, text, likeCount, "
                    "publishedAt, totalReplyCount}); set include_metadata for "
                    "raw commentThread resources."
                ),
                tags=("google_youtube",),
                unwrap_envelope=True,
                fail_message="Failed to fetch comments.",
                input_schema={
                    "video_id": {
                        "type": "string",
                        "description": "The YouTube video ID.",
                        "example": "dQw4w9WgXcQ",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of comments to return.",
                        "example": 50,
                    },
                    "include_metadata": {
                        **_INCLUDE_METADATA_SCHEMA,
                        "description": (
                            "Return raw commentThread resources (default false = lean)."
                        ),
                    },
                },
                arg_map=lambda d: {
                    "video_id": d["video_id"],
                    "max_results": d.get("max_results", 50),
                },
            ),
            _lean_comments,
        ),
    ]
