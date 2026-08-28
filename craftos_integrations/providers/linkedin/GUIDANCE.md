# LinkedIn

Official LinkedIn API integration. Profile, posts, search, organisation
analytics, and (with elevated perms) DMs.

## Multi-account
- One connected account = one LinkedIn member profile. Every LinkedIn
  action accepts an optional `account` (email, nickname, or a unique
  fragment like "work"). Omit it to use the primary account.
- When the user names an account in any form ("my consulting LinkedIn",
  "the company profile"), pass it as `account` — never silently default
  to primary.
- Post URNs, comment URNs, invitation URNs, and the auto-constructed
  `urn:li:person:...` author are **account-scoped**: a post created with
  `account="work"` must be liked/commented/deleted with
  `account="work"` on every follow-up action.
- For destructive actions (create/delete post, comment, like, DM,
  connection request) with multiple accounts connected and no account
  named: ask the user which account before acting.
- **Adding another account:** LinkedIn's OAuth page has no account
  chooser — it reuses your current browser session. To add a different
  LinkedIn account, log out of linkedin.com in the browser first, then
  click Add account.

## Essentials
- **Recipient is a LinkedIn URN, not a username or numeric ID.** Format:
  `urn:li:person:<linkedin_id>`. The integration handles URL-encoding
  internally — pass the raw URN string verbatim.
- **The integration knows the user's own `linkedin_id`** (the `sub`
  claim from the OAuth userinfo response) — per connected account. NEVER
  ask the user for it; the integration auto-constructs
  `urn:li:person:<linkedin_id>` for self-references on the resolved
  account.
- **Many endpoints need elevated API access.** Search-people,
  search-jobs, and messaging often return a `"note"` field warning that
  LinkedIn restricts access to non-partner apps. Surface that note to
  the user — they likely need a different API tier; retrying won't help.
- **Posts have a 3000-character limit.** Truncate or split before
  calling `create_linkedin_post`; don't let LinkedIn truncate silently.
- **Access tokens last ~60 days** with automatic refresh. A 401 usually
  means revocation (the user disconnected the app), not expiry — direct
  them to reconnect.
- **URN identity zoo:** `urn:li:person:...` for users,
  `urn:li:organization:...` for companies, `urn:li:share:...` for posts.
  They're not interchangeable — read each action's schema for which it
  expects.
