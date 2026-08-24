# Google Calendar

Events, free/busy availability, Meet links, calendar sharing and settings.

## Multi-account
- Every Calendar action accepts an optional `account` (email, nickname, or a
  unique fragment like "work"). Omit it to use the primary account.
- When the user names an account in any form ("my school calendar", "the
  work account"), pass it as `account` — never silently default to primary.
- Event and calendar ids are **account-scoped**: an id returned by
  `list_google_calendar_events` with `account="work"` must be used with
  `account="work"` on every follow-up action (get/update/delete/etc.).
  Note `calendar_id="primary"` names a *different* calendar on each account.
- For destructive actions (`delete_google_calendar_event`,
  `delete_google_calendar`, `clear_google_calendar`,
  `delete_google_calendar_acl_rule`) with multiple accounts connected and
  no account named: ask the user which account before acting.

## Behavior
- `calendar_id` defaults to `"primary"` — the connected account's main
  calendar. Don't ask which calendar to use unless the user explicitly
  mentions a shared one. Other calendar IDs are email-like
  (e.g. `team@group.calendar.google.com`); discover them via
  `list_google_calendars`.
- Event IDs are opaque Google strings. Pull them from
  `list_google_calendar_events` / `get_google_calendar_event`; never
  construct them.
- Times are ISO 8601 with timezone (e.g. `2026-05-20T09:00:00-04:00` or
  `...Z`). The integration knows the connected account's email but NOT its
  default timezone — if the user gives a bare time ("3pm"), establish the
  timezone first (`get_google_calendar_setting` with
  `setting_id="timezone"` returns it).
- Recurring events expand on read: `list_google_calendar_events` returns
  expanded single instances, each with its own `id`. Deleting one instance
  does not affect the series; use `list_google_calendar_event_instances`
  to enumerate a series.
- Meet links: use `create_google_meet` (or pass a
  `conferenceData.createRequest` block in `event_data` to
  `create_google_calendar_event`). The returned `hangoutLink` is the share
  URL — never construct meeting URLs by hand.
- No event listening: Calendar never pushes incoming changes. Don't promise
  the user "I'll notify you when X is scheduled."
- The connected account's own email is known to the integration — never ask
  the user for "your email" to invite themselves.
