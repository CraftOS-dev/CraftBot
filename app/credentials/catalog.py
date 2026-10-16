"""Immutable host helper catalog. No provider discovery from agent settings."""

from .contracts import CredentialKind, HelperOperation
from .helpers import HttpsCredentialCheck, HttpsJsonOperation


def specification(item):
    if type(item) is not dict:
        raise ValueError("invalid_helper")
    common = {"helper", "operation", "kind", "endpoint", "secret_field"}
    form_fields = {
        "login_page",
        "success_url",
        "username_field",
        "password_field",
        "csrf_field",
        "cookie_names",
    }
    extra = {
        "type",
        "method",
        "auth_header",
        "auth_prefix",
        "protocol",
        "query_fields",
        "path_fields",
        "envelope",
        "request_format",
        "response_format",
        "max_response_bytes",
        "header_fields",
    } | form_fields
    if set(item) - common - extra:
        raise ValueError("invalid_helper")
    arguments = (
        HelperOperation(item["helper"], item["operation"]),
        CredentialKind(item["kind"]),
        item["endpoint"],
        item.get("secret_field"),
    )
    if item.get("type") == "form" and not (
        set(item) & {"method", "auth_header", "auth_prefix", "protocol", "query_fields"}
    ):
        from .browser_helper import HttpsFormLogin

        if type(item.get("cookie_names")) is not list:
            raise ValueError("invalid_browser_cookies")

        return HttpsFormLogin(
            *arguments,
            **{
                key: tuple(value) if key == "cookie_names" else value
                for key, value in item.items()
                if key in form_fields
            },
        )
    if item.get("type", "check") == "check" and not (set(item) & (extra - {"type"})):
        return HttpsCredentialCheck(*arguments)
    if item.get("type") == "json":
        if set(item) & form_fields:
            raise ValueError("invalid_helper")
        if "query_fields" in item and type(item["query_fields"]) is not list:
            raise ValueError("invalid_helper_query")
        return HttpsJsonOperation(
            *arguments,
            method=item.get("method", "POST"),
            auth_header=item.get("auth_header", "Authorization"),
            auth_prefix=item.get("auth_prefix", "Bearer "),
            protocol=item.get("protocol", "json"),
            query_fields=tuple(item.get("query_fields", [])),
            path_fields=tuple(item.get("path_fields", [])),
            envelope=item.get("envelope", False),
            request_format=item.get("request_format", "json"),
            response_format=item.get("response_format", "json"),
            max_response_bytes=item.get("max_response_bytes", 2_000_000),
            header_fields=tuple(item.get("header_fields", [])),
        )
    raise ValueError("invalid_helper")


