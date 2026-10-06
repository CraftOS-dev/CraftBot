# Figma

Use Figma to inspect designs, export assets, understand published libraries,
and manage feedback through REST. Create and edit native designs through the
optional published browser plugin connection below.

## Create and edit designs in the browser

The easiest setup is Settings → Integrations → Figma → Manage → Design in Figma.
Click Start canvas connection, open the published plugin in the target browser
file, click its Connect button on port 3055, then paste its channel into Settings
and click Connect channel. No application approval is required. A PAT account
in CraftBot is still needed for integration routing and REST features.

Alternatively run `start_figma_canvas` first. The user opens their target design in the Figma
browser editor and runs the published **Talk To Figma MCP Plugin** (community
plugin 1485687494525374295). Connect on port 3055 and use the channel shown by
the plugin with `connect_figma_canvas`. No development plugin, Bun, separate
MCP server, or Figma Desktop is required. Keep the plugin open while editing.

Canvas operations target the paired plugin's **open document and page**.
The REST `default_file_key` does not select a canvas target. A new connection
must be paired explicitly; never invent a channel or assume which file is open.
Read `read_figma_canvas` and confirm the intended page before writing. A page
switch blocks writes until explicit reconnection. This connection is local to
the CraftBot process and account client; it must be reconnected after restart,
account reconnect, plugin close, or 15 minutes without activity.

`create_figma_design` accepts one root FRAME with children (FRAME, RECTANGLE,
TEXT) and creates editable native nodes, returning their ids. Use parent-local
x/y, width/height, names, hex `fill`, and `corner_radius`; TEXT uses `text`,
`font_size` and `font_weight` with Inter. FRAME can use `layout` (NONE,
HORIZONTAL, VERTICAL), `padding`, `gap`. Limit: 100 nodes, 8 levels, 128 KiB.
Split larger designs into multiple frames. This creates designs in an existing
open file; it does not create a new cloud file. See advanced operations below
for image fills, existing component instances and layout changes.

### Advanced canvas work

Call `get_figma_canvas_capabilities` for the supported command catalog and exact
parameter schemas. These are the adapter's supported upstream commands, not a
guarantee that every published plugin version implements them. An unsupported
command error requires reporting that version limitation; do not retry it.

Use `read_figma_canvas_details(command, params)` to inspect styles, local
components, selected design, text nodes, node types, annotations, instance
overrides and prototype reactions. Reads report `truncated`; narrow the node
scope when necessary. Local component scans can cover all pages in the file.

Use `edit_figma_canvas(actions)` for up to 30 ordered actions (128 KiB total).
Each has `command`, upstream camelCase `params`, and optionally `as` on creation
or clone commands. Later node-id fields can reference `$alias`, e.g. create a
frame `as: "card"`, then set a stroke with `nodeId: "$card"`.
The entire input is validated before mutation. Supported workflows include
native frames/rectangles/text/sections, cloning, reparenting, text/fill/strokes,
corner radius, layout mode/wrapping/padding/alignment/sizing/spacing, creating
instances from existing local or published components, copying instance
overrides, annotations, focus and selection. Creating component definitions,
variables, arbitrary vectors or executing JavaScript is unavailable.
No delete commands are accepted in this batch; use the explicit delete tool.

`set_figma_canvas_image` applies an absolute local PNG/JPG/GIF/WebP file up to
5 MiB as a fill (FILL/FIT/CROP/TILE). It does not fetch URLs. The file bytes go
only to the paired plugin. `export_figma_canvas_image` exports unsaved canvas
nodes as PNG into unique files in an absolute local directory (scale 0.01–4,
5 MiB limit). Use REST for other export formats after the file synchronizes.
The plugin may reject dimensions/formats beyond its Figma image support.

`update_figma_canvas_node` changes name, text, fill, corner radius, local x/y
(provide both), or width/height (provide both). `delete_figma_canvas_node`
deletes a specific design node and its descendants; never delete existing user
content without an instruction. Read the live nodes after changes to verify.
REST reads/exports can lag behind the live plugin until Figma syncs the file.

