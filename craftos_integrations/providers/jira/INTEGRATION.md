# Jira — Integration Reference

REST integration for Jira Cloud / Server via API token or OAuth. JQL search, issue CRUD, comments, transitions, label-based polling.

## Essentials

- **Issue identifier is the `key` (e.g. `PROJ-123`), not a numeric ID.** Every action expects `issue_key`. Resolve from `search_jira_issues` first if the user gives only a number or a title.
- **Assignee is an `account_id`, not a display name.** Use `search_jira_users` to translate `"Alice Chen"` → account_id before calling `assign_jira_issue`. Pass empty string to unassign.
- **Comments are Atlassian Document Format (ADF) on the wire.** The integration auto-converts plain text on send and auto-extracts plain text on read — pass plain strings, don't construct ADF JSON.
- **`watch_tag` and `watch_labels` config silently drop traffic.** If `watch_labels` is non-empty, only issues with at least one matching label trigger the listener. If `watch_tag` is set, only comments containing that tag dispatch (the instruction is the text AFTER the tag). If incoming events stop, check both.
- **Session-level facts:** `cred.domain`, `cred.email`, `cred.cloud_id` (OAuth) are stored at login. Don't ask the user for their Jira site.
- **Auth errors don't recover by retry.** `401` = bad/expired token; `403` = account lacks API permission; `404` = wrong domain. Ask the user to verify credentials or request admin access.
