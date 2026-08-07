# WhatsApp Web

The WhatsApp Web integration connects the agent to your personal WhatsApp account by linking it as a device, the same way the WhatsApp Web client does. You scan a QR code once, and the agent can send and receive messages, manage chats and groups, and work with contacts. There are no API keys and no Meta app setup. For the official Cloud API route, see [WhatsApp Business](whatsapp-business.md).

## Requirements

| Requirement | Details |
|---|---|
| WhatsApp account | A phone with an active WhatsApp account to link the device |
| Node.js 18 or newer | The integration runs a Node bridge built on `whatsapp-web.js` |
| Chromium | Installed automatically with the bridge; the bridge drives a headless Chromium through Puppeteer |
| Phone reachable at link time | You scan the QR from **WhatsApp → Linked devices** on your phone |

## Setup

1. Install Node.js 18 or newer and confirm `node --version` reports 18 or higher.
2. Run `/whatsapp_web login`. On first run CraftBot installs the bridge dependencies (`npm install` inside the integration folder), then starts the bridge and shows a QR code.
3. On your phone, open **WhatsApp → Linked devices → Link a device** and scan the QR code before it rotates.
4. Wait for the bridge to report the session is ready. CraftBot stores the linked session and the connected phone.
5. Verify with `/whatsapp_web status`. It shows the connected account and whether the session is live.

`/whatsapp_web logout` unlinks the session and stops the bridge.

## How it connects

**Authentication.** There are no keys. Linking the device produces a session that `whatsapp-web.js` persists on disk under `.credentials/whatsapp_wwebjs_auth/`, so the agent reconnects on later runs without a new scan. If your phone ends the linked-device session, you scan again. See [Credentials](credentials.md).

**Realtime listener.** The bridge is a Node subprocess that wraps `whatsapp-web.js` and exchanges JSON lines with CraftBot. It pushes new messages to the agent in real time as they arrive, so there is no polling interval. Shortly after the session becomes ready the bridge emits a catchup of unread chats. The bridge starts with the agent and takes a few seconds to become ready; calls made before then report that the client is not ready.

**Single account.** One linked session runs at a time. The bridge already knows the linked account's own phone, display name, and identity, so the agent looks those up rather than asking you. A self-send shortcut lets the agent message your own number without a lookup.

## What the agent can do

The 40 WhatsApp Web actions are grouped into action sets the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Sending messages

| Action | Purpose |
|---|---|
| `send_whatsapp_web_text_message` | Send a text message |
| `send_whatsapp_web_media_message` | Send an image, video, audio, or document, with sticker, voice, or document overrides |
| `send_whatsapp_location` | Send a location pin |

### Message actions

| Action | Purpose |
|---|---|
| `reply_whatsapp_message` | Quote-reply to a specific message |
| `edit_whatsapp_message` | Edit a sent message within WhatsApp's edit window (about 15 minutes) |
| `delete_whatsapp_message` | Delete a message, optionally for everyone within the recall window |
| `forward_whatsapp_message` | Forward a message to another chat |
| `react_to_whatsapp_message` | Add or remove an emoji reaction on a message |
| `star_whatsapp_message` | Star or unstar a message |
| `download_whatsapp_message_media` | Download an attached image, video, audio, or document to a local path |
| `get_whatsapp_quoted_message` | Get the message that a reply is quoting |
| `send_whatsapp_typing_state` | Show typing or recording state in a chat |

### Chats

| Action | Purpose |
|---|---|
| `get_whatsapp_chat_history` | Get a chat's message history |
| `get_whatsapp_unread_chats` | List chats with unread messages |
| `mark_whatsapp_chat_read` | Mark a chat as read and send read receipts |
| `mark_whatsapp_chat_unread` | Flag a chat as unread for follow-up |
| `archive_whatsapp_chat` | Archive or unarchive a chat |
| `pin_whatsapp_chat` | Pin or unpin a chat |
| `mute_whatsapp_chat` | Mute or unmute a chat, optionally until a set time |
| `clear_whatsapp_chat_messages` | Clear all messages in a chat locally, keeping the chat |
| `delete_whatsapp_chat` | Delete a chat locally |

