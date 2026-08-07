# YouTube

The YouTube integration lets the agent search YouTube, read your channel and subscriptions, manage playlists, rate videos, and post comments. You connect once through Google's consent screen, and everything after that runs through the YouTube Data API. There is no listener: YouTube never pushes new-video or new-comment events to the agent, so every action is a request the agent makes on your behalf.

## Requirements

| Requirement | Details |
|---|---|
| Google account | Any Google account with a YouTube channel |
| A browser | For the one-time OAuth consent |
| CraftBot running | Connect from **Settings → Integrations** in the browser interface |
| OAuth app | None needed. Release builds embed a CraftOS Google client (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` override it for self-hosted setups) |

## Setup

1. Open **Settings → Integrations** and click **Connect** on the YouTube card. You can also run `/google_youtube login` in chat.
2. Your browser opens Google's consent screen. CraftBot requests `youtube.readonly` (read your channel, subscriptions, and playlists) and `youtube.force-ssl` (subscribe, rate, and comment), plus `userinfo.email` and `userinfo.profile` to record which account is connected.
3. Approve access. Google redirects back to `http://localhost:8765`, where CraftBot exchanges the code for tokens.
4. CraftBot confirms with "YouTube connected as *your address*". The credential is saved locally as `youtube.json`.
5. Verify any time with `/google_youtube status` or `/cred status`.

Connecting YouTube grants the YouTube scopes to this credential only. Gmail, Google Calendar, Google Docs, and Google Drive each have their own card, their own consent screen, and their own credential file. Connecting one Google service does not connect the others.

## How it connects

**Authentication.** OAuth 2.0 authorization code flow with PKCE, using the shared CraftOS Google client. Consent is requested with offline access, so CraftBot receives a refresh token along with the access token.

**Token refresh.** Access tokens expire after about an hour. Before each API call CraftBot checks the stored expiry and refreshes the token automatically with the refresh token, writing the new token back to `youtube.json`. You only reconnect if Google revokes the refresh token, for example after a password change.

**No listener.** YouTube does not poll or receive push notifications. The agent reads channels and posts comments only when a task calls for it.

## What the agent can do

All 11 YouTube actions, grouped by domain. Each purpose comes from the action's registered description.

### Channel and search

| Action | Purpose |
|---|---|
| `get_my_youtube_channel` | Return the authenticated user's YouTube channel info (id, title, subscriber and view counts) |
| `search_youtube` | Search YouTube for videos, channels, or playlists. Lean results by default; set `include_metadata` for raw results |
| `get_youtube_video` | Get full metadata for a YouTube video (snippet, statistics, content details) |

### Subscriptions

| Action | Purpose |
|---|---|
| `list_my_youtube_subscriptions` | List the channels the authenticated user is subscribed to. Set `include_metadata` for the subscription ID used by unsubscribe |
| `subscribe_to_youtube_channel` | Subscribe the authenticated user to a YouTube channel |
| `unsubscribe_from_youtube_channel` | Remove a YouTube subscription. Takes the subscription ID from `list_my_youtube_subscriptions`, not the channel ID |

### Playlists

| Action | Purpose |
|---|---|
| `list_my_youtube_playlists` | List playlists owned by the authenticated user. Lean results by default; set `include_metadata` for raw results |
| `list_youtube_playlist_items` | List videos in a YouTube playlist. Lean results by default; set `include_metadata` for raw results |

### Ratings and comments

| Action | Purpose |
|---|---|
| `rate_youtube_video` | Like, dislike, or clear your rating on a YouTube video |
| `post_youtube_comment` | Post a top-level comment on a YouTube video |
| `get_youtube_video_comments` | Get top-level comments on a YouTube video, most recent first. Set `include_metadata` for raw commentThread resources |

## Example requests

- "Search YouTube for recent videos about Rust async and give me the top five with links."
- "How many subscribers does my channel have right now?"
- "Subscribe me to the channel behind that video you just found."
- "List the videos in my Watch Later playlist and summarize what they cover."
- "Like the video I linked and post a comment thanking the creator."
- "Show me the most recent comments on my latest upload."

## Configuration

- **Own OAuth app.** Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` as environment variables to use your own Google Cloud OAuth client instead of the embedded one. See [Credentials](credentials.md).
- **Credential file.** The token lives in `youtube.json` in the local credential store. `/google_youtube logout` removes it. The Google Workspace meta-integration writes this file too when you connect everything at once, so the two stay interchangeable.
- **Comment scope.** Comments are top-level only. `post_youtube_comment` does not reply to another comment, and `get_youtube_video_comments` returns top-level comments without expanding their reply threads.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Consent completes but CraftBot never confirms | Port `8765` is blocked or in use, so the redirect never arrived | Free the port and run `/google_youtube login` again |
| Actions fail with "No google_youtube credentials" | Not connected, or logged out | Connect from **Settings → Integrations** or run `/google_youtube login` |
| `unsubscribe_from_youtube_channel` fails server-side | A channel ID was passed instead of a subscription ID | Get the subscription ID from `list_my_youtube_subscriptions` with `include_metadata`, then unsubscribe with that |
| Clearing a rating does nothing | `rate_youtube_video` clears a rating with the `none` value, not by deletion | Ask the agent to set the rating to `none` |
| Every request fails with 401 after working fine | Google revoked the refresh token (password change, security review) | `/google_youtube logout`, then reconnect |

## Next

- [Google Drive](google-drive.md): manage files with the same Google connection flow
- [Gmail](gmail.md): the mail side of the same Google connection flow
- [Credentials](credentials.md): where the token lives and how refresh works
