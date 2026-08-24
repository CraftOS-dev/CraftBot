# Slack

Team messaging — send/edit messages, channels, threads, reactions, pins,
files, users, usergroups, bookmarks, reminders. Talks to Slack's Web API.

## Multi-account
- One connected account = one Slack **workspace** (team). Every Slack
  action accepts an optional `account` (team id, nickname, or a unique
  fragment like "acme"). Omit it to use the primary workspace.
- When the user names a workspace in any form ("the client's Slack",
  "our community workspace"), pass it as `account` — never silently
  default to primary.
- Channel IDs, message timestamps (`ts`), user IDs, file IDs, and
  usergroup IDs are **workspace-scoped**: an id returned by
  `list_slack_channels` with `account="acme"` must be used with
  `account="acme"` on every follow-up action (send/history/react/etc.).
- For destructive actions (delete message/file, kick user) with multiple
  workspaces connected and no workspace named: ask the user which
  workspace before acting.

## Essentials
- **Channel ID prefix tells you what it is:** `C...` = public channel,
  `G...` = private channel/group, `D...` = direct message channel,
  `U...` = user ID (NOT a channel — can't send to it directly). The
  Slack API never accepts channel NAMES — always IDs. Use
  `list_slack_channels` to translate.
- **DMs need a `D...` channel ID,** not a user ID. Open the DM channel
  first via `open_slack_dm` to get its `D...` id; sending to a user id
  is an error.
- **Thread replies:** pass `thread_ts` (a float-as-string like
  `"1234567890.123456"`) to `send_slack_message`. Without it, the
  message goes to the channel root, not the thread.
- **Don't ask the user for workspace facts:** resolve team/channel/user
  details with `get_slack_auth_info`, `get_slack_team_info`,
  `get_slack_channel_info`, and `list_slack_users`.
- **Error envelope:** Slack returns `{"ok": false, "error": "..."}`.
  Common: `channel_not_found` or `not_in_channel` means the bot isn't a
  member of that channel — invite it (or `join_slack_channel`); don't
  retry.
- **Some actions need a user token (`xoxp-`), not a bot token:**
  `search_slack_messages` (search:read), reminders (reminders:write),
  and `set_slack_user_presence`. With a bot token these return a Slack
  error — report it, don't retry.
