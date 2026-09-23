# PostHog — integration notes

Gotchas that are not obvious from the PostHog docs, and the reasons behind
the choices in `client.py`.

## Auth

- **Key prefixes matter.** Only `phx_` (personal API key) authenticates the
  management API. `phc_` is a project API key for client-side event capture;
  `phs_` is a project secret key for server-side ingestion. `verify_token`
  rejects both by prefix before spending a request, because the 401 PostHog
  returns otherwise gives the user nothing to act on.
- **Keys are scoped.** A personal API key carries a scope list chosen when it
  was minted. A key that reads `/api/users/@me/` may still 403 on
  `/feature_flags/`. **A 403 means the key lacks that scope — retrying will
  not help.** The user must mint a new key with the missing scope; scopes
  cannot be added to an existing key.
- **Connect-time verification is shallow by design.** `verify_token` only
  calls `/api/users/@me/`, which every key can reach. It deliberately does not
  probe each resource — that would be a dozen requests against the user's rate
  limit at connect time. The trade-off is that a too-narrow key connects
  successfully and fails later, at the first scoped call.
- **OAuth exists but is not wired up.** PostHog supports OAuth 2.0 with PKCE
  (S256), and `provider.oauth_spec()` returns its real endpoints and our scope
  set. It is gated on infrastructure, not code: PostHog uses Client ID Metadata
  Documents, so `client_id` must be a URL on a domain we control serving a JSON
  metadata file listing our redirect URIs. Host that document, set
  `POSTHOG_CLIENT_ID` to its URL, flip `auth_type` to `"both"`. The token
  endpoint accepts `none` client authentication — there is no client secret,
  and none should ever be embedded.

## Host is per-credential, never a constant

PostHog runs US Cloud (`https://us.posthog.com`), EU Cloud
(`https://eu.posthog.com`) and self-hosted installs on arbitrary domains. The
host lives on the credential and every request builds its URL from it. Do not
introduce a module-level base-URL constant — it would break every EU and
self-hosted user, and the failure looks like an auth error rather than a
routing one.

`normalize_host` in `provider.py` accepts `us` / `eu` shorthands, a bare
domain, or a full URL, and strips a trailing `/api` that users often paste.

## Identifier shapes

Getting these wrong is the most common source of 404s.

| Resource | Identifier |
|---|---|
| Project (team) | integer, e.g. `136209` |
| Insight | integer `id`; also has a `short_id` string used in URLs — **they are not interchangeable**, the API takes the integer |
| Dashboard, cohort, annotation, action | integer |
| Feature flag | integer `id` — **not** the `key` string. Resolve a key with `list_posthog_feature_flags` first |
| Person | uuid; persons *also* carry `distinct_id` strings from the SDK. `get_posthog_person` takes the uuid; look up by distinct id with `list_posthog_persons` |
| Event definition, property definition | uuid |
| Organization | uuid, or the literal `@current` |

`@current` works server-side for projects and organizations, and the client
falls back to it when no project is known. Identity capture still resolves a
concrete numeric project id at connect time, because `@current` is not stable
across accounts.

## Deletion is a soft delete

PostHog does not really remove rows. `delete_*` on insights, dashboards,
feature flags, cohorts and annotations is implemented as
`PATCH {"deleted": true}`, which is what the UI does and what the in-repo
`skills/api-gateway/references/posthog.md` documents as working. HTTP `DELETE`
also exists on most of these routes, but it returns 204 with no body and
PostHog soft-deletes behind it anyway — the PATCH form is uniform and
recoverable (`PATCH {"deleted": false}` restores).

Two exceptions:

- **Persons** have no per-person DELETE. Erasure goes through
  `POST /persons/bulk_delete/` keyed by uuid or distinct id, optionally taking
  the person's events with it. This one **is** permanent — it is the GDPR path.
- **Dashboard tiles** are removed with `POST /dashboards/{id}/delete_tile/`.

Because "delete" is usually reversible here, `disable_posthog_feature_flag` is
the right way to turn a flag off, not `delete_posthog_feature_flag`.

## Queries

- The legacy `/api/projects/:id/events/` endpoint is deprecated. Everything
  goes through `POST /query/` with HogQL. `list_posthog_events` composes the
  HogQL for the common case so the agent gets one stable shape.
- **Wide scans must be async.** `run_posthog_query` is synchronous and bounded
  by `query_timeout_seconds` (default 60). Anything covering more than a few
  weeks should use `run_posthog_query_async`, then poll
  `get_posthog_query_status` until `complete` is true.
- `list_posthog_events` composes HogQL from agent-supplied values. String
  literals go through `_sql_literal`, which escapes quotes and backslashes —
  do not build HogQL by f-string anywhere else in this client.

## Rate limits

PostHog limits per team (project), not per calling app. Documented ceilings:

| Endpoint group | Limit |
|---|---|
| Analytics endpoints | 240/min, 1200/hour |
| `query` | 2400/hour |
| `events/values` | 60/min, 300/hour |
| Create/read/update/delete | 480/min, 4800/hour |
| Feature flag local evaluation | 600/min |

The query budget is the tightest thing an agent will touch, which is the other
reason there is no polling listener: a poll loop would consume the same budget
the user's analytics questions need.

## No listener

PostHog's inbound story is webhooks and subscriptions, which need a public
callback URL. `make_listener` returns `None` unless the client ever reports
`supports_listening`, so a future webhook path bridges automatically without
touching the provider.

## Pagination

`limit` (1–100, clamped client-side; default 30) and `offset`. List responses
carry `next` / `previous` URLs — surfaced in the result so the agent can chain
pages.
