# -*- coding: utf-8 -*-
"""PostHog integration — REST client over the private (management) API.

PostHog is a product-analytics platform. This client covers the analytics
and feature-flag surface: HogQL queries, insights, dashboards, feature
flags, persons, cohorts, annotations, definitions, and project metadata.

Auth is a personal API key (``phx_...``) sent as a bearer token. Unlike
every other REST integration in this package the base URL is **not** a
module constant: PostHog runs US Cloud, EU Cloud and self-hosted
installations, so the host lives on the credential and every request
builds its URL from it.

See INTEGRATION.md for identifier shapes, the soft-delete rule, the
rate-limit table, and known auth failure modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ... import BasePlatformClient, load_config, register_client
from ...helpers import Result, arequest
from ...logger import get_logger

logger = get_logger(__name__)

POSTHOG_DEFAULT_HOST = "https://us.posthog.com"

# Region presets offered in the connect modal. Self-hosted users paste
# their own origin instead.
POSTHOG_HOSTS = {
    "us": "https://us.posthog.com",
    "eu": "https://eu.posthog.com",
}

# PostHog's OAuth endpoints are region-agnostic (oauth.posthog.com routes
# to whichever cloud the user belongs to). Referenced by the provider.
POSTHOG_OAUTH_AUTHORIZE = "https://oauth.posthog.com/oauth/authorize/"
POSTHOG_OAUTH_TOKEN = "https://oauth.posthog.com/oauth/token/"

# Scopes matching this integration's surface, in PostHog's
# ``<resource>:<read|write>`` naming. Used only by the OAuth path.
POSTHOG_SCOPES = (
    "openid",
    "profile",
    "email",
    "query:read",
    "insight:read",
    "insight:write",
    "dashboard:read",
    "dashboard:write",
    "dashboard_template:read",
    "feature_flag:read",
    "feature_flag:write",
    "early_access_feature:read",
    "early_access_feature:write",
    "person:read",
    "person:write",
    "cohort:read",
    "cohort:write",
    "annotation:read",
    "annotation:write",
    "event_definition:read",
    "event_definition:write",
    "property_definition:read",
    "property_definition:write",
    "action:read",
    "action:write",
    "project:read",
    "organization:read",
    "organization_member:read",
    "user:read",
    "sharing_configuration:read",
)

# Mutations: PostHog returns 200 for PATCH/POST-with-body, 201 for creates
# and 204 for the action endpoints that have no response body.
_EXPECT_WRITE = (200, 201, 202, 204)

# Resources whose "delete" is a soft delete — see INTEGRATION.md. Kept as a
# named constant so the delete helpers can't drift apart.
_SOFT_DELETE_FLAG = {"deleted": True}


@dataclass
class PostHogCredential:
    api_key: str = ""
    # Origin only, no trailing slash, no /api suffix. Never a constant —
    # EU and self-hosted installs differ.
    host: str = POSTHOG_DEFAULT_HOST
    # Numeric project (team) id as a string. Resolved at connect time from
    # /api/users/@me/ so multi-account identity is stable.
    project_id: str = ""
    org_id: str = ""
    user_email: str = ""
    org_name: str = ""
    project_name: str = ""


@dataclass
class PostHogConfig:
    """Post-connect runtime knobs."""

    default_project_id: str = ""
    query_timeout_seconds: int = 60
    default_date_range: str = "-7d"


@register_client
class PostHogClient(BasePlatformClient):
    """PostHog management-API client, one instance per connected account.

    Credential-injected by design: the provider calls ``bind_credential``
    before use. There is no disk-credential path — PostHog is a
    greenfield integration and never had a single-account predecessor.
    """

    PLATFORM_ID = "posthog"

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[PostHogCredential] = None
        self._persist = None

    # ── credential plumbing ──────────────────────────────────────────

    def bind_credential(self, credential: Dict[str, Any], persist) -> None:
        known = {f for f in PostHogCredential.__dataclass_fields__}
        self._cred = PostHogCredential(
            **{k: v for k, v in credential.items() if k in known}
        )
        self._persist = persist

    def has_credentials(self) -> bool:
        return self._cred is not None and bool(self._cred.api_key)

    def _load(self) -> PostHogCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    def _config(self) -> PostHogConfig:
        # Read fresh so a config change takes effect without a restart.
        return load_config("posthog_config.json", PostHogConfig) or PostHogConfig()

    def _headers(self, *, json_body: bool = True) -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self._load().api_key}"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _api(self, path: str) -> str:
        """Absolute URL for an ``/api/`` path fragment."""
        host = (self._load().host or POSTHOG_DEFAULT_HOST).rstrip("/")
        return f"{host}/api/{path.lstrip('/')}"

    def _project(self, project_id: Optional[str] = None) -> str:
        """Resolve the project to act on.

        Explicit argument wins, then the runtime-config override, then the
        project captured on the credential, then PostHog's ``@current``
        server-side shortcut.
        """
        if project_id:
            return str(project_id)
        cfg = self._config()
        if cfg.default_project_id:
            return str(cfg.default_project_id)
        cred = self._load()
        return str(cred.project_id) if cred.project_id else "@current"

    def _proj(self, path: str, project_id: Optional[str] = None) -> str:
        return self._api(f"projects/{self._project(project_id)}/{path.lstrip('/')}")

    @staticmethod
    def _page(limit: int, offset: int) -> Dict[str, Any]:
        return {"limit": min(max(int(limit), 1), 100), "offset": max(int(offset), 0)}

    @staticmethod
    def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Drop keys the caller did not set, so PATCH never blanks a field."""
        return {k: v for k, v in payload.items() if v is not None}

    # ── BasePlatformClient contract ──────────────────────────────────

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        """PostHog has no messaging surface.

        The closest equivalent — leaving a note on the timeline — is an
        annotation, so ``recipient`` is read as an ISO date (or omitted
        for "now") and ``text`` becomes the annotation content.
        """
        return await self.create_annotation(content=text, date_marker=recipient or None)

    # =================================================================
    # Query (HogQL)
    # =================================================================

    async def run_query(
        self,
        query: str,
        *,
        project_id: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        refresh: Optional[str] = None,
    ) -> Result:
        """Run a HogQL query synchronously and return its rows."""
        body: Dict[str, Any] = {"query": {"kind": "HogQLQuery", "query": query}}
        if variables:
            body["query"]["variables"] = variables
        if refresh:
            body["refresh"] = refresh
        return await arequest(
            "POST",
            self._proj("query/", project_id),
            headers=self._headers(),
            json=body,
            expected=(200,),
            timeout=float(self._config().query_timeout_seconds),
        )

    async def run_query_async(
        self,
        query: str,
        *,
        project_id: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Result:
        """Start a HogQL query in the background.

        Returns a ``query_status`` carrying the id to poll with
        ``get_query_status``. Use this for anything scanning a wide date
        range — the sync path will time out first.
        """
        body: Dict[str, Any] = {
            "query": {"kind": "HogQLQuery", "query": query},
            "async": True,
        }
        if variables:
            body["query"]["variables"] = variables
        return await arequest(
            "POST",
            self._proj("query/", project_id),
            headers=self._headers(),
            json=body,
            expected=(200, 201, 202),
        )

    async def get_query_status(
        self, query_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Poll an async query; carries results once ``complete`` is true."""
        return await arequest(
            "GET",
            self._proj(f"query/{query_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def cancel_query(
        self, query_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "DELETE",
            self._proj(f"query/{query_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=_EXPECT_WRITE,
        )

    async def draft_sql(
        self, prompt: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Ask PostHog's own assistant to draft HogQL from a description."""
        return await arequest(
            "GET",
            self._proj("query/draft_sql/", project_id),
            headers=self._headers(json_body=False),
            params={"prompt": prompt},
            expected=(200,),
        )

    async def list_events(
        self,
        *,
        project_id: Optional[str] = None,
        event: Optional[str] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        distinct_id: Optional[str] = None,
        limit: int = 30,
    ) -> Result:
        """Recent events, via HogQL.

        The legacy ``/events/`` endpoint is deprecated; this composes the
        equivalent HogQL so the agent gets one stable shape.
        """
        where: List[str] = []
        if event:
            where.append(f"event = {_sql_literal(event)}")
        if distinct_id:
            where.append(f"distinct_id = {_sql_literal(distinct_id)}")
        if after:
            where.append(f"timestamp > {_sql_literal(after)}")
        else:
            where.append(
                f"timestamp > now() - interval "
                f"{_interval(self._config().default_date_range)}"
            )
        if before:
            where.append(f"timestamp < {_sql_literal(before)}")
        clause = " AND ".join(where) if where else "1=1"
        sql = (
            "SELECT uuid, event, distinct_id, timestamp, properties "
            f"FROM events WHERE {clause} ORDER BY timestamp DESC "
            f"LIMIT {min(max(int(limit), 1), 100)}"
        )
        return await self.run_query(sql, project_id=project_id)

    async def get_event(
        self, event_uuid: str, *, project_id: Optional[str] = None
    ) -> Result:
        sql = (
            "SELECT uuid, event, distinct_id, timestamp, properties "
            f"FROM events WHERE uuid = {_sql_literal(event_uuid)} LIMIT 1"
        )
        return await self.run_query(sql, project_id=project_id)

    # =================================================================
    # Insights
    # =================================================================

    async def list_insights(
        self,
        *,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        favorited: Optional[bool] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        params = self._page(limit, offset)
        if search:
            params["search"] = search
        if favorited is not None:
            params["favorited"] = favorited
        return await arequest(
            "GET",
            self._proj("insights/", project_id),
            headers=self._headers(json_body=False),
            params=params,
            expected=(200,),
        )

    async def get_insight(
        self, insight_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"insights/{insight_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def create_insight(
        self,
        *,
        name: str,
        query: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        dashboards: Optional[List[int]] = None,
        favorited: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {
                "name": name,
                "query": query,
                "description": description,
                "dashboards": dashboards,
                "favorited": favorited,
                "tags": tags,
            }
        )
        return await arequest(
            "POST",
            self._proj("insights/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def update_insight(
        self,
        insight_id: str,
        *,
        name: Optional[str] = None,
        query: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        dashboards: Optional[List[int]] = None,
        favorited: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {
                "name": name,
                "query": query,
                "description": description,
                "dashboards": dashboards,
                "favorited": favorited,
                "tags": tags,
            }
        )
        return await arequest(
            "PATCH",
            self._proj(f"insights/{insight_id}/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def delete_insight(
        self, insight_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Soft delete — recoverable by PATCHing ``deleted: false``."""
        return await arequest(
            "PATCH",
            self._proj(f"insights/{insight_id}/", project_id),
            headers=self._headers(),
            json=_SOFT_DELETE_FLAG,
            expected=_EXPECT_WRITE,
        )

    async def get_insight_sharing(
        self, insight_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"insights/{insight_id}/sharing/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def list_trending_insights(
        self, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj("insights/trending/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def get_insight_activity(
        self, insight_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"insights/{insight_id}/activity/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    # =================================================================
    # Dashboards
    # =================================================================

    async def list_dashboards(
        self,
        *,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        params = self._page(limit, offset)
        if search:
            params["search"] = search
        return await arequest(
            "GET",
            self._proj("dashboards/", project_id),
            headers=self._headers(json_body=False),
            params=params,
            expected=(200,),
        )

    async def get_dashboard(
        self, dashboard_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"dashboards/{dashboard_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def create_dashboard(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        pinned: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {
                "name": name,
                "description": description,
                "pinned": pinned,
                "tags": tags,
            }
        )
        return await arequest(
            "POST",
            self._proj("dashboards/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def update_dashboard(
        self,
        dashboard_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        pinned: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {
                "name": name,
                "description": description,
                "pinned": pinned,
                "tags": tags,
            }
        )
        return await arequest(
            "PATCH",
            self._proj(f"dashboards/{dashboard_id}/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def delete_dashboard(
        self, dashboard_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Soft delete — recoverable by PATCHing ``deleted: false``."""
        return await arequest(
            "PATCH",
            self._proj(f"dashboards/{dashboard_id}/", project_id),
            headers=self._headers(),
            json=_SOFT_DELETE_FLAG,
            expected=_EXPECT_WRITE,
        )

    async def add_insight_to_dashboard(
        self,
        insight_id: str,
        dashboard_id: str,
        *,
        project_id: Optional[str] = None,
    ) -> Result:
        """Attach an existing insight to a dashboard.

        PostHog models tiles from the insight side: the insight carries a
        ``dashboards`` list, so this reads the current list and appends.
        """
        current = await self.get_insight(insight_id, project_id=project_id)
        if "error" in current:
            return current
        existing = (current.get("result") or {}).get("dashboards") or []
        target = int(dashboard_id)
        if target not in existing:
            existing = list(existing) + [target]
        return await self.update_insight(
            insight_id, dashboards=existing, project_id=project_id
        )

    async def create_dashboard_text_tile(
        self,
        dashboard_id: str,
        body: str,
        *,
        project_id: Optional[str] = None,
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"dashboards/{dashboard_id}/create_text_tile/", project_id),
            headers=self._headers(),
            json={"body": body},
            expected=_EXPECT_WRITE,
        )

    async def delete_dashboard_tile(
        self,
        dashboard_id: str,
        tile_id: str,
        *,
        project_id: Optional[str] = None,
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"dashboards/{dashboard_id}/delete_tile/", project_id),
            headers=self._headers(),
            json={"tile_id": int(tile_id)},
            expected=_EXPECT_WRITE,
        )

    async def list_dashboard_templates(
        self, *, project_id: Optional[str] = None, limit: int = 30, offset: int = 0
    ) -> Result:
        return await arequest(
            "GET",
            self._proj("dashboard_templates/", project_id),
            headers=self._headers(json_body=False),
            params=self._page(limit, offset),
            expected=(200,),
        )

    # =================================================================
    # Feature flags
    # =================================================================

    async def list_feature_flags(
        self,
        *,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        active: Optional[bool] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        params = self._page(limit, offset)
        if search:
            params["search"] = search
        if active is not None:
            params["active"] = active
        return await arequest(
            "GET",
            self._proj("feature_flags/", project_id),
            headers=self._headers(json_body=False),
            params=params,
            expected=(200,),
        )

    async def get_feature_flag(
        self, flag_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"feature_flags/{flag_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def create_feature_flag(
        self,
        *,
        key: str,
        name: Optional[str] = None,
        active: bool = True,
        rollout_percentage: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        ensure_experience_continuity: Optional[bool] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        """Create a flag.

        ``filters`` wins when supplied; otherwise ``rollout_percentage``
        builds the single-group release condition that covers the common
        "roll out to N% of everyone" case.
        """
        if filters is None:
            pct = 100 if rollout_percentage is None else int(rollout_percentage)
            filters = {"groups": [{"properties": [], "rollout_percentage": pct}]}
        body = self._clean(
            {
                "key": key,
                "name": name if name is not None else key,
                "active": active,
                "filters": filters,
                "ensure_experience_continuity": ensure_experience_continuity,
            }
        )
        return await arequest(
            "POST",
            self._proj("feature_flags/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def update_feature_flag(
        self,
        flag_id: str,
        *,
        key: Optional[str] = None,
        name: Optional[str] = None,
        active: Optional[bool] = None,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {"key": key, "name": name, "active": active, "filters": filters}
        )
        return await arequest(
            "PATCH",
            self._proj(f"feature_flags/{flag_id}/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def set_feature_flag_rollout(
        self,
        flag_id: str,
        rollout_percentage: int,
        *,
        project_id: Optional[str] = None,
    ) -> Result:
        """Set the rollout percentage on the flag's first release condition.

        Reads the flag first so the other groups and their property
        filters survive — a blind PATCH of ``filters`` would drop them.
        """
        current = await self.get_feature_flag(flag_id, project_id=project_id)
        if "error" in current:
            return current
        flag = current.get("result") or {}
        filters = flag.get("filters") or {}
        groups = filters.get("groups") or [{"properties": []}]
        groups[0] = dict(groups[0])
        groups[0]["rollout_percentage"] = int(rollout_percentage)
        filters = dict(filters)
        filters["groups"] = groups
        return await self.update_feature_flag(
            flag_id, filters=filters, project_id=project_id
        )

    async def delete_feature_flag(
        self, flag_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Soft delete — recoverable by PATCHing ``deleted: false``."""
        return await arequest(
            "PATCH",
            self._proj(f"feature_flags/{flag_id}/", project_id),
            headers=self._headers(),
            json=_SOFT_DELETE_FLAG,
            expected=_EXPECT_WRITE,
        )

    async def enable_feature_flag(
        self, flag_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"feature_flags/{flag_id}/enable/", project_id),
            headers=self._headers(),
            json={},
            expected=_EXPECT_WRITE,
        )

    async def disable_feature_flag(
        self, flag_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"feature_flags/{flag_id}/disable/", project_id),
            headers=self._headers(),
            json={},
            expected=_EXPECT_WRITE,
        )

    async def archive_feature_flag(
        self, flag_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"feature_flags/{flag_id}/archive/", project_id),
            headers=self._headers(),
            json={},
            expected=_EXPECT_WRITE,
        )

    async def unarchive_feature_flag(
        self, flag_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"feature_flags/{flag_id}/unarchive/", project_id),
            headers=self._headers(),
            json={},
            expected=_EXPECT_WRITE,
        )

    async def get_feature_flag_status(
        self, flag_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"feature_flags/{flag_id}/status/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def get_feature_flag_blast_radius(
        self,
        *,
        condition: Dict[str, Any],
        group_type_index: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        """How many users a proposed release condition would match."""
        body = self._clean(
            {"condition": condition, "group_type_index": group_type_index}
        )
        return await arequest(
            "POST",
            self._proj("feature_flags/user_blast_radius/", project_id),
            headers=self._headers(),
            json=body,
            expected=(200,),
        )

    async def list_my_feature_flags(self, *, project_id: Optional[str] = None) -> Result:
        return await arequest(
            "GET",
            self._proj("feature_flags/my_flags/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def list_early_access_features(
        self, *, project_id: Optional[str] = None, limit: int = 30, offset: int = 0
    ) -> Result:
        return await arequest(
            "GET",
            self._proj("early_access_feature/", project_id),
            headers=self._headers(json_body=False),
            params=self._page(limit, offset),
            expected=(200,),
        )

    async def create_early_access_feature(
        self,
        *,
        name: str,
        description: Optional[str] = None,
        stage: str = "beta",
        feature_flag_id: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {
                "name": name,
                "description": description,
                "stage": stage,
                "feature_flag_id": feature_flag_id,
            }
        )
        return await arequest(
            "POST",
            self._proj("early_access_feature/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    # =================================================================
    # Persons
    # =================================================================

    async def list_persons(
        self,
        *,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        distinct_id: Optional[str] = None,
        email: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        params = self._page(limit, offset)
        if search:
            params["search"] = search
        if distinct_id:
            params["distinct_id"] = distinct_id
        if email:
            # PostHog's person search covers email; this is the documented
            # property-filter form.
            params["properties"] = (
                f'[{{"key":"email","value":"{email}","operator":"exact","type":"person"}}]'
            )
        return await arequest(
            "GET",
            self._proj("persons/", project_id),
            headers=self._headers(json_body=False),
            params=params,
            expected=(200,),
        )

    async def get_person(
        self, person_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"persons/{person_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def update_person(
        self,
        person_id: str,
        properties: Dict[str, Any],
        *,
        project_id: Optional[str] = None,
    ) -> Result:
        return await arequest(
            "PATCH",
            self._proj(f"persons/{person_id}/", project_id),
            headers=self._headers(),
            json={"properties": properties},
            expected=_EXPECT_WRITE,
        )

    async def update_person_property(
        self,
        person_id: str,
        key: str,
        value: Any,
        *,
        project_id: Optional[str] = None,
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"persons/{person_id}/update_property/", project_id),
            headers=self._headers(),
            json={"key": key, "value": value},
            expected=_EXPECT_WRITE,
        )

    async def delete_person_property(
        self, person_id: str, key: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "POST",
            self._proj(f"persons/{person_id}/delete_property/", project_id),
            headers=self._headers(),
            json={"$unset": key},
            expected=_EXPECT_WRITE,
        )

    async def delete_persons(
        self,
        *,
        person_ids: Optional[List[str]] = None,
        distinct_ids: Optional[List[str]] = None,
        delete_events: bool = False,
        project_id: Optional[str] = None,
    ) -> Result:
        """Bulk person deletion (the GDPR path).

        PostHog exposes no per-person DELETE; deletion goes through
        ``bulk_delete`` keyed by either uuid or distinct id.
        """
        params: Dict[str, Any] = {}
        if delete_events:
            params["delete_events"] = "true"
        body = self._clean({"ids": person_ids, "distinct_ids": distinct_ids})
        return await arequest(
            "POST",
            self._proj("persons/bulk_delete/", project_id),
            headers=self._headers(),
            json=body,
            params=params or None,
            expected=_EXPECT_WRITE,
        )

    async def list_person_cohorts(
        self, person_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj("persons/cohorts/", project_id),
            headers=self._headers(json_body=False),
            params={"person_id": person_id},
            expected=(200,),
        )

    async def get_person_properties_timeline(
        self, person_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"persons/{person_id}/properties_timeline/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def list_person_property_values(
        self, key: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Distinct values seen for one person property — useful before
        building a cohort or release condition on it."""
        return await arequest(
            "GET",
            self._proj("persons/values/", project_id),
            headers=self._headers(json_body=False),
            params={"key": key},
            expected=(200,),
        )

    # =================================================================
    # Cohorts
    # =================================================================

    async def list_cohorts(
        self, *, project_id: Optional[str] = None, limit: int = 30, offset: int = 0
    ) -> Result:
        return await arequest(
            "GET",
            self._proj("cohorts/", project_id),
            headers=self._headers(json_body=False),
            params=self._page(limit, offset),
            expected=(200,),
        )

    async def get_cohort(
        self, cohort_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"cohorts/{cohort_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def create_cohort(
        self,
        *,
        name: str,
        groups: Optional[List[Dict[str, Any]]] = None,
        description: Optional[str] = None,
        is_static: Optional[bool] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {
                "name": name,
                "groups": groups,
                "description": description,
                "is_static": is_static,
            }
        )
        return await arequest(
            "POST",
            self._proj("cohorts/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def update_cohort(
        self,
        cohort_id: str,
        *,
        name: Optional[str] = None,
        groups: Optional[List[Dict[str, Any]]] = None,
        description: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {"name": name, "groups": groups, "description": description}
        )
        return await arequest(
            "PATCH",
            self._proj(f"cohorts/{cohort_id}/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def delete_cohort(
        self, cohort_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Soft delete — recoverable by PATCHing ``deleted: false``."""
        return await arequest(
            "PATCH",
            self._proj(f"cohorts/{cohort_id}/", project_id),
            headers=self._headers(),
            json=_SOFT_DELETE_FLAG,
            expected=_EXPECT_WRITE,
        )

    async def list_cohort_persons(
        self,
        cohort_id: str,
        *,
        project_id: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"cohorts/{cohort_id}/persons/", project_id),
            headers=self._headers(json_body=False),
            params=self._page(limit, offset),
            expected=(200,),
        )

    async def add_persons_to_cohort(
        self,
        cohort_id: str,
        person_ids: List[str],
        *,
        project_id: Optional[str] = None,
    ) -> Result:
        """Static cohorts only — dynamic cohorts recompute from filters.

        The wire field is ``person_ids`` even though the values are person
        uuids (PostHog's naming, confirmed against the OpenAPI schema).
        """
        return await arequest(
            "PATCH",
            self._proj(
                f"cohorts/{cohort_id}/add_persons_to_static_cohort/", project_id
            ),
            headers=self._headers(),
            json={"person_ids": person_ids},
            expected=_EXPECT_WRITE,
        )

    # =================================================================
    # Annotations
    # =================================================================

    async def list_annotations(
        self, *, project_id: Optional[str] = None, limit: int = 30, offset: int = 0
    ) -> Result:
        return await arequest(
            "GET",
            self._proj("annotations/", project_id),
            headers=self._headers(json_body=False),
            params=self._page(limit, offset),
            expected=(200,),
        )

    async def get_annotation(
        self, annotation_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"annotations/{annotation_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def create_annotation(
        self,
        *,
        content: str,
        date_marker: Optional[str] = None,
        scope: str = "project",
        dashboard_item: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {
                "content": content,
                "date_marker": date_marker,
                "scope": scope,
                "dashboard_item": dashboard_item,
            }
        )
        return await arequest(
            "POST",
            self._proj("annotations/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def update_annotation(
        self,
        annotation_id: str,
        *,
        content: Optional[str] = None,
        date_marker: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean({"content": content, "date_marker": date_marker})
        return await arequest(
            "PATCH",
            self._proj(f"annotations/{annotation_id}/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def delete_annotation(
        self, annotation_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        """Soft delete — recoverable by PATCHing ``deleted: false``."""
        return await arequest(
            "PATCH",
            self._proj(f"annotations/{annotation_id}/", project_id),
            headers=self._headers(),
            json=_SOFT_DELETE_FLAG,
            expected=_EXPECT_WRITE,
        )

    # =================================================================
    # Definitions & actions
    # =================================================================

    async def list_event_definitions(
        self,
        *,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        params = self._page(limit, offset)
        if search:
            params["search"] = search
        return await arequest(
            "GET",
            self._proj("event_definitions/", project_id),
            headers=self._headers(json_body=False),
            params=params,
            expected=(200,),
        )

    async def get_event_definition(
        self, definition_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"event_definitions/{definition_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def update_event_definition(
        self,
        definition_id: str,
        *,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        verified: Optional[bool] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {"description": description, "tags": tags, "verified": verified}
        )
        return await arequest(
            "PATCH",
            self._proj(f"event_definitions/{definition_id}/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def list_property_definitions(
        self,
        *,
        project_id: Optional[str] = None,
        search: Optional[str] = None,
        event_names: Optional[List[str]] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> Result:
        params = self._page(limit, offset)
        if search:
            params["search"] = search
        if event_names:
            params["event_names"] = ",".join(event_names)
        return await arequest(
            "GET",
            self._proj("property_definitions/", project_id),
            headers=self._headers(json_body=False),
            params=params,
            expected=(200,),
        )

    async def update_property_definition(
        self,
        definition_id: str,
        *,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean({"description": description, "tags": tags})
        return await arequest(
            "PATCH",
            self._proj(f"property_definitions/{definition_id}/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    async def list_actions(
        self, *, project_id: Optional[str] = None, limit: int = 30, offset: int = 0
    ) -> Result:
        return await arequest(
            "GET",
            self._proj("actions/", project_id),
            headers=self._headers(json_body=False),
            params=self._page(limit, offset),
            expected=(200,),
        )

    async def get_action(
        self, action_id: str, *, project_id: Optional[str] = None
    ) -> Result:
        return await arequest(
            "GET",
            self._proj(f"actions/{action_id}/", project_id),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def create_action(
        self,
        *,
        name: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        description: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Result:
        body = self._clean(
            {"name": name, "steps": steps, "description": description}
        )
        return await arequest(
            "POST",
            self._proj("actions/", project_id),
            headers=self._headers(),
            json=body,
            expected=_EXPECT_WRITE,
        )

    # =================================================================
    # Projects, organization, user
    # =================================================================

    async def get_current_user(self) -> Result:
        return await arequest(
            "GET",
            self._api("users/@me/"),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def get_organization(self, organization_id: str = "@current") -> Result:
        return await arequest(
            "GET",
            self._api(f"organizations/{organization_id}/"),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def list_organization_members(
        self, organization_id: str = "@current", *, limit: int = 30, offset: int = 0
    ) -> Result:
        return await arequest(
            "GET",
            self._api(f"organizations/{organization_id}/members/"),
            headers=self._headers(json_body=False),
            params=self._page(limit, offset),
            expected=(200,),
        )

    async def list_projects(self, organization_id: str = "@current") -> Result:
        """Projects in the organization.

        Project listing hangs off the organization, not ``/api/projects/``
        — the latter only serves per-project sub-resources.
        """
        return await arequest(
            "GET",
            self._api(f"organizations/{organization_id}/projects/"),
            headers=self._headers(json_body=False),
            expected=(200,),
        )

    async def get_project(
        self, project_id: Optional[str] = None, organization_id: str = "@current"
    ) -> Result:
        return await arequest(
            "GET",
            self._api(
                f"organizations/{organization_id}/projects/"
                f"{self._project(project_id)}/"
            ),
            headers=self._headers(json_body=False),
            expected=(200,),
        )


# ── module-private helpers ───────────────────────────────────────────


def _sql_literal(value: str) -> str:
    """Single-quoted HogQL string literal with quotes escaped.

    The event-listing helpers compose HogQL from agent-supplied values;
    without escaping, an event name containing a quote would break the
    query (or worse, extend it).
    """
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _interval(date_range: str) -> str:
    """``-7d`` → ``7 day``. Falls back to 7 days on anything unparseable."""
    text = (date_range or "").strip().lstrip("-")
    units = {"d": "day", "w": "week", "m": "month", "h": "hour"}
    if text and text[-1].lower() in units and text[:-1].isdigit():
        return f"{int(text[:-1])} {units[text[-1].lower()]}"
    return "7 day"
