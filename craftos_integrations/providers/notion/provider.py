"""Notion provider — multi-account wrapper over the legacy ``NotionClient``.

API surface comes from the legacy client (all Notion REST methods live
there, unchanged); the binding below only replaces its disk credential
plumbing with the injected per-account credential.

One connected account = one Notion workspace: the OAuth grant is issued
per workspace via Notion's native workspace picker, and the access token
never expires (``refresh()`` returns None).
"""

from __future__ import annotations

import copy
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...integrations.notion import NotionClient, NotionCredential, NotionHandler
from .._google import read_guidance
from .operations import build_operations

# Real endpoints from the legacy NotionHandler.oauth flow.
NOTION_AUTH_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"

# Notion's authorize page includes a native workspace picker, so
# has_chooser=True; ``owner=user`` mirrors the legacy OAuthFlow params.
NOTION_AUTH_PARAMS = {"owner": "user"}


class NotionClientBinding:
    """Overrides NotionClient's disk plumbing: credential is injected per
    account; there is no token refresh (Notion tokens don't expire). MRO
    puts this before the legacy client:

        class BoundNotionClient(NotionClientBinding, NotionClient): pass
    """

    _cred: Optional[NotionCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        # OAuth invites store "access_token"; manual token entry (and the
        # old notion.json) store "token" — accept both.
        token = credential.get("token") or credential.get("access_token") or ""
        self._cred = NotionCredential(token=token)
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> NotionCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundNotionClient(NotionClientBinding, NotionClient):
    """NotionClient with per-account credential binding (see NotionClientBinding)."""


class NotionProvider:
    id = "notion"
    family = None
    display_name = "Notion"

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Workspace id (falling back to bot id) from the OAuth response.

        Old token-only shapes ({"token": "secret_..."}) carry neither —
        return None so the core stores them under LEGACY_IDENTITY and
        upgrades in place on the next re-auth.
        """
        for key in ("workspace_id", "bot_id"):
            value = credential.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url=NOTION_AUTH_URL,
            token_url=NOTION_TOKEN_URL,
            scopes=(),  # Notion OAuth has no scope parameter
            extra_authorize_params=dict(NOTION_AUTH_PARAMS),
            has_chooser=True,  # native workspace picker on the authorize page
        )

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = BoundNotionClient()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # Notion integration tokens do not expire

    async def run_login(self) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
        """Full add-account flow via the legacy handler's OAuthFlow — the
        machinery behind the legacy ``invite()`` subcommand (Basic-auth
        JSON token exchange, no userinfo endpoint; workspace metadata
        arrives in the token response itself). The manual token-entry
        ``login()`` path is host UI territory and is not ported here.

        A *copy* of the shared flow gets the provider spec's
        ``extra_authorize_params`` (``owner=user``, same as legacy)
        applied — the shared handler instance is never mutated.

        Returns (identity, credential, message). Identity is computed by
        ``identity_of`` (workspace id, falling back to bot id). When the
        token response carries neither, the credential is returned with
        identity None — the core stores it under LEGACY_IDENTITY and
        upgrades it in place on the next re-auth.
        """
        oauth = copy.copy(NotionHandler.oauth)
        oauth.extra_auth_params = dict(self.oauth_spec().extra_authorize_params)
        result = await oauth.run()
        if "error" in result and not result.get("access_token"):
            return None, None, f"Notion OAuth failed: {result['error']}"
        raw = result.get("raw") or {}
        credential = {
            # build_client accepts "token" (the legacy key) or "access_token".
            "token": result.get("access_token", ""),
            "workspace_id": raw.get("workspace_id") or "",
            "bot_id": raw.get("bot_id") or "",
            "workspace_name": raw.get("workspace_name") or "",
        }
        identity = self.identity_of(credential)
        ws_name = raw.get("workspace_name") or "default"
        message = f"Notion connected via CraftOS integration: {ws_name}"
        if not identity:
            message += (
                " (no workspace id returned — stored as the legacy account "
                "until the next re-auth)"
            )
        return identity, credential, message

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ):
        return None  # Notion is request-response only (no event listening)
