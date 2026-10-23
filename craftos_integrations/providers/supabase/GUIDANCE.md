# Using Supabase

## Load the set that owns the job

The `supabase` action set is a shortlist — it does NOT contain bucket
management, secrets, user create/update/delete, branches or project
settings. Before doing any of those, load the set that has them:

| Job | Load |
|---|---|
| Buckets (create / update / empty / delete), move / copy files, signed URLs | `supabase_storage` |
| Edge-function secrets (list / set / delete) | `supabase_secrets` |
| Auth users (create / update / ban / delete / invite / magic links) | `supabase_auth` |
| Functions beyond deploy / invoke / delete (metadata, verify_jwt) | `supabase_functions` |
| Migrations history, rollback on branches | `supabase_migrations` |
| Projects: create / rename / pause / restore / settings, organizations | `supabase_projects` |
| Branches | `supabase_branches` |
| Logs beyond the default, performance advisors, API usage | `supabase_monitoring` |

**Never work around a missing operation with SQL** on Supabase's own schemas:
`storage.*` (Supabase blocks deleting buckets/objects there — it fails), `auth.*`
(skips Auth's own cleanup), or `vault.*`. Edge-function secrets are **not** in
Vault — they're only reachable through `supabase_secrets`. If an operation
seems missing, the answer is to load its set, not to tell the user to use the
dashboard.

## Find the project first

Almost every operation takes a `project_ref` — the 20-letter id of a Supabase
project. If the user hasn't named one and no default is configured, call
`list_supabase_projects` and match their words against project names. If
several fit, ask. Projects with status `INACTIVE` are paused: their data APIs
are offline until `restore_supabase_project`.

## Look before you query

Before reading or writing data in an unfamiliar project, call
`list_supabase_tables`, then `describe_supabase_table` on the tables you need.
Guessing column names produces errors and, worse, wrong filters.

## Reading data

- Questions ("how many orders last week", "top customers"): write SQL and
  run it with **`run_supabase_sql_readonly`**. It cannot change anything, so
  use it freely. Pass user-supplied values through `parameters` ($1, $2) —
  never paste them into the SQL string.
- Fetching specific rows to show or edit: `select_supabase_rows` with
  PostgREST filters (`{"status": "eq.open"}`), `order`, `limit`. Follow
  `next_offset` to page.
- `select_supabase_rows` only reaches schemas exposed to the API (usually
  `public`). For `auth`, `storage` or private schemas use SQL.

## Changing data

All row, storage and user operations run with the project's service role:
**Row Level Security does not protect anything here.** So:

- `update_supabase_rows` / `delete_supabase_rows` need `filters`. Run the same
  filters through `select_supabase_rows` (with `count: true`) first and tell
  the user how many rows will change before changing more than a handful.
- `insert_supabase_rows` returns the inserted rows — report the new ids.
- Use `run_supabase_sql` only for changes the row operations can't express.

## Changing the schema

Use **`apply_supabase_migration`** for any DDL — create/alter table, indexes,
RLS policies, functions, extensions — with a snake_case `name`. To undo a
change on a production project, apply a new migration that reverses it
(`rollback_supabase_migrations` only works on development branches). It is recorded in migration history, which keeps the
project in sync with the user's local `supabase/migrations`. Don't use
`run_supabase_sql` for DDL unless the user asks for an untracked change.

After creating a table, enable RLS and add policies in the same migration
unless the user says otherwise, then run `get_supabase_security_advisors` —
it flags tables left open.

## Building an app on Supabase

`get_supabase_project_keys` returns the project URL and the publishable key —
the two values a frontend needs. The secret key is never available to you and
must never be put in client code. `generate_supabase_typescript_types` gives
typed table definitions for a TypeScript app.

A brand-new table may take a couple of seconds to become visible to the row
operations — they retry automatically, so just call them.

## Storage

Files live in buckets. `list_supabase_files` lists one folder level; entries
with `is_folder: true` are prefixes to list next. Upload from and download to
absolute local paths. To share a private file, `create_supabase_signed_url`.
`delete_supabase_bucket` only works on an empty bucket — `empty_supabase_bucket`
first, after confirming with the user.

## Users

`list_supabase_users` / `get_supabase_user` are the project's end users, not
Supabase dashboard members (those are `list_supabase_organization_members`).
`invite_supabase_user` sends an email; `create_supabase_user` doesn't. To ban,
`update_supabase_user` with `ban_duration` (`"none"` lifts it). Magic or
recovery links from `generate_supabase_auth_link` are credentials — hand them
only to the user who asked.

## Edge functions

Deploy with `deploy_supabase_function` and `files: {"index.ts": "..."}`;
redeploying the same slug replaces the code. Existing source can't be read
back — if the user wants an edit, ask for the source or find it in their
workspace. Function config goes in secrets (`set_supabase_secrets`, read in
code with `Deno.env.get`). Test with `invoke_supabase_function`, and when it
fails, `get_supabase_logs` with `source: "edge_function_runtime"`.

## Debugging a project

1. `get_supabase_project_health` — is a service down?
2. `get_supabase_logs` — `postgres` for database errors, `api` for HTTP
   errors, `auth` for login problems; narrow with `search`.
3. `get_supabase_security_advisors` / `get_supabase_performance_advisors`.

## Things that need a yes from the user first

Deleting or pausing a project, `rollback_supabase_migrations`,
`empty_supabase_bucket`, deleting users, `create_supabase_project` and
`create_supabase_branch` (both can cost money), and any bulk row change.

## Read-only mode

If an operation fails with "read-only mode", the user has switched the
integration to read-only in Settings. Tell them; don't look for a workaround.

## Multiple accounts

A personal-access-token account sees every organization its user belongs to.
An OAuth account sees only the organization chosen when it was connected —
to add a different organization, connect again and pick that organization on
Supabase's consent screen.
