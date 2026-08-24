"""LINE provider — an auth-layer bridge port.

Bridge pattern (see slack/provider.py for the full binding rationale):
the battle-tested legacy ``LineClient`` API surface is reused unchanged,
with only its credential plumbing overridden by a small binding mixin —
the credential is injected per account by ``build_client`` and never read
from ``spec.cred_file`` (which is single-account and would cross-wire
secondaries). Operations and guidance stay with the legacy action layer
(``operations()`` returns ``[]``); only account routing is centralized.

LINE is token-only: credentials come from the LINE Developers console
(channel access token + channel secret), so ``oauth_spec()`` raises
NotImplementedError and connect goes through ``verify_token`` — the same
``GET /v2/bot/info`` check the legacy ``LineHandler.login()`` runs, which
also captures the bot's ``userId`` as the stable account identity.

Long-lived channel access tokens do not expire on a refresh schedule, so
``refresh()`` returns None. LINE delivers inbound messages via webhooks
only (no long-poll; ``LineClient.supports_listening`` is False), so
``make_listener`` returns None — no inbound events from a desktop agent.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from ...integrations.line import LINE_API_BASE, LineClient, LineCredential

_CRED_FIELDS = {f.name for f in fields(LineCredential)}


class LineClientBinding:
    """Overrides LineClient's disk plumbing: credential is injected per
    account. MRO puts this before the legacy client:

        class BoundLineClient(LineClientBinding, LineClient): pass

    No token refresh — long-lived channel access tokens don't rotate, so
    ``_persist`` is never called (kept so the build_client contract is
    uniform across providers).
    """

    _cred: Optional[LineCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = LineCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> LineCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundLineClient(LineClientBinding, LineClient):
    """LineClient with per-account credential binding (see LineClientBinding)."""


class LineProvider:
    id = "line"
    display_name = "LINE"
    family = None  # standalone — no cross-provider alias sharing
    client_cls = BoundLineClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """The bot's LINE user id (captured at verify time), lowercased.
        None for credentials saved before identity capture existed."""
        bot_user_id = credential.get("bot_user_id")
        if isinstance(bot_user_id, str) and bot_user_id.strip():
            return bot_user_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError("line is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # long-lived channel access tokens are non-expiring

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Same verification the legacy ``LineHandler.login()`` runs:
        ``GET /v2/bot/info`` with the channel access token; same credential
        dict shape, with the bot's ``userId`` captured as ``bot_user_id``
        so ``identity_of`` gets a stable account key.

        Input keys mirror the handler's ``fields``: ``channel_access_token``
        (required) and ``channel_secret`` (optional — webhook signature
        verification only, not needed for send).
        """
        token = (credentials.get("channel_access_token") or "").strip()
        secret = (credentials.get("channel_secret") or "").strip()
        if not token:
            return False, "Channel access token is required.", None

        result = http_request(
            "GET",
            f"{LINE_API_BASE}/info",
            headers={"Authorization": f"Bearer {token}"},
            expected=(200,),
        )
        if "error" in result:
            return False, f"Invalid channel access token: {result['error']}", None
        info = result.get("result") or {}

        credential = asdict(
            LineCredential(
                channel_access_token=token,
                channel_secret=secret,
                bot_user_id=info.get("userId", ""),
                bot_display_name=info.get("displayName", ""),
            )
        )
        label = info.get("displayName") or info.get("userId") or "bot"
        return True, f"LINE connected: {label}", credential

    def operations(self) -> List[Operation]:
        return []  # bridge provider — legacy actions remain the operation surface

    def guidance(self) -> str:
        return ""  # bridge provider — legacy action docs remain the guidance

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        """LINE is webhook-push only — the legacy client has no listen loop
        (``supports_listening`` is False), so there are no inbound events."""
        return None
