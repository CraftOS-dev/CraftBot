"""Supabase operations — the agent-facing surface.

71 operations across ten tag sets. Every op maps to exactly one
``SupabaseClient`` method via ``client_op``; the client returns the
package ``{ok, result}`` / ``{error, details}`` envelope, which
``shape_result`` collapses with no options needed.

Conventions enforced here (see craftos_integrations/README.md):
- names are verb-first and carry the integration name
- every project-scoped op takes an optional ``project_ref``; omitted, the
  client falls back to the configured default project
- mutations set ``parallelizable=False``; anything that deletes, wipes,
  or takes a service offline also sets ``destructive=True``
- ``account`` is never declared — the host injects it

The intentionally-excluded surface is listed at the bottom of this file.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...contracts import Operation
from .._shared import client_op

_UMBRELLA = "supabase"
_PROJECTS = "supabase_projects"
_DATABASE = "supabase_database"
_MIGRATIONS = "supabase_migrations"
_ROWS = "supabase_rows"
_STORAGE = "supabase_storage"
_AUTH = "supabase_auth"
_FUNCTIONS = "supabase_functions"
_SECRETS = "supabase_secrets"
_BRANCHES = "supabase_branches"
_MONITORING = "supabase_monitoring"


# ────────────────────────────────────────────────────────────────────────
# Schema-fragment builders (fresh dicts per call — never share instances)
# ────────────────────────────────────────────────────────────────────────


def _s(description: str, example: str = "", *, required: bool) -> Dict[str, Any]:
    return {"type": "string", "required": required, "description": description, "example": example}


def _i(description: str, example: int, *, required: bool) -> Dict[str, Any]:
    return {"type": "integer", "required": required, "description": description, "example": example}


def _b(description: str, example: bool = False, *, required: bool) -> Dict[str, Any]:
    return {"type": "boolean", "required": required, "description": description, "example": example}


def _arr(description: str, example: List[Any], *, required: bool) -> Dict[str, Any]:
    return {"type": "array", "required": required, "description": description, "example": example}


def _obj(description: str, example: Dict[str, Any], *, required: bool) -> Dict[str, Any]:
    return {"type": "object", "required": required, "description": description, "example": example}


def _ref(*, required: bool) -> Dict[str, Any]:
    return _s(
        "20-character project ref (e.g. from list_supabase_projects). Omit to "
        "use the default project from the integration config.",
        "abcdefghijklmnopqrst",
        required=required,
    )


def _schema(*, required: bool) -> Dict[str, Any]:
    return _s("Postgres schema. Default 'public'.", "public", required=required)


def _table(*, required: bool) -> Dict[str, Any]:
    return _s("Table or view name, without the schema prefix.", "orders", required=required)


def _filters(example: Dict[str, Any], *, required: bool) -> Dict[str, Any]:
    return _obj(
        "Row filters in PostgREST syntax: {column: '<op>.<value>'}. Operators: "
        "eq, neq, gt, gte, lt, lte, like, ilike, is, in, cs, cd. Examples: "
        "{'id': 'eq.42'}, {'status': 'in.(open,pending)'}, "
        "{'deleted_at': 'is.null'}. A list value repeats the column "
        "(['gte.18', 'lt.65']). Use key 'or' for "
        "'(status.eq.open,priority.gt.3)'.",
        example,
        required=required,
    )


def _bucket(*, required: bool) -> Dict[str, Any]:
    return _s("Storage bucket id (its name).", "avatars", required=required)


def _object_path(*, required: bool) -> Dict[str, Any]:
    return _s(
        "Object path inside the bucket, '/'-separated, no leading slash.",
        "users/42/profile.png",
        required=required,
    )


def _branch_id(*, required: bool) -> Dict[str, Any]:
    return _s(
        "Branch id (UUID) or the branch's own project ref, from "
        "list_supabase_branches.",
        "0b4c1f9e-2a7d-4c3e-9f10-5d6e7a8b9c0d",
        required=required,
    )


def build_operations() -> List[Operation]:
    return [
        # ═════════════════════════════════════════════════════════════
        # Projects & organizations — tag: supabase_projects
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_supabase_projects",
            "list_projects",
            description=(
                "List every Supabase project the connected account can see. "
                "Returns ref (the project identifier every other operation "
                "takes), name, organization_slug, region and status."
            ),
            input_schema={
                "organization_slug": _s(
                    "Only projects in this organization.", "",
                    required=False,
                ),
            },
            tags=(_PROJECTS, _UMBRELLA),
        ),
        client_op(
            "get_supabase_project",
            "get_project",
            description=(
                "Get one project by ref: name, region, status (ACTIVE_HEALTHY, "
                "INACTIVE = paused, …), database host and Postgres version."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_PROJECTS, _UMBRELLA),
        ),
        client_op(
            "get_supabase_project_keys",
            "get_project_keys",
            description=(
                "Get a project's API URL and publishable (anon) key — the two "
                "values a frontend or mobile app needs to talk to Supabase. "
                "Never returns the secret/service_role key."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_PROJECTS, _UMBRELLA),
        ),
        client_op(
            "create_supabase_project",
            "create_project",
            description=(
                "Create a new Supabase project in an organization. May incur "
                "charges on paid plans — confirm with the user first. Returns "
                "the new project (ref, status COMING_UP); when db_pass is "
                "omitted a strong one is generated and returned once as "
                "generated_db_password."
            ),
            input_schema={
                "name": _s("Project name.", "acme-prod", required=True),
                "organization_slug": _s(
                    "Organization slug from list_supabase_organizations.",
                    "acme-inc",
                    required=True,
                ),
                "db_pass": _s(
                    "Database password. Omit to generate a strong one.", "",
                    required=False,
                ),
                "region": _s(
                    "Region code (e.g. 'us-east-1', 'eu-central-1') or a "
                    "smart group ('americas', 'emea', 'apac'). See "
                    "list_supabase_regions.",
                    "us-east-1",
                    required=False,
                ),
                "desired_instance_size": _s(
                    "Compute size (nano, micro, small, medium, large, …). "
                    "Omit for the plan default.",
                    "",
                    required=False,
                ),
            },
            parallelizable=False,
            tags=(_PROJECTS,),
        ),
        client_op(
            "update_supabase_project",
            "update_project",
            description="Rename a Supabase project. Returns its id, ref and new name.",
            input_schema={
                "name": _s("New project name.", "acme-production", required=True),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_PROJECTS,),
        ),
        client_op(
            "delete_supabase_project",
            "delete_project",
            description=(
                "Permanently delete a Supabase project and ALL its data, "
                "storage and functions. Irreversible — confirm the exact ref "
                "and name with the user first. project_ref is required here "
                "(no default fallback)."
            ),
            input_schema={
                "project_ref": _s(
                    "20-character ref of the project to delete. Required.",
                    "abcdefghijklmnopqrst",
                    required=True,
                ),
            },
            destructive=True,
            parallelizable=False,
            tags=(_PROJECTS,),
        ),
        client_op(
            "pause_supabase_project",
            "pause_project",
            description=(
                "Pause a project: its API and database go offline until "
                "restored. Data is kept. Use restore_supabase_project to "
                "bring it back."
            ),
            input_schema={"project_ref": _ref(required=False)},
            destructive=True,
            parallelizable=False,
            tags=(_PROJECTS,),
        ),
        client_op(
            "restore_supabase_project",
            "restore_project",
            description=(
                "Un-pause a paused project (status INACTIVE). Takes a few "
                "minutes; poll get_supabase_project until ACTIVE_HEALTHY. "
                "This is not a backup restore."
            ),
            input_schema={"project_ref": _ref(required=False)},
            parallelizable=False,
            tags=(_PROJECTS,),
        ),
        client_op(
            "restart_supabase_project",
            "restart_project",
            description=(
                "Restart a project's services (database, API, auth). Causes a "
                "short outage. Use after config changes that require it."
            ),
            input_schema={"project_ref": _ref(required=False)},
            parallelizable=False,
            tags=(_PROJECTS,),
        ),
        client_op(
            "get_supabase_project_health",
            "get_project_health",
            description=(
                "Health status of a project's services (auth, db, pooler, "
                "realtime, rest, storage). Returns one entry per service with "
                "status ACTIVE_HEALTHY / COMING_UP / UNHEALTHY."
            ),
            input_schema={
                "services": _arr(
                    "Subset of services to check. Omit for all.", ["db", "rest"],
                    required=False,
                ),
                "project_ref": _ref(required=False),
            },
            tags=(_PROJECTS,),
        ),
        client_op(
            "list_supabase_regions",
            "list_regions",
            description=(
                "Regions available for a new project in an organization, with "
                "Supabase's recommendation. Use before create_supabase_project."
            ),
            input_schema={
                "organization_slug": _s("Organization slug.", "acme-inc", required=True),
                "continent": _s(
                    "Bias the recommendation: NA, SA, EU, AF, AS, OC.", "EU",
                    required=False,
                ),
            },
            tags=(_PROJECTS,),
        ),
        client_op(
            "list_supabase_organizations",
            "list_organizations",
            description=(
                "List the Supabase organizations the account belongs to. "
                "Returns slug (the organization identifier) and name."
            ),
            input_schema={},
            tags=(_PROJECTS,),
        ),
        client_op(
            "list_supabase_organization_members",
            "list_organization_members",
            description=(
                "List members of an organization: user id, name, email, role "
                "and whether MFA is enabled."
            ),
            input_schema={
                "organization_slug": _s("Organization slug.", "acme-inc", required=True),
            },
            tags=(_PROJECTS,),
        ),
        client_op(
            "get_supabase_service_config",
            "get_service_config",
            description=(
                "Read a project service's configuration. service is one of: "
                "auth (site URL, redirect URLs, providers, SMTP, signup "
                "rules), postgrest (exposed schemas, max rows), realtime, "
                "storage (file size limit, features), postgres (server "
                "settings). Secrets in the result are redacted."
            ),
            input_schema={
                "service": _s(
                    "auth | postgrest | realtime | storage | postgres.", "auth",
                    required=True,
                ),
                "project_ref": _ref(required=False),
            },
            tags=(_PROJECTS,),
        ),
        client_op(
            "update_supabase_service_config",
            "update_service_config",
            description=(
                "Change fields of a project service's configuration. Pass only "
                "the fields to change (read them first with "
                "get_supabase_service_config). Examples: auth {'site_url': "
                "'https://app.acme.com', 'disable_signup': true}; postgrest "
                "{'db_schema': 'public,api'}. Returns the updated config."
            ),
            input_schema={
                "service": _s(
                    "auth | postgrest | realtime | storage | postgres.", "auth",
                    required=True,
                ),
                "config": _obj(
                    "Fields to change, using the names from "
                    "get_supabase_service_config.",
                    {"site_url": "https://app.acme.com"},
                    required=True,
                ),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_PROJECTS,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Database — tag: supabase_database
        # ═════════════════════════════════════════════════════════════
        client_op(
            "run_supabase_sql_readonly",
            "run_sql_readonly",
            description=(
                "Run a SQL query as Supabase's read-only database role — any "
                "write fails, so this is the safe default for SELECTs, "
                "counts, joins and catalog queries. Returns the result rows "
                "as a list of objects."
            ),
            input_schema={
                "query": _s(
                    "SQL to run. Use $1, $2 placeholders with 'parameters' "
                    "for any user-supplied values.",
                    "select status, count(*) from public.orders group by 1",
                    required=True,
                ),
                "parameters": _arr("Values for $1, $2, … placeholders.", [], required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_DATABASE, _UMBRELLA),
        ),
        client_op(
            "run_supabase_sql",
            "run_sql",
            description=(
                "Run any SQL with full privileges (postgres role) on the "
                "user's own tables: INSERT/UPDATE/DELETE, grants, functions, "
                "policies. Schema changes (CREATE/ALTER/DROP/GRANT…) without "
                "$n parameters are recorded in migration history "
                "automatically. Use run_supabase_sql_readonly for reads. "
                "Never use it on "
                "storage.*, auth.* or vault.* — buckets, files, auth users "
                "and edge-function secrets have their own operations (sets "
                "supabase_storage / supabase_auth / supabase_secrets). "
                "Returns result rows."
            ),
            input_schema={
                "query": _s(
                    "SQL to run. Use $1, $2 placeholders with 'parameters'.",
                    "update public.orders set status = 'shipped' where id = $1",
                    required=True,
                ),
                "parameters": _arr("Values for $1, $2, … placeholders.", [42], required=False),
                "project_ref": _ref(required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_DATABASE, _UMBRELLA),
        ),
        client_op(
            "list_supabase_tables",
            "list_tables",
            description=(
                "List tables, views and materialized views in the given "
                "schemas with RLS status, estimated row count and comment. "
                "Call this before querying an unfamiliar database."
            ),
            input_schema={
                "schemas": _arr(
                    "Schemas to list. Default ['public'].", ["public"],
                    required=False,
                ),
                "project_ref": _ref(required=False),
            },
            tags=(_DATABASE, _UMBRELLA),
        ),
        client_op(
            "describe_supabase_table",
            "describe_table",
            description=(
                "Full definition of one table: columns (type, nullable, "
                "default), constraints (primary/foreign keys, checks), "
                "indexes, RLS status and policies, and triggers."
            ),
            input_schema={
                "table": _table(required=True),
                "schema": _schema(required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_DATABASE, _UMBRELLA),
        ),
        client_op(
            "list_supabase_extensions",
            "list_extensions",
            description=(
                "List Postgres extensions available to the project, installed "
                "ones first, with installed and default versions. Enable one "
                "with apply_supabase_migration ('create extension …')."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_DATABASE,),
        ),
        client_op(
            "generate_supabase_typescript_types",
            "generate_typescript_types",
            description=(
                "Generate TypeScript type definitions for the database schema "
                "(the same output as `supabase gen types`). Returns {types: "
                "<source text>}."
            ),
            input_schema={
                "schemas": _arr("Schemas to include. Default ['public'].", ["public"], required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_DATABASE,),
        ),
        client_op(
            "list_supabase_backups",
            "list_backups",
            description=(
                "List the project's database backups and whether point-in-time "
                "recovery is enabled. Read-only; restoring is done from the "
                "Supabase dashboard."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_DATABASE,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Migrations — tag: supabase_migrations
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_supabase_migrations",
            "list_migrations",
            description=(
                "List migrations applied to the project's database, oldest "
                "first. Returns version (timestamp string) and name."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_MIGRATIONS, _UMBRELLA),
        ),
        client_op(
            "get_supabase_migration",
            "get_migration",
            description=(
                "Get one applied migration by version: its SQL statements and "
                "stored rollback statements."
            ),
            input_schema={
                "version": _s("Migration version from list_supabase_migrations.",
                              "20250312000000", required=True),
                "project_ref": _ref(required=False),
            },
            tags=(_MIGRATIONS,),
        ),
        client_op(
            "apply_supabase_migration",
            "apply_migration",
            description=(
                "Apply a schema change (DDL) as a tracked migration — the "
                "right way to create/alter tables, add columns, indexes, RLS "
                "policies, functions or extensions. Recorded in migration "
                "history. To undo on a production project, apply another "
                "migration that reverses it; 'rollback' SQL is only used on "
                "development branches."
            ),
            input_schema={
                "query": _s(
                    "Migration SQL.",
                    "create table public.widgets (id bigint generated always "
                    "as identity primary key, name text not null);",
                    required=True,
                ),
                "name": _s("snake_case migration name.", "create_widgets_table", required=False),
                "rollback": _s(
                    "SQL that undoes this migration.",
                    "drop table if exists public.widgets;",
                    required=False,
                ),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_MIGRATIONS, _UMBRELLA),
        ),
        client_op(
            "rollback_supabase_migrations",
            "rollback_migrations",
            description=(
                "On a DEVELOPMENT BRANCH only: undo every migration with "
                "version >= from_version by running their stored rollback SQL "
                "and remove them from history. Supabase refuses this on a "
                "production project — there, apply a new migration that "
                "reverses the change. Can drop tables and data — confirm with "
                "the user first."
            ),
            input_schema={
                "from_version": _s(
                    "Oldest migration version to roll back (inclusive).",
                    "20250312000000",
                    required=True,
                ),
                "project_ref": _ref(required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_MIGRATIONS,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Rows (PostgREST, service role) — tag: supabase_rows
        # ═════════════════════════════════════════════════════════════
        client_op(
            "select_supabase_rows",
            "select_rows",
            description=(
                "Read rows from a table or view with filters, ordering and "
                "paging. Bypasses RLS (service role). Returns {rows, returned, "
                "next_offset, total?}. The schema must be exposed to the API "
                "(see get_supabase_service_config 'postgrest'); otherwise use "
                "run_supabase_sql_readonly."
            ),
            input_schema={
                "table": _table(required=True),
                "columns": _s(
                    "PostgREST select list; supports embedded relations "
                    "('id,total,customer:customers(name)'). Default '*'.",
                    "id,status,total",
                    required=False,
                ),
                "filters": _filters({"status": "eq.open"}, required=False),
                "order": _s(
                    "Ordering, e.g. 'created_at.desc' or 'name.asc,id.desc'.",
                    "created_at.desc",
                    required=False,
                ),
                "limit": _i("Max rows (default 30, capped by config max_rows).", 30, required=False),
                "offset": _i("Rows to skip; pass next_offset to page.", 0, required=False),
                "count": _b("Also return the exact total matching rows.", False, required=False),
                "schema": _schema(required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_ROWS, _UMBRELLA),
        ),
        client_op(
            "insert_supabase_rows",
            "insert_rows",
            description=(
                "Insert one row (object) or many (list of objects) into a "
                "table; set upsert=true to update rows that conflict on the "
                "primary key or on_conflict columns. Bypasses RLS. Returns "
                "the inserted rows."
            ),
            input_schema={
                "table": _table(required=True),
                "rows": _arr(
                    "Rows to insert (a single object is also accepted).",
                    [{"name": "Widget", "price": 9.5}],
                    required=True,
                ),
                "upsert": _b("Merge into existing rows on conflict.", False, required=False),
                "on_conflict": _s(
                    "Comma-separated unique columns for upsert. Default: "
                    "primary key.",
                    "",
                    required=False,
                ),
                "schema": _schema(required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_ROWS, _UMBRELLA),
        ),
        client_op(
            "update_supabase_rows",
            "update_rows",
            description=(
                "Update the rows matching filters with new column values. "
                "Filters are required (refuses to touch every row). Bypasses "
                "RLS. Returns the updated rows."
            ),
            input_schema={
                "table": _table(required=True),
                "values": _obj("Columns to set.", {"status": "shipped"}, required=True),
                "filters": _filters({"id": "eq.42"}, required=True),
                "schema": _schema(required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_ROWS, _UMBRELLA),
        ),
        client_op(
            "delete_supabase_rows",
            "delete_rows",
            description=(
                "Delete the rows matching filters. Filters are required "
                "(refuses to delete every row). Bypasses RLS. Returns the "
                "deleted rows."
            ),
            input_schema={
                "table": _table(required=True),
                "filters": _filters({"id": "eq.42"}, required=True),
                "schema": _schema(required=False),
                "project_ref": _ref(required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_ROWS, _UMBRELLA),
        ),
        client_op(
            "call_supabase_rpc",
            "call_rpc",
            description=(
                "Call a Postgres function exposed through the API "
                "(/rest/v1/rpc/<function>) with named arguments. Returns the "
                "function's result."
            ),
            input_schema={
                "function": _s("Function name.", "get_monthly_revenue", required=True),
                "args": _obj("Named arguments.", {"month": "2026-09"}, required=False),
                "schema": _schema(required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_ROWS,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Storage — tag: supabase_storage
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_supabase_buckets",
            "list_buckets",
            description=(
                "List storage buckets: id, public flag, file size limit and "
                "allowed MIME types."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_STORAGE,),
        ),
        client_op(
            "create_supabase_bucket",
            "create_bucket",
            description=(
                "Create a storage bucket. public=true makes every file "
                "readable by URL without auth. Returns the bucket name."
            ),
            input_schema={
                "name": _s("Bucket id/name (lowercase, no spaces).", "avatars", required=True),
                "public": _b("Files readable without auth.", False, required=False),
                "file_size_limit": _i("Max file size in bytes.", 5242880, required=False),
                "allowed_mime_types": _arr(
                    "Accepted MIME types; wildcards ok.", ["image/*"],
                    required=False,
                ),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_STORAGE,),
        ),
        client_op(
            "update_supabase_bucket",
            "update_bucket",
            description=(
                "Change a bucket's public flag, size limit or allowed MIME "
                "types. Unspecified settings are kept."
            ),
            input_schema={
                "name": _bucket(required=True),
                "public": _b("Files readable without auth.", False, required=False),
                "file_size_limit": _i("Max file size in bytes.", 10485760, required=False),
                "allowed_mime_types": _arr("Accepted MIME types.", ["image/*"], required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_STORAGE,),
        ),
        client_op(
            "delete_supabase_bucket",
            "delete_bucket",
            description=(
                "Delete a storage bucket. It must be empty — call "
                "empty_supabase_bucket first."
            ),
            input_schema={"name": _bucket(required=True), "project_ref": _ref(required=False)},
            destructive=True,
            parallelizable=False,
            tags=(_STORAGE,),
        ),
        client_op(
            "empty_supabase_bucket",
            "empty_bucket",
            description=(
                "Permanently delete every file in a bucket (the bucket itself "
                "stays). Irreversible — confirm with the user first."
            ),
            input_schema={"name": _bucket(required=True), "project_ref": _ref(required=False)},
            destructive=True,
            parallelizable=False,
            tags=(_STORAGE,),
        ),
        client_op(
            "list_supabase_files",
            "list_files",
            description=(
                "List files and folders in a bucket under a prefix (one level, "
                "like `ls`). Entries with is_folder=true are prefixes to list "
                "next. Returns name, size/mimetype metadata and timestamps."
            ),
            input_schema={
                "bucket": _bucket(required=True),
                "prefix": _s("Folder path to list. Default: bucket root.", "users/42", required=False),
                "search": _s("Only names containing this text.", "", required=False),
                "limit": _i("Max entries (default 100, max 1000).", 100, required=False),
                "offset": _i("Entries to skip.", 0, required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_STORAGE, _UMBRELLA),
        ),
        client_op(
            "upload_supabase_file",
            "upload_file",
            description=(
                "Upload a local file to a bucket at the given object path. "
                "Fails if the path exists unless upsert=true. Returns bucket, "
                "path, size and content type."
            ),
            input_schema={
                "bucket": _bucket(required=True),
                "path": _object_path(required=True),
                "file_path": _s(
                    "Absolute local path of the file to upload.",
                    "/home/user/workspace/profile.png",
                    required=True,
                ),
                "upsert": _b("Overwrite an existing object.", False, required=False),
                "content_type": _s("MIME type. Default: guessed from name.", "", required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_STORAGE, _UMBRELLA),
        ),
        client_op(
            "download_supabase_file",
            "download_file",
            description=(
                "Download a file from a bucket to a local path. Returns "
                "saved_to, size and content type."
            ),
            input_schema={
                "bucket": _bucket(required=True),
                "path": _object_path(required=True),
                "save_to": _s(
                    "Absolute local path to write.",
                    "/home/user/workspace/profile.png",
                    required=True,
                ),
                "project_ref": _ref(required=False),
            },
            tags=(_STORAGE, _UMBRELLA),
        ),
        client_op(
            "delete_supabase_files",
            "delete_files",
            description=(
                "Delete one or more files from a bucket by object path. "
                "Returns the deleted objects."
            ),
            input_schema={
                "bucket": _bucket(required=True),
                "paths": _arr("Object paths to delete.", ["users/42/old.png"], required=True),
                "project_ref": _ref(required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_STORAGE, _UMBRELLA),
        ),
        client_op(
            "move_supabase_file",
            "move_file",
            description=(
                "Move or rename a file within a bucket, or to another bucket "
                "with to_bucket."
            ),
            input_schema={
                "bucket": _bucket(required=True),
                "from_path": _object_path(required=True),
                "to_path": _s("New object path.", "users/42/avatar.png", required=True),
                "to_bucket": _s("Destination bucket if different.", "", required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_STORAGE,),
        ),
        client_op(
            "copy_supabase_file",
            "copy_file",
            description=(
                "Copy a file to a new path in the same bucket, or to another "
                "bucket with to_bucket."
            ),
            input_schema={
                "bucket": _bucket(required=True),
                "from_path": _object_path(required=True),
                "to_path": _s("Destination object path.", "backups/profile.png", required=True),
                "to_bucket": _s("Destination bucket if different.", "", required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_STORAGE,),
        ),
        client_op(
            "create_supabase_signed_url",
            "create_signed_url",
            description=(
                "Create a time-limited download URL for a file in a private "
                "bucket, shareable with anyone. Returns signed_url and also the "
                "permanent public URL form (works only for public buckets)."
            ),
            input_schema={
                "bucket": _bucket(required=True),
                "path": _object_path(required=True),
                "expires_in": _i("Validity in seconds (default 3600).", 3600, required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_STORAGE,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Auth users — tag: supabase_auth
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_supabase_users",
            "list_users",
            description=(
                "List the project's end users (Supabase Auth): id (UUID), "
                "email, phone, providers, created/last-sign-in times, "
                "metadata. Paged; returns next_page when more exist."
            ),
            input_schema={
                "page": _i("Page number, from 1.", 1, required=False),
                "per_page": _i("Users per page (default 50, max 1000).", 50, required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_AUTH, _UMBRELLA),
        ),
        client_op(
            "get_supabase_user",
            "get_user",
            description="Get one auth user by UUID, including identities and metadata.",
            input_schema={
                "user_id": _s("User UUID.", "7f3c2a10-1b2c-4d5e-8f90-a1b2c3d4e5f6", required=True),
                "project_ref": _ref(required=False),
            },
            tags=(_AUTH,),
        ),
        client_op(
            "create_supabase_user",
            "create_user",
            description=(
                "Create an auth user directly (no email sent). Set "
                "email_confirm=true to skip email verification. Returns the "
                "new user."
            ),
            input_schema={
                "email": _s("Email address.", "jane@example.com", required=False),
                "phone": _s("Phone in E.164.", "", required=False),
                "password": _s("Initial password.", "", required=False),
                "email_confirm": _b("Mark the email as confirmed.", True, required=False),
                "phone_confirm": _b("Mark the phone as confirmed.", False, required=False),
                "user_metadata": _obj("Profile data the user can edit.",
                                      {"full_name": "Jane Doe"}, required=False),
                "app_metadata": _obj("Server-controlled data (roles, plan).",
                                     {"role": "admin"}, required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_AUTH,),
        ),
        client_op(
            "update_supabase_user",
            "update_user",
            description=(
                "Update an auth user by UUID: email, phone, password, "
                "confirmation flags, metadata, or ban_duration ('24h', "
                "'876000h' to ban, 'none' to unban). Returns the user."
            ),
            input_schema={
                "user_id": _s("User UUID.", "7f3c2a10-1b2c-4d5e-8f90-a1b2c3d4e5f6", required=True),
                "email": _s("New email.", "", required=False),
                "phone": _s("New phone.", "", required=False),
                "password": _s("New password.", "", required=False),
                "email_confirm": _b("Mark the email as confirmed.", True, required=False),
                "phone_confirm": _b("Mark the phone as confirmed.", False, required=False),
                "user_metadata": _obj("Replaces user_metadata.", {}, required=False),
                "app_metadata": _obj("Replaces app_metadata.", {}, required=False),
                "ban_duration": _s("Ban length, or 'none' to lift a ban.", "", required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_AUTH,),
        ),
        client_op(
            "delete_supabase_user",
            "delete_user",
            description=(
                "Delete an auth user by UUID. soft_delete=true keeps the row "
                "(anonymised) so foreign keys don't break."
            ),
            input_schema={
                "user_id": _s("User UUID.", "7f3c2a10-1b2c-4d5e-8f90-a1b2c3d4e5f6", required=True),
                "soft_delete": _b("Soft delete instead of hard delete.", False, required=False),
                "project_ref": _ref(required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_AUTH,),
        ),
        client_op(
            "invite_supabase_user",
            "invite_user",
            description=(
                "Send an invitation email (via the project's auth email "
                "settings) so a new user can set a password. Returns the "
                "invited user."
            ),
            input_schema={
                "email": _s("Email to invite.", "jane@example.com", required=True),
                "redirect_to": _s(
                    "URL to land on after accepting; must be in the auth "
                    "redirect allow-list.",
                    "https://app.acme.com/welcome",
                    required=False,
                ),
                "data": _obj("Initial user_metadata.", {}, required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_AUTH,),
        ),
        client_op(
            "generate_supabase_auth_link",
            "generate_auth_link",
            description=(
                "Generate an auth action link WITHOUT sending email — for "
                "magic links, password recovery, signup confirmation, invite "
                "or email change. Returns action_link and the user. Treat the "
                "link as a credential."
            ),
            input_schema={
                "link_type": _s(
                    "signup | magiclink | recovery | invite | "
                    "email_change_current | email_change_new.",
                    "magiclink",
                    required=True,
                ),
                "email": _s("User email.", "jane@example.com", required=True),
                "password": _s("Required for type 'signup'.", "", required=False),
                "new_email": _s("Required for email_change types.", "", required=False),
                "redirect_to": _s("Post-action redirect URL.", "", required=False),
                "data": _obj("user_metadata for signup/invite.", {}, required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_AUTH,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Edge functions — tag: supabase_functions
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_supabase_functions",
            "list_functions",
            description=(
                "List the project's edge functions: slug (the identifier), "
                "name, status, version, verify_jwt and timestamps."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_FUNCTIONS, _UMBRELLA),
        ),
        client_op(
            "get_supabase_function",
            "get_function",
            description=(
                "Get one edge function's metadata by slug (status, version, "
                "entrypoint, verify_jwt). Source code is not retrievable "
                "through the API."
            ),
            input_schema={
                "slug": _s("Function slug.", "hello-world", required=True),
                "project_ref": _ref(required=False),
            },
            tags=(_FUNCTIONS,),
        ),
        client_op(
            "deploy_supabase_function",
            "deploy_function",
            description=(
                "Create or redeploy an edge function (Deno/TypeScript) from "
                "source. Pass 'files' as {relative_path: source} or a local "
                "'source_dir'. Redeploying an existing slug replaces its code. "
                "Returns the function with its new version."
            ),
            input_schema={
                "slug": _s("Function slug (letters, digits, - and _).", "hello-world", required=True),
                "files": _obj(
                    "Source files keyed by path relative to the function root.",
                    {
                        "index.ts": "Deno.serve(async (req) => new Response("
                        "JSON.stringify({ ok: true }), { headers: { "
                        "'Content-Type': 'application/json' } }))"
                    },
                    required=False,
                ),
                "source_dir": _s(
                    "Alternative to 'files': local folder holding the function.",
                    "",
                    required=False,
                ),
                "entrypoint": _s("Entrypoint file. Default 'index.ts'.", "index.ts", required=False),
                "name": _s("Display name. Default: the slug.", "", required=False),
                "verify_jwt": _b(
                    "Require a valid JWT in Authorization. Set false for "
                    "public webhooks.",
                    True,
                    required=False,
                ),
                "import_map_path": _s("Import map / deno.json path, if any.", "", required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_FUNCTIONS, _UMBRELLA),
        ),
        client_op(
            "update_supabase_function",
            "update_function",
            description=(
                "Change an edge function's display name or verify_jwt setting "
                "without redeploying code."
            ),
            input_schema={
                "slug": _s("Function slug.", "hello-world", required=True),
                "name": _s("New display name.", "", required=False),
                "verify_jwt": _b("Require a valid JWT.", True, required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_FUNCTIONS,),
        ),
        client_op(
            "delete_supabase_function",
            "delete_function",
            description="Delete an edge function by slug. Its URL stops working immediately.",
            input_schema={
                "slug": _s("Function slug.", "hello-world", required=True),
                "project_ref": _ref(required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_FUNCTIONS, _UMBRELLA),
        ),
        client_op(
            "invoke_supabase_function",
            "invoke_function",
            description=(
                "Call a deployed edge function over HTTP with a JSON body. "
                "Returns status_code, content_type and the parsed response "
                "body. Runs with service-role credentials."
            ),
            input_schema={
                "slug": _s("Function slug.", "hello-world", required=True),
                "body": _obj("JSON request body.", {"name": "Jane"}, required=False),
                "method": _s("HTTP method. Default POST.", "POST", required=False),
                "headers": _obj("Extra request headers.", {}, required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_FUNCTIONS, _UMBRELLA),
        ),
        # ═════════════════════════════════════════════════════════════
        # Secrets — tag: supabase_secrets
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_supabase_secrets",
            "list_secrets",
            description=(
                "List the names of the project's edge-function secrets "
                "(environment variables). Values are never returned."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_SECRETS,),
        ),
        client_op(
            "set_supabase_secrets",
            "set_secrets",
            description=(
                "Create or overwrite edge-function secrets, readable in "
                "functions via Deno.env.get(NAME). Names may not start with "
                "SUPABASE_. Returns the names set."
            ),
            input_schema={
                "secrets": _obj(
                    "NAME → value.", {"STRIPE_WEBHOOK_SECRET": "whsec_..."},
                    required=True,
                ),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_SECRETS,),
        ),
        client_op(
            "delete_supabase_secrets",
            "delete_secrets",
            description="Delete edge-function secrets by name.",
            input_schema={
                "names": _arr("Secret names to delete.", ["OLD_API_KEY"], required=True),
                "project_ref": _ref(required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_SECRETS,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Branches — tag: supabase_branches
        # ═════════════════════════════════════════════════════════════
        client_op(
            "list_supabase_branches",
            "list_branches",
            description=(
                "List a project's preview/persistent branches: id, name, its "
                "own project_ref, git branch, status. Requires branching "
                "enabled on a paid plan."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_BRANCHES,),
        ),
        client_op(
            "get_supabase_branch",
            "get_branch",
            description=(
                "Get a branch's database details (host, port, Postgres "
                "version, status) by branch id or branch ref."
            ),
            input_schema={"branch_id": _branch_id(required=True)},
            tags=(_BRANCHES,),
        ),
        client_op(
            "create_supabase_branch",
            "create_branch",
            description=(
                "Create a development branch — a separate copy of the project "
                "with the same migrations. Billed per hour; confirm with the "
                "user. Work on it with its own project_ref."
            ),
            input_schema={
                "branch_name": _s("Branch name.", "feature-login", required=True),
                "git_branch": _s("Linked git branch, if any.", "", required=False),
                "persistent": _b("Keep it instead of auto-pausing.", False, required=False),
                "with_data": _b("Copy production data into the branch.", False, required=False),
                "region": _s("Region code. Default: parent's region.", "", required=False),
                "project_ref": _ref(required=False),
            },
            parallelizable=False,
            tags=(_BRANCHES,),
        ),
        client_op(
            "update_supabase_branch",
            "update_branch",
            description="Rename a branch, change its git branch, or toggle persistence.",
            input_schema={
                "branch_id": _branch_id(required=True),
                "branch_name": _s("New name.", "", required=False),
                "git_branch": _s("Linked git branch.", "", required=False),
                "persistent": _b("Keep it running.", True, required=False),
            },
            parallelizable=False,
            tags=(_BRANCHES,),
        ),
        client_op(
            "delete_supabase_branch",
            "delete_branch",
            description="Delete a branch and its database.",
            input_schema={"branch_id": _branch_id(required=True)},
            destructive=True,
            parallelizable=False,
            tags=(_BRANCHES,),
        ),
        client_op(
            "merge_supabase_branch",
            "merge_branch",
            description=(
                "Merge a branch's migrations (and edge functions) into the "
                "parent project. Check diff_supabase_branch first. Returns a "
                "workflow_run_id."
            ),
            input_schema={
                "branch_id": _branch_id(required=True),
                "migration_version": _s("Merge only up to this version.", "", required=False),
            },
            parallelizable=False,
            tags=(_BRANCHES,),
        ),
        client_op(
            "reset_supabase_branch",
            "reset_branch",
            description=(
                "Reset a branch's database to its migrations, discarding all "
                "data and untracked changes on the branch."
            ),
            input_schema={
                "branch_id": _branch_id(required=True),
                "migration_version": _s("Reset to this version.", "", required=False),
            },
            destructive=True,
            parallelizable=False,
            tags=(_BRANCHES,),
        ),
        client_op(
            "diff_supabase_branch",
            "diff_branch",
            description=(
                "Show the schema SQL diff between a branch and its parent — "
                "what merge_supabase_branch would apply."
            ),
            input_schema={
                "branch_id": _branch_id(required=True),
                "schemas": _arr("Schemas to diff. Default: all.", ["public"], required=False),
            },
            tags=(_BRANCHES,),
        ),
        # ═════════════════════════════════════════════════════════════
        # Monitoring — tag: supabase_monitoring
        # ═════════════════════════════════════════════════════════════
        client_op(
            "get_supabase_logs",
            "get_logs",
            description=(
                "Recent logs for one project service, newest first. source: "
                "api, postgres, auth, storage, realtime, edge_function "
                "(invocations), edge_function_runtime (console output), "
                "postgrest, pooler. Window up to 24h. Pass 'sql' for a custom "
                "Logflare query instead."
            ),
            input_schema={
                "source": _s("Log source.", "postgres", required=False),
                "minutes": _i("Look-back window in minutes (max 1440).", 60, required=False),
                "limit": _i("Max log lines (default 100).", 100, required=False),
                "search": _s("Case-insensitive regex on the message.", "error", required=False),
                "sql": _s("Custom log query; overrides source/search/limit.", "", required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_MONITORING, _UMBRELLA),
        ),
        client_op(
            "get_supabase_security_advisors",
            "get_security_advisors",
            description=(
                "Security lint for the project: tables without RLS, policies "
                "that leak data, exposed auth.users, mutable search paths. "
                "Each finding has a level, description and remediation link."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_MONITORING, _UMBRELLA),
        ),
        client_op(
            "get_supabase_performance_advisors",
            "get_performance_advisors",
            description=(
                "Performance lint for the project: unindexed foreign keys, "
                "unused or duplicate indexes, slow RLS patterns."
            ),
            input_schema={"project_ref": _ref(required=False)},
            tags=(_MONITORING,),
        ),
        client_op(
            "get_supabase_api_usage",
            "get_api_usage",
            description=(
                "API request counts over time (REST, auth, storage, realtime) "
                "for an interval: 15min, 30min, 1hr, 3hr, 1day, 3day, 7day."
            ),
            input_schema={
                "interval": _s("Time window.", "1day", required=False),
                "project_ref": _ref(required=False),
            },
            tags=(_MONITORING,),
        ),
    ]


# ────────────────────────────────────────────────────────────────────────
# Intentionally excluded (Management API v1, 169 endpoints) — one line per
# group, so the next session doesn't re-litigate it.
#
# Billing / add-ons (billing/addons)          — money; dashboard only.
# Organization create + project-claim tokens  — account administration.
# Project API-key management (api-keys CRUD,
#   legacy-key toggle, JWT signing keys)       — credential admin; the client
#                                                reads keys internally only.
# SSO providers, third-party auth             — org identity admin.
# Network bans / restrictions, SSL enforcement — perimeter security; a
#                                                wrong call locks the user out.
# JIT database access, CLI login role         — privilege grants.
# pgsodium root key                           — rotating it makes encrypted
#                                                data unreadable.
# Backup restore / PITR / restore points /
#   undo                                       — overwrites the live database;
#                                                listing backups is kept.
# Postgres version upgrade, disk config /
#   autoscale, read replicas, pooler config   — infra changes with cost and
#                                                downtime.
# Custom hostname, vanity subdomain           — DNS-coupled, multi-step.
# Readonly-mode override, database webhooks
#   enable, realtime shutdown                  — operational escape hatches.
# Branch push / restore, disable branching,
#   action runs                                — CI plumbing, covered by
#                                                merge/reset/diff.
# Function bulk update, function body          — bulk update is CI plumbing;
#                                                body is an eszip bundle, not
#                                                readable source.
# Analytics: metrics scrape, function stats,
#   requests-count                             — overlaps get_supabase_logs /
#                                                get_supabase_api_usage.
# SQL snippets, entitlements, database
#   context, PostgREST OpenAPI                 — dashboard conveniences;
#                                                list_supabase_tables covers it.
# OAuth endpoints                              — used by the provider, not
#                                                the agent.
# ────────────────────────────────────────────────────────────────────────
