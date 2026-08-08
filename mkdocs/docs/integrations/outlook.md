# Outlook

The Outlook integration gives the agent your Microsoft 365 or Outlook.com mailbox: it can read, search, send, and organize email, and it is notified when new mail arrives. You connect once through Microsoft's sign-in screen, and everything after that runs through the Microsoft Graph API. This integration covers mail only. It does not touch your Outlook calendar, OneDrive files, or contacts.

## Requirements

| Requirement | Details |
|---|---|
| Microsoft account | Any Microsoft 365 work/school account or personal Outlook.com account |
| A browser | For the one-time OAuth consent |
| CraftBot running | Connect from **Settings → Integrations** in the browser interface |
| OAuth app | None needed. Release builds embed a CraftOS Microsoft client. Self-hosted setups set `OUTLOOK_CLIENT_ID` (a public client, PKCE, no client secret) |

## Setup

1. Open **Settings → Integrations** and click **Connect** on the Outlook card. You can also run `/outlook login` in chat.
2. Your browser opens Microsoft's sign-in screen. CraftBot requests five scopes: `Mail.Read` and `Mail.ReadWrite` (read and organize mail), `Mail.Send` (send mail), `User.Read` (read your profile and address), and `offline_access` (keep the connection alive without re-consent).
3. Approve access. Microsoft redirects back to `http://localhost:8765`, where CraftBot exchanges the code for tokens.
4. CraftBot confirms with "Outlook connected as *your address*". The credential is saved locally as `outlook.json`.
5. Verify any time with `/outlook status` or `/cred status`.

The embedded CraftOS client is multi-tenant, so both work/school accounts and personal Microsoft accounts sign in through the same card. Mail you send always comes from the connected account and cannot be spoofed.

## How it connects

**Authentication.** OAuth 2.0 authorization code flow with PKCE, using a Microsoft public client (a client ID only, no client secret). `offline_access` returns a refresh token along with the access token.

**Token refresh.** Microsoft access tokens are short-lived. Before each API call CraftBot checks the stored expiry and refreshes the token automatically, 60 seconds before it lapses, writing the new token back to `outlook.json`. A single 401 usually means a token just expired and is being refreshed, so retry before reconnecting. Only reconnect if 401s persist across retries.

**Listener.** Outlook polls for new mail. A loop queries Graph every 5 seconds for messages received since the last check, ordered by receive time. Each new message from someone else is delivered to the agent as a platform message carrying the sender, subject, and preview. In practice this means new mail can wake the agent: an incoming email enters the same trigger queue as a chat message, and the agent can read it, act on it, or deliberately ignore it. Mail you sent yourself is filtered out by matching the sender against your own address. If a poll fails, the listener waits 10 seconds and retries, refreshing the token first if the error was a 401.

## What the agent can do

All 40 Outlook actions, grouped by domain. Each purpose comes from the action's registered description.

### Mail

| Action | Purpose |
|---|---|
| `send_outlook_email` | Send an email via Outlook |
| `list_outlook_emails` | List recent emails from the Outlook inbox, optionally unread only |
| `get_outlook_email` | Get full details of a message by ID; the body is plain text by default, or HTML with `include_metadata` |
| `read_top_outlook_emails` | Read the top N recent emails with details, optionally including full bodies |
| `search_outlook_emails` | Search messages by free-text query across subject, body, and attachments, sorted by relevance |
| `reply_outlook_email` | Reply to the sender of a message. Sent immediately |
| `reply_all_outlook_email` | Reply-all to a message. Sent immediately |
| `forward_outlook_email` | Forward a message to other recipients |

### Drafts

| Action | Purpose |
|---|---|
| `create_outlook_draft` | Create a new email draft (not sent); returns the `draft_id` for later editing and sending |
| `create_outlook_reply_draft` | Create a draft reply pre-populated with the quoted original |
| `create_outlook_forward_draft` | Create a draft forward pre-populated with the quoted original |
| `update_outlook_draft` | Edit a draft's subject, body, or recipients before sending |
| `send_outlook_draft` | Send a previously created draft |

### Organizing messages

| Action | Purpose |
|---|---|
| `delete_outlook_email` | Permanently delete a message; move it to `deleteditems` instead for a soft delete |
| `move_outlook_email` | Move a message to another folder (well-known name or folder ID) |
| `copy_outlook_email` | Copy a message to another folder, leaving the original in place |
| `mark_outlook_email_read` | Mark a message as read |
| `mark_outlook_email_unread` | Mark a message as unread |
| `flag_outlook_email` | Set the flag status on a message (`notFlagged`, `flagged`, or `complete`) |
| `set_outlook_email_categories` | Replace the categories assigned to a message |

