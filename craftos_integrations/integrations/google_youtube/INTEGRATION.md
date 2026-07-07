# YouTube — Integration Reference

Search YouTube, manage the user's subscriptions and playlists, post comments, and rate videos. Part of the Google Workspace bundle.

## Essentials

- **No event listening.** `supports_listening = False`. YouTube will never push new-video / new-comment notifications — purely request-response.
- **ID formats are fixed and distinct — don't mix:**
  - video IDs are 11-char strings (e.g. `dQw4w9WgXcQ`)
  - channel IDs are 24-char strings starting with `UC...`
  - playlist IDs start with `PL...` and are usually 34+ chars
  - **subscription IDs ≠ channel IDs**
- **`unsubscribe_from_youtube_channel` takes the SUBSCRIPTION ID,** not the channel ID. Get it from `list_my_youtube_subscriptions`. Passing a channel ID fails server-side.
- **`rate_youtube_video` enum is `like` | `dislike` | `none`.** `"none"` is how you clear an existing rating — not deletion.
- **Comments are top-level only.** `post_youtube_comment` does not support replies-to-comments. `get_youtube_video_comments` returns top-level comments most-recent first; thread expansion is not exposed.
- **Multiple Google accounts may be connected**, each with an optional nickname ("work", "personal") — shared across Gmail/Calendar/Docs/Drive/YouTube, so a nickname set once applies to all of them. Every action takes an optional `account` param (email, unique email substring, or nickname). **If the user's message qualifies which account at all** ("my work channel", "the school one"), extract that word and pass it — don't silently default to primary. Only omit `account` when the user gave no qualifier. An unresolvable/ambiguous `account` returns an error listing the connected accounts — relay that to the user instead of guessing.
- **Session-level facts:** `cred.email` is the *primary* connected Google account; the user's own channel info is one `get_my_youtube_channel` call away — don't ask the user for their channel name or subscriber count.
