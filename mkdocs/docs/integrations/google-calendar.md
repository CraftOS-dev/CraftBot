# Google Calendar

The Google Calendar integration lets the agent manage your calendars: it can create and update events, check your availability, generate Google Meet links, and control who a calendar is shared with. You connect once through Google's consent screen, and everything after that runs through the Google Calendar API. There is no listener: Calendar never pushes events to the agent, so every action is a request the agent makes on your behalf.

## Requirements

| Requirement | Details |
|---|---|
| Google account | Any Gmail or Google Workspace account |
| A browser | For the one-time OAuth consent |
| CraftBot running | Connect from **Settings → Integrations** in the browser interface |
| OAuth app | None needed. Release builds embed a CraftOS Google client (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` override it for self-hosted setups) |

## Setup

1. Open **Settings → Integrations** and click **Connect** on the Google Calendar card. You can also run `/google_calendar login` in chat.
2. Your browser opens Google's consent screen. CraftBot requests `calendar` (full read and write access to your calendars and events), plus `userinfo.email` and `userinfo.profile` to record which account is connected.
3. Approve access. Google redirects back to `http://localhost:8765`, where CraftBot exchanges the code for tokens.
4. CraftBot confirms with "Google Calendar connected as *your address*". The credential is saved locally as `gcal.json`.
5. Verify any time with `/google_calendar status` or `/cred status`.

Connecting Google Calendar grants the calendar scope to this credential only. Gmail, Google Drive, Google Docs, and YouTube each have their own card, their own consent screen, and their own credential file. Connecting Calendar does not connect any of the other Google services.

## How it connects

**Authentication.** OAuth 2.0 authorization code flow with PKCE, using the shared CraftOS Google client. Consent is requested with offline access, so CraftBot receives a refresh token along with the access token.

**Token refresh.** Access tokens expire after about an hour. Before each API call CraftBot checks the stored expiry and refreshes the token automatically with the refresh token, writing the new token back to `gcal.json`. You only reconnect if Google revokes the refresh token, for example after a password change.

**No listener.** Calendar does not poll or receive push notifications. The agent reads and writes the calendar only when a task calls for it. To get calendar activity on a schedule, such as a daily agenda, pair it with a scheduled task.

## What the agent can do

All 32 Google Calendar actions, grouped by domain. Each purpose comes from the action's registered description. Every action defaults to your primary calendar unless you pass a `calendar_id`, and times use ISO 8601 with a timezone.

### Events

| Action | Purpose |
|---|---|
| `list_google_calendar_events` | List events on a calendar between two times, expanded to single events and sorted by start time |
| `get_google_calendar_event` | Get a single event by ID |
| `create_google_calendar_event` | Create an event from a full Event resource (summary, start, end, attendees) |
| `update_google_calendar_event` | Replace an event entirely |
| `patch_google_calendar_event` | Update only the supplied fields of an event |
| `delete_google_calendar_event` | Delete an event |
| `move_google_calendar_event` | Move an event from one calendar to another |
| `quick_add_google_calendar_event` | Create an event from a natural-language string like "Lunch with Alice tomorrow at noon" |
| `list_google_calendar_event_instances` | Expand a recurring event into its individual instances |
| `import_google_calendar_event` | Import a pre-existing event with its own iCal UID, preserving identity across calendars |

### Meetings and availability

| Action | Purpose |
|---|---|
| `create_google_meet` | Create a calendar event that includes a Google Meet link |
| `check_calendar_availability` | Check free/busy availability over a time range |
| `check_availability_and_schedule` | Schedule a Meet-enabled meeting only if the time slot is free |

### Calendars

| Action | Purpose |
|---|---|
| `list_google_calendars` | List the calendars you have access to |
| `get_google_calendar` | Get metadata for a single calendar (summary, timezone, description) |
| `create_google_calendar` | Create a new secondary calendar you own |
| `update_google_calendar` | Replace a calendar's metadata |
| `patch_google_calendar` | Update only the supplied metadata fields of a calendar |
| `delete_google_calendar` | Delete a secondary calendar (cannot be used on the primary) |
| `clear_google_calendar` | Delete every event on your primary calendar. Irreversible |

### Calendar list (subscriptions and display)

| Action | Purpose |
|---|---|
| `get_google_calendar_list_entry` | Get your per-calendar settings (color, visibility, display name) |
| `subscribe_google_calendar` | Add an existing calendar to your calendar list by ID |
| `update_google_calendar_list_entry` | Update your per-calendar color, visibility, or display name |
| `unsubscribe_google_calendar` | Remove a calendar from your list without deleting the calendar itself |

### Sharing (ACL)

| Action | Purpose |
|---|---|
| `list_google_calendar_acl` | List who has what access to a calendar |
| `get_google_calendar_acl_rule` | Get a single access rule by ID |
| `add_google_calendar_acl_rule` | Grant access to a user, group, domain, or everyone, at a chosen role |
| `update_google_calendar_acl_rule` | Change the role of an existing access rule |
| `delete_google_calendar_acl_rule` | Revoke access by deleting an access rule |

### Settings and colors

| Action | Purpose |
|---|---|
| `list_google_calendar_settings` | List your Calendar settings (timezone, locale, week start) |
| `get_google_calendar_setting` | Get a single setting by ID (for example `timezone`) |
| `get_google_calendar_colors` | Get the color palette available for calendars and events |

## Example requests

- "What's on my calendar tomorrow?"
- "Schedule a 30-minute sync with alice@example.com on Thursday at 2pm and add a Google Meet link."
- "Check whether I'm free between 1 and 4pm on Friday, and book a design review if I am."
- "Share my primary calendar with my assistant as a reader."
- "Move next Monday's standup to 10am."
- "Every weekday at 7am, send me my agenda for the day on Telegram." Calendar has no listener, so a recurring schedule is how you get a daily digest. See [Scheduling](../core/concepts/scheduling.md).

## Configuration

- **Own OAuth app.** Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` as environment variables to use your own Google Cloud OAuth client instead of the embedded one. See [Credentials](credentials.md).
- **Credential file.** The token lives in `gcal.json` in the local credential store. `/google_calendar logout` removes it. The Google Workspace meta-integration writes this file too when you connect everything at once, so the two stay interchangeable.
- **Default calendar.** Every action targets your primary calendar unless you pass a `calendar_id`. Get IDs for shared and secondary calendars from `list_google_calendars`.
- **No listener.** Calendar never triggers the agent on its own. Use a scheduled task for any recurring calendar work.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Consent completes but CraftBot never confirms | Port `8765` is blocked or in use, so the redirect never arrived | Free the port and run `/google_calendar login` again |
| Actions fail with "No google_calendar credentials" | Not connected, or logged out | Connect from **Settings → Integrations** or run `/google_calendar login` |
| Event lands at the wrong time | A bare time was given without a timezone | Give an ISO 8601 time with an offset, or state the timezone; the account's default timezone is not assumed |
| Deleting one occurrence left the series intact | Recurring events expand into instances, each with its own ID | Delete the series event to remove every occurrence, or delete a single instance to remove one |
| `clear_google_calendar` did nothing on a shared calendar | Clear only affects your primary calendar | Delete the events individually, or delete the secondary calendar |
| Every request fails with 401 after working fine | Google revoked the refresh token (password change, security review) | `/google_calendar logout`, then reconnect |

## Next

- [Gmail](gmail.md): the mail side of the same Google connection flow
- [Google Drive](google-drive.md): manage files and folders on the same account
- [Scheduling](../core/concepts/scheduling.md): recurring agendas and reminders
- [Credentials](credentials.md): where the token lives and how refresh works
