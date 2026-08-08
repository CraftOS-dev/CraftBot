# Integrations

An integration is a connected external service. Once you connect one, its API operations join the agent's [action registry](../core/concepts/actions-and-action-sets.md) as regular actions, so the agent creates issues, sends messages, reads calendars, and updates records the same way it runs any other action. Many integrations also install a listener. A listener watches the platform for inbound activity (a Discord message, a GitHub mention, a new email) and turns each event into a [trigger](../core/concepts/triggers.md) that starts or feeds a task. Connecting a service therefore does two things at once: it gives the agent new actions to call, and it lets the outside world reach the agent.

The two halves are independent. An integration can expose actions without a listener (Stripe, Google Calendar, LinkedIn), it can expose both (Discord, GitHub, Slack), and one case exposes a listener with no agent actions (WhatsApp Business, which receives inbound webhooks but has no outbound action set).

## Available integrations

CraftBot ships with the following integrations. The **Inbound events** column shows how each listener receives activity and how often it checks. The **Actions** column shows how many actions the integration adds to the registry.

| Integration | Auth method | Inbound events | Actions | Page |
|---|---|---|---|---|
| Discord | Bot token | Gateway WebSocket | 80 | [discord.md](discord.md) |
| GitHub | Personal access token | Poll, 15s | 107 | [github.md](github.md) |
| Gmail | Google OAuth | Poll, 5s | 34 | [gmail.md](gmail.md) |
| Google Calendar | Google OAuth | None | 32 | [google-calendar.md](google-calendar.md) |
| Google Docs | Google OAuth | None | 33 | [google-docs.md](google-docs.md) |
| Google Drive | Google OAuth | None | 39 | [google-drive.md](google-drive.md) |
| YouTube | Google OAuth | None | 11 | [google-youtube.md](google-youtube.md) |
| HubSpot | OAuth or private-app token | None | 90 | [hubspot.md](hubspot.md) |
| Jira | Domain + email + API token | Poll, 10s | 61 | [jira.md](jira.md) |
| Lark | App ID + App Secret | WebSocket | 46 messaging, 26 calendar, 76 drive | [lark.md](lark.md) |
| LINE | Channel token + secret | Send-only | 59 | [line.md](line.md) |
| LinkedIn | OAuth | None | 31 | [linkedin.md](linkedin.md) |
| Notion | OAuth or internal token | None | 29 | [notion.md](notion.md) |
| Outlook | OAuth with PKCE | Poll, 5s | 40 | [outlook.md](outlook.md) |
| Slack | OAuth or bot token | Poll, 3s | 60 | [slack.md](slack.md) |
| Stripe | API key | None | 99 | [stripe.md](stripe.md) |
| Telegram Bot | Bot token | Long-poll | 76 shared | [telegram-bot.md](telegram-bot.md) |
| Telegram User | MTProto api_id / api_hash + phone | Realtime | 76 shared | [telegram-user.md](telegram-user.md) |
| Twitter / X | OAuth1 (4 keys) | Poll, 30s | 46 | [twitter.md](twitter.md) |
| WhatsApp Web | QR scan | Bridge stream | 40 | [whatsapp-web.md](whatsapp-web.md) |
| WhatsApp Business | Cloud API token | Webhook | 0 agent actions | [whatsapp-business.md](whatsapp-business.md) |

Telegram Bot and Telegram User share one action set of 76 messaging actions, so the number counts the same surface once for each. Lark spreads its surface across three areas: messaging, calendar, and drive.

## Three ways to connect

You can connect an integration from the settings page, by asking the agent in chat, or with a slash command. All three paths run through the same connection logic in the `craftos_integrations` package, so they produce the same result, including starting the listener when the connect succeeds.

### Settings page

Open **Settings → Integrations**, pick a service, and follow its connect form. Token-based services show a field for each credential (a bot token, an API key). OAuth services show a **Connect** button that opens the browser consent flow. Interactive services (WhatsApp Web) show a QR code to scan. The form is generated from the integration's declared fields, and a `?` popover next to each field explains where to find the value.

### Asking the agent in chat

Tell the agent what you want to connect. It calls `list_available_integrations` to check what is available and which credentials each one needs, asks you for any required tokens, and then calls `connect_integration` to run the flow. For OAuth services the agent hands you a browser URL. For WhatsApp Web it returns a QR code to scan. The matching `check_integration_status` and `disconnect_integration` actions let the agent confirm a connection or remove one, all without leaving the chat.

### Per-integration slash commands

Every registered integration gets its own command named after the integration, such as `/github`, `/slack`, or `/gmail`. Each command accepts these subcommands:

| Subcommand | Effect |
|---|---|
| `/<service> connect [values]` | Connect using the integration's auth type. Token services take the credential values as arguments in field order; OAuth services open the browser; interactive services start the QR or code flow |
| `/<service> status` | Show whether the integration is connected and which account is linked |
| `/<service> disconnect` | Remove the stored credential and stop the listener |

Integrations that need it also expose their own subcommands through the same command, such as `login`, `logout`, and `invite`. Running `/<service>` with no subcommand prints the full list for that integration. Across every integration, `/cred status` lists all connections and their state in one place. See [Credentials](credentials.md) for where those credentials are stored.

## Next

- [Credentials](credentials.md): where connection tokens live, the OAuth flow, and how to revoke access
- [MCP servers](mcp.md): add external tool providers as actions alongside built-in integrations
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how integration actions load into a task
