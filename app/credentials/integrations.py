"""Host adapter for source accounts. No raw source credential enters a provider."""

import asyncio
import json

from .client import CredentialHostUnavailable
from .invocation import invoke
from .references import parse
from types import SimpleNamespace


METHODS = {
    "figma": {"get_current_user": ("get_figma_current_user", (), {})},
    "slack": {
        "list_channels": (
            "list_slack_channels",
            ("types", "limit", "exclude_archived"),
            {
                "types": "public_channel,private_channel",
                "limit": 100,
                "exclude_archived": True,
            },
        ),
        "get_channel_info": ("get_slack_channel_info", ("channel",), {}),
        "get_channel_history": (
            "get_slack_channel_history",
            ("channel", "limit", "oldest", "latest"),
            {"limit": 100},
        ),
        "list_users": ("list_slack_users", ("limit",), {"limit": 100}),
        "get_user_info": ("get_slack_user_info", ("user_id",), {}),
        "get_thread_replies": (
            "get_slack_thread_replies",
            ("channel", "ts", "limit", "cursor"),
            {"limit": 100},
        ),
    },
}


class SourceOperationFacade:
    """A named-operation interface with references only; no SDK/auth internals."""

    def __init__(self, provider, reference, metadata):
        parse(reference)
        self._provider, self._reference = provider, reference
        self.cred = SimpleNamespace(
            **{
                key: metadata[key]
                for key in ("user_id", "username", "workspace_id")
                if key in metadata
            }
        )

    def __getattr__(self, method):
        rule = METHODS.get(self._provider, {}).get(method)
        if rule is None:
            raise AttributeError("credential_operation_helper_unavailable")

        def call(*args, **kwargs):
            operation, parameters, defaults = rule
            if len(args) > len(parameters) or set(parameters[: len(args)]) & set(
                kwargs
            ):
                raise TypeError("credential_operation_arguments_invalid")
            data = {**defaults, **dict(zip(parameters, args)), **kwargs}
            if self._provider == "slack" and method == "get_user_info":
                data["user"] = data.pop("user_id")
            response = invoke(
                self._reference,
                f"integration_{self._provider}",
                operation,
                data or None,
                subject=f"{self._provider}: {operation}",
            )
            if not 200 <= response["status"] < 300:
                return {"error": "credential_operation_failed"}
            result = json.loads(response["body"])
            return (
                {"ok": True, "result": result} if self._provider == "figma" else result
            )

        if self._provider == "figma":

            async def async_call(*args, **kwargs):
                return await asyncio.to_thread(call, *args, **kwargs)

            return async_call
        return call


