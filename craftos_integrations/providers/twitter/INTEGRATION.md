# Twitter / X — Integration Reference

X API v2 integration via OAuth 1.0a. Post / reply / delete tweets, search, timeline, like / retweet, and mention-polling.

## Essentials

- **Tweet IDs are numeric strings, not URLs or @handles.** Treat as opaque — pull from `search_tweets` / `get_twitter_timeline` results and pass through. Never construct.
- **280-char hard limit on `post_tweet`.** No auto-truncation. >280 → API returns 400. The router must truncate (or split into a thread) before calling, not after the error.
- **Session-level facts:** `cred.user_id` and `cred.username` are resolved at first connect and saved to the credential. Don't ask the user for their handle — read the credential.
- **`watch_tag` config silently drops mentions.** If set, only mentions containing that tag trigger the router (the instruction is the text AFTER the tag, with leading @-mentions stripped). Empty tag = all mentions trigger.
- **`429` rate-limit means back off, not retry.** The poller already sleeps 60s on 429. Don't add a retry loop in actions — repeated calls deepen the rate-limit window.
- **Reply target field is `reply_to_tweet_id`, not `reply_to`.** Passing the wrong field name → reply posts as a standalone tweet to the user's feed.