def model_helpers():
    # Endpoints match the provider factory. Custom hosts require an explicit
    # reviewed installation descriptor; mutable settings cannot install helpers.
    result = []
    for provider, base, protocol in (
        ("openai", "https://api.openai.com/v1", "openai"),
        ("openrouter", "https://openrouter.ai/api/v1", "openai"),
        ("anthropic", "https://api.anthropic.com/v1", "anthropic"),
        ("byteplus", "https://ark.ap-southeast.bytepluses.com/api/v3", "openai"),
        ("minimax", "https://api.minimax.io/v1", "openai"),
        ("deepseek", "https://api.deepseek.com", "openai"),
        ("moonshot", "https://api.moonshot.ai/v1", "openai"),
        ("grok", "https://api.x.ai/v1", "openai"),
        ("glm", "https://api.z.ai/api/paas/v4", "openai"),
        ("fugu", "https://api.sakana.ai/v1", "openai"),
        ("groq", "https://api.groq.com/openai/v1", "openai"),
        ("mistral", "https://api.mistral.ai/v1", "openai"),
        ("together", "https://api.together.ai/v1", "openai"),
        ("fireworks", "https://api.fireworks.ai/inference/v1", "openai"),
        ("cerebras", "https://api.cerebras.ai/v1", "openai"),
        ("qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "openai"),
        ("huggingface", "https://router.huggingface.co/v1", "openai"),
        ("nvidia", "https://integrate.api.nvidia.com/v1", "openai"),
        ("perplexity", "https://api.perplexity.ai", "openai"),
    ):
        routes = (
            (("messages", "POST"), ("models", "GET"))
            if protocol == "anthropic"
            else (
                ("chat/completions", "POST"),
                ("responses", "POST"),
                ("models", "GET"),
                ("embeddings", "POST"),
                ("images/generations", "POST"),
            )
        )
        for path, method in routes:
            result.append(
                {
                    "type": "json",
                    "helper": f"model_{provider}",
                    "operation": path.replace("/", "_"),
                    "kind": "api_key",
                    "endpoint": f"{base}/{path}",
                    "method": method,
                    "max_response_bytes": 64_000_000
                    if path == "images/generations"
                    else 2_000_000,
                    "protocol": protocol,
                    "auth_header": "x-api-key"
                    if protocol == "anthropic"
                    else "Authorization",
                    "auth_prefix": "" if protocol == "anthropic" else "Bearer ",
                }
            )
    for model in (
        "gemini-2.0-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-3-pro-image",
    ):
        result.append(
            {
                "type": "json",
                "helper": "model_gemini",
                "operation": f"generate_{model}",
                "kind": "api_key",
                "endpoint": f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                "max_response_bytes": 64_000_000,
                "auth_header": "x-goog-api-key",
                "auth_prefix": "",
            }
        )
    result.append(
        {
            "type": "json",
            "helper": "model_gemini",
            "operation": "embed_text-embedding-004",
            "kind": "api_key",
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent",
            "auth_header": "x-goog-api-key",
            "auth_prefix": "",
        }
    )
    result.append(
        {
            "type": "json",
            "helper": "model_gemini",
            "operation": "create_cache",
            "kind": "api_key",
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/cachedContents",
            "auth_header": "x-goog-api-key",
            "auth_prefix": "",
        }
    )
    result.append(
        {
            "type": "json",
            "helper": "model_gemini",
            "operation": "models",
            "kind": "api_key",
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
            "method": "GET",
            "auth_header": "x-goog-api-key",
            "auth_prefix": "",
        }
    )
    for operation, path in (("credits", "credits"), ("auth_key", "auth/key")):
        result.append(
            {
                "type": "json",
                "helper": "model_openrouter",
                "operation": operation,
                "kind": "api_key",
                "endpoint": f"https://openrouter.ai/api/v1/{path}",
                "method": "GET",
            }
        )
    result.append(
        {
            "type": "json",
            "helper": "model_google",
            "operation": "custom_search",
            "kind": "api_key",
            "endpoint": "https://customsearch.googleapis.com/customsearch/v1",
            "method": "GET",
            "query_fields": ["q", "cx", "num"],
            "auth_header": "x-goog-api-key",
            "auth_prefix": "",
        }
    )
    result.append(
        {
            "type": "json",
            "helper": "model_bedrock",
            "operation": "converse_default",
            "kind": "service_secret",
            "secret_field": "secret_access_key",
            "protocol": "aws_bedrock",
            "endpoint": "https://bedrock-runtime.us-east-1.amazonaws.com/model/us.anthropic.claude-haiku-4-5-20251001-v1:0/converse",
        }
    )
    return result + media_helpers()


def media_helpers():
    result = []

    def route(provider, operation, endpoint, method="POST", **extra):
        from .route_policy import path_names

        result.append(
            {
                "type": "json",
                "helper": "model_" + provider,
                "operation": operation,
                "kind": "api_key",
                "endpoint": endpoint,
                "method": method,
                "envelope": True,
                "path_fields": list(path_names(endpoint)),
                **extra,
            }
        )

    for action in ("generateContent", "embedContent", "predict", "predictLongRunning"):
        route(
            "gemini",
            "model_" + action,
            "https://generativelanguage.googleapis.com/v1beta/models/:model:" + action,
            auth_header="x-goog-api-key",
            auth_prefix="",
            max_response_bytes=64_000_000,
        )
    for path in (
        "/operations/:operation_id",
        "/models/:model/operations/:operation_id",
    ):
        route(
            "gemini",
            "poll_" + str(len(result)),
            "https://generativelanguage.googleapis.com/v1beta" + path,
            "GET",
            auth_header="x-goog-api-key",
            auth_prefix="",
        )
    route(
        "gemini",
        "delete_cache",
        "https://generativelanguage.googleapis.com/v1beta/cachedContents/:cache_id",
        "DELETE",
        auth_header="x-goog-api-key",
        auth_prefix="",
    )
    for path in (
        "/v1beta/files/:file_id:download",
        "/download/v1beta/files/:file_id:download",
        "/v1beta/files/:file_id",
    ):
        route(
            "gemini",
            "download_" + str(len(result)),
            "https://generativelanguage.googleapis.com" + path,
            "GET",
            auth_header="x-goog-api-key",
            auth_prefix="",
            query_fields=["alt"],
            response_format="binary",
            max_response_bytes=64_000_000,
        )
    route(
        "openai",
        "images_edits",
        "https://api.openai.com/v1/images/edits",
        request_format="multipart",
        max_response_bytes=64_000_000,
    )
    route(
        "openai",
        "audio_transcriptions",
        "https://api.openai.com/v1/audio/transcriptions",
        request_format="multipart",
        response_format="text",
    )
    route(
        "openai",
        "audio_speech",
        "https://api.openai.com/v1/audio/speech",
        response_format="binary",
        max_response_bytes=64_000_000,
    )
    route(
        "byteplus",
        "video_submit",
        "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks",
    )
    route(
        "byteplus",
        "video_poll",
        "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks/:task_id",
        "GET",
    )
    return result


def integration_helpers():
    result = [
        {
            "type": "json",
            "helper": f"integration_{provider}",
            "operation": "verify",
            "kind": "api_key",
            "endpoint": endpoint,
            "method": "GET",
            "auth_header": header,
            "auth_prefix": prefix,
        }
        for provider, endpoint, header, prefix in (
            ("github", "https://api.github.com/user", "Authorization", "Bearer "),
            ("figma", "https://api.figma.com/v1/me", "X-Figma-Token", ""),
            ("slack", "https://slack.com/api/auth.test", "Authorization", "Bearer "),
        )
    ]
    result.extend(authentication_helpers())
    result.append(
        {
            "type": "json",
            "helper": "integration_figma",
            "operation": "get_figma_current_user",
            "kind": "api_key",
            "endpoint": "https://api.figma.com/v1/me",
            "method": "GET",
            "auth_header": "X-Figma-Token",
            "auth_prefix": "",
        }
    )
    for name, path, query in (
        (
            "list_slack_channels",
            "conversations.list",
            ["types", "limit", "exclude_archived", "cursor"],
        ),
        ("get_slack_channel_info", "conversations.info", ["channel"]),
        (
            "get_slack_channel_history",
            "conversations.history",
            ["channel", "limit", "oldest", "latest", "cursor"],
        ),
        ("list_slack_users", "users.list", ["limit", "cursor"]),
        ("get_slack_user_info", "users.info", ["user"]),
        (
            "get_slack_thread_replies",
            "conversations.replies",
            ["channel", "ts", "limit", "cursor"],
        ),
    ):
        result.append(
            {
                "type": "json",
                "helper": "integration_slack",
                "operation": name,
                "kind": "api_key",
                "endpoint": f"https://slack.com/api/{path}",
                "method": "GET",
                "query_fields": query,
            }
        )
    import json
    from pathlib import Path

    for provider, endpoint, prefix in (
        ("discord", "https://discord.com/api/v10/users/@me", "Bot "),
        ("stripe", "https://api.stripe.com/v1/account", "Bearer "),
        ("notion", "https://api.notion.com/v1/users/me", "Bearer "),
        ("hubspot", "https://api.hubapi.com/account-info/v3/details", "Bearer "),
        ("posthog", "https://us.posthog.com/api/users/@me/", "Bearer "),
        ("supabase", "https://api.supabase.com/v1/profile", "Bearer "),
        ("line", "https://api.line.me/v2/bot/info", "Bearer "),
        ("telegram_bot", "https://api.telegram.org/bot_TOKEN_/getMe", "Bearer "),
    ):
        result.append(
            {
                "type": "json",
                "helper": "integration_" + provider,
                "operation": "verify",
                "kind": "api_key",
                "endpoint": endpoint,
                "method": "GET",
                "auth_prefix": prefix,
                **({"protocol": "telegram"} if provider == "telegram_bot" else {}),
            }
        )
    result.append(
        {
            "type": "json",
            "helper": "integration_jira",
            "operation": "verify",
            "kind": "service_secret",
            "secret_field": "api_token",
            "protocol": "basic",
            "endpoint": "https://jira.example.invalid/rest/api/3/myself",
            "method": "GET",
        }
    )
    result.append(
        {
            "type": "json",
            "helper": "integration_whatsapp_business",
            "operation": "verify",
            "kind": "api_key",
            "endpoint": "https://graph.facebook.com/v21.0/:phone_number_id",
            "method": "GET",
            "envelope": True,
            "path_fields": ["phone_number_id"],
        }
    )
    result.append(
        {
            "type": "json",
            "helper": "integration_discord",
            "operation": "gateway_events",
            "kind": "api_key",
            "endpoint": "https://gateway.discord.gg/",
            "method": "GET",
            "protocol": "discord_gateway",
        }
    )
    return (
        result
        + json.loads(
            Path(__file__).with_name("provider_routes.json").read_text(encoding="utf-8")
        )
        + oauth_helpers()
    )


def oauth_helpers():
    # Match confidential-client exchanges already performed by shipped clients.
    # Token persistence remains exclusively with those clients.
    result = []
    for provider, endpoint, basic, json_body in (
        ("google", "https://oauth2.googleapis.com/token", False, False),
        ("slack", "https://slack.com/api/oauth.v2.access", False, False),
        ("linkedin", "https://www.linkedin.com/oauth/v2/accessToken", False, False),
        ("hubspot", "https://api.hubapi.com/oauth/v1/token", False, False),
        ("figma", "https://api.figma.com/v1/oauth/token", True, False),
        ("figma", "https://api.figma.com/v1/oauth/refresh", True, False),
        ("notion", "https://api.notion.com/v1/oauth/token", True, True),
        ("supabase", "https://api.supabase.com/v1/oauth/token", True, False),
        ("line", "https://api.line.me/oauth2/v3/token", False, False),
    ):
        result.append(
            {
                "type": "json",
                "helper": "oauth_" + provider,
                "operation": "exchange_" + str(len(result)),
                "kind": "api_key",
                "endpoint": endpoint,
                "method": "POST",
                "envelope": True,
                "request_format": "json" if json_body else "form",
                "protocol": "oauth_basic"
                if basic
                else "oauth_json"
                if json_body
                else "oauth_form",
            }
        )
    return result


def authentication_helpers():
    result = [
        {
            "type": "json",
            "helper": "integration_twitter",
            "operation": "verify",
            "kind": "service_secret",
            "secret_field": "api_secret",
            "endpoint": "https://api.twitter.com/2/users/me",
            "method": "GET",
            "protocol": "twitter_oauth1",
            "envelope": True,
        }
    ]
    for operation, protocol, endpoint in (
        (
            "tenant_token",
            "lark_token",
            "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        ),
        (
            "websocket_endpoint",
            "lark_websocket",
            "https://open.larksuite.com/callback/ws/endpoint",
        ),
    ):
        result.append(
            {
                "type": "json",
                "helper": "auth_lark",
                "operation": operation,
                "kind": "api_key",
                "endpoint": endpoint,
                "protocol": protocol,
            }
        )
    for operation in ("send_code", "complete", "qr_login", "complete_password"):
        result.append(
            {
                "type": "json",
                "helper": "auth_telegram_user",
                "operation": operation,
                "kind": "service_secret",
                "secret_field": "api_hash",
                "endpoint": "https://api.telegram.org/mtproto/" + operation,
                "protocol": "telegram_mtproto",
            }
        )
    return result
