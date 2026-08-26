# WhatsApp Web — Integration Reference

Operational notes the action schemas can't fit. Grep here before asking the user.

## Essentials

Routing-time guidance — these are the rules that the agent loses sight of most often. Read these *before* deciding what to do.

- **The bridge knows the logged-in user's own phone, name, and JID.** Never ask the user for them — call `get_whatsapp_web_session_status` to look them up. Required for any "send to my WhatsApp" / "message myself" request.
- **Self-send shortcut:** `to: "user"` (also `"me"`, `"self"`, `"owner"`) is auto-resolved to the owner's phone by the integration. No lookup needed.
- **Sending by name (not number):** call `search_whatsapp_contact` first, then pass the result's `number` field **verbatim** as `to` in `send_whatsapp_web_text_message`. Do NOT strip `@lid` or `@c.us` suffixes — they're part of valid JIDs.
- **Identity formats:** both `<phone>@c.us` and `<id>@lid` are valid JIDs. The bare `<id>` part of a `@lid` JID is **not** a phone number and must not be dialled or sent to `getNumberId`.
- **Common errors:** `Number X is not on WhatsApp` after a search → you stripped a JID suffix; pass it back exactly as the search returned it. `Client not ready` → bridge is starting or waiting for a QR scan; surface to the user, don't retry blindly.

## Architecture

A Node subprocess (`bridge.js`) speaks WhatsApp's WebSocket protocol via Baileys (no browser) and talks to the Python side over stdin/stdout JSON lines. Commands like `send_message`, `search_contact`, `get_chat_messages` map 1:1 to bridge cases. Errors surface back as `{success: false, error: "..."}`.

## Session-level facts the bridge already knows

Once `Client ready` fires, the bridge knows everything about the logged-in account. **Never ask the user for any of this** — call `get_whatsapp_web_session_status` instead:

- `owner_phone` — the user's own phone number (E.164 without `+`), e.g. `"447417378160"`.
- `owner_name` — the user's WhatsApp display name (pushname).
- `wid` — the user's full JID (`<phone>@c.us` or `<id>@lid`).
- `ready` — whether the session is actually live; `false` means QR scan pending or bridge starting up.

Send-to-self works with either `to: "user"` (magic value) or `to: <owner_phone>`.

## Identity formats — `@c.us` vs `@lid`

WhatsApp uses two JID shapes:

- `<phone>@c.us` — phone-based. The `<phone>` part is a dialable number (E.164 without `+`).
- `<lid_user>@lid` — LID (Linked ID) based. The `<lid_user>` part is an **opaque numeric ID**, NOT a phone number. You cannot dial it, and you cannot resolve it via `getNumberId`. It's only meaningful as a full JID.

Modern WhatsApp creates `@lid` identities for many contacts. `search_whatsapp_contact` will return them when applicable.

## Canonical workflows

### Send a message by name (no number known)

1. Call `search_whatsapp_contact` with `name`.
2. Pick the best match from `contacts[]`.
3. Pass the match's `number` field **verbatim** as `to` in `send_whatsapp_web_text_message`.
   - Do NOT strip `@lid` or `@c.us` suffixes.
   - Do NOT keep only the digits.
   - The bridge routes anything containing `@` straight through to the send path (legacy `@c.us` jids are converted to `@s.whatsapp.net`).

### Send a message by phone number

Pass the phone number directly (e.g. `"447417378160"`). The bridge runs `getNumberId` server-side to resolve and verify. Returns `Number X is not on WhatsApp` if the number isn't registered.

### Search

`search_whatsapp_contact` searches **chats first** (fast, covers anyone you've messaged) and falls back to an in-page filter against `window.Store.Contact` if zero chat matches. Either way, the result shape is `{id, name, number, is_group}`.

For LID-based results, both `id` and `number` are the full `xxx@lid` JID — the bridge never returns a bare LID user portion, because that's not a usable identifier anywhere.

## Known errors

| Error | What it means | Fix |
|---|---|---|
| `Number X is not on WhatsApp` | Either a wrong number, OR you stripped a JID suffix you shouldn't have. | Re-check that `to` is the exact `number` value from `search_whatsapp_contact`. |
| `Number X is not on WhatsApp` | The bridge couldn't resolve a bare phone number. | Use the JID from `search_whatsapp_contact` instead of constructing one locally. |
| `Client not ready` | Bridge is starting up or waiting for a QR scan. | Wait for the `ready` event, or have the user scan the QR. |
| `Command 'search_contact' timed out` | Historical — the old code called `getContacts()` which round-tripped every contact across RPC. Fixed by chat-first search. | Should not happen on current code. If it does, the bridge is stuck. |

## Group chats

- Group JIDs end in `@g.us` (e.g. `<group_id>@g.us`). They appear in `search_whatsapp_contact` results with `is_group: true`.
- Sending to a group is the same call as sending to a person: pass the group JID as `to` in `send_whatsapp_web_text_message`.
- `get_whatsapp_chat_history` works on group JIDs too — same `phone_number` arg accepts either a phone or a JID.

## Quirks

- The bridge restarts with the agent. There's a startup window (typically <10s after the agent boots) before `Client ready` fires. Calls before then return `Client not ready`.
- `Catchup complete: N unread chat(s)` fires shortly after `ready`. The unread list is emitted as a `catchup` event, not a return value — wait for it if you need fresh unread state on boot.
- `to: "user"` is a magic value some send actions accept that means "send to yourself" (the WhatsApp account's own number). It's not a contact lookup.
- There is **no built-in rate limit** on the bridge. WhatsApp itself will block accounts that send to many unknown contacts in a short window — don't bulk-send to cold contacts.
- If the user is disconnected (`ready: false`), retrying a send won't help — the user needs to re-scan a QR. Surface that clearly rather than retrying in a loop.
