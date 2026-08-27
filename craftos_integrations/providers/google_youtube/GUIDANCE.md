# YouTube

Search YouTube, manage the user's subscriptions and playlists, post
comments, and rate videos.

## Multi-account
- Every YouTube action accepts an optional `account` (email, nickname, or a
  unique fragment like "work"). Omit it to use the primary account.
- When the user names an account in any form ("my creator account", "the
  work Google account"), pass it as `account` — never silently default to
  primary.
- Subscription and playlist ids are **account-scoped**: a subscription id
  returned by `list_my_youtube_subscriptions` with `account="work"` must be
  used with `account="work"` on the follow-up `unsubscribe_from_youtube_channel`.
- For public-facing actions (posting comments, subscribing) with multiple
  accounts connected and no account named: ask the user which account
  before acting.

## Essentials
- **No event listening.** YouTube will never push new-video / new-comment
  notifications — purely request-response.
- **ID formats are fixed and distinct — don't mix:**
  - video IDs are 11-char strings (e.g. `dQw4w9WgXcQ`)
  - channel IDs are 24-char strings starting with `UC...`
  - playlist IDs start with `PL...` and are usually 34+ chars
  - **subscription IDs ≠ channel IDs**
- **`unsubscribe_from_youtube_channel` takes the SUBSCRIPTION ID,** not the
  channel ID. Get it from `list_my_youtube_subscriptions` (with
  `include_metadata` for the raw resource). Passing a channel ID fails
  server-side.
- **`rate_youtube_video` enum is `like` | `dislike` | `none`.** `"none"` is
  how you clear an existing rating — not deletion.
- **Comments are top-level only.** `post_youtube_comment` does not support
  replies-to-comments. `get_youtube_video_comments` returns top-level
  comments most-recent first; thread expansion is not exposed.
- The user's own channel info is one `get_my_youtube_channel` call away —
  don't ask the user for their channel name or subscriber count.
