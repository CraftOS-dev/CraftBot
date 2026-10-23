"""Figma provider: PAT by default, OAuth when host app credentials exist.

Public OAuth requires a Figma-approved app and secure secret deployment.
No shared app secret is embedded here. See INTEGRATION.md.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict, Optional

from ...config import ConfigStore
from ...contracts import OAuthSpec
from ...helpers import request as http_request
from ...oauth_flow import OAuthFlow
from .._shared import read_guidance
from .client import (
    FIGMA_API,
    FIGMA_AUTHORIZE,
    FIGMA_SCOPES,
    FIGMA_TOKEN,
    FigmaClient,
    FigmaConfig,
    FigmaCredential,
)
from .operations import build_operations


def user_identity(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip().lower()
    return text or None


class FigmaProvider:
    id = "figma"
    family = None
    display_name = "Figma"
    description = (
        "Design files, assets, libraries, comments, and browser canvas creation"
    )
    icon = "Figma"
    supports_listening = False
    fields = [
        {
            "key": "access_token",
            "label": "Personal Access Token",
            "placeholder": "Paste your scoped Figma token",
            "password": True,
        }
    ]
    connect_help = [
        "In Figma, open Settings → Security → Personal access tokens and generate a token for CraftBot.",
        "Grant current_user:read, file_content:read, file_metadata:read and file_versions:read.",
        "For comments, grant file_comments:read/write. For libraries, grant library_assets:read, library_content:read and team_library_content:read.",
        "For folder discovery, grant folders:read. Personal tokens return basic folder metadata; full folder metadata requires OAuth with folder_metadata:read. Copy the token and paste it here; reconnect when it expires.",
        "OAuth is also available when the host configures FIGMA_CLIENT_ID and FIGMA_CLIENT_SECRET for an approved Figma app.",
        "To create designs, open Manage → Design in Figma, start the connection, run the published Talk To Figma MCP Plugin in your browser design, and paste its channel. Keep the plugin open. No Figma Desktop, development plugin, extra server, or OAuth application is needed for this workflow.",
    ]
    subcommands = ["login", "logout", "status"]
    client_cls = FigmaClient
    config_class = FigmaConfig
    config_fields = [
        {
            "key": "default_file_key",
            "label": "Default file",
            "type": "text",
            "help": "A Figma file key or design URL used when file_key is omitted.",
        },
        {
            "key": "default_team_id",
            "label": "Default team",
            "type": "text",
            "help": "Numeric team id or team URL. The API cannot list your teams.",
        },
        {
            "key": "cache_ttl_seconds",
            "label": "Read cache (seconds)",
            "type": "number",
            "help": "0 disables caching; values are bounded to 0–300. Cache is isolated by account.",
        },
        {
            "key": "max_document_nodes",
            "label": "Maximum returned document nodes",
            "type": "number",
            "help": "1–2000, default 500. Truncated results tell the agent to request specific nodes.",
        },
    ]

    @property
    def auth_type(self):
        if ConfigStore.get_oauth("FIGMA_CLIENT_ID") and ConfigStore.get_oauth(
            "FIGMA_CLIENT_SECRET"
        ):
            return "both"
        return "token"

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        return (
            user_identity(credential.get("user_id"))
            if isinstance(credential, dict)
            else None
        )

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url=FIGMA_AUTHORIZE,
            token_url=FIGMA_TOKEN,
            scopes=FIGMA_SCOPES,
            has_chooser=True,
        )

    def build_client(self, credential: Dict[str, Any], persist) -> FigmaClient:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    def verify_token(self, credentials: Dict[str, str]):
        token = str(credentials.get("access_token") or "").strip()
        if not token:
            return False, "Missing Figma personal access token.", None
        result = http_request(
            "GET",
            f"{FIGMA_API}/v1/me",
            headers={"X-Figma-Token": token},
            expected=(200,),
        )
        if "error" in result:
            return (
                False,
                "Figma token verification failed. Check token expiry and current_user:read scope.",
                None,
            )
        user = result.get("result") or {}
        identity = user_identity(user.get("id"))
        if not identity:
            return (
                False,
                "Figma returned no usable user id; the account was not saved.",
                None,
            )
        credential = asdict(
            FigmaCredential(
                access_token=token,
                user_id=identity,
                user_email=user.get("email") or "",
                user_name=user.get("handle") or "",
            )
        )
        return (
            True,
            f"Figma connected as {credential['user_email'] or credential['user_name'] or identity}",
            credential,
        )

    async def run_login(self):
        if self.auth_type != "both":
            return (
                None,
                None,
                "Figma OAuth is not configured. Set FIGMA_CLIENT_ID and FIGMA_CLIENT_SECRET, or connect with a personal access token.",
            )
        oauth = OAuthFlow(
            client_id_key="FIGMA_CLIENT_ID",
            client_secret_key="FIGMA_CLIENT_SECRET",
            auth_url=FIGMA_AUTHORIZE,
            token_url=FIGMA_TOKEN,
            userinfo_url=f"{FIGMA_API}/v1/me",
            scopes=" ".join(FIGMA_SCOPES),
            use_pkce=True,
            token_auth_basic=True,
        )
        result = await oauth.run()
        if "error" in result or not result.get("access_token"):
            return (
                None,
                None,
                "Figma OAuth sign-in failed or was cancelled. Check app credentials and the registered redirect URL, then retry.",
            )
        user = result.get("userinfo") or {}
        identity = user_identity(
            user.get("id") or (result.get("raw") or {}).get("user_id_string")
        )
        if not identity:
            return (
                None,
                None,
                "Figma sign-in returned no usable user id. Grant current_user:read and reconnect.",
            )
        credential = asdict(
            FigmaCredential(
                access_token=result["access_token"],
                auth_kind="oauth",
                user_id=identity,
                user_email=user.get("email") or "",
                user_name=user.get("handle") or "",
                refresh_token=result.get("refresh_token") or "",
                token_expiry=time.time() + float(result.get("expires_in") or 0),
            )
        )
        return (
            identity,
            credential,
            f"Figma connected as {credential['user_email'] or identity}",
        )

    async def refresh(self, credential):
        if credential.get("auth_kind", "pat") != "oauth":
            return None
        updated: Dict[str, Any] = {}
        client = self.build_client(credential, updated.update)
        result = await client.refresh_access_token()
        return updated or None if "error" not in result else None

    def operations(self):
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)

    def make_listener(self, client, cursor, emit):
        return None  # No polling; webhook receiver is a separate feature.
