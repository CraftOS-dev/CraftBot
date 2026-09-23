"""PostHog provider — personal-API-key auth over a credential-injected client.

PostHog is token-only *today*: the user mints a personal API key
(``phx_...``) scoped to the resources the agent may touch. Keys never
expire, so ``refresh()`` returns None.

**On OAuth.** PostHog does support OAuth 2.0 for third-party apps, and
``oauth_spec()`` below returns its real endpoints and our scope set. It is
not wired into ``auth_type`` yet because PostHog uses Client ID Metadata
Documents: the ``client_id`` is a URL on a domain we control, serving a
JSON metadata file that lists our redirect URIs. That document has to be
hosted before the flow can work, which is infrastructure rather than
code. Once it is live, set ``POSTHOG_CLIENT_ID`` to its URL and change
``auth_type`` to ``"both"`` — nothing else here needs to move. PKCE
(S256) is supported and the token endpoint accepts ``none`` client
authentication, so no client secret is needed and none should ever be
embedded.

One account = one PostHog project. Identity is ``<org_id>:<project_id>``
rather than the user's email, because the same person routinely holds
keys for several projects across several organizations and each is a
separate connected account.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from ...logger import get_logger
from .._shared import ClientListenerAdapter, read_guidance
from .client import (
    POSTHOG_DEFAULT_HOST,
    POSTHOG_HOSTS,
    POSTHOG_OAUTH_AUTHORIZE,
    POSTHOG_OAUTH_TOKEN,
    POSTHOG_SCOPES,
    PostHogClient,
    PostHogConfig,
    PostHogCredential,
)
from .operations import build_operations

logger = get_logger(__name__)


def normalize_host(raw: Optional[str]) -> str:
    """User-typed host → a usable origin.

    Accepts the region shorthands ('us', 'eu'), a bare domain, or a full
    URL, and strips any trailing slash or ``/api`` suffix the user pasted
    along with it. Empty input falls back to US Cloud.
    """
    text = (raw or "").strip().rstrip("/")
    if not text:
        return POSTHOG_DEFAULT_HOST
    lowered = text.lower()
    if lowered in POSTHOG_HOSTS:
        return POSTHOG_HOSTS[lowered]
    if not lowered.startswith(("http://", "https://")):
        text = f"https://{text}"
    if text.lower().endswith("/api"):
        text = text[: -len("/api")]
    return text.rstrip("/")


class PostHogProvider:
    id = "posthog"
    family = None  # standalone — no cross-provider alias sharing

    # ----- UI metadata -----
    display_name = "PostHog"
    description = "Product analytics, feature flags, and dashboards"
    auth_type = "token"
    icon = "posthog"
    fields = [
        {
            "key": "api_key",
            "label": "Personal API Key (phx_…)",
            "placeholder": "phx_…",
            "password": True,
        },
        {
            "key": "host",
            "label": "PostHog host",
            "placeholder": "us, eu, or https://posthog.yourcompany.com",
            "optional": True,
        },
        {
            "key": "project_id",
            "label": "Project ID (optional — detected automatically)",
            "placeholder": "136209",
            "optional": True,
        },
    ]
    connect_help = [
        "In PostHog, click your avatar (top right) → 'Personal API keys'",
        "Click 'Create personal API key' and name it (e.g. 'CraftBot')",
        "Scopes: grant read+write for Query, Insight, Dashboard, Feature "
        "flag, Cohort, Person and Annotation — the agent can only do what "
        "the key allows",
        "Copy the key (starts with phx_) — PostHog shows it only once",
        "Host: type 'us' or 'eu' for PostHog Cloud, or paste your full "
        "self-hosted URL. Leave Project ID blank and it is detected for you",
    ]
    subcommands = ["login", "logout", "status"]

    config_class = PostHogConfig
    config_fields = [
        {
            "key": "default_project_id",
            "label": "Default project",
            "type": "text",
            "placeholder": "136209",
            "help": (
                "Project id used when an action omits 'project_id'. Overrides "
                "the project captured when the account was connected. Use "
                "list_posthog_projects to find ids."
            ),
        },
        {
            "key": "query_timeout_seconds",
            "label": "Query timeout (seconds)",
            "type": "number",
            "placeholder": "60",
            "help": (
                "How long run_posthog_query waits before giving up. Wide date "
                "ranges should use run_posthog_query_async instead of a "
                "longer timeout."
            ),
        },
        {
            "key": "default_date_range",
            "label": "Default date range",
            "type": "text",
            "placeholder": "-7d",
            "help": (
                "Window applied by list_posthog_events when no 'after' is "
                "given. Format: -7d, -24h, -4w, -3m."
            ),
        },
    ]

    client_cls = PostHogClient

    # ----- accounts -----

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """``<org_id>:<project_id>``, lowercased.

        Deliberately not the email: one user commonly connects several
        projects, and each must be a distinct account. Falls back to the
        org alone when the project was not captured, and to None for junk
        or pre-identity credentials.
        """
        if not isinstance(credential, dict):
            return None
        org = credential.get("org_id")
        project = credential.get("project_id")
        org_text = "" if org is None or isinstance(org, (dict, list)) else str(org).strip()
        project_text = (
            ""
            if project is None or isinstance(project, (dict, list))
            else str(project).strip()
        )
        if org_text and project_text:
            return f"{org_text}:{project_text}".lower()
        if org_text:
            return org_text.lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        """PostHog's real OAuth endpoints — see the module docstring for why
        ``auth_type`` is still ``"token"``.

        ``has_chooser=True``: PostHog's authorize screen lets the user pick
        which organization and project to grant, so adding a second
        account does not require logging out first.
        """
        return OAuthSpec(
            authorize_url=POSTHOG_OAUTH_AUTHORIZE,
            token_url=POSTHOG_OAUTH_TOKEN,
            scopes=POSTHOG_SCOPES,
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
        return None  # personal API keys do not expire

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validate the key and capture org + project identity.

        Rejects the two keys users reach for by mistake before spending a
        request: ``phc_`` (project API key — client-side event ingestion)
        and ``phs_`` (project secret key). Neither authenticates the
        management API, and the resulting 401 is unhelpful.

        The success message names the project so the user can tell
        straight away whether they pasted a key for the wrong one.
        """
        token = (credentials.get("api_key") or "").strip()
        host = normalize_host(credentials.get("host"))

        if not token:
            return False, "Missing PostHog personal API key (api_key).", None
        if token.startswith("phc_"):
            return (
                False,
                "That's a project API key (phc_…). Those are for client-side "
                "event capture and can't read the PostHog API. Create a "
                "personal API key instead: avatar → Personal API keys.",
                None,
            )
        if token.startswith("phs_"):
            return (
                False,
                "That's a project secret key (phs_…), which only works for "
                "server-side ingestion. Create a personal API key instead: "
                "avatar → Personal API keys.",
                None,
            )
        if not token.startswith("phx_"):
            return (
                False,
                "That doesn't look like a PostHog personal API key — they "
                "start with phx_. Find one under avatar → Personal API keys.",
                None,
            )

        me = http_request(
            "GET",
            f"{host}/api/users/@me/",
            headers={"Authorization": f"Bearer {token}"},
            expected=(200,),
        )
        if "error" in me:
            detail = str(me.get("details") or "")[:200]
            return (
                False,
                f"PostHog auth failed against {host}: {me['error']}. "
                "Check the key, and check the host — US Cloud keys don't work "
                f"on EU Cloud. {detail}".strip(),
                None,
            )

        data = me.get("result") or {}
        organization = data.get("organization") or {}
        team = data.get("team") or {}

        # An explicit project_id from the connect form wins over the key's
        # current team — a user connecting a second project pastes it.
        project_id = str(credentials.get("project_id") or team.get("id") or "").strip()

        credential = asdict(
            PostHogCredential(
                api_key=token,
                host=host,
                project_id=project_id,
                org_id=str(organization.get("id") or ""),
                user_email=data.get("email") or "",
                org_name=organization.get("name") or "",
                project_name=team.get("name") or "",
            )
        )

        label = " / ".join(
            part
            for part in (organization.get("name"), team.get("name"))
            if part
        ) or (data.get("email") or "PostHog")
        region = "EU Cloud" if "eu.posthog.com" in host else (
            "US Cloud" if "us.posthog.com" in host else host
        )
        message = f"PostHog connected: {label} ({region})"
        if not project_id:
            message += (
                " — no project detected; pass 'project_id' on actions or set a "
                "default project in the integration's config"
            )
        return True, message, credential

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

        PostHog's inbound story is webhooks, which need a public callback
        URL, and polling the query endpoint would burn the tightest rate
        limit the user has. Checked dynamically so a future webhook or
        poll loop on the client bridges automatically.
        """
        if getattr(client, "supports_listening", False):
            return ClientListenerAdapter(client, emit)
        return None
