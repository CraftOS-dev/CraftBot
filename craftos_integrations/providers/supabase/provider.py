"""Supabase provider — personal access token or OAuth, one credential for
every project the account can reach.

**Auth decision (README "three questions").** Supabase OAuth installs our
app into the user's *organization*: calls act as that user (Q1: user's
identity), Management API rate limits are counted per user/token (Q2:
user's quota), and abuse gets the user's account limited, not every
install (Q3: user's account). All three are "the user's", so OAuth with
our embedded client credentials is the right one-click path. Supabase
OAuth apps are confidential clients (``client_secret_basic``) with PKCE
S256 — confirmed against ``/.well-known/oauth-authorization-server``.

That path needs a registered Supabase OAuth app (Organization settings →
OAuth Apps, redirect URI ``http://localhost:8765``) whose id and secret
land in ``SUPABASE_SHARED_CLIENT_ID`` / ``SUPABASE_SHARED_CLIENT_SECRET``.
Until they are configured ``auth_type`` reports ``"token"`` so the UI does
not offer a button that cannot work; the moment they are set it reports
``"both"`` — nothing else moves. The personal-access-token path is always
available and is the fallback for power users.

**Identity.** A personal access token belongs to a *user* and spans every
organization that user is in. The Management API won't tell an access
token who its user is (``/v1/profile`` answers 403 to PATs), so a PAT
account is keyed ``token:<sha256 fingerprint>`` — or ``user:<gotrue id>``
on the rare occasion the profile is readable. An OAuth grant is scoped to the one organization the user picked on
Supabase's consent screen, so an OAuth account is keyed ``org:<slug>`` —
the same person granting two organizations gets two accounts, which is
exactly how the grants behave.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import asdict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...config import ConfigStore
from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from ...logger import get_logger
from ...oauth_flow import OAuthFlow
from .._shared import ClientListenerAdapter, read_guidance
from .client import (
    SUPABASE_CLIENT_ID_KEY,
    SUPABASE_CLIENT_SECRET_KEY,
    SUPABASE_MGMT,
    SUPABASE_OAUTH_AUTHORIZE,
    SUPABASE_OAUTH_TOKEN,
    SUPABASE_SCOPES,
    SupabaseClient,
    SupabaseConfig,
    SupabaseCredential,
)
from .operations import build_operations

logger = get_logger(__name__)

# Keys users paste by mistake, with the message that sends them to the
# right one. Checked before spending a request — every one of these gets
# an unhelpful 401 from the Management API.
_WRONG_KEY_PREFIXES = (
    (
        "sb_secret_",
        "That's a project secret key (sb_secret_…). It only works for one "
        "project's data API. Create a personal access token instead: "
        "supabase.com/dashboard/account/tokens.",
    ),
    (
        "sb_publishable_",
        "That's a project publishable key (sb_publishable_…), meant for "
        "browsers and apps. Create a personal access token instead: "
        "supabase.com/dashboard/account/tokens.",
    ),
    (
        "eyJ",
        "That looks like a project anon or service_role key (a JWT). Those "
        "only work for one project's data API. Create a personal access "
        "token instead: supabase.com/dashboard/account/tokens.",
    ),
)


def token_fingerprint(token: str) -> str:
    """Stable, non-reversible id for a personal access token.

    The Management API exposes no "who am I" endpoint to access tokens
    (/v1/profile answers 403), so the token itself is the only stable
    thing that identifies the account. Re-connecting with the same token
    updates the account in place; a new token is a new account.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _rejection_message(result: Dict[str, Any]) -> str:
    """Turn a failed validity check into what the user should do."""
    error = str(result.get("error") or "")
    detail = str(result.get("details") or "")[:200]
    if "401" in error:
        return (
            "Supabase rejected the token (401): it's invalid, expired or "
            "revoked. Generate a new one at supabase.com/dashboard/account/tokens "
            "and paste it whole."
        )
    if "403" in error:
        return (
            "Supabase accepted the token but refused to list your "
            f"organizations (403). {detail}".strip()
        )
    return f"Couldn't reach Supabase to check the token: {error} {detail}".strip()


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


