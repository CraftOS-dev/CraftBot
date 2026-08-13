"""Jira provider — auth-layer bridge over the legacy ``JiraClient``.

Bridge port: the legacy Jira actions keep calling the legacy client's API
surface, and only account routing moves to the integration system. So
``operations()`` is empty and ``guidance()`` is "" — this provider exists
for identity, credential storage, token verification, and the listener.

Jira API tokens are Basic-auth (email:token) and never expire, so there
is no refresh path (``refresh()`` returns None) and no OAuth flow
(``oauth_spec`` raises NotImplementedError — the explicit token-only
declaration the conformance suite recognizes).

One account = one (user, site) pair: the same person on two Jira sites is
two accounts, so identity is ``<email-or-accountId>@<site-host>``.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, fields
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from ...contracts import OAuthSpec, Operation
from ...integrations.jira import JiraClient, JiraCredential
from .._shared import LegacyListenerAdapter

_CRED_FIELDS = {f.name for f in fields(JiraCredential)}


def _clean_domain(raw: str) -> str:
    """Mirror the legacy JiraHandler.login() domain normalization:
    strip scheme + trailing slash, and default bare names to
    ``<name>.atlassian.net``."""
    domain = (raw or "").strip().rstrip("/")
    if domain.startswith("https://"):
        domain = domain[len("https://") :]
    if domain.startswith("http://"):
        domain = domain[len("http://") :]
    domain = domain.split("/", 1)[0]
    if domain and "." not in domain:
        domain = f"{domain}.atlassian.net"
    return domain


class JiraClientBinding:
    """Overrides JiraClient's disk plumbing: credential is injected per
    account, never read from ``spec.cred_file`` (single-account, would
    cross-wire secondaries). MRO puts this before the legacy client:

        class BoundJiraClient(JiraClientBinding, JiraClient): pass

    No token refresh — Jira API tokens are non-expiring, so ``_persist``
    is never called (kept so the build_client contract is uniform across
    providers).
    """

    _cred: Optional[JiraCredential]
    _persist: Callable[[Dict[str, Any]], None]

    def bind_credential(
        self, credential: Dict[str, Any], persist: Callable[[Dict[str, Any]], None]
    ) -> None:
        self._cred = JiraCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> JiraCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred


class BoundJiraClient(JiraClientBinding, JiraClient):
    """JiraClient with per-account credential binding (see JiraClientBinding)."""


class JiraProvider:
    id = "jira"
    display_name = "Jira"
    family = None  # standalone — no cross-provider alias sharing
    client_cls = BoundJiraClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        """``<email-or-accountId>@<site-host>``, lowercased.

        Both halves are required: the same person on two Jira sites is two
        accounts, and two people on one site are two accounts. The host
        comes from ``domain`` (Basic-auth shape) or ``site_url`` (OAuth
        shape), scheme stripped. None when either half is missing — the
        core stores such credentials under LEGACY_IDENTITY.
        """
        if not isinstance(credential, dict):
            return None
        user = None
        for key in ("email", "account_id", "accountId"):
            value = credential.get(key)
            if isinstance(value, str) and value.strip():
                user = value.strip().lower()
                break
        if user is None:
            return None
        host = None
        for key in ("domain", "site_url"):
            value = credential.get(key)
            if isinstance(value, str) and value.strip():
                host = _clean_domain(value).lower()
                if host:
                    break
                host = None
        if host is None:
            return None
        return f"{user}@{host}"

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError("jira is token-only")

    def build_client(
        self,
        credential: Dict[str, Any],
        persist: Callable[[Dict[str, Any]], None],
    ) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None  # Jira API tokens are non-expiring

    def verify_token(
        self, credentials: Dict[str, str]
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Same verification the legacy JiraHandler.login() runs:
        normalize the domain, then Basic-auth ``GET /rest/api/3/myself``
        (falling back to v2); same credential keys as the handler's
        ``fields`` (domain, email, api_token). The verified user's
        ``account_id`` is captured alongside — identity already comes
        from email+domain, but the account id is the API-stable user key.
        """
        clean_domain = _clean_domain(credentials.get("domain") or "")
        email = (credentials.get("email") or "").strip()
        api_token = (credentials.get("api_token") or "").strip()
        if not clean_domain or not email or not api_token:
            return (
                False,
                "Jira needs a domain (e.g. mycompany.atlassian.net), your "
                "account email, and an API token from "
                "https://id.atlassian.com/manage-profile/security/api-tokens",
                None,
            )

        raw_auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        auth_headers = {
            "Authorization": f"Basic {raw_auth}",
            "Accept": "application/json",
        }

        data = None
        last_status = 0
        for api_ver in ("3", "2"):
            url = f"https://{clean_domain}/rest/api/{api_ver}/myself"
            try:
                r = httpx.get(
                    url, headers=auth_headers, timeout=15, follow_redirects=True
                )
            except httpx.ConnectError:
                return (
                    False,
                    f"Cannot connect to https://{clean_domain} - check the domain name.",
                    None,
                )
            except Exception as e:
                return False, f"Jira connection error: {e}", None
            if r.status_code == 200:
                data = r.json()
                break
            last_status = r.status_code

        if data is None:
            hints = [f"Tried: https://{clean_domain}/rest/api/3/myself"]
            if last_status == 401:
                hints.append(
                    "Ensure you are using an API token, not your account password."
                )
                hints.append(
                    "The email must match your Atlassian account email exactly."
                )
            elif last_status == 403:
                hints.append(
                    "Your account may not have REST API access. Check Jira permissions."
                )
            elif last_status == 404:
                hints.append(
                    f"Domain '{clean_domain}' not reachable or has no REST API."
                )
            hint_str = "\n".join(f"  - {h}" for h in hints)
            return False, f"Jira auth failed (HTTP {last_status}).\n{hint_str}", None

        credential = asdict(
            JiraCredential(domain=clean_domain, email=email, api_token=api_token)
        )
        account_id = data.get("accountId")
        if isinstance(account_id, str) and account_id.strip():
            credential["account_id"] = account_id.strip()
        display_name = data.get("displayName", email)
        return True, f"Jira connected as {display_name} ({clean_domain})", credential

    def operations(self) -> List[Operation]:
        return []  # bridge provider — legacy jira actions keep the surface

    def guidance(self) -> str:
        return ""  # bridge provider — no v2 operations to guide

    def make_listener(
        self,
        client: Any,
        cursor: Optional[Dict[str, Any]],
        emit: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Optional[LegacyListenerAdapter]:
        """Issue-update poll loop re-used verbatim from the legacy client
        (``supports_listening`` is True); no cursor — the loop keeps its
        watermark in memory and catches up on start."""
        return LegacyListenerAdapter(client, emit)
