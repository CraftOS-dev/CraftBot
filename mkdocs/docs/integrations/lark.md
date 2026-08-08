# Lark

The Lark integration connects the agent to Lark (Feishu) across three surfaces: messaging, calendar, and drive. All three run on one Lark Custom App that you create once, so a single App ID and App Secret authorize everything. In CraftBot they connect as three separate integrations (Lark, Lark Calendar, and Lark Drive), each with its own credential and connect state, and you paste the same App ID and App Secret into each. The agent can send and receive chat messages, manage groups and contacts, work with calendars and events, and read and write files, Docs, Sheets, Bitables, and Wiki pages.

## Requirements

| Requirement | Details |
|---|---|
| Lark workspace | The Custom App lives in your Lark (or Feishu) tenant |
| Lark Custom App | Create one at [open.larksuite.com/app](https://open.larksuite.com/app). The agent acts as this app's bot |
| App ID and App Secret | Found on the app's Credentials & Basic Info tab. The same pair connects all three modules |
| Bot feature | Add the Bot feature to the app before messaging works |
| Permission scopes | Messaging needs `im:message`. Calendar needs `calendar:calendar` and `calendar:calendar.event.attendee`. Drive needs `drive:drive` and `drive:file:upload` |
| Tenant admin approval | Each app version must be released and approved by a workspace admin before scopes take effect and events flow |
| Network access | CraftBot calls `open.larksuite.com` over HTTPS and opens one WebSocket for messaging |

## Setup

You configure one Custom App with every feature and scope you want, then connect each CraftBot module to it.

1. Open [open.larksuite.com/app](https://open.larksuite.com/app), sign in, and click **Create Custom App**. Give it a name.
2. In the left sidebar, open **Add Features** and add the **Bot** feature.
3. Open **Events & Callbacks → Event Configuration**. Set **Subscription Mode** to **Receive callbacks through persistent connection**. This is the mode the messaging listener uses.
4. Still under Event Configuration, click **Add Event** and subscribe to **`im.message.receive_v1`** (Receive Message). Without this event, no incoming messages reach CraftBot.
5. Under **Events & Callbacks → Encryption Strategy**, leave the **Encryption Key** empty. This integration does not support encrypted events. If you set an encryption key, incoming messages will not decode.
6. Open **Permissions & Scopes** and enable the scopes for the modules you want:
    - Messaging: `im:message` (plus `im:message.p2p_msg` and `im:message.group_at_msg:readonly` for direct and group @-mention delivery).
    - Calendar: `calendar:calendar` and `calendar:calendar.event.attendee`.
    - Drive: `drive:drive` and `drive:file:upload`.
7. Open **Version Management**, click **Create Version**, and submit it for tenant admin approval. Scopes and events do not take effect until a workspace admin approves and the version is released.
8. Once the version is released, open **Credentials & Basic Info** and copy the **App ID** and **App Secret**.
9. In CraftBot, open **Settings → Integrations** and connect each module you want. Paste the same App ID and App Secret into **Lark**, **Lark Calendar**, and **Lark Drive**. From chat, `/lark login <app_id> <app_secret>`, `/lark_calendar login <app_id> <app_secret>`, and `/lark_drive login <app_id> <app_secret>` do the same thing.

Verify each with `/lark status`, `/lark_calendar status`, and `/lark_drive status`. Each `logout` command removes that module's credential, and `/lark logout` also stops the messaging listener.

## How it connects

**Authentication.** All three modules authenticate the same way. From your App ID and App Secret, CraftBot mints a `tenant_access_token` against `open.larksuite.com` and caches it with its expiry. The shared scaffolding in `_lark_common` refreshes the token automatically when it comes within 60 seconds of its roughly two-hour expiry, so there is no manual renewal. Each module keeps its own credential file (`lark.json`, `lark_calendar.json`, `lark_drive.json`) with its own cached token, which is why connect and disconnect are independent per module even though the App ID and App Secret are identical. See [Credentials](credentials.md).

**Messaging listener.** While the Lark messaging module is connected, CraftBot opens one persistent-connection WebSocket to Lark using the official `lark-oapi` SDK and subscribes to `im.message.receive_v1`. Incoming messages arrive in real time and dispatch to the agent as events. The SDK reconnects on its own with backoff if the network drops. The WebSocket connects even when the app version is unapproved, but events only flow once a workspace admin has released the version, so a silent listener with no incoming messages usually means approval is still pending.

**Calendar and drive have no listeners.** The Lark Calendar and Lark Drive modules are request-driven only. They make REST calls when the agent runs an action and do not open a WebSocket or receive events. Only messaging delivers events into the agent.

## What the agent can do

The Lark actions load in action sets that the agent pulls in as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Messaging

The 46 messaging actions cover sending and reading messages, reactions and pins, media, group chats, and the contact directory.

Sending messages:

| Action | Purpose |
|---|---|
| `send_lark_message` | Send a plain text message to a user or chat, addressed by open_id, user_id, email, chat_id, or union_id |
| `reply_lark_message` | Reply to an existing message by its message_id |
| `send_lark_rich_message` | Send any message type: text, post, image, file, audio, media, sticker, card, or a shared chat or user |
| `send_lark_image` | Send an image using a key from `upload_lark_image` |
| `send_lark_file` | Send a file using a key from `upload_lark_im_file` |
| `send_lark_card` | Send an interactive card built from a card schema |
| `send_lark_post` | Send a styled, multi-line rich-text post |
| `reply_lark_rich_message` | Reply with non-text content and optionally start a thread |
| `forward_lark_message` | Forward a message to another recipient |
| `update_lark_message` | Edit a text or interactive message the bot already sent |
| `delete_lark_message` | Recall a message the bot sent |
| `batch_send_lark_message` | Broadcast one message to many recipients in a single call |
| `send_lark_urgent` | Escalate a message to selected users by in-app push, SMS, or phone call |

Reading messages:

| Action | Purpose |
|---|---|
| `get_lark_message` | Get a single message by ID |
| `list_lark_chat_messages` | List a chat's message history over a time window |
| `list_lark_message_read_users` | See who has read a message and when |

Reactions and pins:

| Action | Purpose |
|---|---|
| `add_lark_reaction` | Add an emoji reaction to a message |
| `remove_lark_reaction` | Remove a reaction by its reaction_id |
| `list_lark_reactions` | List the reactions on a message |
| `pin_lark_message` | Pin a message in its chat |
| `unpin_lark_message` | Unpin a previously pinned message |
| `list_lark_pinned_messages` | List the pinned messages in a chat |

Media:

| Action | Purpose |
|---|---|
| `upload_lark_image` | Upload a local image and get an image_key |
| `upload_lark_im_file` | Upload a local file and get a file_key |
| `download_lark_message_resource` | Download an image, file, or audio attachment from a message |

Chats and groups:

| Action | Purpose |
|---|---|
| `list_lark_chats` | List the groups the bot belongs to |
| `create_lark_chat` | Create a group or topic chat |
| `get_lark_chat` | Get a chat's members, owner, and settings |
| `update_lark_chat` | Update a chat's settings |
| `dissolve_lark_chat` | Dissolve a group (owner only) |
| `list_lark_chat_members` | List the members of a chat |
| `add_lark_chat_members` | Add members to a chat |
| `remove_lark_chat_members` | Remove members from a chat |
| `search_lark_chats` | Search chats by name |
| `get_lark_chat_announcement` | Get a chat's announcement doc |
| `update_lark_chat_announcement` | Update a chat's announcement |
| `set_lark_chat_moderation` | Set who may send messages in a chat |

Users and departments:

| Action | Purpose |
|---|---|
| `get_lark_user` | Get one user by ID |
| `batch_get_lark_users` | Get several users by ID in one call |
| `get_lark_user_by_email` | Resolve a user's open_id from a company email |
| `batch_lookup_lark_users` | Resolve many emails or mobiles to user IDs at once |
| `search_lark_users_by_name` | Search users by name |
| `list_lark_department_users` | List the users in a department |
| `get_lark_department` | Get information about a department |
| `list_lark_department_children` | List the child departments under a parent |
| `get_lark_bot_info` | Get the connected bot's name, open_id, and app info |

### Calendar

The 26 calendar actions cover calendars, events, attendees and rooms, and sharing.

Calendars:

| Action | Purpose |
|---|---|
| `list_lark_calendars` | List the calendars the bot can access |
| `get_lark_primary_calendar` | Get the bot's primary calendar and its calendar_id |
| `get_lark_calendar` | Get metadata for one calendar |
| `create_lark_calendar` | Create a secondary calendar owned by the bot |
| `update_lark_calendar` | Patch fields on a calendar |
| `delete_lark_calendar` | Delete a calendar the bot owns |
| `search_lark_calendars` | Search visible calendars by name |
| `subscribe_to_lark_calendar` | Subscribe to a shared calendar so it appears in listings |
| `unsubscribe_from_lark_calendar` | Unsubscribe from a shared calendar |

Events:

| Action | Purpose |
|---|---|
| `list_lark_calendar_events` | List events on a calendar between two timestamps |
| `get_lark_calendar_event` | Get one event by ID |
| `create_lark_calendar_event` | Create an event on a calendar |
| `update_lark_calendar_event` | Patch fields on an event |
| `delete_lark_calendar_event` | Delete an event by ID |
| `search_lark_calendar_events` | Full-text search over event titles and descriptions |
| `rsvp_lark_calendar_event` | RSVP accept, decline, or tentative to an invitation |
| `list_lark_event_instances` | List the occurrences of a recurring event in a window |

Attendees and rooms:

| Action | Purpose |
|---|---|
| `add_lark_event_attendees` | Invite users, external emails, or whole chats to an event |
| `list_lark_event_attendees` | List the current attendees on an event |
| `remove_lark_event_attendees` | Remove attendees from an event |
| `list_lark_event_chat_attendee_members` | List the chat members behind a chat-type attendee |
| `book_lark_meeting_room` | Attach a meeting room to an event as a resource |

Sharing and availability:

| Action | Purpose |
|---|---|
| `list_lark_calendar_acls` | List the sharing entries on a calendar |
| `share_lark_calendar_with_user` | Share a calendar with a user at an owner, reader, writer, or free-busy role |
| `revoke_lark_calendar_share` | Revoke a calendar share |
| `check_lark_free_busy` | Query users' busy intervals over a window to find a slot |

### Drive

The 76 drive actions cover files, permissions, comments, import and export, Docs, Sheets, Bitables, and Wiki.

Files:

| Action | Purpose |
|---|---|
| `list_lark_drive_files` | List files and folders in a Drive folder |
| `get_lark_drive_file_metadata` | Fetch metadata for one or more file tokens |
| `create_lark_drive_folder` | Create a folder |
| `upload_lark_drive_file` | Upload a local file up to 20MB |
| `download_lark_drive_file` | Download a regular file to a local path |
| `delete_lark_drive_file` | Delete a file, folder, or doc by token |
| `search_lark_drive_files` | Full-text search across Drive files |
| `copy_lark_drive_file` | Copy a file or doc into a folder |
| `move_lark_drive_file` | Move a file, folder, or doc to another folder |
| `list_lark_drive_file_versions` | List version history for a Doc or Sheet |
| `get_lark_drive_file_statistics` | Get views, likes, and comment counts for a file |

Permissions:

| Action | Purpose |
|---|---|
| `list_lark_drive_permissions` | List the members with access to a file |
| `add_lark_drive_permission` | Grant a member view, edit, or full access |
| `update_lark_drive_permission` | Change a member's permission level |
| `remove_lark_drive_permission` | Revoke a member's access |
| `get_lark_drive_public_permission` | Get a file's public-link settings |
| `update_lark_drive_public_permission` | Update a file's public-link scope, comments, and security |
| `transfer_lark_drive_ownership` | Transfer ownership of a file to another user |

Comments:

| Action | Purpose |
|---|---|
| `list_lark_drive_comments` | List comments on a file |
| `create_lark_drive_comment` | Post a comment on a file |
| `get_lark_drive_comment` | Get a single comment |
| `resolve_lark_drive_comment` | Mark a comment resolved or unresolved |
| `list_lark_drive_comment_replies` | List the replies on a comment |
| `update_lark_drive_comment_reply` | Edit a reply |
| `delete_lark_drive_comment_reply` | Delete a reply |

Import and export:

| Action | Purpose |
|---|---|
| `import_lark_drive_file` | Convert an uploaded file into a Doc, Sheet, or Bitable |
| `get_lark_drive_import_task` | Poll an import task until it finishes |
| `export_lark_drive_file` | Convert a Doc, Sheet, or Bitable into a regular file such as PDF or XLSX |
| `get_lark_drive_export_task` | Poll an export task until it finishes |
| `download_lark_drive_export` | Download the blob from a finished export |

Docs:

| Action | Purpose |
|---|---|
| `create_lark_doc` | Create a new Doc |
| `get_lark_doc` | Get a Doc's metadata |
| `get_lark_doc_raw_content` | Get a Doc's plain-text content for skimming |
| `list_lark_doc_blocks` | List a Doc's blocks |
| `get_lark_doc_block` | Get a single block |
| `append_lark_doc_blocks` | Append child blocks under a parent block |
| `update_lark_doc_block` | Update one block |
| `batch_update_lark_doc_blocks` | Update several blocks in one call |
| `delete_lark_doc_blocks` | Delete a contiguous range of child blocks |

Sheets:

| Action | Purpose |
|---|---|
| `create_lark_sheet` | Create a new spreadsheet |
| `get_lark_sheet` | Get spreadsheet metadata |
| `rename_lark_sheet` | Rename a spreadsheet |
| `list_lark_sheet_tabs` | List the tabs in a spreadsheet |
| `get_lark_sheet_tab` | Get info about one tab, including its rows and columns |
| `read_lark_sheet_values` | Read a range of cells |
| `batch_read_lark_sheet_values` | Read several ranges in one call |
| `write_lark_sheet_values` | Write a values array into a range |
| `append_lark_sheet_values` | Append rows after the last filled row |
| `batch_write_lark_sheet_values` | Write to several ranges in one call |
| `find_in_lark_sheet` | Find cells matching text within a range |
| `replace_in_lark_sheet` | Find and replace across a range |
| `insert_lark_sheet_rows_or_cols` | Insert rows or columns into a tab |

Bitables:

| Action | Purpose |
|---|---|
| `create_lark_bitable` | Create a new Bitable |
| `get_lark_bitable` | Get a Bitable's metadata |
| `update_lark_bitable` | Update a Bitable's name or advanced flag |
| `list_lark_bitable_tables` | List the tables in a Bitable |
| `create_lark_bitable_table` | Create a table |
| `delete_lark_bitable_table` | Delete a table |
| `list_lark_bitable_records` | List records in a table |
| `get_lark_bitable_record` | Get a single record |
| `create_lark_bitable_record` | Create a record |
| `update_lark_bitable_record` | Update a record |
| `delete_lark_bitable_record` | Delete a record |
| `batch_create_lark_bitable_records` | Create many records in one call |
| `batch_update_lark_bitable_records` | Update many records in one call |
| `batch_delete_lark_bitable_records` | Delete many records in one call |
| `search_lark_bitable_records` | Search records with filter and sort syntax |
| `list_lark_bitable_fields` | List the field definitions in a table |
| `create_lark_bitable_field` | Create a field of a chosen type |
| `list_lark_bitable_views` | List the views in a table |

Wiki:

| Action | Purpose |
|---|---|
| `list_lark_wiki_spaces` | List the Wiki spaces the bot can access |
| `get_lark_wiki_space` | Get info about a Wiki space |
| `list_lark_wiki_nodes` | List the nodes (pages) in a space |
| `get_lark_wiki_node` | Resolve a wiki node token to its underlying doc token and type |
| `create_lark_wiki_node` | Create a wiki node as a new doc or a shortcut to an existing one |
| `move_lark_wiki_node` | Move a wiki node to another parent or space |

## Example requests

```
Send a Lark message to alice@acme.com asking her to review the Q3 deck by Friday.
```

```
Create a Lark group called "Launch War Room", add the platform team, and pin the launch checklist.
```

```
Put a 30-minute sync on my Lark calendar tomorrow at 2pm and invite bob@acme.com.
```

```
Check when the design team is free on Thursday and book a meeting room for an hour.
```

```
Read the "Roadmap" Lark Sheet, find every row marked Blocked, and summarize them.
```

```
Export the "Launch Plan" Lark Doc to PDF and post it as a comment on the Bitable tracker.
```

## Configuration

Lark has no listener filters or watch settings to tune. The only configuration is the App ID and App Secret you paste when connecting each module. They are stored in the credential store, one file per module: `lark.json` for messaging, `lark_calendar.json` for calendar, and `lark_drive.json` for drive. Each file also caches that module's `tenant_access_token` and its expiry so a restart reuses the cached token instead of minting a new one. See [Credentials](credentials.md).

| Setting | Where | Effect |
|---|---|---|
| App ID | Each module's connect form, or `/<module> login` | Identifies the Custom App the module acts as |
| App Secret | Each module's connect form, or `/<module> login` | Signs the token request. Stored encrypted in the credential store |

Because all three modules point at the same Custom App, adding a scope (for example enabling `drive:file:upload`) requires a new released app version and admin approval before that module's actions start working, even though the module is already connected.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Listener connects but no messages ever arrive | The app version is not released, or admin approval is still pending | Ask a workspace admin to approve and release the version in Version Management. The WebSocket connects before approval, but events only flow after it |
| An action fails with a permission or scope error | The needed scope is not enabled, or a new scope was added without a released version | Enable the scope in Permissions & Scopes, create a new version, and get admin approval. Retrying the same call before release does not help |
| Incoming messages never decode or the listener stays silent | An Encryption Key is set on the app's Event Configuration | Clear the Encryption Key. This integration does not support encrypted events |
| Calls fail after roughly two hours, or right after a long idle | The cached tenant_access_token expired | No action needed in normal use. CraftBot refreshes the token automatically within 60 seconds of expiry. If it persists, reconnect the module to mint a fresh token |
| `send_lark_message` fails on an email recipient | The recipient was addressed with the wrong id type | Set the receive id type to email, or resolve the open_id first with `get_lark_user_by_email` |
| One module works but another says not connected | Each module has its own credential and connect state | Connect each module separately with the same App ID and App Secret |

## Next

- [Slack](slack.md): team messaging with a real-time socket listener
- [Google Calendar](google-calendar.md): calendar and events on Google Workspace
- [Credentials](credentials.md): where tokens are stored and how `/cred status` reports them
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
