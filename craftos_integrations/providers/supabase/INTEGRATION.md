# Supabase — integration notes

For whoever debugs this at 2am. Agent-facing advice lives in `GUIDANCE.md`.

## Two planes, one credential

| Plane | Base URL | Auth | Used for |
|---|---|---|---|
| Management API | `https://api.supabase.com/v1` | `Authorization: Bearer <PAT or OAuth token>` | projects, orgs, SQL, migrations, functions (manage), branches, secrets, logs, advisors, service config |
| Project APIs | `https://<ref>.supabase.co` | the project's **secret** key | PostgREST rows (`/rest/v1`), Storage (`/storage/v1`), Auth admin (`/auth/v1`), function invoke (`/functions/v1`) |

The user never pastes a project key. `SupabaseClient._keys_for(ref)` calls
`GET /v1/projects/{ref}/api-keys?reveal=true` once per project per client
instance and keeps the result **in memory only** — never persisted, never
returned to the agent (`get_supabase_project_keys` returns only the URL and
the publishable key). A 401 from a project API invalidates the cache and
retries once, which is what a rotated key looks like.

Needs the `secrets:read` permission (OAuth) — without it every data-plane
operation fails with "Could not read API keys for project …".

### Key formats on the data plane

- **New keys** — `sb_secret_…` / `sb_publishable_…`. Not JWTs. Sent in the
  `apikey` header only; putting one in `Authorization: Bearer` is rejected
  by the gateway.
- **Legacy keys** — `anon` / `service_role`, both JWTs (`eyJ…`). Sent in
  both `apikey` and `Authorization`.

The client prefers a `secret` key, falls back to legacy `service_role`.

**Edge-function invocation** with `verify_jwt=true` needs a JWT in
`Authorization`. Only legacy keys are JWTs, so `invoke_function` prefers the
legacy service_role key when the project still has legacy keys enabled. A
project that has *disabled* legacy keys and has a verify_jwt function will
answer 401 to `invoke_supabase_function` — redeploy it with
`verify_jwt=false` and check auth inside the function, or invoke it with a
user JWT in `headers`. **Unverified live** — confirm in the smoke test.

### Service role bypasses RLS

Every data-plane operation acts as the service role: Row Level Security does
not apply. That matches the dashboard table editor and is what "manage my
Supabase" means, but it is why `update_supabase_rows` / `delete_supabase_rows`
refuse empty `filters`, and why `GUIDANCE.md` tells the agent to confirm bulk
changes.

## Identifiers

| Resource | Shape | Example |
|---|---|---|
| Project | ref, 20 lowercase letters | `abcdefghijklmnopqrst` |
| Organization | slug | `acme-inc` (older orgs: 20-letter ref-like string) |
| Branch | UUID, or the branch's own project ref | both accepted by `/v1/branches/{id_or_ref}` |
| Edge function | slug `^[A-Za-z][A-Za-z0-9_-]*$` | `hello-world` |
| Migration | version, timestamp digits | `20250312000000` |
| Auth user | UUID | `7f3c2a10-…` |
| Storage object | `<bucket>` + `/`-separated path, no leading slash | `avatars` + `users/42/a.png` |

`project_ref` falls back to the `default_project_ref` config knob. **Except**
`delete_supabase_project`, which requires it explicitly.

## Auth

### Personal access token (always available)

`sbp_…`, from supabase.com/dashboard/account/tokens. Never expires unless
revoked; `refresh()` returns None. Spans every organization the user is in.

**`/v1/profile` answers 403 to personal access tokens** (seen live
2026-10-05; the schema gives it no permission scope, unlike every endpoint a
PAT can call). So validity is checked with `GET /v1/organizations`, profile is
best-effort, and identity is `token:<sha256(token)[:16]>` unless the profile
happened to be readable (`user:<gotrue_id>`). Same token reconnected → same
account; a new token → a new account (remove the old one).

`verify_token` distinguishes 401 (invalid / revoked) from 403 (token valid,
access refused).

`verify_token` rejects `sb_secret_`, `sb_publishable_` and `eyJ…` (anon /
service_role JWT) by prefix — the three things people paste by mistake.
Other unknown prefixes are still tried, deliberately.

### OAuth (one-click, once our app is registered)