class RoutedSourceClient:
    """Run the unchanged provider's normalizers with a dummy, unauthenticated client.

    Context routing only selects a transport. Authority remains the protected
    host's real process binding and native consent, never the ContextVar.
    """

    def __init__(self, provider, reference, metadata):
        self.provider, self.reference = provider.id, reference
        self.sessions = {}
        fake = {
            **metadata,
            **{
                key: "vault-managed"
                for key in (
                    "access_token",
                    "token",
                    "bot_token",
                    "api_key",
                    "personal_api_key",
                    "secret_key",
                    "channel_access_token",
                )
            },
        }
        if provider.id in ("figma", "supabase"):
            fake["auth_kind"] = "pat"
        if provider.id == "twitter":
            fake.update(
                api_key="vault-managed",
                api_secret="vault-managed",
                access_token=metadata.get("access_token", ""),
                access_token_secret=metadata.get("access_token_secret", ""),
            )
        if provider.id == "jira":
            fake.update(
                access_token="",
                cloud_id="",
                email="vault-managed@example.invalid",
                api_token="vault-managed",
            )
        self.client = provider.build_client(fake, lambda updated: None)

    def _request(
        self,
        method,
        url,
        *,
        cancelled,
        headers=None,
        json=None,
        params=None,
        data=None,
        files=None,
        content=None,
        repeat=False,
        **transport_options,
    ):
        import httpx
        from .model_transport import installed_model_helpers, multipart_data
        from .route_policy import match_route
        from urllib.parse import urlencode

        routes = [
            r
            for r in installed_model_helpers()
            if r["helper"] == "integration_" + self.provider
        ]
        if params:
            if self.provider == "telegram_bot" and isinstance(params, dict):
                import json as json_module

                params = {
                    k: json_module.dumps(v) if isinstance(v, list) else v
                    for k, v in params.items()
                }
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        if self.provider == "telegram_bot":
            url = url.replace("/botvault-managed/", "/bot_TOKEN_/")
        matched = match_route(routes, method.upper(), url)
        if matched is None:
            raise CredentialHostUnavailable("credential_destination_denied")
        route, path, query = matched
        body = json if json is not None else data
        if content is not None:
            import base64

            if route.get("request_format") != "image" or not isinstance(content, bytes):
                raise CredentialHostUnavailable("credential_request_invalid")
            body = {
                "data": base64.b64encode(content).decode(),
                "content_type": (headers or {}).get("Content-Type"),
            }
        if files:
            request = httpx.Request(method, url, data=data, files=files)
            body = multipart_data(request.read(), request.headers["Content-Type"])
        payload = (
            {
                "path": path,
                "query": query,
                "data": body,
                "headers": {
                    k: v
                    for k, v in (headers or {}).items()
                    if k in route.get("header_fields", ())
                },
            }
            if route.get("envelope")
            else query
            if method.upper() == "GET"
            else body
        )
        if self.provider == "twitter":
            payload["session"] = {
                name: getattr(self.client._cred, name)
                for name in ("access_token", "access_token_secret")
            }
        arguments = (
            self.reference,
            route["helper"],
            route["operation"],
            payload,
        )
        if repeat and method.upper() == "GET":
            from .operation_session import OperationSession
            import time

            key = route["operation"]
            session = self.sessions.get(key)
            if session is None or session.closed or time.monotonic() >= session.expires:
                if session is not None:
                    session.close()
                session = OperationSession(
                    *arguments[:3], self.provider + " listener: " + key
                )
                self.sessions[key] = session
            result = session.invoke(payload, cancelled=cancelled)
        else:
            result = invoke(
                *arguments,
                subject=self.provider + ": " + route["operation"],
                cancelled=cancelled,
            )
        if route.get("response_format") == "binary" and 200 <= result["status"] < 300:
            import base64
            import json as json_module

            binary = json_module.loads(result["body"])
            result = {
                **result,
                "body": base64.b64decode(binary["data"], validate=True),
                "content_type": binary["media_type"],
            }
        return httpx.Response(
            result["status"],
            content=result["body"].encode()
            if isinstance(result["body"], str)
            else result["body"],
            headers={"Content-Type": result["content_type"]},
        )

    def make_source_listener(self, provider, cursor, emit):
        from .listeners import SourceListener

        return SourceListener(self, provider, cursor, emit)

    def close_sessions(self):
        for session in self.sessions.values():
            session.close()
        self.sessions.clear()

    def __getattr__(self, name):
        if name in ("_headers", "_bot_headers", "_load", "_ensure_token"):
            raise AttributeError("credential_auth_client_unavailable")
        value = getattr(self.client, name)
        if self.provider == "discord" and name.startswith("user_"):
            return value  # Existing generated user session retains its transport.
        if not callable(value):
            return value
        import inspect
        from threading import Event
        from functools import partial
        from craftos_integrations.helpers.source_requests import using

        if inspect.iscoroutinefunction(value):

            async def asynchronous(*args, **kwargs):
                cancelled = Event()
                try:
                    with using(partial(self._request, cancelled=cancelled)):
                        return await value(*args, **kwargs)
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

            return asynchronous

        def synchronous(*args, **kwargs):
            with using(partial(self._request, cancelled=Event())):
                return value(*args, **kwargs)

        return synchronous


