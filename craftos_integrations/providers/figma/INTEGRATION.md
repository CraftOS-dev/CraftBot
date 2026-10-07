# Figma integration

Native provider with 43 operations across files (6), assets (3),
libraries (9), comments (7), discovery (5), and optional browser canvas (13).
The `figma` umbrella has 25 operations.
Source of truth: [official OpenAPI](https://github.com/figma/rest-api-spec) and
[REST documentation](https://developers.figma.com/docs/rest-api/).

## Authentication and identity

PAT login accepts `access_token`, verifies `GET /v1/me` using `X-Figma-Token`,
and stores the string user id as account identity. Require `current_user:read`.
Email/display name is descriptive, never the account key. Other scopes are
checked by the vendor when an operation runs; successful login does not prove
every operation is authorized. PAT expiration needs a new token and reconnect.

OAuth appears (`auth_type=both`) only when `FIGMA_CLIENT_ID` and
`FIGMA_CLIENT_SECRET` are configured through `configure(oauth={...})` or process
environment variables. The app does not automatically load `.env.example`.
No shared client secret is embedded or stored in account credentials.
Public distribution requires Figma approval and a secure deployment for the
app secret; this provider alone does not provision an OAuth app or token broker.

OAuth uses browser authorization, S256 PKCE, and form-encoded Basic-auth token
exchange at `/v1/oauth/token`. Register the shared callback URL (by default
`http://localhost:8765`) with Figma and verify it for your app before rollout.
Figma's authorization code must be exchanged within 30 seconds. OAuth scopes:

```
current_user:read file_content:read file_metadata:read file_versions:read
file_comments:read file_comments:write library_assets:read library_content:read
team_library_content:read folder_metadata:read
```

Refresh uses `/v1/oauth/refresh` with Basic auth and the stored refresh token.
It runs before expiry, under a per-client lock. The replacement access token is
persisted before being made visible; failed refreshes leave the credential
unchanged. Figma invalidates the previous access token on refresh. Separate
running processes using the same OAuth grant still need coordination beyond
this in-process lock; avoid multiple live instances for one grant.

For PAT folder listing add `folders:read`; public OAuth cannot request that scope.
An eligible private OAuth deployment can extend its approved scope set separately.
The PAT settings UI does not offer `folder_metadata:read`. If the metadata endpoint
returns 401/403 for a PAT, the client verifies folder access through the folder listing
endpoint and returns only its id/name, marked `partial_metadata`, with an explicit
list of unavailable fields. It never invents timestamps, thumbnails, or file counts.
OAuth uses the full metadata endpoint and does not fall back to the restricted
folder listing scope. The fallback must authenticate successfully; expired tokens
or inaccessible folders still return the original access error.

## Identifiers, response bounds, pagination

- File keys and branch keys remain case-sensitive strings. Supported Figma URLs
  supply the key; `node-id=12-34` becomes `12:34`. Compound instance ids survive.
- Published component/style keys are not node ids. User/team/folder/comment IDs
  remain strings, avoiding precision loss.
- Document depth defaults to 2 (1–10), with a configurable total node cap
  defaulting to 500 (1–2000). Truncation is explicit. Search covers the fetched
  tree only. Null nodes and failed image renders remain visible.
- Team libraries and file versions use native cursors and `page_size`. Reactions
  use `cursor`. Other list endpoints are locally sliced using `limit`/`offset`;
  pagination includes total/next_offset/local. This does not reduce API cost.
- Version pagination URLs can be supplied as `before`/`after`. Only official
  HTTPS URLs for the same file's versions endpoint are accepted. The client
  extracts the native primary/secondary cursors, bounds page size, and calls its
  fixed API endpoint; it never navigates to caller-supplied URLs.
- Team ids are supplied explicitly or via a default; there is no list-my-teams
  REST endpoint. Use the v2 folder API; deprecated projects are excluded.

## HTTP, caching, and exports

Requests use the standard `{ok, result}` / `{error, details}` envelopes.
The shared HTTP helper's optional response hook captures status/Retry-After
without changing existing envelopes or callers.

Only GET requests retry a 429: at most twice, and only when Retry-After is at
most 5 seconds. Longer delays return an actionable error. Writes never replay
automatically; a timeout can mean a comment was accepted. 401/403/404 are not
retried blindly. Posts, replies and deletes also enable the host's irreversible
action guard to prevent automatic replay after a crash. There is no inbound
polling listener.

Read cache lives on the account-bound client, with a configurable TTL (0–300s),
request-parameter keys and a 64-entry cap. Writes and token changes invalidate
it. Output bounding/slicing cannot mutate cached originals.

Rendered URLs expire after 30 days; image-fill URLs after at most 14 days.
Downloads accept generated HTTPS Figma/AWS asset URLs only, send no account
authorization to asset hosts, reject redirects, cap each asset at 50 MiB, remove
partial files on failure, and use unique filenames in an absolute directory.
Partial success includes the failed node ids.

## Offline verification

Canvas creation uses the published [Talk To Figma MCP Plugin](https://www.figma.com/community/plugin/1485687494525374295/talk-to-figma-mcp-plugin)
and its [open source protocol](https://github.com/grab/cursor-talk-to-figma-mcp).
CraftBot implements its own local adapter; no third-party server/package is run.
See GUIDANCE.md for setup and supported declarative fields.

The bridge binds IPv4/IPv6 loopback only on port 3055, restricts Host/Origin,
caps peers/messages/history (8 MiB wire messages, 64 KiB per history entry), and never relays peer-originated commands or sends
credentials. A user-provided plugin channel is claimed by one account client;
other account clients cannot use its commands/results. The published plugin
does not expose a reliable file key/current user identity, so the explicit
channel chooses the open document, independently of REST account defaults.
The channel is a pairing hint, not a secure replacement for an authenticated
Figma OAuth grant. Only existing authenticated CraftBot operations can issue
commands; no public HTTP command endpoint exists. Settings has an allowlisted,
account-bound start/connect/status/stop handler and cannot dispatch design writes.
Do not expose this port to
the network. Sessions expire after 15 minutes idle (unpaired peers: 5 minutes).

Whole-design validation precedes mutations. Each request has a UUID and is
sent once; late replies update a bounded status history. Timeouts/disconnections
report unknown outcome and partial node ids. Writes use the host replay guard,
invalidate REST caches, and require the paired current page unchanged before
the operation. Multi-command writes are not atomic; the user should keep the
target page open until the operation finishes. The community plugin declares
Google Analytics usage events. Published plugin versions can change independently
of CraftBot, so a live smoke test is required when upgrading the plugin.

```
python scripts/verify_integration.py figma
python -m pytest tests/integrations/test_figma_client.py
```

Use CraftBot's resolved interpreter if the shell Python lacks dependencies.
Conformance tests cover the provider contract, auth, action schemas and account
routing. Client tests cover captured API shapes, pagination, truncation/cache
behavior, comments, exports, rate limits, refresh, and the shared HTTP hook.

## Live smoke checklist

Use a test design and a token scoped for the workflows being tested:

1. Connect a PAT; verify profile identity in settings.
2. Connect a second user; give it an alias and check both primary/explicit routing.
3. "Read this Figma frame: <node URL>"; verify text/layout against the design.
4. "Export this frame as SVG and save it to <absolute directory>"; inspect it.
5. "List published components and styles in this file"; verify keys/data.
6. "Post 'CraftBot smoke test' on this frame"; verify in Figma.
7. "Reply to that comment, then delete the test reply and root comment".
8. "List files in this folder" using a PAT with folders:read.
9. Test a file inaccessible to the selected account and a missing-scope token.
10. With configured OAuth app credentials: connect, add another account, refresh,
    and confirm reconnection guidance when the grant is revoked.
11. Start the canvas bridge, run the published plugin in the browser QA design,
    pair its channel, create a native frame with text/shapes, and verify the nodes.
12. Update text, rename/move/resize/style a disposable node, then delete that node.
13. Close/reopen the plugin and verify disconnected/reconnection behavior. Stop
    the bridge when finished. Test page-switch and timeout recovery offline.

Offline tests cannot establish vendor acceptance or OAuth app eligibility.

## Intentional exclusions

Canvas supports the documented native creation/editing, layouts, duplication,
reparenting, image fills/live PNG exports, component instantiation/overrides,
annotations and selection through the unmodified community plugin. Command
schemas are in canvas_commands.py; advanced operations validate bounded batches
before mutation and report progress/aliases on partial failure. Plugin-returned
nested failure envelopes are errors, never silent success. Compatibility with
published plugin versions must be checked live; upstream main may be ahead of
the marketplace release. CraftBot does not fork, publish or vendor the plugin.
Arbitrary JavaScript, new cloud-file creation, vector authoring, component
definition creation, custom fonts and variable authoring are unavailable.
Variables and library analytics require Enterprise access; organization/admin
logs, AI metering and billing are outside scope. Webhooks require a deployed
public receiver and are deferred. Comment edit/resolve is not a REST capability.
