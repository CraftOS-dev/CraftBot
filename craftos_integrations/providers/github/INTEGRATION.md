# GitHub — Integration Reference

REST + notification-polling integration via a personal access token. Issues, PRs, comments, labels, and notification dispatch.

## Essentials

- **Issue / PR identifier is `owner/repo#number`** (e.g. `acme/web#42`). Numeric IDs on their own are ambiguous — always include `owner/repo`. Pull from `list_github_issues` / notifications; don't construct.
- **`watch_tag` and `watch_repos` config silently drop traffic.** If `watch_tag` is set, the poller skips any notification whose comment doesn't contain the tag. If `watch_repos` is non-empty, notifications from any repo not in the list are dropped before the router sees them. If incoming events stop, check these first.
- **Session-level facts:** `cred.username` is set at login. Don't ask the user for their GitHub handle — read the credential.
- **Token scope failures don't recover by retry.** A `403` (or `404` on a known repo) usually means the PAT lacks the required scope (`repo`, `workflow`, `notifications`). Direct the user to regenerate the token with broader scopes; retrying the same call is futile.
- **Notification IDs are opaque** strings from the GitHub API — pass them through, never construct.