class SupabaseProvider:
    id = "supabase"
    family = None  # standalone — no cross-provider alias sharing

    # ----- UI metadata -----
    display_name = "Supabase"
    description = "Postgres database, auth, storage, edge functions and projects"
    icon = "supabase"
    fields = [
        {
            "key": "access_token",
            "label": "Personal Access Token (sbp_…)",
            "placeholder": "sbp_…",
            "password": True,
        },
    ]
    connect_help = [
        "Open supabase.com/dashboard/account/tokens (avatar → Account "
        "preferences → Access Tokens)",
        "Click 'Generate new token' and name it (e.g. 'CraftBot')",
        "Copy the token — it starts with sbp_ and is shown only once",
        "Paste it here. One token covers every project in every organization "
        "you belong to; the agent reads each project's keys on its own",
        "Not a project API key: sb_secret_, sb_publishable_ and anon/"
        "service_role keys won't work here",
    ]
    subcommands = ["invite", "login", "logout", "status"]

    config_class = SupabaseConfig
    config_fields = [
        {
            "key": "default_project_ref",
            "label": "Default project",
            "type": "text",
            "placeholder": "abcdefghijklmnopqrst",
            "help": (
                "Project ref used when an action omits 'project_ref'. Find it in "
                "the project URL (supabase.com/dashboard/project/<ref>) or with "
                "list_supabase_projects."
            ),
        },
        {
            "key": "read_only",
            "label": "Read-only mode",
            "type": "checkbox",
            "help": (
                "Refuse every change — SQL writes, migrations, row edits, "
                "uploads, deploys, project changes. Reads keep working."
            ),
        },
        {
            "key": "max_rows",
            "label": "Max rows per read",
            "type": "number",
            "placeholder": "500",
            "help": "Ceiling on rows select_supabase_rows returns in one call.",
        },
    ]

    client_cls = SupabaseClient

    # ----- auth type follows configuration -----

    @property
    def auth_type(self) -> str:
        """``both`` once our OAuth app's credentials are configured,
        ``token`` until then — never advertise a flow that cannot run."""
        if ConfigStore.get_oauth(SUPABASE_CLIENT_ID_KEY) and ConfigStore.get_oauth(
            SUPABASE_CLIENT_SECRET_KEY
        ):
            return "both"
        return "token"

    # ----- accounts -----

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """``org:<slug>`` for OAuth grants; ``user:<id>`` for personal
        tokens when the profile is readable, else ``token:<fingerprint>``
        (see module docstring). Lowercased; None for junk."""
        if not isinstance(credential, dict):
            return None
        kind = _text(credential.get("auth_kind")).lower()
        org = _text(credential.get("org_slug"))
        user = _text(credential.get("user_id")) or _text(credential.get("email"))
        token_id = _text(credential.get("token_id"))
        if kind == "oauth" and org:
            return f"org:{org}".lower()
        if user:
            return f"user:{user}".lower()
        if token_id:
            return f"token:{token_id}".lower()
        if org:
            return f"org:{org}".lower()
        return None

    def default_alias(self, credential: Dict[str, Any]) -> Optional[str]:
        """Name for a newly connected account. The identity is opaque (a
        token fingerprint or org slug), so suggest what the user knows it
        by: their email, the OAuth organization, or the projects it reaches.
        """
        if not isinstance(credential, dict):
            return None
        for key in ("email", "org_name", "display_name"):
            value = _text(credential.get(key))
            if value:
                return value[:60]
        return None

    def oauth_spec(self) -> OAuthSpec:
        """Supabase's consent screen asks the user which organization to
        grant, so a second connect can pick a different one."""
        return OAuthSpec(
            authorize_url=SUPABASE_OAUTH_AUTHORIZE,
            token_url=SUPABASE_OAUTH_TOKEN,
            scopes=SUPABASE_SCOPES,
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
        """Out-of-band refresh. Operations refresh inline before each
        Management API call; personal access tokens never expire."""
        if _text(credential.get("auth_kind")) != "oauth":
            return None
        holder: Dict[str, Any] = {}
        client = self.build_client(credential, holder.update)
        ok = await asyncio.to_thread(client._refresh_sync)
        return holder or None if ok else None

    # ----- token path -----

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validate a personal access token and capture the user identity.

        Rejects the project-level keys users reach for by mistake before
        spending a request. Unknown prefixes are still tried — Supabase
        has changed token formats before and a strict allow-list would
        lock out a valid new one.
        """
        token = (credentials.get("access_token") or "").strip()
        if not token:
            return False, "Missing Supabase personal access token (access_token).", None
        for prefix, message in _WRONG_KEY_PREFIXES:
            if token.startswith(prefix):
                return False, message, None

        headers = {"Authorization": f"Bearer {token}"}
        # Validity check against an endpoint access tokens are actually
        # granted. /v1/profile is NOT one of them: it carries no permission
        # scope in the API schema and answers 403 to personal access
        # tokens, so it can only ever be a best-effort extra.
        orgs = http_request(
            "GET", f"{SUPABASE_MGMT}/organizations", headers=headers, expected=(200,)
        )
        if "error" in orgs:
            return False, _rejection_message(orgs), None
        org_list = [o for o in (orgs.get("result") or []) if isinstance(o, dict)]
        org_names = [o.get("name") for o in org_list if o.get("name")]

        profile = http_request(
            "GET", f"{SUPABASE_MGMT}/profile", headers=headers, expected=(200,)
        )
        me = (profile.get("result") or {}) if "error" not in profile else {}

        credential = asdict(
            SupabaseCredential(
                access_token=token,
                auth_kind="token",
                token_id=token_fingerprint(token),
                user_id=_text(me.get("gotrue_id")),
                email=_text(me.get("primary_email")),
                username=_text(me.get("username")),
            )
        )
        who = credential["email"] or credential["username"] or "Supabase token"
        # Some tokens list no organizations even though they reach projects
        # (seen live) — so describe reach by projects, not organizations.
        projects = http_request(
            "GET", f"{SUPABASE_MGMT}/projects", headers=headers, expected=(200,)
        )
        project_names = [
            p.get("name")
            for p in ((projects.get("result") or []) if "error" not in projects else [])
            if isinstance(p, dict) and p.get("name")
        ]
        parts = []
        if org_names:
            parts.append(f"{len(org_names)} organization(s): {', '.join(org_names)}")
        if project_names:
            shown = ", ".join(project_names[:5])
            more = f" +{len(project_names) - 5} more" if len(project_names) > 5 else ""
            parts.append(f"{len(project_names)} project(s): {shown}{more}")
        scope = " · ".join(parts) or "no projects visible yet"
        if project_names:
            more = f" +{len(project_names) - 2}" if len(project_names) > 2 else ""
            credential["display_name"] = ", ".join(project_names[:2]) + more
        return True, f"Supabase connected: {who} — {scope}", credential

    # ----- OAuth path -----

    async def run_login(self) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
        """Browser OAuth: authorize → token → read which organization was
        granted. Returns (identity, credential, message)."""
        if self.auth_type != "both":
            return (
                None,
                None,
                "Supabase OAuth isn't configured in this build (missing "
                f"{SUPABASE_CLIENT_ID_KEY}/{SUPABASE_CLIENT_SECRET_KEY}). Connect "
                "with a personal access token instead.",
            )
        flow = OAuthFlow(
            client_id_key=SUPABASE_CLIENT_ID_KEY,
            client_secret_key=SUPABASE_CLIENT_SECRET_KEY,
            auth_url=SUPABASE_OAUTH_AUTHORIZE,
            token_url=SUPABASE_OAUTH_TOKEN,
            # Permissions are fixed on the registered OAuth app; Supabase
            # does not take a scope parameter on authorize.
            scopes="",
            use_pkce=True,
            token_auth_basic=True,
        )
        result = await flow.run()
        access_token = result.get("access_token") or ""
        if not access_token:
            return None, None, f"Supabase OAuth failed: {result.get('error', 'no token')}"

        headers = {"Authorization": f"Bearer {access_token}"}
        orgs = http_request(
            "GET", f"{SUPABASE_MGMT}/organizations", headers=headers, expected=(200,)
        )
        org_list = [o for o in (orgs.get("result") or []) if isinstance(o, dict)] \
            if "error" not in orgs else []
        org = org_list[0] if org_list else {}
        if len(org_list) > 1:
            logger.warning(
                "[SUPABASE] OAuth grant spans %d organizations; keying the "
                "account by the first (%s).", len(org_list), org.get("slug")
            )

        # Best effort — some OAuth grants cannot read /profile.
        profile = http_request(
            "GET", f"{SUPABASE_MGMT}/profile", headers=headers, expected=(200,)
        )
        me = (profile.get("result") or {}) if "error" not in profile else {}

        expires_in = float(result.get("expires_in") or 0)
        credential = asdict(
            SupabaseCredential(
                access_token=access_token,
                auth_kind="oauth",
                refresh_token=result.get("refresh_token") or "",
                token_expiry=time.time() + expires_in if expires_in else 0.0,
                user_id=_text(me.get("gotrue_id")),
                email=_text(me.get("primary_email")),
                username=_text(me.get("username")),
                org_slug=_text(org.get("slug")),
                org_name=_text(org.get("name")),
            )
        )
        identity = self.identity_of(credential)
        label = credential["org_name"] or credential["org_slug"] or "organization"
        message = f"Supabase connected via OAuth: {label}"
        if not identity:
            message += " (organization not captured — stored without an identity)"
        return identity, credential, message

    # ----- agent surface -----

    def operations(self) -> List[Operation]:
        return build_operations()

    def guidance(self) -> str:
        return read_guidance(__file__)

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Optional[ClientListenerAdapter]:
        """No inbound events in v1.

        Supabase's push channels (database webhooks, Realtime) deliver to a
        public URL or a long-lived websocket per project; neither fits the
        per-account listener model without choosing tables to watch.
        Checked dynamically so a future client loop bridges automatically.
        """
        if getattr(client, "supports_listening", False):
            return ClientListenerAdapter(client, emit)
        return None