### Attachments

| Action | Purpose |
|---|---|
| `list_outlook_attachments` | List attachments on a message |
| `download_outlook_attachment` | Download a file attachment to a local path |
| `add_outlook_attachment` | Attach a local file (under 3 MB) to a draft message |
| `delete_outlook_attachment` | Remove an attachment from a draft |

### Folders

| Action | Purpose |
|---|---|
| `list_outlook_folders` | List mail folders |
| `get_outlook_folder` | Get metadata for a single folder (counts, parent) |
| `create_outlook_folder` | Create a new mail folder, top-level by default |
| `update_outlook_folder` | Rename a mail folder |
| `delete_outlook_folder` | Delete a mail folder and every message in it |
| `list_outlook_child_folders` | List the child folders of a folder |
| `list_outlook_folder_messages` | List messages in a specific folder |

### Mailbox settings, rules, and categories

| Action | Purpose |
|---|---|
| `get_outlook_mailbox_settings` | Get mailbox settings (timezone, language, working hours, auto-reply status) |
| `get_outlook_automatic_replies` | Get the current out-of-office / automatic reply settings |
| `update_outlook_automatic_replies` | Set the out-of-office reply (`disabled`, `alwaysEnabled`, or `scheduled`) |
| `list_outlook_inbox_rules` | List server-side inbox rules |
| `create_outlook_inbox_rule` | Create an inbox rule from Graph condition and action objects |
| `delete_outlook_inbox_rule` | Delete an inbox rule |
| `list_outlook_categories` | List the master categories (color-coded tags for messages) |
| `create_outlook_category` | Create a master category with a preset color |
| `delete_outlook_category` | Delete a master category |

## Example requests

- "Summarize my unread Outlook mail from today."
- "Reply to the latest message from Priya and let her know the deck is attached."
- "File every message from billing@contoso.com into a Receipts folder and flag anything with an invoice."
- "Set my out-of-office to 'Back Monday' from Friday 5pm to Monday 9am."
- "Every weekday at 8am, send me a digest of my unread Outlook inbox on Telegram." This creates a recurring schedule that fires a task each morning. See [Scheduling](../core/concepts/scheduling.md).
- "When mail from my manager arrives, draft a reply and show it to me before sending." The 5-second listener makes this possible: the incoming email itself triggers the agent.

## Configuration

- **Own OAuth app.** Set `OUTLOOK_CLIENT_ID` as an environment variable to use your own Azure app registration instead of the embedded client. Register it as a public client (Mobile and desktop applications platform) with redirect URI `http://localhost:8765`, add the Microsoft Graph delegated permissions `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`, `User.Read`, and `offline_access`, and make it multi-tenant if you sign in with a personal account. No client secret is used. See [Credentials](credentials.md).
- **Credential file.** The token lives in `outlook.json` in the local credential store. `/outlook logout` removes it.
- **Incoming mail.** While Outlook is connected, the listener forwards every new message from another sender to the agent. Disconnect the integration to stop it.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Consent completes but CraftBot never confirms | Port `8765` is blocked or in use, so the redirect never arrived | Free the port and run `/outlook login` again |
| Sign-in fails with `AADSTS9002313` or a tenant error | Your own app is registered single-tenant but you signed in with a personal account | Switch the Azure app to multi-tenant, or use the embedded client |
| Actions fail with "No Outlook credentials" | Not connected, or logged out | Connect from **Settings → Integrations** or run `/outlook login` |
| Agent does not react to new mail | Outlook is disconnected, or the listener hit an error | Check `/outlook status`, then check `logs/` for `[OUTLOOK]` entries |
| `download_outlook_attachment` returns a `contentBytes` error | The attachment is an item or reference attachment, not a file attachment | Only file attachments can be saved to disk; open the referenced item instead |
| Every request fails with 401 after working fine | The refresh token expired or was revoked (password change, admin action) | `/outlook logout`, then reconnect |

## Next

- [Gmail](gmail.md): the same mailbox capabilities on a Google account
- [Google Calendar](google-calendar.md): schedule events and check availability
- [Scheduling](../core/concepts/scheduling.md): recurring email digests and reminders
- [Credentials](credentials.md): where the token lives and how refresh works