class SavedSourceOperations:
    def __init__(self, providers=()):
        self.providers = {p.id: p for p in providers}

    def client_for(self, provider_id, reference, metadata):
        if provider_id in self.providers:
            return RoutedSourceClient(self.providers[provider_id], reference, metadata)
        return SourceOperationFacade(provider_id, reference, metadata)

    def connect(self, provider_id, reference, *, public_metadata=None):
        parse(reference)
        public_metadata = public_metadata or {}
        metadata_fields = {
            "whatsapp_business": {"phone_number_id"},
            "twitter": {"access_token", "access_token_secret"},
        }
        if public_metadata and set(public_metadata) != metadata_fields.get(
            provider_id, set()
        ):
            raise CredentialHostUnavailable("credential_account_verification_failed")
        body = None
        if provider_id == "twitter":
            if set(public_metadata) != metadata_fields[provider_id]:
                raise CredentialHostUnavailable(
                    "credential_account_verification_failed"
                )
            body = {"path": {}, "query": {}, "data": None, "session": public_metadata}
        if provider_id == "whatsapp_business":
            import re

            phone = public_metadata.get("phone_number_id")
            if not isinstance(phone, str) or not re.fullmatch(r"[0-9]{5,32}", phone):
                raise CredentialHostUnavailable(
                    "credential_account_verification_failed"
                )
            body = {"path": {"phone_number_id": phone}, "query": {}, "data": None}
        response = invoke(
            reference,
            f"integration_{provider_id}",
            "verify",
            body,
            subject=f"Connect {provider_id} saved account",
        )
        if response["status"] != 200:
            raise CredentialHostUnavailable("credential_account_verification_failed")
        data = json.loads(response["body"])
        if type(data) is not dict or data.get("ok") is False:
            raise CredentialHostUnavailable("credential_account_verification_failed")
        if provider_id == "twitter":
            identity = data.get("data", {}).get("id")
            metadata = {
                "auth_kind": "vault",
                "user_id": identity,
                "username": data.get("data", {}).get("username", ""),
                **public_metadata,
            }
        elif provider_id == "github":
            identity = data.get("login")
            metadata = {"auth_kind": "vault", "username": identity}
        elif provider_id == "figma":
            identity = str(data["id"]) if type(data.get("id")) in (str, int) else None
            metadata = {"auth_kind": "vault", "user_id": identity}
        elif provider_id == "slack" and data.get("ok") is True:
            identity = data.get("team_id")
            metadata = {
                "auth_kind": "vault",
                "workspace_id": identity,
                "user_id": data.get("user_id"),
            }
        else:
            if provider_id not in self.providers:
                raise CredentialHostUnavailable(
                    "credential_account_verification_failed"
                )
            if provider_id == "telegram_bot":
                data = data.get("result", {})
            identity = str(
                data.get("id")
                or data.get("accountId")
                or data.get("portalId")
                or data.get("userId")
                or data.get("account_id")
                or data.get("workspace_id")
                or "vault-" + str(parse(reference).credential_id)
            )
            metadata = {"auth_kind": "vault", "account_id": identity}
            if provider_id == "whatsapp_business":
                if identity != public_metadata["phone_number_id"]:
                    raise CredentialHostUnavailable(
                        "credential_account_verification_failed"
                    )
                metadata["phone_number_id"] = identity
            from .model_transport import installed_model_helpers
            from urllib.parse import urlsplit

            route = next(
                (
                    r
                    for r in installed_model_helpers()
                    if r["helper"] == "integration_" + provider_id
                    and r["operation"] == "verify"
                ),
                None,
            )
            if route:
                origin = urlsplit(route["endpoint"])
                metadata.update(
                    host=f"https://{origin.netloc}",
                    domain=origin.netloc,
                    site_url=f"https://{origin.netloc}",
                )
            for field in ("bot_id", "bot_user_id", "hub_id", "user_id"):
                metadata[field] = identity
            if isinstance(data.get("username"), str):
                metadata["bot_username"] = data["username"]
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            raise CredentialHostUnavailable("credential_account_verification_failed")
        return identity, metadata

    async def execute(self, provider_id, operation, reference, input_data):
        # UI shaping flags never become arbitrary provider query parameters.
        data = dict(input_data)
        data.pop("include_metadata", None)
        if provider_id == "figma" and operation == "get_figma_current_user":
            data = None
        from .invocation import invoke_async

        response = await invoke_async(
            reference,
            f"integration_{provider_id}",
            operation,
            data,
            subject=f"{provider_id}: {operation}",
        )
        if not 200 <= response["status"] < 300:
            return {"error": "credential_operation_failed"}
        result = json.loads(response["body"])
        if provider_id == "slack" and result.get("ok") is not True:
            return {"error": "credential_operation_failed"}
        return {"status": "success", "result": result}
