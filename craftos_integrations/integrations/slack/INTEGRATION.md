# Slack — Integration Reference

Bot-token integration. Send/receive messages, list channels, search history, upload files. Talks to Slack's Web API.

## Essentials

- **Channel ID prefix tells you what it is:** `C...` = public channel, `G...` = private channel/group, `D...` = direct message channel, `U...` = user ID (NOT a channel — can't send to it directly). The Slack API never accepts channel NAMES — always IDs. Use `list_slack_channels` to translate.
- **DMs need a `D...` channel ID,** not a user ID. Open the DM channel first via `open_slack_dm` to get its `D...` id; sending to a user id is an error.
- **Thread replies:** pass `thread_ts` (a float-as-string like `"1234567890.123456"`) to `send_slack_message`. Without it, the message goes to the channel root, not the thread.
- **Multiple Slack workspaces may be connected**, each with an optional nickname. Every action takes an optional `account` param (workspace name, workspace ID, unique substring, or nickname). **If the user's message qualifies which workspace at all** ("the work Slack", "my beta workspace"), extract that word and pass it — don't silently default to primary. Only omit `account` when the user gave no qualifier. An unresolvable/ambiguous `account` returns an error listing connected workspaces; relay that instead of guessing.
- **Session-level facts the integration knows (per connected workspace):** `team_name`, `workspace_id`, `bot_user_id`. Resolved at login — use `get_slack_channel_info` / `list_slack_users` instead of asking the user.
- **Error envelope:** Slack returns `{"ok": false, "error": "..."}`. Common: `channel_not_found` or `not_in_channel` means the bot isn't a member of that channel — invite it; don't retry.
- **Polling auto-drops broken channels:** if a channel keeps throwing `channel_not_found` during polling, the listener stops monitoring it silently. If incoming events stop arriving from one channel only, confirm the bot is still a member.
