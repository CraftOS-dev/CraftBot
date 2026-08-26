# Google Calendar — Integration Reference

Schedule events, check free/busy, and create Google Meet links on the user's Google Calendar. Part of the Google Workspace bundle (shares OAuth shape with `gmail`, `google_drive`, `google_docs`).

## Essentials

- **No event listening.** `supports_listening = False`. Calendar will never push incoming changes. Don't promise the user "I'll notify you when X is scheduled."
- **`calendar_id` defaults to `"primary"`** — the connected user's main calendar. Don't ask which calendar to use unless the user explicitly mentions a shared one. Other calendar IDs are email-like (e.g. `team@group.calendar.google.com`); list them via `list_calendars`.
- **Event IDs are opaque Google strings.** Pull from `list_events` / `get_event`; never construct.
- **Times are ISO 8601 with timezone** (e.g. `2026-05-20T09:00:00-04:00` or `...Z`). The integration knows the user's email (`cred.email`) but NOT their default timezone — if the user gives a bare time ("3pm"), the router must establish the timezone first.
- **Recurring events expand on read.** `list_events` returns `singleEvents=true`-expanded instances, each with its own `id`. Deleting one instance does not affect the series.
- **Meet links require `with_video_meeting=True`** on create (or a `conferenceData.createRequest` block). The returned `meetLink` is the share URL; don't construct meeting URLs by hand.
- **Session-level facts:** `cred.email` is the connected account. Never ask the user for "your email" to invite themselves.
