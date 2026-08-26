"""Twitter/X bridge provider — account-bound wrapper over its API client.

Bridge pattern (see slack/provider.py for the full binding rationale):
``TwitterClient`` keeps its entire API surface;
only the credential plumbing is overridden by a small binding mixin so
the credential is injected per account and never read from
``twitter.json``. ``operations()`` is empty and ``guidance()`` blank —
the action functions remain the tool surface; account routing
happens centrally in the host adapter.

Twitter is token-only in this integration (OAuth 1.0a user context:
consumer key/secret + access token/secret pasted from the developer
portal — no browser OAuth dance), so ``oauth_spec()`` raises
NotImplementedError and there is no ``run_login``. OAuth 1.0a user
tokens do not expire → ``refresh()`` returns None.

One account = one Twitter/X **user**; identity is the numeric user id
from ``GET /2/users/me`` (stable across handle renames), falling back to
the username for pre-bridge credentials saved without one. Lowercased.

Per-instance state audit (two listening accounts): the poll
watermarks ``_since_id``/``_seen_ids`` live on the client instance
(set in ``__init__``), so bound clients never fight over them. The only
shared state is the ``twitter_config.json`` watch-tag file — deliberate
shared *config* (every account filters mentions by the same tag), not
per-account listen state, so it is left alone.

The one direct disk write the binding must intercept: the client's
``start_listening`` backfills ``cred.user_id``/``cred.username`` from
``GET /2/users/me`` when they differ and saves the credential
file . The binding pre-syncs both fields
through ``persist`` instead, so that save never fires and the
update lands on the right account entry.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from .client import (
    TWITTER_API,
    TwitterClient,
    TwitterConfig,
    TwitterCredential,
    _oauth1_header,
)
from .._shared import ClientListenerAdapter

_CRED_FIELDS = {f.name for f in fields(TwitterCredential)}

# Same field keys the TwitterHandler.fields declares.
_REQUIRED_KEYS = ("api_key", "api_secret", "access_token", "access_token_secret")


class TwitterClientBinding:
    """Overrides TwitterClient's disk plumbing: credential is injected per
    account. MRO puts this before the API client:

        class BoundTwitterClient(TwitterClientBinding, TwitterClient): pass

    No token refresh — OAuth 1.0a user tokens are non-expiring — but
    ``_persist`` IS used: ``start_listening`` backfills the
    stored user_id/username from the API and would write ``twitter.json``
    (cross-wiring secondaries), so the binding routes that one update
    through ``persist`` instead.
    """

    _cred: Optional[TwitterCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = TwitterCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> TwitterCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    async def start_listening(self, callback) -> None:
        """Pre-sync user_id/username so that save never fires.

        ``start_listening`` calls ``GET /2/users/me`` and, when
        the stored ``user_id`` or ``username`` differs from the live
        account, writes the credential to the single-account file.
        Doing the same check here first — persisting through
        ``self._persist`` — leaves the branch false, so its
        ``save_credential`` is never reached. Costs one extra cheap
        ``get_me`` at listener start; keeps the poll loop unforked.
        """
        if not self._listening:
            me = await self.get_me()
            if "error" not in me:
                data = me.get("result", {}) or {}
                username = data.get("username", "") or ""
                user_id = data.get("id", "") or ""
                cred = self._load()
                if (user_id and cred.user_id != user_id) or (
                    username and cred.username != username
                ):
                    cred.user_id = user_id or cred.user_id
                    cred.username = username or cred.username
                    self._persist(asdict(cred))
        await super().start_listening(callback)


class BoundTwitterClient(TwitterClientBinding, TwitterClient):
    """TwitterClient with per-account credential binding (see TwitterClientBinding)."""


class TwitterProvider:
    id = "twitter"
    family = None  # standalone — no cross-provider alias sharing
    display_name = "Twitter/X"
    # ----- UI metadata -----
    description = "Tweets, mentions, and timeline"
    icon = "twitter"
    fields = [
        {
            "key": "api_key",
            "label": "Consumer Key",
            "placeholder": "Enter Consumer key",
            "password": True,
        },
        {
            "key": "api_secret",
            "label": "Consumer Secret",
            "placeholder": "Enter Consumer secret",
            "password": True,
        },
        {
            "key": "access_token",
            "label": "Access Token",
            "placeholder": "Enter access token",
            "password": True,
        },
        {
            "key": "access_token_secret",
            "label": "Access Token Secret",
            "placeholder": "Enter access token secret",
            "password": True,
        },
    ]
    connect_help = [
        "Open developer.twitter.com/en/portal/dashboard",
        "Sign up for a developer account if you haven't (free tier works for posting)",
        "Create a Project, then a Standalone App inside it",
        "App settings → User authentication settings → enable OAuth 1.0a with Read+Write",
        "Keys and tokens tab → copy Consumer Key + Consumer Secret",
        "Scroll down → Generate Access Token + Secret → copy both",
    ]
    config_class = TwitterConfig
    config_fields = [
        {
            "key": "watch_tag",
            "label": "Watch tag",
            "type": "text",
            "placeholder": "@craftbot",
            "help": "Trigger keyword in mentions. Leave empty to react to all mentions.",
        },
    ]

    client_cls = BoundTwitterClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """Numeric user id from ``GET /2/users/me`` (stable across handle
        renames), falling back to the username for older credentials
        saved without one. Lowercased; None for pre-bridge junk shapes."""
        try:
            user_id = credential.get("user_id")
            username = credential.get("username")
        except AttributeError:
            return None
        if isinstance(user_id, str) and user_id.strip():
            return user_id.strip().lower()
        if isinstance(username, str) and username.strip():
            return username.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        # Deliberate: OAuth 1.0a keys are pasted from the developer portal
        # (the connect flow's token flow) — no browser OAuth dance.
        raise NotImplementedError("twitter is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # OAuth 1.0a user tokens do not expire

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Token verification:
        ``GET /2/users/me`` signed with the client module's own OAuth 1.0a
        helper; same ``fields`` keys (api_key, api_secret, access_token,
        access_token_secret). The API's ``id``/``username`` are stored as
        ``user_id``/``username`` so ``identity_of`` resolves immediately.
        """
        values = {k: (credentials.get(k) or "").strip() for k in _REQUIRED_KEYS}
        missing = [k for k in _REQUIRED_KEYS if not values[k]]
        if missing:
            return (
                False,
                "Missing Twitter credentials: "
                + ", ".join(missing)
                + ". All four OAuth 1.0a values are required — get them from "
                "developer.x.com → Dashboard → Keys and tokens.",
                None,
            )

        url = f"{TWITTER_API}/users/me"
        params = {"user.fields": "id,name,username"}
        auth_hdr = _oauth1_header(
            "GET",
            url,
            params,
            values["api_key"],
            values["api_secret"],
            values["access_token"],
            values["access_token_secret"],
        )
        result = http_request(
            "GET",
            url,
            headers={"Authorization": auth_hdr},
            params=params,
            expected=(200,),
        )
        if "error" in result:
            return (
                False,
                f"Twitter auth failed: {result['error']}. "
                "Check your API credentials.\n"
                "Get them from developer.x.com → Dashboard → Keys and tokens",
                None,
            )
        data = (result["result"] or {}).get("data", {})

        credential = asdict(
            TwitterCredential(
                api_key=values["api_key"],
                api_secret=values["api_secret"],
                access_token=values["access_token"],
                access_token_secret=values["access_token_secret"],
                user_id=data.get("id", ""),
                username=data.get("username", ""),
            )
        )
        return (
            True,
            f"Twitter/X connected as @{data.get('username')} ({data.get('name', '')})",
            credential,
        )

    def operations(self) -> List[Operation]:
        return []  # bridge provider — action functions stay the surface

    def guidance(self) -> str:
        return ""

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> ClientListenerAdapter:
        """Mentions poll listener — the API client's own
        ``start_listening`` loop (``GET /2/users/{id}/mentions`` every 30s
        with since_id + in-memory seen-id dedup, optional watch-tag
        filter), reused verbatim via the generic adapter. The watermarks
        are instance attributes, so concurrent bound accounts don't
        collide. No restart-safe cursor — the client's own loop keeps its
        watermark in memory."""
        return ClientListenerAdapter(client, emit)
