"""Slack provider — the first non-Google multi-account provider.

Establishes the non-Google binding pattern: reuse the battle-tested API
surface of the legacy ``SlackClient`` unchanged, and override only its
credential plumbing with a small binding mixin (mirroring
``GoogleClientBinding``): the credential is injected per account by
``build_client`` and never read from ``spec.cred_file`` (which is
single-account and would cross-wire secondaries).

Slack bot tokens do not expire, so there is no refresh path: the binding
has no ``refresh_access_token`` and ``refresh()`` returns None (the
contract's "non-expiring" signal). ``persist`` is still accepted and
stored for contract symmetry — future providers with rotating tokens
(Outlook, HubSpot) call it exactly like the Google binding does.

One account = one Slack **workspace**; identity is the team id from the
credential (lowercased). OAuth parameters are referenced from the legacy
handler's ``OAuthFlow`` so the provider spec can never drift from it.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...integrations.slack import SLACK_SCOPES, SlackClient, SlackCredential, SlackHandler
from .listener import SlackListener
from .operations import build_operations

_CRED_FIELDS = {f.name for f in fields(SlackCredential)}


class SlackClientBinding:
    """Overrides SlackClient's disk plumbing: credential is injected per
    account. MRO puts this before the legacy client:

        class BoundSlackClient(SlackClientBinding, SlackClient): pass

    No token refresh — Slack bot tokens are non-expiring, so ``_persist``
    is never called (kept so the build_client contract is uniform across
    providers).
    """

    _cred: Optional[SlackCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = SlackCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> SlackCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundSlackClient(SlackClientBinding, SlackClient):
    """SlackClient with per-account credential binding (see SlackClientBinding)."""


class SlackProvider:
    id = "slack"
    display_name = "Slack"
    family = None  # standalone — no cross-provider alias sharing
    client_cls = BoundSlackClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Slack team (workspace) id, lowercased. None for pre-multi-account raw-token
        credentials saved before the team id was captured."""
        team_id = credential.get("workspace_id")
        if isinstance(team_id, str) and team_id.strip():
            return team_id.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url=SlackHandler.oauth.auth_url,
            token_url=SlackHandler.oauth.token_url,
            scopes=tuple(s for s in SLACK_SCOPES.split(",") if s),
            # Slack's authorize page always shows a workspace picker — no
            # extra params needed to add a *different* workspace.
            has_chooser=True,
        )

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # Slack bot tokens are non-expiring

    async def run_login(self) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
        """Full add-account flow via the legacy handler's OAuthFlow — the
        machinery behind the legacy ``invite()`` subcommand (HTTPS
        localhost callback, ``oauth.v2.access`` exchange; the bot token
        and team metadata arrive in the raw token response, Slack has no
        OAuthFlow userinfo endpoint). The raw-bot-token ``login()`` path
        is host UI territory and is not ported here.

        A *copy* of the shared flow gets the provider spec's
        ``extra_authorize_params`` applied (empty — Slack's authorize
        page always shows its own workspace picker); the shared handler
        instance is never mutated.

        Returns (identity, credential, message). Identity is computed by
        ``identity_of`` (team id). When Slack returns no team id the
        credential is returned with identity None — the core stores it
        under LEGACY_IDENTITY and upgrades it in place on the next
        re-auth.
        """
        oauth = copy.copy(SlackHandler.oauth)
        oauth.extra_auth_params = dict(self.oauth_spec().extra_authorize_params)
        result = await oauth.run()
        if "error" in result and not result.get("access_token"):
            return None, None, f"Slack OAuth failed: {result['error']}"
        raw = result.get("raw") or {}
        # Slack signals failure with HTTP 200 + ok:false — same check as
        # the legacy invite().
        if not raw.get("ok"):
            return None, None, f"Slack OAuth token exchange failed: {raw.get('error')}"

        bot_token = raw.get("access_token", "")
        team = raw.get("team") or {}
        team_id = team.get("id", "")
        team_name = team.get("name", team_id)
        credential = asdict(
            SlackCredential(
                bot_token=bot_token,
                workspace_id=team_id,
                team_name=team_name,
            )
        )
        identity = self.identity_of(credential)
        message = f"Slack connected via CraftOS app: {team_name} ({team_id})"
        if not identity:
            message = (
                "Slack connected, but no team id was returned — stored as "
                "the legacy account until the next re-auth."
            )
        return identity, credential, message

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        path = Path(__file__).parent / "GUIDANCE.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> SlackListener:
        """Workspace poll listener (legacy loop re-homed — see listener.py)."""
        return SlackListener(client, cursor, emit)
