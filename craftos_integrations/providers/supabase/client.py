# -*- coding: utf-8 -*-
"""Supabase integration — one credential, two API planes.

Supabase exposes two separate HTTP surfaces and this client covers both:

- **Management API** (``https://api.supabase.com/v1``) — the control plane.
  Projects, organizations, SQL, migrations, edge functions, branches,
  secrets, logs, advisors, service config. Authenticated with the
  connected account's bearer token (a personal access token ``sbp_...``
  or an OAuth access token). One token reaches every project the account
  can see.

- **Project APIs** (``https://<ref>.supabase.co``) — the data plane.
  PostgREST rows, Storage objects, Auth (GoTrue) admin, edge-function
  invocation. Each project needs its *own* key. Rather than make the user
  paste one per project, the client fetches the project's secret key
  through the Management API (``GET /v1/projects/{ref}/api-keys?reveal=true``)
  on first use and caches it in memory for the life of the client. The
  key is never persisted and never returned to the agent.

That secret key bypasses Row Level Security — data-plane operations act
with full privileges, exactly like the dashboard's table editor. See
INTEGRATION.md for the consequences and GUIDANCE.md for how the agent is
told to handle them.

See INTEGRATION.md for identifier shapes, key-format quirks, rate limits
and auth failure modes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import httpx

from ... import BasePlatformClient, load_config, register_client
from ...config import ConfigStore
from ...helpers import Result, arequest
from ...helpers import request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

SUPABASE_API = "https://api.supabase.com"
SUPABASE_MGMT = f"{SUPABASE_API}/v1"

# OAuth — confirmed against /.well-known/oauth-authorization-server.
# Supabase OAuth apps are confidential clients (client_secret_basic/post)
# and support PKCE S256. Referenced by the provider.
SUPABASE_OAUTH_AUTHORIZE = f"{SUPABASE_MGMT}/oauth/authorize"
SUPABASE_OAUTH_TOKEN = f"{SUPABASE_MGMT}/oauth/token"
SUPABASE_CLIENT_ID_KEY = "SUPABASE_SHARED_CLIENT_ID"
SUPABASE_CLIENT_SECRET_KEY = "SUPABASE_SHARED_CLIENT_SECRET"

# The permission set this integration's surface needs. Supabase OAuth apps
# fix their permissions at registration time (org settings → OAuth Apps),
# so this tuple documents what to tick there; it is not sent on the
# authorize URL.
SUPABASE_SCOPES = (
    "organizations:read",
    "projects:read",
    "projects:write",
    "database:read",
    "database:write",
    "analytics:read",
    "auth:read",
    "auth:write",
    "edge_functions:read",
    "edge_functions:write",
    "environment:read",
    "environment:write",
    "secrets:read",
    "secrets:write",
    "storage:read",
    "storage:write",
    "rest:read",
    "rest:write",
)

# Service configs reachable through get/update_supabase_service_config.
# Value: (path under /projects/{ref}/, update method).
SERVICE_CONFIG_PATHS: Dict[str, Tuple[str, str]] = {
    "auth": ("config/auth", "PATCH"),
    "postgrest": ("postgrest", "PATCH"),
    "realtime": ("config/realtime", "PATCH"),
    "storage": ("config/storage", "PATCH"),
    "postgres": ("config/database/postgres", "PUT"),
}

# Log sources for get_supabase_logs → the analytics table behind each.
LOG_SOURCES: Dict[str, str] = {
    "api": "edge_logs",
    "postgres": "postgres_logs",
    "auth": "auth_logs",
    "storage": "storage_logs",
    "realtime": "realtime_logs",
    "edge_function": "function_edge_logs",
    "edge_function_runtime": "function_logs",
    "postgrest": "postgrest_logs",
    "pooler": "supavisor_logs",
}

HEALTH_SERVICES = ("auth", "db", "pooler", "realtime", "rest", "storage")

_EXPECT_READ = (200,)
_EXPECT_WRITE = (200, 201, 202, 204)

# Refresh OAuth access tokens this many seconds before they expire.
_REFRESH_MARGIN = 120


@dataclass
class SupabaseCredential:
    # Bearer token for the Management API: a personal access token
    # (``sbp_...``) or an OAuth access token.
    access_token: str = ""
    # "token" (PAT pasted by the user) or "oauth".
    auth_kind: str = "token"
    refresh_token: str = ""
    # Epoch seconds; 0 = never expires (PATs).
    token_expiry: float = 0.0
    # Identity. PAT accounts span every org the user belongs to and are
    # keyed by a fingerprint of the token (the API won't name the user to
    # a PAT); OAuth grants are scoped to one organization and keyed by it.
    token_id: str = ""
    # Human name suggested for the account at connect time (see
    # SupabaseProvider.default_alias); the identity itself is opaque.
    display_name: str = ""
    user_id: str = ""
    email: str = ""
    username: str = ""
    org_slug: str = ""
    org_name: str = ""


@dataclass
class SupabaseConfig:
    """Post-connect runtime knobs."""

    # Project ref used when an operation omits ``project_ref``.
    default_project_ref: str = ""
    # When True every mutating operation is refused client-side — the same
    # guarantee as the official Supabase MCP server's --read-only flag.
    read_only: bool = False
    # Ceiling on rows returned by SQL helpers and select_supabase_rows.
    max_rows: int = 500


class ReadOnlyModeError(RuntimeError):
    pass


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys the caller did not set, so a PATCH never blanks a field."""
    return {k: v for k, v in payload.items() if v is not None}


def _object_path(path: str) -> str:
    """URL-encode a storage object path, keeping its ``/`` separators."""
    return "/".join(quote(part, safe="") for part in path.strip("/").split("/"))


def _is_jwt(key: str) -> bool:
    return key.startswith("eyJ") and key.count(".") == 2


_DDL_START = re.compile(
    r"^\s*(create|alter|drop|comment\s+on|grant|revoke)\b", re.IGNORECASE
)
_DDL_OBJECT = re.compile(
    r"^\s*(create(?:\s+or\s+replace)?|alter|drop|comment\s+on|grant|revoke)\s+"
    r"(?:unique\s+|materialized\s+|temp(?:orary)?\s+)?"
    r"(table|view|index|function|policy|trigger|type|schema|extension|sequence|"
    r"role|column)?\s*(?:if\s+(?:not\s+)?exists\s+)?((?:\w+\.)?(?:\"[^\"]+\"|\w+))?",
    re.IGNORECASE,
)


def _sql_statements(query: str) -> List[str]:
    """Statements of a SQL script with comments removed (dollar-quoted
    bodies are kept intact so a function body doesn't split)."""
    text = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
    text = re.sub(r"--[^\n]*", " ", text)
    parts, buf, in_dollar = [], [], None
    for token in re.split(r"(\$[A-Za-z_]*\$|;)", text):
        if token is None:
            continue
        if re.fullmatch(r"\$[A-Za-z_]*\$", token):
            in_dollar = None if in_dollar == token else (in_dollar or token)
            buf.append(token)
        elif token == ";" and not in_dollar:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(token)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def ddl_migration_name(query: str) -> Optional[str]:
    """A snake_case migration name if the script changes the schema, else
    None. Temporary objects don't count — they vanish with the session."""
    for statement in _sql_statements(query):
        if not _DDL_START.match(statement):
            continue
        if re.match(r"^\s*create\s+temp(orary)?\b", statement, re.IGNORECASE):
            continue
        m = _DDL_OBJECT.match(statement)
        words = [w for w in (m.groups() if m else ()) if w]
        name = "_".join(words).lower()
        name = re.sub(r"[^a-z0-9]+", "_", name.replace('"', "")).strip("_")
        name = re.sub(r"^(\w+?)_public_", r"\1_", name)  # drop default schema
        return (name or "schema_change")[:60]
    return None