- Endpoints confirmed via `https://api.supabase.com/.well-known/oauth-authorization-server`:
  authorize `/v1/oauth/authorize`, token `/v1/oauth/token`, PKCE S256,
  `client_secret_basic`. Refresh tokens issued.
- **Infra to do:** register a Supabase OAuth app (Organization settings →
  OAuth Apps), redirect URI `http://localhost:8765`, tick the permissions in
  `SUPABASE_SCOPES` (client.py). Put the id/secret in
  `SUPABASE_SHARED_CLIENT_ID` / `SUPABASE_SHARED_CLIENT_SECRET` (env, or the
  embedded credential registry under service `supabase`).
- `auth_type` is a property: `"token"` until both keys are configured,
  `"both"` after. Nothing else changes.
- Permissions are fixed on the app registration; the authorize URL carries
  no `scope`.
- An OAuth grant is scoped to the organization the user picks on the consent
  screen → identity `org:<slug>`.
- Access tokens expire; the client refreshes inline (`_ensure_token`,
  2-minute margin, serialized by a lock) and persists through the core.

### Failure modes

| Symptom | Meaning |
|---|---|
| 401 on Management API | token revoked / expired OAuth token that failed to refresh. Reconnect. |
| 403 on Management API | OAuth app lacks the permission for that endpoint, or the user's org role is read-only. Retrying won't help. |
| "Could not read API keys for project …" | no `secrets:read`, or the project is paused (`INACTIVE`). |
| 404 on `/rest/v1/<table>` | table not in an exposed schema (PostgREST `db_schema`), or doesn't exist. Use SQL. |
| 400 `PGRST…` codes | PostgREST query error — bad filter syntax or column name. Body says which. |
| 540 / connection error on data plane | project paused. `restore_supabase_project`. |

## Rate limits

- Management API: documented at roughly **120 requests / minute per user**
  (per token), across all projects — re-check the current number in
  Supabase's docs if 429s show up. Bursty agents on large accounts can hit it — `list_supabase_*`
  then fan-out is the usual cause. 429 = wait a minute.
- Project APIs are not rate-limited by the gateway beyond the plan's compute;
  heavy `select_supabase_rows` paging is bounded by `max_rows` config
  (default 500 per call).
- Logs API: window ≤ 24h per query (`get_logs` clamps `minutes` to 1440).

## Read-only mode

Config `read_only = true` makes every mutating client method raise before
any request (`_guard_write`). The SQL read path uses Supabase's dedicated
`/database/query/read-only` endpoint, which runs as `supabase_read_only_user`
— a database-enforced guarantee, not a regex on the SQL.

## Live findings (2026-10-05, scratch project)

- **PostgREST schema cache.** Right after DDL the row API answers 404
  `PGRST205` for a few seconds. `SupabaseClient._rest` sends
  `notify pgrst, 'reload schema'` and retries (1s, 2.5s).
- **Migration rollback is branch-only.** `DELETE /database/migrations` on a
  production project → 400 "You cannot rollback a production branch". Undo on
  production = a new reversing migration.
- **Logs API moved.** `logs.all` → 410 Gone. `logs` takes ClickHouse SQL over
  one `logs` table filtered by `source_name`; nested fields in
  `log_attributes[...]`. Failed queries come back as HTTP 200 with
  `{"error": ...}` in the body — `_analytics_result` turns that into an error.
  On the test project every query (even `SELECT 1`) returned "Backend error!"
  — a Supabase-side outage for that project, not a query problem. The logs
  endpoint has its own, tighter throttle (429 after ~10 quick calls).
- **Organizations can be invisible.** A valid token listed zero
  organizations (and 403 on members) while reaching a project in one —
  connect messages describe reach by projects.
- **`/v1/profile` is 403 for PATs** — see Auth above.

## What isn't here and why

See the exclusion block at the bottom of `operations.py`. Notably: billing,
API-key and signing-key admin, SSO, network restrictions, backup restore /
PITR, Postgres upgrades, custom domains.

Function **source** can't be read back: `GET /functions/{slug}/body` returns
the compiled eszip bundle, not the files. Keep source in the workspace.

## No listener

Supabase's push channels are database webhooks (need a public URL) and
Realtime (a websocket per project, per table). Neither fits the per-account
listener model without the user choosing what to watch — a v2 candidate:
poll a user-chosen table via `select_supabase_rows` with an `updated_at`
cursor.
