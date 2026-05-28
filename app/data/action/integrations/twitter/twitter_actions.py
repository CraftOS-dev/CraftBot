from agent_core import action


# ------------------------------------------------------------------
# Tweets — post, reply, delete, lookup, mentions, quote, hide, search
# Sub-set: twitter_tweets
# ------------------------------------------------------------------


@action(
    name="post_tweet",
    description="Post a tweet on Twitter/X.",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "text": {
            "type": "string",
            "description": "Tweet text (max 280 chars).",
            "example": "Hello world!",
        },
        "reply_to": {
            "type": "string",
            "description": "Tweet ID to reply to. Leave empty for a new tweet.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def post_tweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "post_tweet",
        text=input_data["text"],
        reply_to=input_data.get("reply_to") or None,
    )


@action(
    name="reply_to_tweet",
    description="Reply to a tweet on Twitter/X.",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to reply to.",
            "example": "1234567890",
        },
        "text": {
            "type": "string",
            "description": "Reply text.",
            "example": "Thanks for sharing!",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def reply_to_tweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    return await with_client(
        "twitter",
        lambda c: c.reply_to_tweet(input_data["tweet_id"], input_data["text"]),
    )


@action(
    name="delete_tweet",
    description="Delete a tweet.",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to delete.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_tweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "delete_tweet", tweet_id=input_data["tweet_id"])


@action(
    name="get_tweet",
    description="Fetch a single tweet by ID.",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_tweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "get_tweet", tweet_id=input_data["tweet_id"])


@action(
    name="lookup_tweets",
    description="Batch-lookup up to 100 tweets by their IDs.",
    action_sets=["twitter_tweets"],
    input_schema={
        "tweet_ids": {
            "type": "array",
            "description": "List of tweet IDs (max 100).",
            "example": ["123", "456"],
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def lookup_tweets(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "lookup_tweets", tweet_ids=input_data["tweet_ids"]
    )


@action(
    name="search_tweets",
    description="Search recent tweets on Twitter/X.",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Search query.",
            "example": "from:elonmusk",
        },
        "max_results": {
            "type": "integer",
            "description": "Max results (10-100).",
            "example": 10,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_tweets(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    return await with_client(
        "twitter",
        lambda c: c.search_tweets(
            input_data["query"], max_results=input_data.get("max_results", 10)
        ),
    )


@action(
    name="get_twitter_timeline",
    description="Get recent tweets from a user's timeline.",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "user_id": {
            "type": "string",
            "description": "User ID. Leave empty for your own timeline.",
            "example": "",
        },
        "max_results": {
            "type": "integer",
            "description": "Max tweets to return.",
            "example": 10,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_twitter_timeline(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "get_user_timeline",
        user_id=input_data.get("user_id") or None,
        max_results=input_data.get("max_results", 10),
    )


@action(
    name="get_twitter_mentions",
    description="Get recent mentions of a user (defaults to the authenticated user).",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "user_id": {
            "type": "string",
            "description": "User ID. Leave empty for self.",
            "example": "",
        },
        "max_results": {
            "type": "integer",
            "description": "Max mentions.",
            "example": 10,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_twitter_mentions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "get_user_mentions",
        user_id=input_data.get("user_id") or None,
        max_results=input_data.get("max_results", 10),
    )


@action(
    name="post_quote_tweet",
    description="Post a quote tweet that wraps another tweet with your own commentary.",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "text": {
            "type": "string",
            "description": "Your commentary.",
            "example": "Great point —",
        },
        "quoted_tweet_id": {
            "type": "string",
            "description": "Tweet ID being quoted.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def post_quote_tweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "post_quote_tweet",
        text=input_data["text"],
        quoted_tweet_id=input_data["quoted_tweet_id"],
    )


@action(
    name="hide_tweet_reply",
    description="Hide (or unhide) a reply to one of your tweets.",
    action_sets=["twitter_tweets"],
    input_schema={
        "reply_tweet_id": {
            "type": "string",
            "description": "ID of the reply tweet.",
            "example": "1234567890",
        },
        "hidden": {
            "type": "boolean",
            "description": "True to hide, False to unhide.",
            "example": True,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def hide_tweet_reply(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "hide_reply",
        reply_tweet_id=input_data["reply_tweet_id"],
        hidden=input_data.get("hidden", True),
    )


@action(
    name="post_tweet_with_media",
    description="Post a tweet that includes already-uploaded media (use upload_twitter_media first to get media_ids).",
    action_sets=["twitter_tweets", "twitter"],
    input_schema={
        "text": {
            "type": "string",
            "description": "Tweet text.",
            "example": "Check this out!",
        },
        "media_ids": {
            "type": "array",
            "description": "Up to 4 media_id_string values from upload_twitter_media.",
            "example": ["1234567890"],
        },
        "reply_to": {
            "type": "string",
            "description": "Optional tweet ID to reply to.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def post_tweet_with_media(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "post_tweet_with_media",
        text=input_data["text"],
        media_ids=input_data["media_ids"],
        reply_to=input_data.get("reply_to") or None,
    )


# ------------------------------------------------------------------
# Engagement — like, unlike, retweet, unretweet, bookmarks, lookups
# Sub-set: twitter_engagement
# ------------------------------------------------------------------


@action(
    name="like_tweet",
    description="Like a tweet on Twitter/X.",
    action_sets=["twitter_engagement", "twitter"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to like.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def like_tweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "like_tweet", tweet_id=input_data["tweet_id"])


@action(
    name="unlike_tweet",
    description="Unlike a previously liked tweet.",
    action_sets=["twitter_engagement"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to unlike.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unlike_tweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "unlike_tweet", tweet_id=input_data["tweet_id"])


@action(
    name="retweet",
    description="Retweet a tweet on Twitter/X.",
    action_sets=["twitter_engagement", "twitter"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to retweet.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def retweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "retweet", tweet_id=input_data["tweet_id"])


@action(
    name="unretweet",
    description="Undo a retweet.",
    action_sets=["twitter_engagement"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Original tweet ID that was retweeted.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unretweet(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "unretweet", tweet_id=input_data["tweet_id"])


@action(
    name="add_twitter_bookmark",
    description="Bookmark a tweet (saves to the authed user's bookmarks).",
    action_sets=["twitter_engagement", "twitter"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to bookmark.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_twitter_bookmark(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "add_bookmark", tweet_id=input_data["tweet_id"])


@action(
    name="remove_twitter_bookmark",
    description="Remove a tweet from bookmarks.",
    action_sets=["twitter_engagement"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID to remove from bookmarks.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_twitter_bookmark(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "remove_bookmark", tweet_id=input_data["tweet_id"]
    )


@action(
    name="list_twitter_bookmarks",
    description="List the authenticated user's bookmarked tweets.",
    action_sets=["twitter_engagement", "twitter"],
    input_schema={
        "max_results": {
            "type": "integer",
            "description": "Max results.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_bookmarks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "list_bookmarks", max_results=input_data.get("max_results", 50)
    )


@action(
    name="list_tweet_liking_users",
    description="List users who liked a specific tweet.",
    action_sets=["twitter_engagement"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID.",
            "example": "1234567890",
        },
        "max_results": {"type": "integer", "description": "Max users.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_tweet_liking_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_liking_users",
        tweet_id=input_data["tweet_id"],
        max_results=input_data.get("max_results", 50),
    )


@action(
    name="list_tweet_retweeted_by",
    description="List users who retweeted a specific tweet.",
    action_sets=["twitter_engagement"],
    input_schema={
        "tweet_id": {
            "type": "string",
            "description": "Tweet ID.",
            "example": "1234567890",
        },
        "max_results": {"type": "integer", "description": "Max users.", "example": 50},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_tweet_retweeted_by(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_retweeted_by",
        tweet_id=input_data["tweet_id"],
        max_results=input_data.get("max_results", 50),
    )


# ------------------------------------------------------------------
# Users — lookup, follow, block, mute
# Sub-set: twitter_users
# ------------------------------------------------------------------


@action(
    name="get_twitter_user",
    description="Look up a Twitter/X user by username.",
    action_sets=["twitter_users", "twitter"],
    input_schema={
        "username": {
            "type": "string",
            "description": "Twitter username (without @).",
            "example": "elonmusk",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_twitter_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "get_user_by_username", username=input_data["username"]
    )


@action(
    name="get_twitter_me",
    description="Get the authenticated Twitter/X user's profile.",
    action_sets=["twitter_users", "twitter"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_twitter_me(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "get_me")


@action(
    name="follow_twitter_user",
    description="Follow a Twitter/X user by their numeric user_id.",
    action_sets=["twitter_users", "twitter"],
    input_schema={
        "target_user_id": {
            "type": "string",
            "description": "Target user_id (numeric).",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def follow_twitter_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "follow_user", target_user_id=input_data["target_user_id"]
    )


@action(
    name="unfollow_twitter_user",
    description="Unfollow a Twitter/X user.",
    action_sets=["twitter_users"],
    input_schema={
        "target_user_id": {
            "type": "string",
            "description": "Target user_id (numeric).",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unfollow_twitter_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "unfollow_user", target_user_id=input_data["target_user_id"]
    )


@action(
    name="list_twitter_following",
    description="List who a user is following (defaults to the authed user).",
    action_sets=["twitter_users", "twitter"],
    input_schema={
        "user_id": {
            "type": "string",
            "description": "User ID. Leave empty for self.",
            "example": "",
        },
        "max_results": {
            "type": "integer",
            "description": "Max users to return.",
            "example": 100,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_following(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_following",
        user_id=input_data.get("user_id") or None,
        max_results=input_data.get("max_results", 100),
    )


@action(
    name="list_twitter_followers",
    description="List a user's followers (defaults to the authed user).",
    action_sets=["twitter_users", "twitter"],
    input_schema={
        "user_id": {
            "type": "string",
            "description": "User ID. Leave empty for self.",
            "example": "",
        },
        "max_results": {"type": "integer", "description": "Max users.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_followers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_followers",
        user_id=input_data.get("user_id") or None,
        max_results=input_data.get("max_results", 100),
    )


@action(
    name="block_twitter_user",
    description="Block a Twitter/X user.",
    action_sets=["twitter_users"],
    input_schema={
        "target_user_id": {
            "type": "string",
            "description": "Target user_id.",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def block_twitter_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "block_user", target_user_id=input_data["target_user_id"]
    )


@action(
    name="unblock_twitter_user",
    description="Unblock a Twitter/X user.",
    action_sets=["twitter_users"],
    input_schema={
        "target_user_id": {
            "type": "string",
            "description": "Target user_id.",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unblock_twitter_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "unblock_user", target_user_id=input_data["target_user_id"]
    )


@action(
    name="mute_twitter_user",
    description="Mute a Twitter/X user (hides their content from your timeline).",
    action_sets=["twitter_users"],
    input_schema={
        "target_user_id": {
            "type": "string",
            "description": "Target user_id.",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def mute_twitter_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "mute_user", target_user_id=input_data["target_user_id"]
    )


@action(
    name="unmute_twitter_user",
    description="Unmute a previously muted user.",
    action_sets=["twitter_users"],
    input_schema={
        "target_user_id": {
            "type": "string",
            "description": "Target user_id.",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unmute_twitter_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "unmute_user", target_user_id=input_data["target_user_id"]
    )


# ------------------------------------------------------------------
# Lists — create, get, update, delete, members
# Sub-set: twitter_lists
# ------------------------------------------------------------------


@action(
    name="create_twitter_list",
    description="Create a new Twitter/X list.",
    action_sets=["twitter_lists", "twitter"],
    input_schema={
        "name": {
            "type": "string",
            "description": "List name.",
            "example": "Tech founders",
        },
        "description": {
            "type": "string",
            "description": "Optional description.",
            "example": "",
        },
        "private": {
            "type": "boolean",
            "description": "Private list.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_twitter_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "create_list",
        name=input_data["name"],
        description=input_data.get("description", ""),
        private=input_data.get("private", False),
    )


@action(
    name="get_twitter_list",
    description="Get a Twitter/X list by ID.",
    action_sets=["twitter_lists"],
    input_schema={
        "list_id": {
            "type": "string",
            "description": "List ID.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_twitter_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "get_list", list_id=input_data["list_id"])


@action(
    name="update_twitter_list",
    description="Update a Twitter/X list's name, description, or privacy.",
    action_sets=["twitter_lists"],
    input_schema={
        "list_id": {
            "type": "string",
            "description": "List ID.",
            "example": "1234567890",
        },
        "name": {"type": "string", "description": "New name.", "example": ""},
        "description": {
            "type": "string",
            "description": "New description.",
            "example": "",
        },
        "private": {
            "type": "boolean",
            "description": "Private flag.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_twitter_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "update_list",
        list_id=input_data["list_id"],
        name=input_data.get("name") or None,
        description=input_data.get("description")
        if input_data.get("description") is not None
        else None,
        private=input_data.get("private"),
    )


@action(
    name="delete_twitter_list",
    description="Delete a Twitter/X list.",
    action_sets=["twitter_lists"],
    input_schema={
        "list_id": {
            "type": "string",
            "description": "List ID.",
            "example": "1234567890",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_twitter_list(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "delete_list", list_id=input_data["list_id"])


@action(
    name="list_twitter_owned_lists",
    description="List the lists owned by a user (defaults to the authed user).",
    action_sets=["twitter_lists", "twitter"],
    input_schema={
        "user_id": {
            "type": "string",
            "description": "User ID. Leave empty for self.",
            "example": "",
        },
        "max_results": {"type": "integer", "description": "Max lists.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_owned_lists(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_owned_lists",
        user_id=input_data.get("user_id") or None,
        max_results=input_data.get("max_results", 100),
    )


@action(
    name="add_twitter_list_member",
    description="Add a user to a Twitter/X list.",
    action_sets=["twitter_lists"],
    input_schema={
        "list_id": {
            "type": "string",
            "description": "List ID.",
            "example": "1234567890",
        },
        "user_id": {
            "type": "string",
            "description": "User ID to add.",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_twitter_list_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "add_list_member",
        list_id=input_data["list_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="remove_twitter_list_member",
    description="Remove a user from a Twitter/X list.",
    action_sets=["twitter_lists"],
    input_schema={
        "list_id": {
            "type": "string",
            "description": "List ID.",
            "example": "1234567890",
        },
        "user_id": {
            "type": "string",
            "description": "User ID to remove.",
            "example": "44196397",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_twitter_list_member(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "remove_list_member",
        list_id=input_data["list_id"],
        user_id=input_data["user_id"],
    )


@action(
    name="list_twitter_list_members",
    description="List members of a Twitter/X list.",
    action_sets=["twitter_lists"],
    input_schema={
        "list_id": {
            "type": "string",
            "description": "List ID.",
            "example": "1234567890",
        },
        "max_results": {"type": "integer", "description": "Max users.", "example": 100},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_list_members(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_list_members",
        list_id=input_data["list_id"],
        max_results=input_data.get("max_results", 100),
    )


@action(
    name="list_twitter_list_tweets",
    description="List recent tweets in a Twitter/X list.",
    action_sets=["twitter_lists"],
    input_schema={
        "list_id": {
            "type": "string",
            "description": "List ID.",
            "example": "1234567890",
        },
        "max_results": {
            "type": "integer",
            "description": "Max tweets.",
            "example": 100,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_list_tweets(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_list_tweets",
        list_id=input_data["list_id"],
        max_results=input_data.get("max_results", 100),
    )


# ------------------------------------------------------------------
# Direct Messages
# Sub-set: twitter_dms
# ------------------------------------------------------------------


@action(
    name="send_twitter_dm",
    description="Send a one-on-one direct message on Twitter/X (creates the conversation if needed).",
    action_sets=["twitter_dms", "twitter"],
    input_schema={
        "participant_id": {
            "type": "string",
            "description": "Recipient user_id (numeric).",
            "example": "44196397",
        },
        "text": {"type": "string", "description": "Message text.", "example": "Hello!"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_twitter_dm(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "send_dm_to_user",
        participant_id=input_data["participant_id"],
        text=input_data["text"],
    )


@action(
    name="send_twitter_dm_to_conversation",
    description="Send a DM into an existing conversation by ID.",
    action_sets=["twitter_dms"],
    input_schema={
        "dm_conversation_id": {
            "type": "string",
            "description": "Conversation ID.",
            "example": "1234567890-987654321",
        },
        "text": {
            "type": "string",
            "description": "Message text.",
            "example": "Following up...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def send_twitter_dm_to_conversation(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "send_dm_to_conversation",
        dm_conversation_id=input_data["dm_conversation_id"],
        text=input_data["text"],
    )


@action(
    name="create_twitter_group_dm",
    description="Create a new group DM conversation and send the first message.",
    action_sets=["twitter_dms"],
    input_schema={
        "participant_ids": {
            "type": "array",
            "description": "List of user_ids to add.",
            "example": ["44196397", "987654321"],
        },
        "text": {
            "type": "string",
            "description": "First message.",
            "example": "Hi everyone",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_twitter_group_dm(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "create_group_dm",
        participant_ids=input_data["participant_ids"],
        text=input_data["text"],
    )


@action(
    name="list_twitter_dm_events",
    description="List recent DM events across all conversations for the authed user.",
    action_sets=["twitter_dms", "twitter"],
    input_schema={
        "max_results": {
            "type": "integer",
            "description": "Max events.",
            "example": 100,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_dm_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter", "list_dm_events", max_results=input_data.get("max_results", 100)
    )


@action(
    name="list_twitter_dm_events_with_user",
    description="List DM events in the conversation with a specific user.",
    action_sets=["twitter_dms"],
    input_schema={
        "participant_id": {
            "type": "string",
            "description": "Other user's user_id.",
            "example": "44196397",
        },
        "max_results": {
            "type": "integer",
            "description": "Max events.",
            "example": 100,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_twitter_dm_events_with_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "list_dm_events_with_user",
        participant_id=input_data["participant_id"],
        max_results=input_data.get("max_results", 100),
    )


# ------------------------------------------------------------------
# Media
# Sub-set: twitter_media
# ------------------------------------------------------------------


@action(
    name="upload_twitter_media",
    description="Upload an image / GIF / video for use in a tweet. Returns the media_id_string to pass to post_tweet_with_media.",
    action_sets=["twitter_media", "twitter"],
    input_schema={
        "file_path": {
            "type": "string",
            "description": "Local file path.",
            "example": "/tmp/image.jpg",
        },
        "media_category": {
            "type": "string",
            "description": "tweet_image | tweet_gif | tweet_video | dm_image | dm_video.",
            "example": "tweet_image",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def upload_twitter_media(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "twitter",
        "upload_media",
        file_path=input_data["file_path"],
        media_category=input_data.get("media_category", "tweet_image"),
    )


# ------------------------------------------------------------------
# Listener configuration (custom: sync, bespoke success messages)
# Sub-set: twitter_listener
# ------------------------------------------------------------------


@action(
    name="set_twitter_watch_tag",
    description="Set a keyword the Twitter listener watches for in mentions. Only mentions containing this keyword will trigger events.",
    action_sets=["twitter_listener"],
    input_schema={
        "tag": {
            "type": "string",
            "description": "Keyword to watch for. Empty = all mentions.",
            "example": "@craftbot",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_twitter_watch_tag(input_data: dict) -> dict:
    try:
        from craftos_integrations import get_client

        client = get_client("twitter")
        if not client or not client.has_credentials():
            return {
                "status": "error",
                "message": "No Twitter/X credential. Use /twitter login first.",
            }
        tag = input_data.get("tag", "").strip()
        client.set_watch_tag(tag)
        if tag:
            return {
                "status": "success",
                "message": f"Now only triggering on mentions containing '{tag}'.",
            }
        return {
            "status": "success",
            "message": "Watch tag disabled. Triggering on all mentions.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
