from agent_core import action


@action(
    name="get_my_youtube_channel",
    description="Return the authenticated user's YouTube channel info (id, title, subscriber/view counts).",
    action_sets=["google_youtube"],
    input_schema={
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_my_youtube_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_youtube",
        "get_my_channel",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to fetch channel.",
    )


@action(
    name="search_youtube",
    description="Search YouTube for videos, channels, or playlists. Lean results by default ({videoId/channelId/playlistId, title, channelTitle, publishedAt, description}); set include_metadata for raw results.",
    action_sets=["google_youtube"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw search results (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def search_youtube(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "google_youtube",
        "search",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="YouTube search failed.",
        query=input_data["query"],
        type_filter=input_data.get("type", "video"),
        max_results=input_data.get("max_results", 25),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        items = res.get("result")
        if isinstance(items, list):
            lean = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                snippet = it.get("snippet") or {}
                rid = it.get("id") or {}
                entry = {}
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
            res = {**res, "result": lean}
    return res


@action(
    name="get_youtube_video",
    description="Get full metadata for a YouTube video (snippet, statistics, content details).",
    action_sets=["google_youtube"],
    input_schema={
        "video_id": {
            "type": "string",
            "description": "The YouTube video ID.",
            "example": "dQw4w9WgXcQ",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_youtube_video(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_youtube",
        "get_video",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to fetch video.",
        video_id=input_data["video_id"],
    )


@action(
    name="list_my_youtube_subscriptions",
    description="List the channels the authenticated user is subscribed to. Lean results by default ({channelId, title, description}); set include_metadata for raw results (needed for the subscription ID used by unsubscribe).",
    action_sets=["google_youtube"],
    input_schema={
        "max_results": {
            "type": "integer",
            "description": "Max number of subscriptions to return.",
            "example": 50,
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw subscription resources (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_my_youtube_subscriptions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "google_youtube",
        "list_my_subscriptions",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list subscriptions.",
        max_results=input_data.get("max_results", 50),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        items = res.get("result")
        if isinstance(items, list):
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
            res = {**res, "result": lean}
    return res


@action(
    name="list_my_youtube_playlists",
    description="List playlists owned by the authenticated user. Lean results by default ({id, title, itemCount}); set include_metadata for raw results.",
    action_sets=["google_youtube"],
    input_schema={
        "max_results": {
            "type": "integer",
            "description": "Max number of playlists to return.",
            "example": 50,
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw playlist resources (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_my_youtube_playlists(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "google_youtube",
        "list_my_playlists",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list playlists.",
        max_results=input_data.get("max_results", 50),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        items = res.get("result")
        if isinstance(items, list):
            res = {
                **res,
                "result": [
                    {
                        "id": it.get("id"),
                        "title": (it.get("snippet") or {}).get("title"),
                        "itemCount": (it.get("contentDetails") or {}).get(
                            "itemCount"
                        ),
                    }
                    for it in items
                    if isinstance(it, dict)
                ],
            }
    return res


@action(
    name="list_youtube_playlist_items",
    description="List videos in a YouTube playlist. Lean results by default ({videoId, title, position, publishedAt}); set include_metadata for raw results.",
    action_sets=["google_youtube"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw playlistItem resources (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def list_youtube_playlist_items(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "google_youtube",
        "list_playlist_items",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to list playlist items.",
        playlist_id=input_data["playlist_id"],
        max_results=input_data.get("max_results", 50),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        items = res.get("result")
        if isinstance(items, list):
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
            res = {**res, "result": lean}
    return res


@action(
    name="subscribe_to_youtube_channel",
    description="Subscribe the authenticated user to a YouTube channel.",
    action_sets=["google_youtube"],
    input_schema={
        "channel_id": {
            "type": "string",
            "description": "The channel ID to subscribe to.",
            "example": "UC...",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def subscribe_to_youtube_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_youtube",
        "subscribe",
        account=input_data.get("account"),
        unwrap_envelope=True,
        success_message="Subscribed.",
        fail_message="Failed to subscribe.",
        channel_id=input_data["channel_id"],
    )


@action(
    name="unsubscribe_from_youtube_channel",
    description="Remove a YouTube subscription. Takes the subscription ID (from list_my_youtube_subscriptions), not the channel ID.",
    action_sets=["google_youtube"],
    input_schema={
        "subscription_id": {
            "type": "string",
            "description": "The subscription record ID.",
            "example": "abc123...",
        },
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def unsubscribe_from_youtube_channel(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_youtube",
        "unsubscribe",
        account=input_data.get("account"),
        unwrap_envelope=True,
        success_message="Unsubscribed.",
        fail_message="Failed to unsubscribe.",
        subscription_id=input_data["subscription_id"],
    )


@action(
    name="rate_youtube_video",
    description="Like, dislike, or clear your rating on a YouTube video.",
    action_sets=["google_youtube"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def rate_youtube_video(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_youtube",
        "rate_video",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to rate video.",
        video_id=input_data["video_id"],
        rating=input_data["rating"],
    )


@action(
    name="post_youtube_comment",
    irreversible=True,
    description="Post a top-level comment on a YouTube video.",
    action_sets=["google_youtube"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def post_youtube_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    return run_client_sync(
        "google_youtube",
        "post_comment",
        account=input_data.get("account"),
        unwrap_envelope=True,
        success_message="Comment posted.",
        fail_message="Failed to post comment.",
        video_id=input_data["video_id"],
        text=input_data["text"],
    )


@action(
    name="get_youtube_video_comments",
    description="Get top-level comments on a YouTube video, most recent first. Lean results by default ({author, text, likeCount, publishedAt, totalReplyCount}); set include_metadata for raw commentThread resources.",
    action_sets=["google_youtube"],
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
        "account": {
            "type": "string",
            "description": "Optional Google account email (or unique fragment, e.g. 'work'). Omit to use the primary account.",
            "example": "",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return raw commentThread resources (default false = lean).",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_youtube_video_comments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client_sync

    res = run_client_sync(
        "google_youtube",
        "get_video_comments",
        account=input_data.get("account"),
        unwrap_envelope=True,
        fail_message="Failed to fetch comments.",
        video_id=input_data["video_id"],
        max_results=input_data.get("max_results", 50),
    )
    if not input_data.get("include_metadata") and res.get("status") == "success":
        items = res.get("result")
        if isinstance(items, list):
            lean = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                thread = it.get("snippet") or {}
                comment = (thread.get("topLevelComment") or {}).get("snippet") or {}
                lean.append(
                    {
                        "author": comment.get("authorDisplayName"),
                        "text": comment.get("textOriginal")
                        or comment.get("textDisplay"),
                        "likeCount": comment.get("likeCount"),
                        "publishedAt": comment.get("publishedAt"),
                        "totalReplyCount": thread.get("totalReplyCount"),
                    }
                )
            res = {**res, "result": lean}
    return res
