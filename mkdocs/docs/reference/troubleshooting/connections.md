# Integration issues

This page covers problems that are common across integrations and MCP servers: connecting an account, listeners that stop delivering, and MCP servers that will not start. For a fault specific to one service, such as a particular scope or a per-service rate limit, read that integration's own troubleshooting table from [Integrations](../../integrations/index.md). For where auth errors appear, read `logs/<run>/all.log`. See [Logs](../../core/concepts/logs.md).

## Connecting an account

Most integrations authorize through a browser. CraftBot runs a temporary callback server on your machine at `127.0.0.1:8765` to capture the authorization code. It serves HTTP by default, and HTTPS with a self-signed certificate for providers that require an `https` redirect, such as Slack.

| Symptom | Cause | Fix |
|---|---|---|
| The browser opens, you approve, but the connection times out | The callback on port `8765` never reached CraftBot, usually because firewall or security software blocked the local listener | Temporarily allow local connections on `8765`, retry the connect, then re-enable the software |
| The browser warns that the connection is not private during a Slack connect | The callback uses a self-signed certificate on `https://localhost:8765`, which the browser does not trust | Click through the warning. Choose **Advanced**, then **Proceed to localhost**. The certificate is generated locally for this one exchange |
| The connect fails with a redirect or callback error | Port `8765` is already in use by another process | Stop whatever holds the port, or restart CraftBot, then connect again |
| An OAuth connect fails right after approval | The authorization code or PKCE verifier did not round-trip, often because the callback server exited early | Retry the connect. If it keeps failing, read the `logs/<run>/all.log` lines around the attempt for the provider's error text |
| An integration worked yesterday and today every call is unauthorized | The access token expired and the refresh failed, or the refresh token was revoked | Disconnect and reconnect the integration to mint a fresh token. Password resets, account changes, and provider security actions all revoke tokens. See [Credentials](../../integrations/credentials.md) |

## Listeners do not deliver

A listener is what turns incoming platform activity into events the agent reacts to. Some integrations poll on an interval, and some receive webhooks. If outbound actions work but inbound messages never arrive, the listener is the place to look.

| Symptom | Cause | Fix |
|---|---|---|
| Outbound messages send, but the agent never reacts to incoming ones | The listener is not running, or the integration has no listener | Confirm the integration is connected. Disconnecting stops the listener, and some integrations, such as Calendar, have no listener at all and need a scheduled task instead |
| Incoming messages arrive late, not instantly | Polling listeners check on a fixed interval rather than in real time | This is expected. A polling listener, such as GitHub's, checks every few seconds and dispatches each item once. Real-time delivery needs a webhook |
| A bot receives nothing in a channel | The bot is not a member of that channel | Invite the bot to the channel. A bot only sees messages in channels it has joined |
| The agent ignores most messages and reacts only to some | A mention-only setting is on, so the listener requires a mention or a watch tag | Mention the bot, or turn off the mention-only flag in that integration's settings. See [Credentials](../../integrations/credentials.md) for where the config lives |
| The listener reacts only to some repositories or chats | An allowlist restricts the listener to specific targets, such as GitHub's watch repositories | Widen or clear the allowlist in the integration's settings. The listener re-reads it without a reconnect |
| A webhook integration receives nothing inbound | Webhooks require the provider to reach your machine, which a local install does not expose | Expose your local endpoint through a tunnel and configure the public URL with the provider, or switch to a polling action on a schedule. See [Triggers](../../core/concepts/triggers.md) for how listener events become tasks |

## Gotchas common across integrations

These apply to more than one service. Check them before assuming a bug in one integration.

| Symptom | Cause | Fix |
|---|---|---|
| A bot logs in with a token but messages fail | Bot-token integrations and OAuth integrations authenticate differently, and a bot token carries only what its app was granted | Regenerate the token in the provider's developer portal, then disconnect and reconnect. Confirm the bot is invited with the permissions it needs |
| A call fails with a permission or scope error on an action that should work | The token is missing a scope | Re-authorize and grant the scope the action needs, or, for a personal access token, regenerate it with the required scope. Retrying the same call without changing scopes does not help |
| Calls succeed for a while, then start failing in bursts | You hit the provider's rate limit | Slow the frequency of the work, or spread it out. Per-service limits and their fixes are on each integration's own page |
| The credential says it is connected but calls still fail | The stored token was revoked upstream even though the local file remains | Disconnect and reconnect. Disconnecting only removes the local file, so also revoke upstream if you intend to cut access fully. See [Credentials](../../integrations/credentials.md) |

## MCP servers

CraftBot connects to MCP servers listed in `app/config/mcp_config.json` and registers each server's tools as actions. Server problems show up under the `[MCP]` tag in the logs.

| Symptom | Cause | Fix |
|---|---|---|
| A server shows disconnected and never connects | The launch command fails, or the entry is disabled | Run the server's command by hand in a terminal to see its error. Confirm `enabled` is `true` for that entry. Read the `[MCP]` log lines |
| An MCP server's tools do not appear as actions | The server started but exposed no tools, or its entry failed validation and was skipped | A `stdio` server with no command, a remote server with no URL, or an unknown transport is skipped with a warning while the rest still load. Fix the entry, and the config is re-read without a restart |
| A server connects but every tool call errors with an auth failure | A required environment variable, such as an API token, is not set on the server entry | Fill the `env` value for that server. Set it from chat with `/mcp env <name> <KEY> <VALUE>`, which writes the config and reloads it |
| An edit to `mcp_config.json` seems ignored | The file is watched, so a syntax error can stop the reload | Confirm the JSON is valid. On a valid save, CraftBot disconnects removed servers, connects newly enabled ones, and re-registers tools without a restart |

See [MCP servers](../../integrations/mcp.md) for the config schema, the transports, and the `/mcp` command.

## Service-specific issues

For anything tied to one platform, its own page has a troubleshooting table with the exact scopes, tokens, and quirks for that service. Open it from [Integrations](../../integrations/index.md).

## Next

- [Provider issues](providers.md): authentication, models, rate limits, and media
- [Credentials](../../integrations/credentials.md): where credentials live and how to revoke them
- [Triggers](../../core/concepts/triggers.md): how listener events become tasks
