# Notion

The Notion integration connects the agent to your Notion workspace, either through the shared CraftOS app or your own internal integration token. The agent can search the workspace, read and write pages, create and query databases, edit block content, post comments, list users, and upload files. Notion does not push changes to CraftBot, so this integration has no listener.

## Requirements

| Requirement | Details |
|---|---|
| Notion workspace | The workspace whose pages and databases the agent works with |
| An integration | Either authorize the shared CraftOS app with `/notion invite`, or create your own at [notion.so/my-integrations](https://www.notion.so/my-integrations) |
| Shared pages | An integration only sees pages and databases you explicitly share with it |
| Network access | CraftBot calls `api.notion.com` over HTTPS |

## Setup

Connect one of two ways.

**Own integration (works on any build):**

1. Open [notion.so/my-integrations](https://www.notion.so/my-integrations) and click **New integration**.
2. Name it, pick the workspace, and choose an internal integration. Submit.
3. Copy the **Internal Integration Secret**.
4. In Notion, open each page or database you want the agent to reach, click **...**, choose **Connect to** (also shown as **Add connections**), and select your integration. Sharing a parent page shares its children.
5. In CraftBot, open **Settings → Integrations → Notion**, paste the secret into the token field, and connect. From chat, `/notion login <integration_token>` does the same thing.

**Shared CraftOS app (release builds):** run `/notion invite`, complete the Notion OAuth prompt, and pick the pages to share. This path needs the app credentials embedded in release builds, so a source checkout uses the own-integration path above.

Verify with `/notion status`, which shows the connected workspace. `/notion logout` removes the credential.

## How it connects

**Authentication.** Every API call sends your integration token as a bearer token to `api.notion.com`, along with a pinned `Notion-Version` header. At login CraftBot validates the token against the bot user endpoint (`/users/me`) and stores the token in the credential store as `notion.json`. The OAuth invite path exchanges the grant for an access token and stores it the same way. See [Credentials](credentials.md).

**No listener.** Notion is request and response only. It does not notify CraftBot when a page or database changes, so nothing dispatches events from Notion and there is no polling loop. The agent acts on Notion only while running a task that calls a Notion action.

**Sharing model.** An integration starts with access to nothing. It can read or edit only the pages and databases you have shared with it, so a page the agent cannot find is almost always a page that has not been shared. Share it from the page's **...** menu under **Connect to**.

**Identifiers.** Pages, databases, and blocks are addressed by 36-character UUIDs with hyphens, not by their titles. The agent runs `search_notion` first to resolve a name like "Roadmap" to its ID before reading or writing.

## What the agent can do

The 29 Notion actions are grouped into action sets (`notion_pages`, `notion_databases`, `notion_blocks`, and so on) that the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Search

| Action | Purpose |
|---|---|
| `search_notion` | Search the workspace for pages and databases, lean results by default |

### Pages

| Action | Purpose |
|---|---|
| `get_notion_page` | Get a page's metadata and properties (not its block content) |
| `create_notion_page` | Create a new page under a parent page or database |
| `update_notion_page` | Update a page's properties or archive state |
| `archive_notion_page` | Archive a page (send to trash), reversible with restore |
| `restore_notion_page` | Restore a previously archived page |
| `get_notion_page_property` | Get a single page property's full value, following pagination |

### Databases

| Action | Purpose |
|---|---|
| `get_notion_database_schema` | Get a database's schema (property names and types) |
| `query_notion_database` | Query a database with optional filters and sorts, lean rows by default |
| `create_notion_database` | Create a new database under a parent page with a column schema |
| `update_notion_database` | Update a database's title, description, schema, or inline state |
| `archive_notion_database` | Archive a database |
| `restore_notion_database` | Restore an archived database |

### Page content and blocks

| Action | Purpose |
|---|---|
| `get_notion_page_content` | Get a page's content blocks, simplified to type and text by default |
| `append_notion_page_content` | Append content blocks to a page or block |
| `get_notion_block` | Get a single block by ID |
| `update_notion_block` | Update a block's content, or soft-delete it |
| `delete_notion_block` | Delete (send to trash) a block |

### Comments

| Action | Purpose |
|---|---|
| `list_notion_comments` | List comments on a page or block |
| `create_notion_comment` | Post a comment on a page or block, or reply in a discussion |

### Users

| Action | Purpose |
|---|---|
| `list_notion_users` | List workspace members visible to the integration |
| `get_notion_user` | Get a single user by ID |
| `get_notion_bot_info` | Get info about the authenticated bot (workspace name, owner) |

### File uploads

| Action | Purpose |
|---|---|
| `upload_notion_file` | Upload a local file in one call (single part, under 20 MB) |
| `create_notion_file_upload` | Step 1: initialise a file upload resource |
| `send_notion_file_upload` | Step 2: send file bytes to a pending upload |
| `complete_notion_file_upload` | Step 3 (multi-part only): finalize the upload |
| `get_notion_file_upload` | Get the current status of a file upload |
| `list_notion_file_uploads` | List file uploads created by this integration |

## Example requests

```
Search Notion for the Roadmap database and list the items due this month.
```

```
Create a page titled "Weekly sync 2026-07-20" under the Meetings page and add my agenda as bullet points.
```

```
In the Tasks database, mark the "Ship v1.4" row as Done.
```

```
Read the "Onboarding" page and summarize it back to me.
```

```
Post a comment on the Launch Plan page asking the owner to confirm the date.
```

## Configuration

Notion has no watch or listener settings, because it does not emit events. The only thing that controls what the agent can reach is which pages and databases you share with the integration in Notion. To widen or narrow the agent's reach, add or remove the integration from a page through its **...** menu under **Connect to**. Sharing a parent page shares its children.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "object_not_found" on a page you can open | The integration was never shared on that page | In Notion, open the page, click **...**, choose **Connect to**, and select your integration. Retrying does not help |
| 401 or "unauthorized" | Bad, revoked, or expired token | Create a new secret at [notion.so/my-integrations](https://www.notion.so/my-integrations) and run `/notion login <new_token>` |
| Creating a page fails with a validation error | `parent_type` does not match `parent_id`, or the parent does not exist | `parent_type` is `page_id` or `database_id` and must match the parent. The agent resolves the parent with `search_notion` first |
| Appended markdown does not appear | Notion content is block JSON, not markdown | The agent builds block objects (paragraph, heading, bulleted_list_item) rather than passing raw markdown |
| Database query returns nothing | The filter is not in Notion's filter object format | Notion uses its own typed filter objects, not SQL. The agent reads the schema with `get_notion_database_schema` first |
| Writing a database row fails | A property value has the wrong shape for its type | The agent reads the schema to learn each property's type (title, rich_text, select, date), then builds the matching object |

## Next

- [Jira](jira.md): issue tracking with a polling listener
- [Credentials](credentials.md): where tokens are stored and how `/cred status` reports them
- [Connections overview](index.md): every integration and how they connect
