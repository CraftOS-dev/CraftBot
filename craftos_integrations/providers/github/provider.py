"""GitHub bridge provider — account-bound wrapper over its API client.

Bridge pattern (see slack/provider.py for the full binding rationale):
``GitHubClient`` keeps its entire API surface;
only the credential plumbing is overridden by a small binding mixin so
the credential is injected per account and never read from
``github.json``. ``operations()`` is empty and ``guidance()`` blank —
the action functions remain the tool surface; account routing
happens centrally in the host adapter.

GitHub is token-only (personal access tokens): ``oauth_spec()`` raises
NotImplementedError (the conformance suite's explicit token-only
declaration) and there is no ``run_login``. PATs do not auto-refresh, so
``refresh()`` returns None.

One account = one GitHub **user**; identity is the GitHub username
(``login``), lowercased — GitHub usernames are case-insensitive.

The one direct disk write the binding must intercept: the client's
``start_listening`` backfills ``cred.username`` from ``GET /user`` when
it differs and saves the credential file . The
binding pre-syncs the username through ``persist`` instead, so that
save never fires and the update lands on the right account entry.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from .client import GITHUB_API, GitHubClient, GitHubConfig, GitHubCredential
from .._shared import ClientListenerAdapter

_CRED_FIELDS = {f.name for f in fields(GitHubCredential)}


class GitHubClientBinding:
    """Overrides GitHubClient's disk plumbing: credential is injected per
    account. MRO puts this before the API client:

        class BoundGitHubClient(GitHubClientBinding, GitHubClient): pass

    No token refresh — PATs are non-rotating — but ``_persist`` IS used:
    ``start_listening`` backfills the stored username from the
    API and would write ``github.json`` (cross-wiring secondaries), so
    the binding routes that one update through ``persist`` instead.
    """

    _cred: Optional[GitHubCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = GitHubCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> GitHubCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    async def start_listening(self, callback) -> None:
        """Pre-sync the username so that save never fires.

        ``start_listening`` calls ``GET /user`` and, when the
        stored ``username`` differs from the live login, writes the
        credential to the single-account file. Doing the same
        check here first — persisting through ``self._persist`` — leaves
        the backfill branch (``cred.username != username``) false, so its
        ``save_credential`` is never reached. Costs one extra cheap
        ``GET /user`` at listener start; keeps the poll loop unforked.
        """
        if not self._listening:
            me = await self.get_authenticated_user()
            if "error" not in me:
                username = me.get("result", {}).get("login", "") or ""
                cred = self._load()
                if username and cred.username != username:
                    cred.username = username
                    self._persist(asdict(cred))
        await super().start_listening(callback)


class BoundGitHubClient(GitHubClientBinding, GitHubClient):
    """GitHubClient with per-account credential binding (see GitHubClientBinding)."""


class GitHubProvider:
    id = "github"
    display_name = "GitHub"
    # ----- UI metadata -----
    description = "Repositories, issues, and pull requests"
    icon = "github"
    fields = [
        {
            "key": "access_token",
            "label": "Personal Access Token",
            "placeholder": "ghp_...",
            "password": True,
        },
    ]
    connect_help = [
        "Open GitHub: github.com/settings/tokens",
        "Click 'Generate new token' → 'Generate new token (classic)'",
        "Set scopes: at minimum 'repo' (issues + PRs) - add 'workflow' if needed",
        "Copy the ghp_... token before leaving the page (shown once)",
    ]
    config_class = GitHubConfig
    config_fields = [
        {
            "key": "watch_tag",
            "label": "Watch tag",
            "type": "text",
            "placeholder": "@craftbot",
            "help": "Trigger keyword in PR/issue comments. Leave empty to react to all events.",
        },
        {
            "key": "watch_repos",
            "label": "Watched repos",
            "type": "list",
            "placeholder": "owner/repo",
            "help": "Comma-separated. Leave empty to watch every repo the token has access to.",
        },
    ]

    family = None  # standalone — no cross-provider alias sharing
    client_cls = BoundGitHubClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """GitHub username (``login``), lowercased. None for raw-token
        credentials saved before the username was captured."""
        try:
            username = credential.get("username")
        except AttributeError:
            return None
        if isinstance(username, str) and username.strip():
            return username.strip().lower()
        return None

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError("github is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # personal access tokens do not auto-refresh

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Token verification:
        ``GET /user`` with the PAT; same ``fields`` key (``access_token``).
        The API's ``login`` is stored as ``username`` so ``identity_of``
        resolves the account immediately.
        """
        token = (credentials.get("access_token") or "").strip()
        if not token:
            return (
                False,
                "A GitHub personal access token is required. "
                "Generate one at: https://github.com/settings/tokens",
                None,
            )

        result = http_request(
            "GET",
            f"{GITHUB_API}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            expected=(200,),
        )
        if "error" in result:
            return False, f"GitHub auth failed: {result['error']}", None
        data = result["result"]

        credential = asdict(
            GitHubCredential(
                access_token=token,
                username=data.get("login", ""),
            )
        )
        return (
            True,
            f"GitHub connected as @{data.get('login')} ({data.get('name', '')})",
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
        """Notification poll listener — the API client's own
        ``start_listening`` loop (``GET /notifications`` every 15s with
        If-Modified-Since + in-memory seen-id dedup), reused verbatim via
        the generic adapter. No restart-safe cursor, same as under the
        client's own loop."""
        return ClientListenerAdapter(client, emit)
