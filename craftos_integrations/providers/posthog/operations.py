"""PostHog operations — the agent-facing surface.

73 operations across nine tag sets. Every op maps to exactly one
``PostHogClient`` method via ``client_op``; the client returns the
package ``{ok, result}`` / ``{error, details}`` envelope, which
``shape_result`` collapses with no options needed.

Conventions enforced here (see craftos_integrations/README.md):
- names are verb-first and carry the integration name
- every list op takes ``limit`` (1-100, default 30) and ``offset``
- every op takes an optional ``project_id`` override; omitted, the
  client falls back to config → credential → PostHog's ``@current``
- mutations set ``parallelizable=False``; deletes also ``destructive=True``
- ``account`` is never declared — the host injects it

The intentionally-excluded surface is listed at the bottom of this file.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...contracts import Operation
from .._shared import client_op

_UMBRELLA = "posthog"


# ────────────────────────────────────────────────────────────────────────
# Schema-fragment builders (fresh dicts per call — never share instances)
# ────────────────────────────────────────────────────────────────────────


def _s(description: str, example: str = "") -> Dict[str, Any]:
    return {"type": "string", "description": description, "example": example}


def _i(description: str, example: int) -> Dict[str, Any]:
    return {"type": "integer", "description": description, "example": example}


def _b(description: str, example: bool = False) -> Dict[str, Any]:
    return {"type": "boolean", "description": description, "example": example}


def _arr(description: str, example: List[Any]) -> Dict[str, Any]:
    return {"type": "array", "description": description, "example": example}


def _obj(description: str, example: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "description": description, "example": example}


def _limit() -> Dict[str, Any]:
    return _i("Max results (1-100, default 30).", 30)


def _offset() -> Dict[str, Any]:
    return _i("Row offset for paging; add 'limit' each page.", 0)


def _project() -> Dict[str, Any]:
    return _s(
        "Numeric PostHog project id. Omit to use the connected account's "
        "project.",
        "",
    )


def _paged(**extra: Dict[str, Any]) -> Dict[str, Any]:
    schema = dict(extra)
    schema["limit"] = _limit()
    schema["offset"] = _offset()
    schema["project_id"] = _project()
    return schema


def build_operations() -> List[Operation]:
    return [
        # ═════════════════════════════════════════════════════════════
        # Query (HogQL) — tag: posthog_query
        # ═════════════════════════════════════════════════════════════
        client_op(
            "run_posthog_query",
            "run_query",
            description=(
                "Run a HogQL (SQL-like) query against PostHog analytics data "
                "and return the rows. Main tables: events, persons, sessions. "
                "Use this to answer any 'how many / which / top N' analytics "
                "question. Times out on wide date ranges — use "
                "run_posthog_query_async for those."
            ),
            tags=("posthog_query", _UMBRELLA),
            input_schema={
                "query": _s(
                    "HogQL query. Example: SELECT event, count() FROM events "
                    "WHERE timestamp > now() - interval 7 day GROUP BY event "
                    "ORDER BY count() DESC LIMIT 10",
                    "SELECT event, count() FROM events GROUP BY event LIMIT 10",
                ),
                "variables": _obj("Optional HogQL query variables.", {}),
                "refresh": _s(
                    "Cache behaviour: 'blocking', 'async', or 'force_blocking'.",
                    "",
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "run_posthog_query_async",
            "run_query_async",
            description=(
                "Start a HogQL query in the background and return a "
                "query_status with an id. Poll it with "
                "get_posthog_query_status. Use for large scans that would "
                "time out synchronously."
            ),
            tags=("posthog_query", _UMBRELLA),
            input_schema={
                "query": _s(
                    "HogQL query to run in the background.",
                    "SELECT count() FROM events WHERE timestamp > now() - interval 90 day",
                ),
                "variables": _obj("Optional HogQL query variables.", {}),
                "project_id": _project(),
            },
        ),
        client_op(
            "get_posthog_query_status",
            "get_query_status",
            description=(
                "Poll an async PostHog query by its query id. Returns "
                "{complete, results, error} — results are present once "
                "complete is true."
            ),
            tags=("posthog_query", _UMBRELLA),
            input_schema={
                "query_id": _s(
                    "Query id from run_posthog_query_async.",
                    "01890a5d-0000-0000-0000-000000000000",
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "cancel_posthog_query",
            "cancel_query",
            description="Cancel a running async PostHog query by its query id.",
            destructive=True,
            parallelizable=False,
            tags=("posthog_query",),
            input_schema={
                "query_id": _s(
                    "Query id from run_posthog_query_async.",
                    "01890a5d-0000-0000-0000-000000000000",
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "draft_posthog_sql",
            "draft_sql",
            description=(
                "Ask PostHog to draft a HogQL query from a plain-English "
                "description. Returns suggested SQL — run it with "
                "run_posthog_query."
            ),
            tags=("posthog_query",),
            input_schema={
                "prompt": _s(
                    "What the query should compute.",
                    "weekly active users for the last 8 weeks",
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_events",
            "list_events",
            description=(
                "List recent PostHog events, newest first, optionally "
                "filtered by event name, distinct_id and time window. Runs as "
                "a HogQL query (the legacy events endpoint is deprecated)."
            ),
            tags=("posthog_query",),
            input_schema={
                "event": _s("Event name to filter by.", "$pageview"),
                "distinct_id": _s("Only events from this distinct id.", ""),
                "after": _s("ISO timestamp lower bound.", "2026-09-01T00:00:00Z"),
                "before": _s("ISO timestamp upper bound.", ""),
                "limit": _limit(),
                "project_id": _project(),
            },
        ),
        client_op(
            "get_posthog_event",
            "get_event",
            description="Get one PostHog event by its uuid, with full properties.",
            tags=("posthog_query",),
            input_schema={
                "event_uuid": _s(
                    "Event uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "project_id": _project(),
            },
        ),
        # ═════════════════════════════════════════════════════════════
        # Insights — tag: posthog_insights
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_posthog_insights",
            "list_insights",
            description=(
                "List saved PostHog insights (charts). Returns numeric id, "
                "short_id, name and query for each."
            ),
            tags=("posthog_insights", _UMBRELLA),
            input_schema=_paged(
                search=_s("Filter by name or description text.", ""),
                favorited=_b("Only favorited insights.", True),
            ),
        ),
        client_op(
            "get_posthog_insight",
            "get_insight",
            description=(
                "Get a PostHog insight by its numeric id, including its query "
                "definition and the dashboards it belongs to."
            ),
            tags=("posthog_insights", _UMBRELLA),
            input_schema={
                "insight_id": _s("Numeric insight id.", "12345"),
                "project_id": _project(),
            },
        ),
        client_op(
            "create_posthog_insight",
            "create_insight",
            description=(
                "Create a saved PostHog insight. 'query' is a PostHog query "
                "node, e.g. {kind: 'HogQLQuery', query: 'SELECT ...'} or a "
                "TrendsQuery. Returns the new insight id and short_id."
            ),
            parallelizable=False,
            tags=("posthog_insights", _UMBRELLA),
            input_schema={
                "name": _s("Insight name.", "Weekly signups"),
                "query": _obj(
                    "PostHog query node defining the chart.",
                    {"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
                ),
                "description": _s("Longer description.", ""),
                "dashboards": _arr("Dashboard ids to add this insight to.", [1]),
                "favorited": _b("Mark as favorite.", False),
                "tags": _arr("Tags.", ["growth"]),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_insight",
            "update_insight",
            description=(
                "Update a PostHog insight by numeric id (name, query, "
                "description, dashboards, favorited, tags). Only the fields "
                "you pass are changed."
            ),
            parallelizable=False,
            tags=("posthog_insights", _UMBRELLA),
            input_schema={
                "insight_id": _s("Numeric insight id.", "12345"),
                "name": _s("New name.", ""),
                "query": _obj("Replacement query node.", {}),
                "description": _s("New description.", ""),
                "dashboards": _arr("Replacement list of dashboard ids.", [1]),
                "favorited": _b("Mark as favorite.", True),
                "tags": _arr("Replacement tags.", []),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_insight",
            "delete_insight",
            description=(
                "Delete a PostHog insight by numeric id. This is a soft "
                "delete — PostHog keeps the row and it can be restored."
            ),
            destructive=True,
            parallelizable=False,
            tags=("posthog_insights", _UMBRELLA),
            input_schema={
                "insight_id": _s("Numeric insight id.", "12345"),
                "project_id": _project(),
            },
        ),
        client_op(
            "get_posthog_insight_sharing",
            "get_insight_sharing",
            description=(
                "Get the sharing configuration for an insight — whether it is "
                "publicly shared and its share link."
            ),
            tags=("posthog_insights",),
            input_schema={
                "insight_id": _s("Numeric insight id.", "12345"),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_trending_insights",
            "list_trending_insights",
            description="List the insights most viewed recently in this project.",
            tags=("posthog_insights",),
            input_schema={"project_id": _project()},
        ),
        client_op(
            "get_posthog_insight_activity",
            "get_insight_activity",
            description="Get the change history for one PostHog insight.",
            tags=("posthog_insights",),
            input_schema={
                "insight_id": _s("Numeric insight id.", "12345"),
                "project_id": _project(),
            },
        ),
        # ═════════════════════════════════════════════════════════════
        # Dashboards — tag: posthog_dashboards
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_posthog_dashboards",
            "list_dashboards",
            description=(
                "List PostHog dashboards. Returns numeric id, name, "
                "description and pinned state."
            ),
            tags=("posthog_dashboards", _UMBRELLA),
            input_schema=_paged(search=_s("Filter by name text.", "")),
        ),
        client_op(
            "get_posthog_dashboard",
            "get_dashboard",
            description=(
                "Get a PostHog dashboard by numeric id, including its tiles "
                "and the insights on them."
            ),
            tags=("posthog_dashboards", _UMBRELLA),
            input_schema={
                "dashboard_id": _s("Numeric dashboard id.", "1"),
                "project_id": _project(),
            },
        ),
        client_op(
            "create_posthog_dashboard",
            "create_dashboard",
            description="Create an empty PostHog dashboard. Returns its numeric id.",
            parallelizable=False,
            tags=("posthog_dashboards", _UMBRELLA),
            input_schema={
                "name": _s("Dashboard name.", "Growth overview"),
                "description": _s("Description.", ""),
                "pinned": _b("Pin to the project sidebar.", False),
                "tags": _arr("Tags.", []),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_dashboard",
            "update_dashboard",
            description=(
                "Update a PostHog dashboard by numeric id (name, description, "
                "pinned, tags). Only the fields you pass are changed."
            ),
            parallelizable=False,
            tags=("posthog_dashboards", _UMBRELLA),
            input_schema={
                "dashboard_id": _s("Numeric dashboard id.", "1"),
                "name": _s("New name.", ""),
                "description": _s("New description.", ""),
                "pinned": _b("Pin or unpin.", True),
                "tags": _arr("Replacement tags.", []),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_dashboard",
            "delete_dashboard",
            description=(
                "Delete a PostHog dashboard by numeric id. Soft delete — the "
                "dashboard can be restored."
            ),
            destructive=True,
            parallelizable=False,
            tags=("posthog_dashboards", _UMBRELLA),
            input_schema={
                "dashboard_id": _s("Numeric dashboard id.", "1"),
                "project_id": _project(),
            },
        ),
        client_op(
            "add_posthog_insight_to_dashboard",
            "add_insight_to_dashboard",
            description=(
                "Add an existing insight to a dashboard. Takes the numeric "
                "insight id and numeric dashboard id; keeps the insight's "
                "other dashboards."
            ),
            parallelizable=False,
            tags=("posthog_dashboards",),
            input_schema={
                "insight_id": _s("Numeric insight id.", "12345"),
                "dashboard_id": _s("Numeric dashboard id.", "1"),
                "project_id": _project(),
            },
        ),
        client_op(
            "create_posthog_dashboard_text_tile",
            "create_dashboard_text_tile",
            description=(
                "Add a markdown text tile to a PostHog dashboard — useful for "
                "captions and context next to charts."
            ),
            parallelizable=False,
            tags=("posthog_dashboards",),
            input_schema={
                "dashboard_id": _s("Numeric dashboard id.", "1"),
                "body": _s("Markdown text for the tile.", "## Q3 goals"),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_dashboard_tile",
            "delete_dashboard_tile",
            description="Remove one tile from a PostHog dashboard by tile id.",
            destructive=True,
            parallelizable=False,
            tags=("posthog_dashboards",),
            input_schema={
                "dashboard_id": _s("Numeric dashboard id.", "1"),
                "tile_id": _s("Numeric tile id (from get_posthog_dashboard).", "42"),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_dashboard_templates",
            "list_dashboard_templates",
            description="List dashboard templates available in this project.",
            tags=("posthog_dashboards",),
            input_schema=_paged(),
        ),
        # ═════════════════════════════════════════════════════════════
        # Feature flags — tag: posthog_feature_flags
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_posthog_feature_flags",
            "list_feature_flags",
            description=(
                "List PostHog feature flags. Returns numeric id, key, name, "
                "active state and release conditions."
            ),
            tags=("posthog_feature_flags", _UMBRELLA),
            input_schema=_paged(
                search=_s("Filter by key or name text.", ""),
                active=_b("Only active (true) or only inactive (false) flags.", True),
            ),
        ),
        client_op(
            "get_posthog_feature_flag",
            "get_feature_flag",
            description=(
                "Get a PostHog feature flag by its numeric id (not its key). "
                "Use list_posthog_feature_flags to find the id for a key."
            ),
            tags=("posthog_feature_flags", _UMBRELLA),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "project_id": _project(),
            },
        ),
        client_op(
            "create_posthog_feature_flag",
            "create_feature_flag",
            description=(
                "Create a PostHog feature flag. Pass 'rollout_percentage' for "
                "the common percentage rollout, or 'filters' for full control "
                "over release conditions. Returns the new flag id."
            ),
            parallelizable=False,
            tags=("posthog_feature_flags", _UMBRELLA),
            input_schema={
                "key": _s("Flag key used in code.", "new-checkout"),
                "name": _s("Human-readable name; defaults to the key.", ""),
                "active": _b("Whether the flag is enabled on creation.", True),
                "rollout_percentage": _i("Percentage of users (0-100).", 100),
                "filters": _obj(
                    "Full release-condition object; overrides "
                    "rollout_percentage when given.",
                    {"groups": [{"properties": [], "rollout_percentage": 50}]},
                ),
                "ensure_experience_continuity": _b(
                    "Keep a user's variant stable across sessions.", False
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_feature_flag",
            "update_feature_flag",
            description=(
                "Update a PostHog feature flag by numeric id (key, name, "
                "active, filters). To change only the rollout percentage use "
                "set_posthog_feature_flag_rollout, which preserves the other "
                "release conditions."
            ),
            parallelizable=False,
            tags=("posthog_feature_flags", _UMBRELLA),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "key": _s("New flag key.", ""),
                "name": _s("New name.", ""),
                "active": _b("Enable or disable.", True),
                "filters": _obj("Replacement release conditions.", {}),
                "project_id": _project(),
            },
        ),
        client_op(
            "set_posthog_feature_flag_rollout",
            "set_feature_flag_rollout",
            description=(
                "Set the rollout percentage on a feature flag's first release "
                "condition, leaving its other conditions and property filters "
                "intact."
            ),
            parallelizable=False,
            tags=("posthog_feature_flags",),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "rollout_percentage": _i("Percentage of users (0-100).", 25),
                "project_id": _project(),
            },
        ),
        client_op(
            "enable_posthog_feature_flag",
            "enable_feature_flag",
            description="Turn a PostHog feature flag on, by numeric id.",
            parallelizable=False,
            tags=("posthog_feature_flags", _UMBRELLA),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "project_id": _project(),
            },
        ),
        client_op(
            "disable_posthog_feature_flag",
            "disable_feature_flag",
            description="Turn a PostHog feature flag off, by numeric id.",
            parallelizable=False,
            tags=("posthog_feature_flags", _UMBRELLA),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_feature_flag",
            "delete_feature_flag",
            description=(
                "Delete a PostHog feature flag by numeric id. Soft delete — "
                "the flag stops evaluating but can be restored. Prefer "
                "disable_posthog_feature_flag to turn a flag off."
            ),
            destructive=True,
            parallelizable=False,
            tags=("posthog_feature_flags", _UMBRELLA),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "project_id": _project(),
            },
        ),
        client_op(
            "archive_posthog_feature_flag",
            "archive_feature_flag",
            description=(
                "Archive a PostHog feature flag — hides it from the active "
                "list without deleting it."
            ),
            parallelizable=False,
            tags=("posthog_feature_flags",),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "project_id": _project(),
            },
        ),
        client_op(
            "unarchive_posthog_feature_flag",
            "unarchive_feature_flag",
            description="Restore an archived PostHog feature flag to the active list.",
            parallelizable=False,
            tags=("posthog_feature_flags",),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "project_id": _project(),
            },
        ),
        client_op(
            "get_posthog_feature_flag_status",
            "get_feature_flag_status",
            description=(
                "Get a feature flag's evaluation status — whether it is "
                "actively being evaluated and any staleness warnings."
            ),
            tags=("posthog_feature_flags",),
            input_schema={
                "flag_id": _s("Numeric feature flag id.", "678"),
                "project_id": _project(),
            },
        ),
        client_op(
            "get_posthog_feature_flag_blast_radius",
            "get_feature_flag_blast_radius",
            description=(
                "Estimate how many users a proposed release condition would "
                "match, before applying it to a flag."
            ),
            tags=("posthog_feature_flags",),
            input_schema={
                "condition": _obj(
                    "Release condition to evaluate.",
                    {"properties": [], "rollout_percentage": 50},
                ),
                "group_type_index": _i("Group type index for group-based flags.", 0),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_my_feature_flags",
            "list_my_feature_flags",
            description=(
                "List feature flags as they evaluate for the connected user — "
                "which flags are on for you right now."
            ),
            tags=("posthog_feature_flags",),
            input_schema={"project_id": _project()},
        ),
        client_op(
            "list_posthog_early_access_features",
            "list_early_access_features",
            description=(
                "List early-access features (public beta opt-ins backed by "
                "feature flags)."
            ),
            tags=("posthog_feature_flags",),
            input_schema=_paged(),
        ),
        client_op(
            "create_posthog_early_access_feature",
            "create_early_access_feature",
            description=(
                "Create an early-access feature so users can opt into a beta. "
                "Links to an existing feature flag when given one."
            ),
            parallelizable=False,
            tags=("posthog_feature_flags",),
            input_schema={
                "name": _s("Feature name shown to users.", "New checkout"),
                "description": _s("What the beta does.", ""),
                "stage": _s("One of: draft, concept, alpha, beta, general.", "beta"),
                "feature_flag_id": _i("Numeric id of the backing flag.", 678),
                "project_id": _project(),
            },
        ),
        # ═════════════════════════════════════════════════════════════
        # Persons — tag: posthog_persons
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_posthog_persons",
            "list_persons",
            description=(
                "List or search PostHog persons (tracked users). Search by "
                "free text, exact distinct_id, or email. Returns person uuid, "
                "distinct_ids and properties."
            ),
            tags=("posthog_persons", _UMBRELLA),
            input_schema=_paged(
                search=_s("Free-text search across person properties.", ""),
                distinct_id=_s("Exact distinct id to look up.", ""),
                email=_s("Exact email to look up.", "user@example.com"),
            ),
        ),
        client_op(
            "get_posthog_person",
            "get_person",
            description=(
                "Get one PostHog person by uuid (not distinct_id — use "
                "list_posthog_persons with distinct_id to resolve one)."
            ),
            tags=("posthog_persons",),
            input_schema={
                "person_id": _s(
                    "Person uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_person",
            "update_person",
            description=(
                "Replace a person's properties dict, by person uuid. Merges "
                "at the top level — pass only the keys you want set."
            ),
            parallelizable=False,
            tags=("posthog_persons",),
            input_schema={
                "person_id": _s(
                    "Person uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "properties": _obj(
                    "Person properties to set.", {"plan": "pro", "company": "Acme"}
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_person_property",
            "update_person_property",
            description="Set a single property on a person, by person uuid.",
            parallelizable=False,
            tags=("posthog_persons",),
            input_schema={
                "person_id": _s(
                    "Person uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "key": _s("Property name.", "plan"),
                "value": _s("Property value.", "pro"),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_person_property",
            "delete_person_property",
            description="Remove a single property from a person, by person uuid.",
            destructive=True,
            parallelizable=False,
            tags=("posthog_persons",),
            input_schema={
                "person_id": _s(
                    "Person uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "key": _s("Property name to remove.", "plan"),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_persons",
            "delete_persons",
            description=(
                "Permanently delete persons by uuid or distinct id — the GDPR "
                "erasure path. Optionally deletes their events too. This "
                "cannot be undone."
            ),
            destructive=True,
            parallelizable=False,
            tags=("posthog_persons",),
            input_schema={
                "person_ids": _arr(
                    "Person uuids to delete.",
                    ["01890a5d-0000-0000-0000-000000000000"],
                ),
                "distinct_ids": _arr(
                    "Distinct ids to delete instead of uuids.", ["user_123"]
                ),
                "delete_events": _b(
                    "Also delete every event these persons produced.", False
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_person_cohorts",
            "list_person_cohorts",
            description="List the cohorts one person currently belongs to.",
            tags=("posthog_persons",),
            input_schema={
                "person_id": _s(
                    "Person uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "get_posthog_person_properties_timeline",
            "get_person_properties_timeline",
            description=(
                "Get how one person's properties changed over time, by person "
                "uuid."
            ),
            tags=("posthog_persons",),
            input_schema={
                "person_id": _s(
                    "Person uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_person_property_values",
            "list_person_property_values",
            description=(
                "List the distinct values seen for one person property — use "
                "before building a cohort or release condition on it."
            ),
            tags=("posthog_persons",),
            input_schema={
                "key": _s("Person property name.", "plan"),
                "project_id": _project(),
            },
        ),
        # ═════════════════════════════════════════════════════════════
        # Cohorts — tag: posthog_cohorts
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_posthog_cohorts",
            "list_cohorts",
            description=(
                "List PostHog cohorts (saved groups of persons). Returns "
                "numeric id, name, count and whether the cohort is static."
            ),
            tags=("posthog_cohorts", _UMBRELLA),
            input_schema=_paged(),
        ),
        client_op(
            "get_posthog_cohort",
            "get_cohort",
            description="Get a PostHog cohort by numeric id, including its filters.",
            tags=("posthog_cohorts",),
            input_schema={
                "cohort_id": _s("Numeric cohort id.", "42"),
                "project_id": _project(),
            },
        ),
        client_op(
            "create_posthog_cohort",
            "create_cohort",
            description=(
                "Create a PostHog cohort. Dynamic cohorts recompute from "
                "'groups' filters; static cohorts (is_static true) are filled "
                "with add_posthog_persons_to_cohort."
            ),
            parallelizable=False,
            tags=("posthog_cohorts",),
            input_schema={
                "name": _s("Cohort name.", "Power users"),
                "groups": _arr(
                    "Filter groups defining membership.",
                    [{"properties": [{"key": "plan", "value": "pro"}]}],
                ),
                "description": _s("Description.", ""),
                "is_static": _b("Static (manually filled) rather than dynamic.", False),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_cohort",
            "update_cohort",
            description=(
                "Update a PostHog cohort by numeric id (name, groups, "
                "description)."
            ),
            parallelizable=False,
            tags=("posthog_cohorts",),
            input_schema={
                "cohort_id": _s("Numeric cohort id.", "42"),
                "name": _s("New name.", ""),
                "groups": _arr("Replacement filter groups.", []),
                "description": _s("New description.", ""),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_cohort",
            "delete_cohort",
            description=(
                "Delete a PostHog cohort by numeric id. Soft delete — the "
                "cohort can be restored."
            ),
            destructive=True,
            parallelizable=False,
            tags=("posthog_cohorts",),
            input_schema={
                "cohort_id": _s("Numeric cohort id.", "42"),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_cohort_persons",
            "list_cohort_persons",
            description="List the persons currently in a cohort, by numeric cohort id.",
            tags=("posthog_cohorts",),
            input_schema=_paged(cohort_id=_s("Numeric cohort id.", "42")),
        ),
        client_op(
            "add_posthog_persons_to_cohort",
            "add_persons_to_cohort",
            description=(
                "Add persons to a static cohort by their uuids. Only works on "
                "static cohorts — dynamic ones recompute from their filters."
            ),
            parallelizable=False,
            tags=("posthog_cohorts",),
            input_schema={
                "cohort_id": _s("Numeric cohort id.", "42"),
                "person_ids": _arr(
                    "Person uuids to add (the field is named person_ids).",
                    ["01890a5d-0000-0000-0000-000000000000"],
                ),
                "project_id": _project(),
            },
        ),
        # ═════════════════════════════════════════════════════════════
        # Annotations — tag: posthog_annotations
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_posthog_annotations",
            "list_annotations",
            description=(
                "List PostHog annotations — dated notes shown on chart "
                "timelines (deploys, launches, incidents)."
            ),
            tags=("posthog_annotations",),
            input_schema=_paged(),
        ),
        client_op(
            "get_posthog_annotation",
            "get_annotation",
            description="Get one PostHog annotation by numeric id.",
            tags=("posthog_annotations",),
            input_schema={
                "annotation_id": _s("Numeric annotation id.", "7"),
                "project_id": _project(),
            },
        ),
        client_op(
            "create_posthog_annotation",
            "create_annotation",
            description=(
                "Create a PostHog annotation — a dated note on the chart "
                "timeline. Use for deploys, launches and incidents so trends "
                "can be explained later."
            ),
            parallelizable=False,
            tags=("posthog_annotations", _UMBRELLA),
            input_schema={
                "content": _s("Note text.", "Shipped v1.4.3"),
                "date_marker": _s(
                    "ISO timestamp the note marks; defaults to now.",
                    "2026-09-20T12:00:00Z",
                ),
                "scope": _s("One of: project, organization, dashboard_item.", "project"),
                "dashboard_item": _i("Insight id when scope is dashboard_item.", 12345),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_annotation",
            "update_annotation",
            description="Update a PostHog annotation's text or date, by numeric id.",
            parallelizable=False,
            tags=("posthog_annotations",),
            input_schema={
                "annotation_id": _s("Numeric annotation id.", "7"),
                "content": _s("New note text.", ""),
                "date_marker": _s("New ISO timestamp.", ""),
                "project_id": _project(),
            },
        ),
        client_op(
            "delete_posthog_annotation",
            "delete_annotation",
            description=(
                "Delete a PostHog annotation by numeric id. Soft delete — it "
                "can be restored."
            ),
            destructive=True,
            parallelizable=False,
            tags=("posthog_annotations", _UMBRELLA),
            input_schema={
                "annotation_id": _s("Numeric annotation id.", "7"),
                "project_id": _project(),
            },
        ),
        # ═════════════════════════════════════════════════════════════
        # Definitions & actions — tag: posthog_definitions
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_posthog_event_definitions",
            "list_event_definitions",
            description=(
                "List the event types tracked in this project, with "
                "descriptions and verified status. Use this to discover what "
                "event names exist before writing a HogQL query."
            ),
            tags=("posthog_definitions",),
            input_schema=_paged(search=_s("Filter by event name text.", "")),
        ),
        client_op(
            "get_posthog_event_definition",
            "get_event_definition",
            description="Get one event definition by its uuid.",
            tags=("posthog_definitions",),
            input_schema={
                "definition_id": _s(
                    "Event definition uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "project_id": _project(),
            },
        ),
        client_op(
            "update_posthog_event_definition",
            "update_event_definition",
            description=(
                "Update an event definition's description, tags or verified "
                "flag — how the event is documented for the team."
            ),
            parallelizable=False,
            tags=("posthog_definitions",),
            input_schema={
                "definition_id": _s(
                    "Event definition uuid.", "01890a5d-0000-0000-0000-000000000000"
                ),
                "description": _s("What this event means.", ""),
                "tags": _arr("Tags.", []),
                "verified": _b("Mark as verified/official.", True),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_property_definitions",
            "list_property_definitions",
            description=(
                "List the event or person properties tracked in this project. "
                "Use to discover filterable property names."
            ),
            tags=("posthog_definitions",),
            input_schema=_paged(
                search=_s("Filter by property name text.", ""),
                event_names=_arr("Only properties seen on these events.", ["$pageview"]),
            ),
        ),
        client_op(
            "update_posthog_property_definition",
            "update_property_definition",
            description="Update a property definition's description or tags.",
            parallelizable=False,
            tags=("posthog_definitions",),
            input_schema={
                "definition_id": _s(
                    "Property definition uuid.",
                    "01890a5d-0000-0000-0000-000000000000",
                ),
                "description": _s("What this property means.", ""),
                "tags": _arr("Tags.", []),
                "project_id": _project(),
            },
        ),
        client_op(
            "list_posthog_actions",
            "list_actions",
            description=(
                "List PostHog actions — saved combinations of events and "
                "selectors treated as one named behaviour."
            ),
            tags=("posthog_definitions",),
            input_schema=_paged(),
        ),
        client_op(
            "get_posthog_action",
            "get_action",
            description="Get one PostHog action by numeric id, including its steps.",
            tags=("posthog_definitions",),
            input_schema={
                "action_id": _s("Numeric action id.", "99"),
                "project_id": _project(),
            },
        ),
        client_op(
            "create_posthog_action",
            "create_action",
            description=(
                "Create a PostHog action from one or more matching steps "
                "(event name, URL, CSS selector)."
            ),
            parallelizable=False,
            tags=("posthog_definitions",),
            input_schema={
                "name": _s("Action name.", "Clicked signup"),
                "steps": _arr(
                    "Matching steps.",
                    [{"event": "$autocapture", "selector": "button.signup"}],
                ),
                "description": _s("Description.", ""),
                "project_id": _project(),
            },
        ),
        # ═════════════════════════════════════════════════════════════
        # Projects / organization / user — tag: posthog_projects
        # ═════════════════════════════════════════════════════════════
        client_op(
            "get_posthog_current_user",
            "get_current_user",
            description=(
                "Get the connected PostHog user, their organization and "
                "current project. Use to confirm which account and project "
                "the agent is acting on."
            ),
            tags=("posthog_projects",),
            input_schema={},
        ),
        client_op(
            "get_posthog_organization",
            "get_organization",
            description="Get a PostHog organization; defaults to the current one.",
            tags=("posthog_projects",),
            input_schema={
                "organization_id": _s(
                    "Organization uuid, or '@current'.", "@current"
                ),
            },
        ),
        client_op(
            "list_posthog_organization_members",
            "list_organization_members",
            description="List members of a PostHog organization, with their roles.",
            tags=("posthog_projects",),
            input_schema={
                "organization_id": _s(
                    "Organization uuid, or '@current'.", "@current"
                ),
                "limit": _limit(),
                "offset": _offset(),
            },
        ),
        client_op(
            "list_posthog_projects",
            "list_projects",
            description=(
                "List the projects in the organization, with their numeric "
                "ids. Pass an id as 'project_id' on any other operation to "
                "target that project."
            ),
            tags=("posthog_projects", _UMBRELLA),
            input_schema={
                "organization_id": _s(
                    "Organization uuid, or '@current'.", "@current"
                ),
            },
        ),
        client_op(
            "get_posthog_project",
            "get_project",
            description=(
                "Get one PostHog project by numeric id, including its "
                "timezone and ingestion settings."
            ),
            tags=("posthog_projects",),
            input_schema={
                "project_id": _project(),
                "organization_id": _s(
                    "Organization uuid, or '@current'.", "@current"
                ),
            },
        ),
    ]


# ════════════════════════════════════════════════════════════════════════
# Intentionally NOT exposed
# ════════════════════════════════════════════════════════════════════════
#
# Scope decision for v1 (core analytics + feature flags). Recorded so the
# next session does not re-litigate it. See
# docs/plans/posthog-integration-plan.md §3.
#
# - Session recordings / replay — large payloads, little an agent can do
#   with them beyond listing; the value is in watching them. Most likely
#   v2 addition.
# - Experiments (+ holdouts, saved metrics) — statistical lifecycle an
#   agent should not drive unsupervised. Second most likely v2 addition.
# - Surveys — authoring surveys is a design task, not an agent task.
# - Batch exports, external data sources/schemas, warehouse tables/views —
#   data-pipeline configuration; destructive to get wrong, rarely asked
#   for conversationally.
# - Error tracking, LLM analytics/observability, logs, tracing — separate
#   products with their own surfaces; would double the action count.
# - Billing, subscriptions, usage metrics — money. Never agent-driven.
# - Organization admin: invites, roles, access control, SSO/SAML/SCIM,
#   2FA, login sessions, API key management — privilege escalation
#   surface. Deliberately excluded even though the scopes allow it.
# - Plugins / hog functions / hog flows / data pipelines — code
#   deployment into the user's PostHog instance.
# - Notebooks, canvases, comments, file system, subscriptions, alerts —
#   collaboration surfaces with no clear agent workflow yet.
# - Web analytics, revenue analytics, marketing analytics, customer
#   analytics — product-specific dashboards reachable through HogQL
#   anyway via run_posthog_query.
# - Event ingestion (/i/v0/e, /batch) — that is the SDK's job, uses the
#   project API key (phc_), and is a different auth model entirely.
