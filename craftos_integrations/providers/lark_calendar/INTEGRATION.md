# Lark Calendar — Integration Reference

Lark Calendar via the same Custom App as `lark` and `lark_drive`. Events, free/busy, attendees, and auto-generated Lark Meetings.

## Essentials

- **No event listening.** `supports_listening = False`. Calendar changes are not pushed — request-response only.
- **`calendar_id` defaults to `"primary"`** (the connected bot's own calendar). Don't ask for a calendar ID unless the user mentions a shared one — list via `list_lark_calendars` only when needed.
- **Event and calendar IDs are opaque Lark strings.** Always discover via `list_lark_calendars` / `list_lark_calendar_events`; never construct.
- **Times are Unix seconds (int).** The API wire format wraps them as `{"timestamp": "1730000000"}` (stringified) — the client does the conversion. The router just passes Unix seconds.
- **Attendees are a separate call after `create_lark_calendar_event`.** Use `add_lark_event_attendees` afterward — `create_lark_calendar_event` does NOT accept attendees in its body. Attendees accept mixed types in one call: `user_ids` (Lark open_ids), `emails` (external), `chat_ids` (invites all group members).
- **`with_video_meeting=True`** auto-attaches a Lark Meeting URL to the event.
- **App-approval gotcha:** if the tenant admin hasn't approved the Custom App, the endpoints often still answer 200 but no events sync. If the user reports "the agent doesn't see my Lark calendar," tell them to check admin approval before retrying.
- **Same Custom App as `lark` / `lark_drive`** — App ID + Secret are pasted into each service separately (independent connect/disconnect tiles).