Writes are serialized per canvas and never retried automatically. Errors can
contain `created_nodes`, `completed_commands`, `partial`, and `request_id`.
After a timeout/disconnect, a write **may have completed**. Check
`get_figma_canvas_status(request_id=…)` and inspect the canvas before deciding
whether to retry; partial writes are not rolled back. Stop with
`stop_figma_canvas` when finished. This community plugin is independent of
Figma/CraftBot and declares usage analytics; no PAT is sent to it.

## Start from the user's link

Accept a file key or a Figma design/file/board/proto URL. URLs carrying
`node-id=12-34` are normalized to `12:34` automatically. Start with
`get_figma_file_metadata`; use `get_figma_nodes` when a specific frame is linked.
Use `get_figma_file` with a small depth to discover pages/frames first.

Document reads obey both a depth limit and the configured total node cap.
`truncated` or `children_truncated` means more content exists. Request narrower
subtrees rather than assuming missing nodes do not exist. `find_figma_nodes`
searches only the fetched tree; its `searched_depth` and `document_truncated`
describe coverage. It cannot search all files or guarantee a whole-file search.

## Export assets

`export_figma_images` returns temporary PNG/JPG/SVG/PDF URLs, with
`failed_node_ids` for nodes Figma could not render. `download_figma_images`
saves unique local files to an absolute directory, without overwriting files.
Report partial failures. `get_figma_image_fills` retrieves embedded source
images, rather than rendered frames. Exporting an image does not edit a design.

## Components and styles

Library lookups use published component/component-set/style **keys**, not
node ids. Resolve keys with `list_figma_file_components`,
`list_figma_file_component_sets`, or `list_figma_file_styles`. Unpublished
content is in the document tree and `get_figma_nodes`.

## Comments

List comments before replying. A reply requires the id of a **root** comment;
Figma does not allow replies to replies. Optional `client_meta` anchors a new
comment to a node/position. Reactions use emoji shortcodes such as `:heart:`.
Only the author can delete a comment or reaction. REST does not expose comment
editing or resolution. A failed post must not be retried blindly: a timeout
may mean it succeeded. List comments and check first.

## Accounts and discovery

The `account` parameter accepts an identity/alias/unique fragment; omit it for
the primary account. Honor qualifiers like "my work Figma account".

Team ids cannot be obtained through the API; accept a supplied team URL or id,
or use the configured default. Folder listing requires `folders:read` and a
PAT or eligible private OAuth app; public OAuth apps cannot list folders/files.
The default OAuth scope set intentionally excludes this restricted scope.
For public OAuth, work directly from supplied file links and use
`get_figma_folder_metadata` for a supplied folder id.
Personal tokens may return `partial_metadata` containing only the folder id/name.
Respect `unavailable_fields`; full timestamps/counts/thumbnails require OAuth
with `folder_metadata:read`.

Local pagination returns `pagination.next_offset`; pass that as `offset`.
Server-paged team libraries return cursors: use `before`/`after`.
Versions return pagination URLs: pass `pagination.prev_page` as `before` or
`pagination.next_page` as `after`. Their secondary cursor fields are preserved.
Comment reactions use `pagination.next_page` as `cursor`. Never invent cursors.

## Errors

- Permission/expiry errors: check the account, token scopes, file access, and
  token expiry. Reconnect when needed; repeated calls do not grant permissions.
- Rate limits: respect the returned retry interval. Limits depend on the seat
  and resource plan, so aggressive file polling is unsuitable.
- Not found: check the key/id and whether this account can access the resource.
- PATs cannot refresh automatically. OAuth refresh is automatic when configured;
  refresh failure requires reconnection.

Variables, webhooks and Enterprise analytics/admin APIs are
outside this integration's first release. Explain the limitation when requested.
