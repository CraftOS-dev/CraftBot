"""Source-reference hooks; missing transports fail closed before SDK/network I/O."""

import json

from ..config import ConfigStore


def is_reference(value):
    return isinstance(value, str) and value.startswith("craftbot-vault:")


def lark_exchange(operation, app_id, reference):
    hook = ConfigStore.extras.get("source_lark_request")
    if hook is None:
        raise RuntimeError("credential_lark_helper_unavailable")
    return hook(operation, app_id, reference)


async def telegram_exchange(operation, api_id, reference, **data):
    hook = ConfigStore.extras.get("source_telegram_auth")
    if hook is None:
        raise RuntimeError("credential_telegram_helper_unavailable")
    return await hook(operation, str(api_id), reference, **data)


def lark_ws_client(sdk, app_id, reference, **kwargs):
    from lark_oapi.ws.client import JSON, EndpointResp

    class SourceClient(sdk):
        def _get_conn_url(self):
            from urllib.parse import urlsplit

            body = lark_exchange("websocket_endpoint", app_id, reference)
            response = JSON.unmarshal(json.dumps(body), EndpointResp)
            if response.code != 0 or response.data is None:
                raise RuntimeError("credential_lark_connection_failed")
            target = urlsplit(response.data.URL)
            if (
                target.scheme != "wss"
                or not target.hostname
                or not target.hostname.endswith(".larksuite.com")
                or target.username
                or target.password
                or target.port not in (None, 443)
            ):
                raise RuntimeError("credential_lark_connection_failed")
            if response.data.ClientConfig is not None:
                self._configure(response.data.ClientConfig)
            return response.data.URL

    return SourceClient(app_id, "vault-managed", **kwargs)


def telegram_session_client(sdk, session, api_id, api_hash):
    if api_hash != "vault-managed":
        return sdk(session, api_id, api_hash)

    class SessionClient(sdk):
        async def start(self, *args, **kwargs):
            await self.connect()
            if not await self.is_user_authorized():
                await self.disconnect()
                raise RuntimeError(
                    "session_expired: reconnect through the protected login helper"
                )
            return self

    return SessionClient(session, api_id, "vault-managed")
