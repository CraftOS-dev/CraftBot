# Gmail

The Gmail integration gives the agent your mailbox: it can read, search, send, and organize email, and it is notified when new mail arrives. You connect once through Google's consent screen, and everything after that runs through the Gmail API.

## Requirements

| Requirement | Details |
|---|---|
| Google account | Any Gmail or Google Workspace account |
| A browser | For the one-time OAuth consent |
| CraftBot running | Connect from **Settings → Integrations** in the browser interface |
| OAuth app | None needed. Release builds embed a CraftOS Google client (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` override it for self-hosted setups) |

## Setup

1. Open **Settings → Integrations** and click **Connect** on the Gmail card. You can also run `/gmail login` in chat.
2. Your browser opens Google's consent screen. CraftBot requests three scopes: `gmail.modify` (read, send, and organize mail), plus `userinfo.email` and `userinfo.profile` (to record which account is connected).
3. Approve access. Google redirects back to `http://localhost:8765`, where CraftBot exchanges the code for tokens.
4. CraftBot confirms with "Gmail connected as *your address*". The credential is saved locally as `gmail.json`.
5. Verify any time with `/gmail status` or `/cred status`.

Connecting Gmail grants mail scopes only. Google Calendar, Drive, Docs, and YouTube each have their own card, their own consent, and their own credential file.

## How it connects

**Authentication.** OAuth 2.0 authorization code flow with PKCE, using the shared CraftOS Google client. Consent is requested with offline access, so CraftBot receives a refresh token along with the access token.

**Token refresh.** Access tokens expire after about an hour. Before each API call CraftBot checks the stored expiry and refreshes the token automatically with the refresh token, writing the new token back to `gmail.json`. You only reconnect if Google revokes the refresh token, for example after a password change.

**Listener.** Gmail is the only Google integration that listens for events. A polling loop checks Gmail's history API every 5 seconds for messages newly added to your inbox. Each new message from someone else is delivered to the agent as a platform message carrying the sender, subject, and snippet. In practice this means new mail can wake the agent: an incoming email enters the same trigger queue as a chat message, and the agent can read it, act on it, or deliberately ignore it. Mail you sent yourself is skipped. If a poll fails, the listener retries after 10 seconds and re-syncs its position in the history feed.

## What the agent can do

All 34 Gmail actions, grouped by domain. Each purpose comes from the action's registered description.

### Messages

| Action | Purpose |
|---|---|
| `send_gmail` | Send an email via Gmail |
| `list_gmail` | List recent emails from the Gmail inbox |
| `get_gmail` | Get details of a specific message by ID; with `full_body=true` includes body text and an attachments list |
| `read_top_emails` | Read the top N recent emails with details |
| `search_gmail` | Search Gmail using Gmail's `q` syntax (e.g. `from:alice subject:invoice newer_than:7d has:attachment`) |
| `reply_gmail` | Reply to a message, preserving thread and In-Reply-To/References headers; `reply_all=true` also CCs the original To/Cc |
| `forward_gmail` | Forward a message to another address |
| `modify_gmail_labels` | Add/remove labels on a message (common IDs: INBOX, UNREAD, STARRED, IMPORTANT, TRASH, SPAM) |
| `trash_gmail` | Move a message to Trash (soft delete; recoverable for 30 days) |
| `untrash_gmail` | Recover a message from Trash |
| `delete_gmail` | Permanently delete a message. Irreversible; prefer `trash_gmail` |
| `batch_modify_gmail` | Bulk add/remove labels across multiple messages in one call |
| `batch_delete_gmail` | Permanently delete multiple messages. Irreversible |

### Threads

| Action | Purpose |
|---|---|
| `list_gmail_threads` | List conversation threads |
| `get_gmail_thread` | Get a thread and its messages |
| `modify_gmail_thread_labels` | Add/remove labels on every message in a thread |
| `trash_gmail_thread` | Move an entire thread to Trash |
| `untrash_gmail_thread` | Recover a thread from Trash |
| `delete_gmail_thread` | Permanently delete a thread (all messages). Irreversible |

### Drafts

| Action | Purpose |
|---|---|
| `list_gmail_drafts` | List drafts |
| `get_gmail_draft` | Get a draft by ID |
| `create_gmail_draft` | Create a draft (not sent); returns the draft ID for later edit/send |
| `update_gmail_draft` | Replace a draft's content (all fields required) |
| `send_gmail_draft` | Send a previously created draft |
| `delete_gmail_draft` | Permanently delete a draft |

### Labels

| Action | Purpose |
|---|---|
| `list_gmail_labels` | List all labels (system and user) |
| `get_gmail_label` | Get a single label by ID |
| `create_gmail_label` | Create a new user label, with optional colors and visibility |
| `update_gmail_label` | Update (rename / recolor) a label |
| `delete_gmail_label` | Delete a label (also removes it from all messages and threads) |

### Attachments and profile

| Action | Purpose |
|---|---|
| `download_gmail_attachment` | Download an attachment to a local path (get IDs from `get_gmail` with `full_body=true`) |
| `get_gmail_profile` | Get the connected account's profile: email address, message/thread totals, history ID |

### Google Workspace wrappers

Two generic email actions are registered alongside the Gmail set and route through the same client.

| Action | Purpose |
|---|---|
| `send_google_workspace_email` | Send email via Google Workspace |
| `read_recent_google_workspace_emails` | Read recent emails |

## Example requests

- "Summarize my unread email from this week."
- "Reply to the latest message from Alice and confirm that Thursday works."
- "Find every email with an invoice attachment from the last 30 days and download the attachments to my workspace."
- "Create a Newsletters label, apply it to everything from newsletters@example.com, and archive those messages."
- "Every weekday at 8am, send me a digest of my unread inbox on Telegram." This creates a recurring schedule that fires a task each morning. See [Scheduling](../core/concepts/scheduling.md).
- "When an email from my landlord arrives, draft a reply and show it to me before sending." The 5-second listener makes this possible: the incoming email itself triggers the agent.

## Configuration

- **Auto-process incoming emails.** A checkbox on the Gmail integration card, stored as `process_incoming` in `gmail_config.json` (default on). When on, every new inbox message is forwarded to the agent. Turn it off to make Gmail effectively send-only: the listener keeps the connection alive, but incoming mail no longer reaches the agent.
- **Own OAuth app.** Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` as environment variables to use your own Google Cloud OAuth client instead of the embedded one. See [Credentials](credentials.md).
- **Credential file.** The token lives in `gmail.json` in the local credential store. `/gmail logout` removes it. The Google Workspace meta-integration writes the same file when you connect everything at once, so the two stay interchangeable.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Consent completes but CraftBot never confirms | Port `8765` is blocked or in use, so the redirect never arrived | Free the port and run `/gmail login` again |
| Actions fail with "No gmail credentials" | Not connected, or logged out | Connect from **Settings → Integrations** or run `/gmail login` |
| Agent does not react to new mail | **Auto-process incoming emails** is off, or the listener hit an error | Check the toggle on the integration card, then check `logs/` for `[GMAIL]` entries |
| `delete_gmail` returns a permissions error | Permanent deletion needs a broader scope than `gmail.modify` | Use `trash_gmail` instead (recoverable for 30 days) |
| Every request fails with 401 after working fine | Google revoked the refresh token (password change, security review) | `/gmail logout`, then reconnect |

## Next

- [Google Calendar](google-calendar.md): the calendar side of the same Google connection flow
- [Scheduling](../core/concepts/scheduling.md): recurring email digests and reminders
- [Credentials](credentials.md): where the token lives and how refresh works
