# LinkedIn — Integration Reference

Official LinkedIn API integration. Profile, posts, search, organisation analytics, and (with elevated perms) DMs.

## Essentials

- **Recipient is a LinkedIn URN, not a username or numeric ID.** Format: `urn:li:person:<linkedin_id>`. The integration handles URL-encoding internally — pass the raw URN string verbatim.
- **The integration knows the user's own `linkedin_id`** (the `sub` claim from the OAuth userinfo response). NEVER ask the user for it; the integration auto-constructs `urn:li:person:<linkedin_id>` for self-references.
- **Many endpoints need elevated API access.** Search-people, search-jobs, and messaging often return a `"note"` field warning that LinkedIn restricts access to non-partner apps. Surface that note to the user — they likely need a different API tier; retrying won't help.
- **Posts have a 3000-character limit.** Truncate or split before calling `create_linkedin_post`; don't let LinkedIn truncate silently.
- **Access tokens last ~60 days** with automatic refresh. A 401 usually means revocation (the user disconnected the app), not expiry — direct them to reconnect.
- **URN identity zoo:** `urn:li:person:...` for users, `urn:li:organization:...` for companies, `urn:li:share:...` for posts. They're not interchangeable — read each action's schema for which it expects.