### Groups

| Action | Purpose |
|---|---|
| `create_whatsapp_group` | Create a group from phone numbers or identities |
| `add_whatsapp_group_participants` | Add participants to a group (requires admin) |
| `remove_whatsapp_group_participants` | Remove participants from a group (requires admin) |
| `promote_whatsapp_group_participants` | Promote participants to admin (requires admin) |
| `demote_whatsapp_group_participants` | Remove admin status from participants (requires admin) |
| `set_whatsapp_group_subject` | Change a group's name or subject |
| `set_whatsapp_group_description` | Change a group's description |
| `get_whatsapp_group_info` | Get a group's name, description, owner, and participants |
| `leave_whatsapp_group` | Leave a group |
| `get_whatsapp_group_invite_code` | Get a group's invite code and `chat.whatsapp.com` URL (requires admin) |
| `revoke_whatsapp_group_invite` | Invalidate the current invite link and generate a new one (requires admin) |
| `accept_whatsapp_group_invite` | Join a group by invite code or URL |

### Contacts

| Action | Purpose |
|---|---|
| `search_whatsapp_contact` | Search a contact by name |
| `get_whatsapp_contact` | Get full contact details (name, business flag, status) |
| `get_whatsapp_all_contacts` | List all contacts, saved contacts only by default |
| `get_whatsapp_profile_pic_url` | Get a contact's profile picture URL |
| `block_whatsapp_contact` | Block or unblock a contact |
| `check_number_on_whatsapp` | Check whether a phone number is registered on WhatsApp |

### Session

| Action | Purpose |
|---|---|
| `get_whatsapp_web_session_status` | Get session status and the linked account's phone, name, and identity |

## Example requests

```
Send a WhatsApp message to Mom saying I'll be home by 7.
```

```
Message myself on WhatsApp with today's meeting notes.
```

```
Send the file report.pdf to the Project Team group on WhatsApp.
```

```
List my unread WhatsApp chats and summarize each in one line.
```

```
Create a WhatsApp group called Weekend Trip with Alex and Sam.
```

```
Download the image from the last message in my chat with Dad.
```

## Configuration

Open **Settings → Integrations → WhatsApp**. One knob is available.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Self-messages only (`self_messages_only`) | checkbox | off | When on, the agent only receives messages you send to yourself in the WhatsApp self-chat. Incoming DMs and group messages are dropped before reaching the agent, so WhatsApp acts as a private command channel |

Send actions still work for any recipient regardless of this setting. It filters only what reaches the agent as an event.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "WhatsApp bridge not available" or bridge fails to start | Node.js is missing or older than 18 | Install Node.js 18 or newer and run `/whatsapp_web login` again |
| QR expired before you scanned | The WhatsApp Web QR rotates about once a minute | Run `/whatsapp_web login` again and scan promptly |
| "Client not ready" on a send or read | The bridge is still starting or is waiting for a QR scan | Wait for the session to report ready, or scan the QR; do not retry in a loop |
| Session drops and asks for a new scan | Your phone ended the linked-device session | Run `/whatsapp_web login` and scan again |
| "Number X is not on WhatsApp" after a contact search | A stored identity suffix was stripped before sending | Send to the exact value returned by `search_whatsapp_contact` |
| Sends to unknown contacts start failing | WhatsApp rate-limits accounts that message many cold contacts | Slow down and avoid bulk-messaging people who have not messaged you |

## Next

- [WhatsApp Business](whatsapp-business.md): the official Cloud API route with Meta credentials
- [Credentials](credentials.md): where the linked session is stored and how `/cred status` reports it
- [Triggers](../core/concepts/triggers.md): how incoming messages become tasks
