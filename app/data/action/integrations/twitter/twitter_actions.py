from agent_core import action


@action(
    name="post_tweet",
    description="Post a tweet on Twitter/X.",
    action_sets=["twitter"],
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
    action_sets=["twitter"],
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
    action_sets=["twitter"],
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
    name="search_tweets",
    description="Search recent tweets on Twitter/X.",
    action_sets=["twitter"],
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
    action_sets=["twitter"],
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
    name="like_tweet",
    description="Like a tweet on Twitter/X.",
    action_sets=["twitter"],
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
    name="retweet",
    description="Retweet a tweet on Twitter/X.",
    action_sets=["twitter"],
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
    name="get_twitter_user",
    description="Look up a Twitter/X user by username.",
    action_sets=["twitter"],
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
    action_sets=["twitter"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_twitter_me(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("twitter", "get_me")


# ------------------------------------------------------------------
# Watch Settings (custom: bespoke success messages, no async)
# ------------------------------------------------------------------


@action(
    name="set_twitter_watch_tag",
    description="Set a keyword the Twitter listener watches for in mentions. Only mentions containing this keyword will trigger events.",
    action_sets=["twitter"],
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
