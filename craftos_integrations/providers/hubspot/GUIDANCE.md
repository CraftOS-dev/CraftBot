# HubSpot

Per-portal CRM — contacts/companies/deals/tickets, engagements
(tasks/notes/calls/emails/meetings), lists, pipelines, properties, owners,
associations, forms, marketing email, files, conversations, webhooks.
Talks to `api.hubapi.com`.

## Multi-account
- One connected account = one HubSpot **hub** (portal). Every HubSpot
  action accepts an optional `account` (hub id, nickname, or a unique
  fragment like "acme"). Omit it to use the primary hub.
- When the user names a portal in any form ("the client's HubSpot",
  "our sandbox portal"), pass it as `account` — never silently default
  to primary.
- Object IDs (contacts, companies, deals, tickets, engagement IDs, list
  IDs, pipeline/stage IDs, owner IDs, form GUIDs, file IDs, thread IDs)
  are **hub-scoped**: an id returned by `list_hubspot_contacts` with
  `account="acme"` must be used with `account="acme"` on every follow-up
  action (get/update/delete/associate/etc.).
- HubSpot's OAuth authorize page shows its own account/hub chooser, so
  adding a *different* portal works from the normal add-account flow —
  the user picks the portal to grant on HubSpot's side.
- For destructive actions (deletes, sends) with multiple hubs connected
  and no hub named: ask the user which portal before acting.

## Essentials
- **Object IDs are numeric strings, NOT integers.** HubSpot returns IDs
  like `"123456789"`. Pass them through as strings; don't `int()`-cast —
  some IDs overflow JS number range.
- **Object types use plural names.** API paths take `contacts`,
  `companies`, `deals`, `tickets`, `tasks`, `notes`, `calls`, `emails`,
  `meetings`. Custom objects use their schema name (e.g.
  `p12345_project`).
- **Property names are flat snake_case strings.** `firstname`, `email`,
  `dealstage`, `hs_pipeline_stage`. To create a contact you pass
  `{"properties": {"email": "...", "firstname": "..."}}`. There is no
  nesting.
- **Pagination is cursor-based.** Every list returns
  `{results: [...], paging: {next: {after: "<cursor>"}}}`. Pass `after`
  to get the next page. `limit` defaults to 30, capped at 100 for most
  endpoints (500 for owners + lists).
- **Search uses `filterGroups`, not query strings.** The body shape is
  `{filterGroups: [{filters: [{propertyName, operator, value}]}]}`.
  Multiple groups OR together; filters within a group AND. Operators:
  `EQ`, `NEQ`, `GT`, `GTE`, `LT`, `LTE`, `BETWEEN`, `IN`, `NOT_IN`,
  `CONTAINS_TOKEN`, `HAS_PROPERTY`, `NOT_HAS_PROPERTY`.
- **Move a deal/ticket via the stage property.** Don't look for a
  `move_stage` endpoint — update `dealstage` (deals) or
  `hs_pipeline_stage` (tickets) to the target stage ID. The
  `move_hubspot_deal_stage` / `close_hubspot_ticket` actions wrap this.
- **Engagement associations.** Tasks/notes/calls/emails/meetings need an
  associated contact/company/deal/ticket to be useful. The
  `associated_object_type` + `associated_object_id` args on the
  create-engagement actions wire this up via the default-association
  API. Passing only one without the other is silently no-op.
- **Auth: Bearer token works for both Private App and OAuth.** The
  client doesn't branch — `Authorization: Bearer <access_token>` is
  identical for both. The `auth_kind` field on the credential is purely
  informational.
- **Token refresh is automatic for OAuth credentials.** Access tokens
  expire after ~30 minutes; the client checks `token_expiry` on every
  request and exchanges the stored `refresh_token` for a fresh access
  token (60s before actual expiry, to absorb clock skew + in-flight
  calls). Refresh requires `HUBSPOT_SHARED_CLIENT_ID` +
  `HUBSPOT_SHARED_CLIENT_SECRET` to be configured — same credentials
  used at initial OAuth. If a refresh fails (refresh_token revoked,
  network error), the stale token is used and the next API call
  surfaces HubSpot's 401 — the user should reconnect the account.
  Private App tokens (`auth_kind == "token"`) skip the refresh path
  entirely — they don't expire.
- **Rate limits are per-portal.** Standard tier: 100 requests / 10
  seconds / portal across all integrations. Enterprise: 150 / 10s. 429
  responses include `Retry-After` — respect it.
- **Webhooks require an App ID, not a portal ID.** The webhooks API is
  for HubSpot Apps (the same kind registered for OAuth), not Private
  Apps. The `app_id` arg on the webhook actions is HubSpot's app ID
  from the developer console — distinct from the portal/hub ID of the
  authenticated account. Skip these actions entirely when authenticated
  via a Private App token.
- **Form submissions don't take auth.** `submit_hubspot_form` posts to
  `api.hsforms.com`, not `api.hubapi.com`, and the form GUID + portal
  ID alone are the authentication. Anyone can submit; the credential is
  only used so the action wrapper has a way to look up the portal_id —
  make sure the `portal_id` you pass matches the hub the form lives in.
- **The Lists API is v3 only.** The legacy `/contacts/v1/lists`
  endpoints are deprecated — don't add them back. `list_hubspot_lists`
  uses `POST /crm/v3/lists/search`, which is correct.