def _ch_literal(value: str) -> str:
    """Quote a value as a ClickHouse string literal (logs SQL)."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _analytics_result(result: Result) -> Result:
    """Analytics endpoints answer HTTP 200 with ``{"error": ...}`` in the
    body when the query fails (bad SQL, unknown table). Surface that as a
    failure instead of a success that happens to contain an error."""
    if "error" in result:
        return result
    body = result.get("result")
    if isinstance(body, dict) and body.get("error"):
        return {"error": "Log query failed", "details": body["error"]}
    if isinstance(body, dict) and "result" in body:
        return {"ok": True, "result": body["result"]}
    return result


def _shape_response(r: httpx.Response, expected: Iterable[int]) -> Result:
    if r.status_code in expected:
        if not r.content:
            return {"ok": True, "result": {}}
        try:
            return {"ok": True, "result": r.json()}
        except Exception:
            return {"ok": True, "result": r.text}
    return {"error": f"API error: {r.status_code}", "details": r.text[:2000]}


@register_client
class SupabaseClient(BasePlatformClient):
    """Supabase client, one instance per connected account.

    Credential-injected: the provider calls ``bind_credential`` before
    use. There is no disk-credential path — Supabase is a greenfield
    integration.
    """

    PLATFORM_ID = "supabase"

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[SupabaseCredential] = None
        self._persist = None
        # project ref → {"secret": key, "publishable": key, "jwt": key|None}
        self._project_keys: Dict[str, Dict[str, Optional[str]]] = {}
        self._token_lock = asyncio.Lock()

    # ── credential plumbing ──────────────────────────────────────────

    def bind_credential(self, credential: Dict[str, Any], persist) -> None:
        known = set(SupabaseCredential.__dataclass_fields__)
        self._cred = SupabaseCredential(
            **{k: v for k, v in credential.items() if k in known}
        )
        self._persist = persist
        self._project_keys.clear()

    def has_credentials(self) -> bool:
        return self._cred is not None and bool(self._cred.access_token)

    def _load(self) -> SupabaseCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    def _config(self) -> SupabaseConfig:
        # Read fresh so a config change takes effect without a restart.
        return load_config("supabase_config.json", SupabaseConfig) or SupabaseConfig()

    def _guard_write(self) -> None:
        if self._config().read_only:
            raise ReadOnlyModeError(
                "Supabase integration is in read-only mode (integration config "
                "'read_only'). Turn it off in Settings → Integrations → Supabase "
                "to allow changes."
            )

    def _ref(self, project_ref: Optional[str]) -> str:
        ref = (project_ref or self._config().default_project_ref or "").strip()
        if not ref:
            raise ValueError(
                "project_ref is required — call list_supabase_projects to find "
                "the 20-character project ref, or set a default project in the "
                "integration config."
            )
        return ref

    def _max_rows(self) -> int:
        return _clamp(self._config().max_rows, 1, 10000, 500)

    # ── OAuth token lifecycle ────────────────────────────────────────

    def _refresh_sync(self) -> bool:
        cred = self._load()
        client_id = ConfigStore.get_oauth(SUPABASE_CLIENT_ID_KEY)
        client_secret = ConfigStore.get_oauth(SUPABASE_CLIENT_SECRET_KEY)
        if not (client_id and client_secret and cred.refresh_token):
            logger.warning(
                "[SUPABASE] Cannot refresh OAuth token (missing client "
                "credentials or refresh token). Reconnect the account."
            )
            return False
        result = http_request(
            "POST",
            SUPABASE_OAUTH_TOKEN,
            data={"grant_type": "refresh_token", "refresh_token": cred.refresh_token},
            headers={
                "Authorization": "Basic "
                + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            },
            expected=(200, 201),
            timeout=30.0,
        )
        if "error" in result:
            logger.warning(f"[SUPABASE] Token refresh failed: {result.get('error')}")
            return False
        data = result.get("result") or {}
        token = data.get("access_token")
        if not token:
            return False
        cred.access_token = token
        cred.refresh_token = data.get("refresh_token") or cred.refresh_token
        expires_in = data.get("expires_in") or 3600
        cred.token_expiry = time.time() + float(expires_in)
        if self._persist:
            self._persist(asdict(cred))
        logger.info("[SUPABASE] OAuth access token refreshed.")
        return True

    async def _ensure_token(self) -> str:
        cred = self._load()
        if (
            cred.auth_kind == "oauth"
            and cred.token_expiry
            and time.time() > cred.token_expiry - _REFRESH_MARGIN
        ):
            async with self._token_lock:
                if time.time() > cred.token_expiry - _REFRESH_MARGIN:
                    await asyncio.to_thread(self._refresh_sync)
        return cred.access_token

    # ── transport: Management API ────────────────────────────────────

    async def _mgmt(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        expected: Iterable[int] = _EXPECT_READ,
        timeout: float = 30.0,
    ) -> Result:
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        result = await arequest(
            method,
            f"{SUPABASE_MGMT}/{path.lstrip('/')}",
            headers=headers,
            params=params,
            json=json_body,
            data=data,
            files=files,
            expected=expected,
            timeout=timeout,
        )
        if result.get("error") == "API error: 403":
            # Supabase's body is a bare {"message":"Forbidden"}; say what it
            # means so the agent stops instead of retrying variations.
            result["details"] = (
                f"{str(result.get('details') or '')[:200]} — Supabase refused this "
                "for the connected account. The token works but lacks "
                "permission here: usually the user's organization role (e.g. "
                "Developer instead of Owner/Administrator) or how the token was "
                "scoped. Retrying won't help; the user must change the role or "
                "connect a token with more access."
            ).strip()
        return result

    async def _mgmt_text(self, path: str, params: Dict[str, Any]) -> Result:
        """GET a Management endpoint whose 200 body may be plain text."""
        token = await self._ensure_token()

        def _go() -> Result:
            try:
                r = httpx.get(
                    f"{SUPABASE_MGMT}/{path.lstrip('/')}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    timeout=60.0,
                )
                return _shape_response(r, _EXPECT_READ)
            except Exception as e:
                return {"error": str(e)}

        return await asyncio.to_thread(_go)

    # ── transport: project data plane ────────────────────────────────

    async def _keys_for(self, ref: str, *, refresh: bool = False) -> Dict[str, Optional[str]]:
        if not refresh and ref in self._project_keys:
            return self._project_keys[ref]
        result = await self._mgmt(
            "GET", f"projects/{ref}/api-keys", params={"reveal": "true"}
        )
        if "error" in result:
            raise RuntimeError(
                f"Could not read API keys for project {ref}: {result['error']} "
                f"{str(result.get('details') or '')[:200]}".strip()
                + " — the connected account needs the secrets:read permission "
                "on this project."
            )
        keys: Dict[str, Optional[str]] = {"secret": None, "publishable": None, "jwt": None}
        legacy_anon: Optional[str] = None
        for item in result.get("result") or []:
            kind = item.get("type")
            name = (item.get("name") or "").lower()
            value = item.get("api_key")
            if not value:
                continue
            if kind == "secret" and not keys["secret"]:
                keys["secret"] = value
            elif kind == "publishable" and not keys["publishable"]:
                keys["publishable"] = value
            elif kind == "legacy" and name == "service_role":
                keys["jwt"] = value
            elif kind == "legacy" and name == "anon":
                legacy_anon = value
        # New-style keys win regardless of the order Supabase lists them in.
        keys["publishable"] = keys["publishable"] or legacy_anon
        if not keys["secret"]:
            keys["secret"] = keys["jwt"]
        if not keys["secret"]:
            raise RuntimeError(
                f"Project {ref} has no secret or service_role key available. "
                "Create a secret key under Project Settings → API Keys."
            )
        self._project_keys[ref] = keys
        return keys

    @staticmethod
    def _project_url(ref: str) -> str:
        return f"https://{ref}.supabase.co"

    async def _data(
        self,
        ref: str,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        content: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        expected: Iterable[int] = _EXPECT_WRITE,
        timeout: float = 60.0,
        prefer_jwt: bool = False,
        raw: bool = False,
    ) -> Tuple[Result, Optional[httpx.Response]]:
        """Request against ``https://<ref>.supabase.co``.

        Retries once with freshly fetched keys on 401, which is what a
        rotated or revoked key looks like. ``raw=True`` hands back the
        response for callers that need headers or bytes.
        """
        url = f"{self._project_url(ref)}/{path.lstrip('/')}"

        def _send(keys: Dict[str, Optional[str]]) -> httpx.Response:
            key = (keys.get("jwt") if prefer_jwt else None) or keys["secret"] or ""
            h = {"apikey": key}
            # Legacy keys are JWTs and go in Authorization too. The new
            # sb_secret_ keys are not JWTs: the gateway rejects them in
            # Authorization and mints the JWT itself from ``apikey``.
            if _is_jwt(key):
                h["Authorization"] = f"Bearer {key}"
            if headers:
                h.update(headers)
            return httpx.request(
                method,
                url,
                params=params,
                json=json_body if content is None else None,
                content=content,
                headers=h,
                timeout=timeout,
            )

        try:
            keys = await self._keys_for(ref)
            r = await asyncio.to_thread(_send, keys)
            if r.status_code == 401:
                keys = await self._keys_for(ref, refresh=True)
                r = await asyncio.to_thread(_send, keys)
        except Exception as e:
            return {"error": str(e)}, None
        if raw:
            return (
                {"ok": True, "result": {}}
                if r.status_code in expected
                else {"error": f"API error: {r.status_code}", "details": r.text[:2000]}
            ), r
        return _shape_response(r, expected), r

    async def _rest(self, ref: str, *args: Any, **kwargs: Any):
        """PostgREST request that survives a stale schema cache.

        PostgREST caches the database schema. Right after a table or
        function is created (apply_supabase_migration / run_supabase_sql)
        it answers 404 PGRST205 / PGRST202 — "could not find the table /
        function in the schema cache" — for a few seconds (seen live). Ask
        it to reload, wait, retry; a real "no such table" still fails, just
        after the retries.
        """
        result, response = await self._data(ref, *args, **kwargs)
        for delay in (1.0, 2.5):
            details = str(result.get("details") or "") if "error" in result else ""
            if "PGRST205" not in details and "PGRST202" not in details:
                break
            # Internal maintenance, not a user write — bypasses read-only.
            await self._mgmt(
                "POST",
                f"projects/{ref}/database/query",
                json_body={"query": "notify pgrst, 'reload schema';"},
                expected=_EXPECT_WRITE,
            )
            await asyncio.sleep(delay)
            result, response = await self._data(ref, *args, **kwargs)
        return result, response

    # ── BasePlatformClient contract ──────────────────────────────────

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        """Supabase has no messaging surface.

        The closest equivalent is invoking an edge function: ``recipient``
        is read as ``<project_ref>/<function_slug>`` and ``text`` is sent as
        the JSON body ``{"message": text}``.
        """
        ref, _, slug = (recipient or "").partition("/")
        if not ref or not slug:
            return {
                "error": "Supabase has no messaging; recipient must be "
                "'<project_ref>/<function_slug>' to invoke an edge function."
            }
        return await self.invoke_function(slug, body={"message": text}, project_ref=ref)

    # =================================================================
    # Account, organizations, projects
    # =================================================================

    async def get_profile(self) -> Result:
        return await self._mgmt("GET", "profile")

    async def list_organizations(self) -> Result:
        """Organizations the account belongs to.

        Some tokens get an empty list here while still reaching projects
        inside an organization (seen live). Then the organizations are
        recovered from the projects, so the agent still has a slug for
        list_supabase_regions / create_supabase_project.
        """
        result = await self._mgmt("GET", "organizations")
        if "error" in result or result.get("result"):
            return result
        projects = await self._mgmt("GET", "projects")
        if "error" in projects:
            return result
        seen: Dict[str, Dict[str, Any]] = {}
        for project in projects.get("result") or []:
            slug = project.get("organization_slug")
            if slug and slug not in seen:
                seen[slug] = {
                    "slug": slug,
                    "name": None,
                    "projects": [],
                    "source": "derived from your projects — this token can't "
                    "list organizations directly",
                }
            if slug:
                seen[slug]["projects"].append(project.get("name"))
        return {"ok": True, "result": list(seen.values())}

    async def list_organization_members(self, organization_slug: str) -> Result:
        result = await self._mgmt("GET", f"organizations/{organization_slug}/members")
        if "403" in str(result.get("error") or ""):
            return {
                "error": "Supabase refused to list this organization's members (403).",
                "details": "Member lists need an organization owner/admin role, or a "
                "token allowed to read the organization. Project operations are "
                "unaffected.",
            }
        return result

    async def list_projects(self, *, organization_slug: Optional[str] = None) -> Result:
        result = await self._mgmt("GET", "projects")
        if "error" in result or not organization_slug:
            return result
        projects = [
            p
            for p in result.get("result") or []
            if p.get("organization_slug") == organization_slug
        ]
        return {"ok": True, "result": projects}

    async def get_project(self, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt("GET", f"projects/{self._ref(project_ref)}")

    async def list_regions(
        self, organization_slug: str, *, continent: Optional[str] = None
    ) -> Result:
        params = _clean({"organization_slug": organization_slug, "continent": continent})
        return await self._mgmt("GET", "projects/available-regions", params=params)

    async def create_project(
        self,
        *,
        name: str,
        organization_slug: str,
        db_pass: Optional[str] = None,
        region: Optional[str] = None,
        desired_instance_size: Optional[str] = None,
    ) -> Result:
        """Create a project. Generates a strong database password when none
        is given and returns it — it is shown once and needed for direct
        Postgres connections."""
        self._guard_write()
        import secrets as _secrets

        generated = not db_pass
        password = db_pass or _secrets.token_urlsafe(24)
        body: Dict[str, Any] = {
            "name": name,
            "organization_slug": organization_slug,
            "db_pass": password,
        }
        if region:
            smart = region.lower() in ("americas", "emea", "apac")
            body["region_selection"] = {
                "type": "smartGroup" if smart else "specific",
                "code": region.lower() if smart else region,
            }
        if desired_instance_size:
            body["desired_instance_size"] = desired_instance_size
        result = await self._mgmt(
            "POST", "projects", json_body=body, expected=_EXPECT_WRITE, timeout=60.0
        )
        if "error" not in result and generated and isinstance(result.get("result"), dict):
            result["result"]["generated_db_password"] = password
        return result

    async def update_project(self, name: str, *, project_ref: Optional[str] = None) -> Result:
        self._guard_write()
        return await self._mgmt(
            "PATCH",
            f"projects/{self._ref(project_ref)}",
            json_body={"name": name},
            expected=_EXPECT_WRITE,
        )

    async def delete_project(self, project_ref: str) -> Result:
        self._guard_write()
        # Explicit ref only — never fall back to the default project here.
        if not project_ref:
            return {"error": "project_ref is required to delete a project."}
        return await self._mgmt(
            "DELETE", f"projects/{project_ref}", expected=_EXPECT_WRITE, timeout=60.0
        )

    async def pause_project(self, project_ref: Optional[str] = None) -> Result:
        self._guard_write()
        return await self._mgmt(
            "POST", f"projects/{self._ref(project_ref)}/pause", expected=_EXPECT_WRITE
        )

    async def restore_project(self, project_ref: Optional[str] = None) -> Result:
        """Un-pause a paused project (POST /restore — not a backup restore)."""
        self._guard_write()
        return await self._mgmt(
            "POST", f"projects/{self._ref(project_ref)}/restore", expected=_EXPECT_WRITE
        )

    async def restart_project(self, project_ref: Optional[str] = None) -> Result:
        self._guard_write()
        return await self._mgmt(
            "POST", f"projects/{self._ref(project_ref)}/restart", expected=_EXPECT_WRITE
        )

    async def get_project_health(
        self,
        *,
        services: Optional[List[str]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        chosen = [s for s in (services or HEALTH_SERVICES) if s in HEALTH_SERVICES]
        return await self._mgmt(
            "GET",
            f"projects/{self._ref(project_ref)}/health",
            params={"services": ",".join(chosen or HEALTH_SERVICES)},
        )

    async def get_project_keys(self, project_ref: Optional[str] = None) -> Result:
        """Project URL + the *publishable* (anon) key — the two values a
        client app needs. The secret key is deliberately not returned."""
        ref = self._ref(project_ref)
        try:
            keys = await self._keys_for(ref)
        except Exception as e:
            return {"error": str(e)}
        return {
            "ok": True,
            "result": {
                "project_ref": ref,
                "url": self._project_url(ref),
                "publishable_key": keys.get("publishable"),
                "note": "Safe to embed in client apps when Row Level Security is "
                "enabled. The secret/service_role key is never exposed here.",
            },
        }

    async def get_service_config(
        self, service: str, *, project_ref: Optional[str] = None
    ) -> Result:
        if service not in SERVICE_CONFIG_PATHS:
            return {
                "error": f"Unknown service {service!r}; one of "
                f"{', '.join(SERVICE_CONFIG_PATHS)}"
            }
        path, _ = SERVICE_CONFIG_PATHS[service]
        result = await self._mgmt("GET", f"projects/{self._ref(project_ref)}/{path}")
        if "error" not in result and isinstance(result.get("result"), dict):
            # Never surface signing material to the agent.
            for secret_field in ("jwt_secret", "smtp_pass"):
                if result["result"].get(secret_field):
                    result["result"][secret_field] = "***redacted***"
        return result

    async def update_service_config(
        self,
        service: str,
        config: Dict[str, Any],
        *,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        if service not in SERVICE_CONFIG_PATHS:
            return {
                "error": f"Unknown service {service!r}; one of "
                f"{', '.join(SERVICE_CONFIG_PATHS)}"
            }
        if not isinstance(config, dict) or not config:
            return {"error": "config must be a non-empty object of fields to change."}
        path, method = SERVICE_CONFIG_PATHS[service]
        return await self._mgmt(
            method,
            f"projects/{self._ref(project_ref)}/{path}",
            json_body=config,
            expected=_EXPECT_WRITE,
        )

    # =================================================================
    # Database — SQL, schema introspection, types, backups
    # =================================================================

    async def run_sql_readonly(
        self,
        query: str,
        *,
        parameters: Optional[List[Any]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        body = _clean({"query": query, "parameters": parameters or None})
        return await self._mgmt(
            "POST",
            f"projects/{self._ref(project_ref)}/database/query/read-only",
            json_body=body,
            expected=_EXPECT_WRITE,
            timeout=120.0,
        )

    async def run_sql(
        self,
        query: str,
        *,
        parameters: Optional[List[Any]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        """Run SQL with full privileges.

        Schema changes are recorded, whichever operation the agent picked:
        a query containing DDL (and no $n parameters, which the migrations
        endpoint can't take) goes through ``/database/migrations``, which
        executes it identically AND records it in migration history — so a
        "create a table" never leaves an untracked change behind.
        """
        self._guard_write()
        migration_name = None if parameters else ddl_migration_name(query)
        if migration_name:
            result = await self.apply_migration(
                query, name=migration_name, project_ref=project_ref
            )
            if "error" not in result:
                result = {
                    "ok": True,
                    "result": {
                        "applied_as_migration": migration_name,
                        "note": "Schema change recorded in migration history "
                        "(list_supabase_migrations).",
                    },
                }
            return result
        body = _clean({"query": query, "parameters": parameters or None})
        return await self._mgmt(
            "POST",
            f"projects/{self._ref(project_ref)}/database/query",
            json_body=body,
            expected=_EXPECT_WRITE,
            timeout=120.0,
        )

    async def list_tables(
        self, *, schemas: Optional[List[str]] = None, project_ref: Optional[str] = None
    ) -> Result:
        sql = (
            "select n.nspname as schema, c.relname as name, "
            "case c.relkind when 'r' then 'table' when 'p' then 'partitioned table' "
            "when 'v' then 'view' when 'm' then 'materialized view' "
            "when 'f' then 'foreign table' end as kind, "
            "c.relrowsecurity as rls_enabled, "
            "greatest(c.reltuples, 0)::bigint as estimated_rows, "
            "obj_description(c.oid, 'pg_class') as comment "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where c.relkind in ('r','p','v','m','f') "
            "and n.nspname = any(string_to_array($1, ',')) "
            "order by 1, 2"
        )
        return await self.run_sql_readonly(
            sql,
            parameters=[",".join(schemas or ["public"])],
            project_ref=project_ref,
        )

    async def describe_table(
        self, table: str, *, schema: str = "public", project_ref: Optional[str] = None
    ) -> Result:
        sql = (
            "with t as (select c.oid from pg_class c join pg_namespace n "
            "on n.oid = c.relnamespace where n.nspname = $1 and c.relname = $2) "
            "select "
            "(select json_agg(json_build_object('name', column_name, 'type', "
            "data_type, 'udt', udt_name, 'nullable', is_nullable = 'YES', "
            "'default', column_default, 'identity', is_identity = 'YES') "
            "order by ordinal_position) from information_schema.columns "
            "where table_schema = $1 and table_name = $2) as columns, "
            "(select json_agg(json_build_object('name', conname, 'type', contype, "
            "'definition', pg_get_constraintdef(oid))) from pg_constraint "
            "where conrelid = (select oid from t)) as constraints, "
            "(select json_agg(json_build_object('name', indexname, 'definition', "
            "indexdef)) from pg_indexes where schemaname = $1 and tablename = $2) "
            "as indexes, "
            "(select json_agg(json_build_object('name', policyname, 'command', cmd, "
            "'roles', roles, 'using', qual, 'with_check', with_check)) "
            "from pg_policies where schemaname = $1 and tablename = $2) as policies, "
            "(select relrowsecurity from pg_class where oid = (select oid from t)) "
            "as rls_enabled, "
            "(select json_agg(json_build_object('name', tgname, 'definition', "
            "pg_get_triggerdef(oid))) from pg_trigger where tgrelid = "
            "(select oid from t) and not tgisinternal) as triggers"
        )
        result = await self.run_sql_readonly(
            sql, parameters=[schema, table], project_ref=project_ref
        )
        if "error" in result:
            return result
        rows = result.get("result") or []
        row = rows[0] if rows else {}
        if not row or row.get("columns") is None:
            return {"error": f"Table {schema}.{table} not found."}
        return {"ok": True, "result": {"schema": schema, "table": table, **row}}

    async def list_extensions(self, *, project_ref: Optional[str] = None) -> Result:
        sql = (
            "select name, default_version, installed_version, comment "
            "from pg_available_extensions "
            "order by installed_version is null, name"
        )
        return await self.run_sql_readonly(sql, project_ref=project_ref)

    async def generate_typescript_types(
        self, *, schemas: Optional[List[str]] = None, project_ref: Optional[str] = None
    ) -> Result:
        return await self._mgmt(
            "GET",
            f"projects/{self._ref(project_ref)}/types/typescript",
            params={"included_schemas": ",".join(schemas or ["public"])},
            timeout=60.0,
        )

    async def list_backups(self, *, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt(
            "GET", f"projects/{self._ref(project_ref)}/database/backups"
        )

    # =================================================================
    # Migrations
    # =================================================================

    async def list_migrations(self, *, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt(
            "GET", f"projects/{self._ref(project_ref)}/database/migrations"
        )

    async def get_migration(
        self, version: str, *, project_ref: Optional[str] = None
    ) -> Result:
        return await self._mgmt(
            "GET", f"projects/{self._ref(project_ref)}/database/migrations/{version}"
        )

    async def apply_migration(
        self,
        query: str,
        *,
        name: Optional[str] = None,
        rollback: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        return await self._mgmt(
            "POST",
            f"projects/{self._ref(project_ref)}/database/migrations",
            json_body=_clean({"query": query, "name": name, "rollback": rollback}),
            expected=_EXPECT_WRITE,
            timeout=120.0,
        )

    async def rollback_migrations(
        self, from_version: str, *, project_ref: Optional[str] = None
    ) -> Result:
        """Run the stored rollback SQL of every migration >= from_version and
        remove them from history."""
        self._guard_write()
        return await self._mgmt(
            "DELETE",
            f"projects/{self._ref(project_ref)}/database/migrations",
            params={"gte": from_version},
            expected=_EXPECT_WRITE,
            timeout=120.0,
        )

    # =================================================================
    # Rows (PostgREST)
    # =================================================================

    @staticmethod
    def _filter_params(filters: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
        """``{"age": "gte.18", "status": ["neq.banned", "not.is.null"]}`` →
        repeated PostgREST query params. Values use PostgREST's own
        ``<operator>.<value>`` syntax; ``or``/``and`` keys pass through."""
        params: List[Tuple[str, str]] = []
        for column, condition in (filters or {}).items():
            values = condition if isinstance(condition, list) else [condition]
            for value in values:
                params.append((str(column), str(value)))
        return params

    @staticmethod
    def _profile_headers(schema: Optional[str], *, write: bool) -> Dict[str, str]:
        if not schema or schema == "public":
            return {}
        return {"Content-Profile" if write else "Accept-Profile": schema}

    async def select_rows(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Optional[Dict[str, Any]] = None,
        order: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
        schema: str = "public",
        count: bool = False,
        project_ref: Optional[str] = None,
    ) -> Result:
        ref = self._ref(project_ref)
        params = [("select", columns or "*")] + self._filter_params(filters)
        if order:
            params.append(("order", order))
        params.append(("limit", str(_clamp(limit, 1, self._max_rows(), 30))))
        params.append(("offset", str(max(int(offset or 0), 0))))
        headers = self._profile_headers(schema, write=False)
        if count:
            headers["Prefer"] = "count=exact"
        result, response = await self._rest(
            ref, "GET", f"rest/v1/{quote(table, safe='')}",
            params=params, headers=headers, expected=(200, 206),
        )
        if "error" in result:
            return result
        rows = result.get("result") or []
        payload: Dict[str, Any] = {"rows": rows, "returned": len(rows)}
        if response is not None:
            content_range = response.headers.get("content-range", "")
            total = content_range.rpartition("/")[2]
            if total and total != "*":
                payload["total"] = int(total)
        payload["next_offset"] = (
            max(int(offset or 0), 0) + len(rows)
            if len(rows) >= _clamp(limit, 1, self._max_rows(), 30)
            else None
        )
        return {"ok": True, "result": payload}

    async def insert_rows(
        self,
        table: str,
        rows: Any,
        *,
        upsert: bool = False,
        on_conflict: Optional[str] = None,
        schema: str = "public",
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        ref = self._ref(project_ref)
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or not rows:
            return {"error": "rows must be an object or a non-empty list of objects."}
        prefer = ["return=representation"]
        if upsert:
            prefer.append("resolution=merge-duplicates")
        headers = self._profile_headers(schema, write=True)
        headers["Prefer"] = ",".join(prefer)
        params = [("on_conflict", on_conflict)] if on_conflict else None
        result, _ = await self._rest(
            ref, "POST", f"rest/v1/{quote(table, safe='')}",
            params=params, json_body=rows, headers=headers,
        )
        return result

    async def update_rows(
        self,
        table: str,
        values: Dict[str, Any],
        filters: Dict[str, Any],
        *,
        schema: str = "public",
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        if not filters:
            return {
                "error": "filters are required — refusing to update every row. "
                "Use run_supabase_sql for an intentional full-table update."
            }
        if not isinstance(values, dict) or not values:
            return {"error": "values must be a non-empty object of columns to set."}
        headers = self._profile_headers(schema, write=True)
        headers["Prefer"] = "return=representation"
        result, _ = await self._rest(
            self._ref(project_ref), "PATCH", f"rest/v1/{quote(table, safe='')}",
            params=self._filter_params(filters), json_body=values, headers=headers,
        )
        return result

    async def delete_rows(
        self,
        table: str,
        filters: Dict[str, Any],
        *,
        schema: str = "public",
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        if not filters:
            return {
                "error": "filters are required — refusing to delete every row. "
                "Use run_supabase_sql for an intentional truncate."
            }
        headers = self._profile_headers(schema, write=True)
        headers["Prefer"] = "return=representation"
        result, _ = await self._rest(
            self._ref(project_ref), "DELETE", f"rest/v1/{quote(table, safe='')}",
            params=self._filter_params(filters), headers=headers,
        )
        return result

    async def call_rpc(
        self,
        function: str,
        *,
        args: Optional[Dict[str, Any]] = None,
        schema: str = "public",
        project_ref: Optional[str] = None,
    ) -> Result:
        # A database function can do anything, so treat it as a write.
        self._guard_write()
        result, _ = await self._rest(
            self._ref(project_ref), "POST", f"rest/v1/rpc/{quote(function, safe='')}",
            json_body=args or {}, headers=self._profile_headers(schema, write=True),
        )
        return result

    # =================================================================
    # Storage
    # =================================================================

    async def list_buckets(self, *, project_ref: Optional[str] = None) -> Result:
        result, _ = await self._data(
            self._ref(project_ref), "GET", "storage/v1/bucket", expected=_EXPECT_READ
        )
        return result

    async def create_bucket(
        self,
        name: str,
        *,
        public: bool = False,
        file_size_limit: Optional[int] = None,
        allowed_mime_types: Optional[List[str]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        body = _clean(
            {
                "id": name,
                "name": name,
                "public": bool(public),
                "file_size_limit": file_size_limit,
                "allowed_mime_types": allowed_mime_types,
            }
        )
        result, _ = await self._data(
            self._ref(project_ref), "POST", "storage/v1/bucket", json_body=body
        )
        return result

    async def update_bucket(
        self,
        name: str,
        *,
        public: Optional[bool] = None,
        file_size_limit: Optional[int] = None,
        allowed_mime_types: Optional[List[str]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        ref = self._ref(project_ref)
        # PUT replaces the bucket's settings — read first so unspecified
        # fields keep their current values.
        current, _ = await self._data(
            ref, "GET", f"storage/v1/bucket/{quote(name, safe='')}", expected=_EXPECT_READ
        )
        if "error" in current:
            return current
        existing = current.get("result") or {}
        body = {
            "id": name,
            "name": name,
            "public": existing.get("public", False) if public is None else bool(public),
            "file_size_limit": (
                existing.get("file_size_limit")
                if file_size_limit is None
                else file_size_limit
            ),
            "allowed_mime_types": (
                existing.get("allowed_mime_types")
                if allowed_mime_types is None
                else allowed_mime_types
            ),
        }
        result, _ = await self._data(
            ref, "PUT", f"storage/v1/bucket/{quote(name, safe='')}", json_body=body
        )
        return result

    async def delete_bucket(self, name: str, *, project_ref: Optional[str] = None) -> Result:
        self._guard_write()
        result, _ = await self._data(
            self._ref(project_ref), "DELETE", f"storage/v1/bucket/{quote(name, safe='')}"
        )
        return result

    async def empty_bucket(self, name: str, *, project_ref: Optional[str] = None) -> Result:
        self._guard_write()
        result, _ = await self._data(
            self._ref(project_ref), "POST",
            f"storage/v1/bucket/{quote(name, safe='')}/empty",
        )
        return result

    async def list_files(
        self,
        bucket: str,
        *,
        prefix: str = "",
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        project_ref: Optional[str] = None,
    ) -> Result:
        body = _clean(
            {
                "prefix": prefix.strip("/"),
                "limit": _clamp(limit, 1, 1000, 100),
                "offset": max(int(offset or 0), 0),
                "search": search,
                "sortBy": {"column": "name", "order": "asc"},
            }
        )
        result, _ = await self._data(
            self._ref(project_ref), "POST",
            f"storage/v1/object/list/{quote(bucket, safe='')}",
            json_body=body, expected=_EXPECT_READ,
        )
        if "error" in result:
            return result
        entries = result.get("result") or []
        # Folders come back as entries with a null id.
        for entry in entries:
            if isinstance(entry, dict):
                entry["is_folder"] = entry.get("id") is None
        return {"ok": True, "result": entries}

    async def upload_file(
        self,
        bucket: str,
        path: str,
        file_path: str,
        *,
        upsert: bool = False,
        content_type: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        local = os.path.abspath(file_path)
        if not os.path.isfile(local):
            return {"error": f"File not found: {local}"}
        mime = content_type or mimetypes.guess_type(local)[0] or "application/octet-stream"
        with open(local, "rb") as f:
            payload = f.read()
        headers = {"Content-Type": mime, "x-upsert": "true" if upsert else "false"}
        result, _ = await self._data(
            self._ref(project_ref), "POST",
            f"storage/v1/object/{quote(bucket, safe='')}/{_object_path(path)}",
            content=payload, headers=headers, timeout=300.0,
        )
        if "error" not in result:
            result["result"] = {
                "bucket": bucket,
                "path": path.strip("/"),
                "size": len(payload),
                "content_type": mime,
                **(result.get("result") if isinstance(result.get("result"), dict) else {}),
            }
        return result

    async def download_file(
        self,
        bucket: str,
        path: str,
        save_to: str,
        *,
        project_ref: Optional[str] = None,
    ) -> Result:
        result, response = await self._data(
            self._ref(project_ref), "GET",
            f"storage/v1/object/{quote(bucket, safe='')}/{_object_path(path)}",
            expected=_EXPECT_READ, timeout=300.0, raw=True,
        )
        if "error" in result or response is None:
            return result
        target = os.path.abspath(save_to)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "wb") as f:
            f.write(response.content)
        return {
            "ok": True,
            "result": {
                "saved_to": target,
                "size": len(response.content),
                "content_type": response.headers.get("content-type"),
            },
        }

    async def delete_files(
        self, bucket: str, paths: List[str], *, project_ref: Optional[str] = None
    ) -> Result:
        self._guard_write()
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return {"error": "paths must list at least one object path."}
        result, _ = await self._data(
            self._ref(project_ref), "DELETE",
            f"storage/v1/object/{quote(bucket, safe='')}",
            json_body={"prefixes": [p.strip("/") for p in paths]},
        )
        return result

    async def move_file(
        self,
        bucket: str,
        from_path: str,
        to_path: str,
        *,
        to_bucket: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        body = _clean(
            {
                "bucketId": bucket,
                "sourceKey": from_path.strip("/"),
                "destinationKey": to_path.strip("/"),
                "destinationBucket": to_bucket,
            }
        )
        result, _ = await self._data(
            self._ref(project_ref), "POST", "storage/v1/object/move", json_body=body
        )
        return result

    async def copy_file(
        self,
        bucket: str,
        from_path: str,
        to_path: str,
        *,
        to_bucket: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        body = _clean(
            {
                "bucketId": bucket,
                "sourceKey": from_path.strip("/"),
                "destinationKey": to_path.strip("/"),
                "destinationBucket": to_bucket,
            }
        )
        result, _ = await self._data(
            self._ref(project_ref), "POST", "storage/v1/object/copy", json_body=body
        )
        return result

    async def create_signed_url(
        self,
        bucket: str,
        path: str,
        *,
        expires_in: int = 3600,
        project_ref: Optional[str] = None,
    ) -> Result:
        ref = self._ref(project_ref)
        result, _ = await self._data(
            ref, "POST",
            f"storage/v1/object/sign/{quote(bucket, safe='')}/{_object_path(path)}",
            json_body={"expiresIn": _clamp(expires_in, 1, 60 * 60 * 24 * 365, 3600)},
        )
        if "error" in result:
            return result
        signed = (result.get("result") or {}).get("signedURL") or ""
        return {
            "ok": True,
            "result": {
                "signed_url": f"{self._project_url(ref)}/storage/v1{signed}"
                if signed.startswith("/")
                else signed,
                "expires_in": _clamp(expires_in, 1, 60 * 60 * 24 * 365, 3600),
                "public_url_if_bucket_public": f"{self._project_url(ref)}/storage/v1/"
                f"object/public/{quote(bucket, safe='')}/{_object_path(path)}",
            },
        }

    # =================================================================
    # Auth users (GoTrue admin)
    # =================================================================

    async def list_users(
        self, *, page: int = 1, per_page: int = 50, project_ref: Optional[str] = None
    ) -> Result:
        per = _clamp(per_page, 1, 1000, 50)
        result, _ = await self._data(
            self._ref(project_ref), "GET", "auth/v1/admin/users",
            params={"page": max(int(page or 1), 1), "per_page": per},
            expected=_EXPECT_READ,
        )
        if "error" in result:
            return result
        users = (result.get("result") or {}).get("users") or []
        return {
            "ok": True,
            "result": {
                "users": users,
                "page": max(int(page or 1), 1),
                "next_page": max(int(page or 1), 1) + 1 if len(users) >= per else None,
            },
        }

    async def get_user(self, user_id: str, *, project_ref: Optional[str] = None) -> Result:
        result, _ = await self._data(
            self._ref(project_ref), "GET", f"auth/v1/admin/users/{quote(user_id, safe='')}",
            expected=_EXPECT_READ,
        )
        return result

    async def create_user(
        self,
        *,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        password: Optional[str] = None,
        email_confirm: Optional[bool] = None,
        phone_confirm: Optional[bool] = None,
        user_metadata: Optional[Dict[str, Any]] = None,
        app_metadata: Optional[Dict[str, Any]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        if not email and not phone:
            return {"error": "email or phone is required."}
        body = _clean(
            {
                "email": email,
                "phone": phone,
                "password": password,
                "email_confirm": email_confirm,
                "phone_confirm": phone_confirm,
                "user_metadata": user_metadata,
                "app_metadata": app_metadata,
            }
        )
        result, _ = await self._data(
            self._ref(project_ref), "POST", "auth/v1/admin/users", json_body=body
        )
        return result

    async def update_user(
        self,
        user_id: str,
        *,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        password: Optional[str] = None,
        email_confirm: Optional[bool] = None,
        phone_confirm: Optional[bool] = None,
        user_metadata: Optional[Dict[str, Any]] = None,
        app_metadata: Optional[Dict[str, Any]] = None,
        ban_duration: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        body = _clean(
            {
                "email": email,
                "phone": phone,
                "password": password,
                "email_confirm": email_confirm,
                "phone_confirm": phone_confirm,
                "user_metadata": user_metadata,
                "app_metadata": app_metadata,
                "ban_duration": ban_duration,
            }
        )
        if not body:
            return {"error": "Nothing to update — pass at least one field."}
        result, _ = await self._data(
            self._ref(project_ref), "PUT",
            f"auth/v1/admin/users/{quote(user_id, safe='')}", json_body=body,
        )
        return result

    async def delete_user(
        self,
        user_id: str,
        *,
        soft_delete: bool = False,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        result, _ = await self._data(
            self._ref(project_ref), "DELETE",
            f"auth/v1/admin/users/{quote(user_id, safe='')}",
            json_body={"should_soft_delete": bool(soft_delete)},
        )
        return result

    async def invite_user(
        self,
        email: str,
        *,
        redirect_to: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        params = {"redirect_to": redirect_to} if redirect_to else None
        result, _ = await self._data(
            self._ref(project_ref), "POST", "auth/v1/invite",
            params=params, json_body=_clean({"email": email, "data": data}),
        )
        return result

    async def generate_auth_link(
        self,
        link_type: str,
        email: str,
        *,
        password: Optional[str] = None,
        new_email: Optional[str] = None,
        redirect_to: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        """Generate a signup / magiclink / recovery / invite / email-change
        link without sending an email."""
        self._guard_write()
        valid = ("signup", "magiclink", "recovery", "invite", "email_change_current",
                 "email_change_new")
        if link_type not in valid:
            return {"error": f"link_type must be one of {', '.join(valid)}"}
        params = {"redirect_to": redirect_to} if redirect_to else None
        body = _clean(
            {
                "type": link_type,
                "email": email,
                "password": password,
                "new_email": new_email,
                "data": data,
            }
        )
        result, _ = await self._data(
            self._ref(project_ref), "POST", "auth/v1/admin/generate_link",
            params=params, json_body=body,
        )
        return result

    # =================================================================
    # Edge functions
    # =================================================================

    async def list_functions(self, *, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt("GET", f"projects/{self._ref(project_ref)}/functions")

    async def get_function(self, slug: str, *, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt(
            "GET", f"projects/{self._ref(project_ref)}/functions/{quote(slug, safe='')}"
        )

    async def deploy_function(
        self,
        slug: str,
        *,
        files: Optional[Dict[str, str]] = None,
        source_dir: Optional[str] = None,
        entrypoint: str = "index.ts",
        name: Optional[str] = None,
        verify_jwt: bool = True,
        import_map_path: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        """Create or replace an edge function from source.

        Source comes from ``files`` (``{relative_path: source_text}``) or
        from every file under ``source_dir`` on disk. Paths are relative to
        the function root and must include the entrypoint.
        """
        self._guard_write()
        sources: List[Tuple[str, bytes]] = []
        if files:
            sources = [(p.replace("\\", "/").lstrip("/"), c.encode("utf-8"))
                       for p, c in files.items()]
        elif source_dir:
            root = os.path.abspath(source_dir)
            if not os.path.isdir(root):
                return {"error": f"source_dir not found: {root}"}
            for folder, _, names in os.walk(root):
                for fname in names:
                    full = os.path.join(folder, fname)
                    rel = os.path.relpath(full, root).replace("\\", "/")
                    with open(full, "rb") as f:
                        sources.append((rel, f.read()))
        else:
            return {"error": "Pass either 'files' (path → source) or 'source_dir'."}
        if entrypoint not in {p for p, _ in sources}:
            return {
                "error": f"Entrypoint {entrypoint!r} is not among the files: "
                f"{sorted(p for p, _ in sources)[:20]}"
            }
        metadata = _clean(
            {
                "entrypoint_path": entrypoint,
                "name": name or slug,
                "verify_jwt": bool(verify_jwt),
                "import_map_path": import_map_path,
            }
        )
        multipart = [
            ("file", (path, content, mimetypes.guess_type(path)[0] or "text/plain"))
            for path, content in sources
        ]
        return await self._mgmt(
            "POST",
            f"projects/{self._ref(project_ref)}/functions/deploy",
            params={"slug": slug},
            data={"metadata": json.dumps(metadata)},
            files=multipart,
            expected=_EXPECT_WRITE,
            timeout=180.0,
        )

    async def update_function(
        self,
        slug: str,
        *,
        name: Optional[str] = None,
        verify_jwt: Optional[bool] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        body = _clean({"name": name, "verify_jwt": verify_jwt})
        if not body:
            return {"error": "Nothing to update — pass name and/or verify_jwt. "
                    "To change code, use deploy_supabase_function."}
        return await self._mgmt(
            "PATCH",
            f"projects/{self._ref(project_ref)}/functions/{quote(slug, safe='')}",
            json_body=body,
            expected=_EXPECT_WRITE,
        )

    async def delete_function(self, slug: str, *, project_ref: Optional[str] = None) -> Result:
        self._guard_write()
        return await self._mgmt(
            "DELETE",
            f"projects/{self._ref(project_ref)}/functions/{quote(slug, safe='')}",
            expected=_EXPECT_WRITE,
        )

    async def invoke_function(
        self,
        slug: str,
        *,
        body: Any = None,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        # Invocation can have arbitrary side effects inside the function.
        self._guard_write()
        verb = (method or "POST").upper()
        if verb not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return {"error": f"Unsupported method {method!r}."}
        extra = {k: v for k, v in (headers or {}).items()
                 if k.lower() not in ("apikey", "authorization")}
        # Functions with verify_jwt need a JWT; only legacy keys are JWTs.
        result, response = await self._data(
            self._ref(project_ref), verb, f"functions/v1/{quote(slug, safe='')}",
            json_body=body if verb != "GET" else None,
            headers=extra, prefer_jwt=True, expected=range(200, 300),
            timeout=150.0, raw=True,
        )
        if response is None:
            return result
        try:
            parsed: Any = response.json()
        except Exception:
            parsed = response.text[:20000]
        envelope = {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "body": parsed,
        }
        if "error" in result:
            return {"error": result["error"], "details": envelope}
        return {"ok": True, "result": envelope}

    # =================================================================
    # Secrets (edge-function environment variables)
    # =================================================================

    async def list_secrets(self, *, project_ref: Optional[str] = None) -> Result:
        """Names and update times only — values are stripped before they
        reach the agent."""
        result = await self._mgmt("GET", f"projects/{self._ref(project_ref)}/secrets")
        if "error" in result:
            return result
        return {
            "ok": True,
            "result": [
                {"name": s.get("name"), "updated_at": s.get("updated_at")}
                for s in result.get("result") or []
                if isinstance(s, dict)
            ],
        }

    async def set_secrets(
        self, secrets: Dict[str, str], *, project_ref: Optional[str] = None
    ) -> Result:
        self._guard_write()
        if not isinstance(secrets, dict) or not secrets:
            return {"error": "secrets must be a non-empty object of NAME → value."}
        bad = [n for n in secrets if str(n).upper().startswith("SUPABASE_")]
        if bad:
            return {"error": f"Names starting with SUPABASE_ are reserved: {bad}"}
        result = await self._mgmt(
            "POST",
            f"projects/{self._ref(project_ref)}/secrets",
            json_body=[{"name": n, "value": str(v)} for n, v in secrets.items()],
            expected=_EXPECT_WRITE,
        )
        if "error" not in result:
            result["result"] = {"set": sorted(secrets)}
        return result

    async def delete_secrets(
        self, names: List[str], *, project_ref: Optional[str] = None
    ) -> Result:
        self._guard_write()
        if isinstance(names, str):
            names = [names]
        if not names:
            return {"error": "names must list at least one secret name."}
        result = await self._mgmt(
            "DELETE",
            f"projects/{self._ref(project_ref)}/secrets",
            json_body=list(names),
            expected=_EXPECT_WRITE,
        )
        if "error" not in result:
            result["result"] = {"deleted": sorted(names)}
        return result

    # =================================================================
    # Branches
    # =================================================================

    async def list_branches(self, *, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt("GET", f"projects/{self._ref(project_ref)}/branches")

    async def get_branch(self, branch_id: str) -> Result:
        return await self._mgmt("GET", f"branches/{quote(branch_id, safe='')}")

    async def create_branch(
        self,
        branch_name: str,
        *,
        git_branch: Optional[str] = None,
        persistent: Optional[bool] = None,
        with_data: Optional[bool] = None,
        region: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        self._guard_write()
        body = _clean(
            {
                "branch_name": branch_name,
                "git_branch": git_branch,
                "persistent": persistent,
                "with_data": with_data,
                "region": region,
            }
        )
        return await self._mgmt(
            "POST",
            f"projects/{self._ref(project_ref)}/branches",
            json_body=body,
            expected=_EXPECT_WRITE,
            timeout=60.0,
        )

    async def update_branch(
        self,
        branch_id: str,
        *,
        branch_name: Optional[str] = None,
        git_branch: Optional[str] = None,
        persistent: Optional[bool] = None,
    ) -> Result:
        self._guard_write()
        body = _clean(
            {"branch_name": branch_name, "git_branch": git_branch, "persistent": persistent}
        )
        if not body:
            return {"error": "Nothing to update — pass branch_name, git_branch or persistent."}
        return await self._mgmt(
            "PATCH", f"branches/{quote(branch_id, safe='')}",
            json_body=body, expected=_EXPECT_WRITE,
        )

    async def delete_branch(self, branch_id: str) -> Result:
        self._guard_write()
        return await self._mgmt(
            "DELETE", f"branches/{quote(branch_id, safe='')}", expected=_EXPECT_WRITE
        )

    async def merge_branch(
        self, branch_id: str, *, migration_version: Optional[str] = None
    ) -> Result:
        self._guard_write()
        return await self._mgmt(
            "POST", f"branches/{quote(branch_id, safe='')}/merge",
            json_body=_clean({"migration_version": migration_version}),
            expected=_EXPECT_WRITE, timeout=60.0,
        )

    async def reset_branch(
        self, branch_id: str, *, migration_version: Optional[str] = None
    ) -> Result:
        self._guard_write()
        return await self._mgmt(
            "POST", f"branches/{quote(branch_id, safe='')}/reset",
            json_body=_clean({"migration_version": migration_version}),
            expected=_EXPECT_WRITE, timeout=60.0,
        )

    async def diff_branch(
        self, branch_id: str, *, schemas: Optional[List[str]] = None
    ) -> Result:
        params = {"included_schemas": ",".join(schemas)} if schemas else {}
        return await self._mgmt_text(f"branches/{quote(branch_id, safe='')}/diff", params)

    # =================================================================
    # Monitoring — logs, advisors, usage
    # =================================================================

    async def get_logs(
        self,
        *,
        source: str = "api",
        sql: Optional[str] = None,
        minutes: int = 60,
        limit: int = 100,
        search: Optional[str] = None,
        project_ref: Optional[str] = None,
    ) -> Result:
        """Recent logs for one service.

        Since Supabase retired ``logs.all`` the endpoint takes ClickHouse
        SQL over ONE ``logs`` table, filtered by ``source_name`` (the old
        per-source table names). Nested fields live in the
        ``log_attributes`` map, e.g. ``log_attributes['request.method']``.
        """
        source_name = LOG_SOURCES.get(source)
        if not sql and not source_name:
            return {"error": f"source must be one of {', '.join(LOG_SOURCES)}"}
        if not sql:
            where = f"source_name = {_ch_literal(source_name)}"
            if search:
                # re2 regex, case-insensitive unless the caller set flags.
                pattern = search if search.startswith("(?") else f"(?i){search}"
                where += f" and match(event_message, {_ch_literal(pattern)})"
            sql = (
                f"select timestamp, event_message from logs where {where} "
                f"order by timestamp desc limit {_clamp(limit, 1, 1000, 100)}"
            )
        span = _clamp(minutes, 1, 60 * 24, 60)
        end = time.time()
        start = end - span * 60

        def _iso(ts: float) -> str:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

        params = {
            "sql": sql,
            "iso_timestamp_start": _iso(start),
            "iso_timestamp_end": _iso(end),
        }
        path = f"projects/{self._ref(project_ref)}/analytics/endpoints/logs"
        result = _analytics_result(await self._mgmt("GET", path, params=params, timeout=60.0))
        # Supabase asks for a retry on transient backend failures.
        if "Backend error" in str(result.get("details") or ""):
            await asyncio.sleep(2.0)
            result = _analytics_result(
                await self._mgmt("GET", path, params=params, timeout=60.0)
            )
            if "Backend error" in str(result.get("details") or ""):
                result["details"] = (
                    "Supabase's logs service is failing for this project (it "
                    "rejects even trivial queries, so this isn't the query). "
                    "Try again later, or check Logs Explorer in the Supabase "
                    "dashboard."
                )
        return result

    async def get_security_advisors(self, *, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt(
            "GET", f"projects/{self._ref(project_ref)}/advisors/security", timeout=60.0
        )

    async def get_performance_advisors(self, *, project_ref: Optional[str] = None) -> Result:
        return await self._mgmt(
            "GET", f"projects/{self._ref(project_ref)}/advisors/performance", timeout=60.0
        )

    async def get_api_usage(
        self, *, interval: str = "1day", project_ref: Optional[str] = None
    ) -> Result:
        valid = ("15min", "30min", "1hr", "3hr", "1day", "3day", "7day")
        result = await self._mgmt(
            "GET",
            f"projects/{self._ref(project_ref)}/analytics/endpoints/usage.api-counts",
            params={"interval": interval if interval in valid else "1day"},
        )
        return _analytics_result(result)
