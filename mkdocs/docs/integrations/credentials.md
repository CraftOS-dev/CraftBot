# Credentials

Every integration you connect stores a credential on disk so the agent can act as your account and the listener can keep receiving events. This page covers where those files live, how the OAuth flow produces them, which services use a shared CraftOS app versus your own credentials, and how to revoke access.

## Where credentials live

Credentials are stored locally in a `.credentials/` directory at the CraftBot project root. Nothing is sent to the cloud. Each integration writes one JSON document named after it, such as `github.accounts.json`, `slack.accounts.json`, or `gmail.accounts.json`.

Every integration is multi-account: that document holds an entry per connected account, keyed by a stable identity the integration derives (an email, a workspace id, a bot user id). Each entry holds whatever that account needs to authenticate — a bot token, an API key, an OAuth access token and refresh token, or a session string — plus its alias, whether it is the primary, and whether its listener is enabled.

CraftBot sets restrictive permissions on a best-effort basis. The `.credentials/` directory is created with owner-only access (`0700`) and each file is written owner read-write only (`0600`). On Windows these calls are attempted and any failure is ignored, so the files are created regardless. Keep the directory off shared drives and out of version control.

### Credential files versus config files

Two file types sit side by side in `.credentials/`:

| File | Holds | Example |
|---|---|---|
| `<integration>.accounts.json` | Every connected account's credential (tokens, keys, session data) | `github.accounts.json` |
| `<integration>_config.json` | Post-connect runtime settings, not secrets | `github_config.json` |

The config file holds tunable listener settings such as GitHub's watch tag, Discord's mention-only flag, or a polling filter. It is kept separate so that saving a setting never rewrites the secret-bearing account document. Not every integration has a config file. One appears only when the integration declares runtime settings. Config is per-integration, not per-account.

### What disconnect does

Disconnecting an integration (`/<service> disconnect`, the settings page, or `disconnect_integration` in chat) removes its accounts and stops their listeners. Disconnect one account by naming it (its alias or identity) and the others keep working; disconnect without naming one and all of them go, deleting the account document. The matching config file, if any, is left in place, so reconnecting restores your previous settings. Disconnecting does not revoke the token on the provider's side. To fully revoke access, see [Revoking access](#revoking-access) below.

## The OAuth flow

OAuth integrations (Google, LinkedIn, Outlook, and the invite paths on Slack and Notion) authorize through the browser. CraftBot runs the whole exchange on your machine:

1. You start the connect. CraftBot builds the provider's authorization URL, including a random `state` value for CSRF protection and, when the provider supports it, a PKCE `code_challenge`.
2. CraftBot starts a local callback server on `localhost` port `8765` and opens the authorization URL in your browser.
3. You approve the requested scopes on the provider's consent page.
4. The provider redirects back to `http://localhost:8765` (or `https://localhost:8765` when the provider requires HTTPS, as Slack does) with an authorization code.
5. The local server captures the code. Before accepting it, CraftBot checks that the returned `state` matches the value it sent, rejecting a mismatch as a possible CSRF attack.
6. CraftBot exchanges the code (plus the PKCE `code_verifier`) for an access token and, when granted, a refresh token, then saves them to the credential file.

The callback server waits up to 120 seconds for you to finish. If you do not approve in time, the flow reports a timeout and no credential is written. If the browser cannot open, CraftBot prints the URL for you to visit manually.

OAuth integrations store a refresh token alongside the access token. When the short-lived access token expires, the integration's client uses the refresh token to obtain a new access token without prompting you again. Reconnecting is only necessary when the refresh token itself is revoked or expires.

## Shared CraftOS apps versus your own credentials

OAuth needs a registered client application. For some services CraftBot ships its own client credentials so connecting is one click. For others you must supply your own. The split is deliberate.

**One-click, shared CraftOS app.** Google (Gmail, Calendar, Drive, Docs, YouTube), LinkedIn, Slack, Notion, Outlook, and HubSpot connect through a client application that CraftBot provides. You grant that application scoped access to your own account, and the token you receive is isolated to you. Your identity, your rate limits, and your suspension risk stay yours, so sharing one client application across users is safe.

**Bring your own credential.** Discord (bot token), GitHub (personal access token), and Twitter / X (four OAuth1 keys) require credentials you generate yourself. The reasons differ by service:

- A Discord bot token *is* the bot account. If everyone connected through one shared CraftBot bot token, they would all act as the same bot with the same name, the same rate-limit budget, and the same fate if one user got it banned. Each user needs their own bot so identity and risk stay separate.
- Twitter's rate limits and pricing tiers are billed per application, not per user. The free tier is capped for the whole application, and X suspends applications aggressively. One heavy or misbehaving user would break the integration for everyone sharing the application, so each user runs under their own developer app.
- GitHub offers no user-authorization OAuth for this use, so you paste a personal access token that carries only the scopes you grant it.

Other credential-based integrations follow the same rule for the same reasons: Jira (domain, email, API token), Lark (App ID and Secret), LINE (channel token and secret), and WhatsApp Business (Cloud API token) all use credentials you supply.

## Overriding the OAuth client credentials

You do not have to use the shared CraftOS applications. If you want OAuth integrations to run under your own registered app, set your client ID and secret in the `oauth` section of `settings.json`, using the key names each integration expects (for example `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `LINKEDIN_CLIENT_ID`, `OUTLOOK_CLIENT_ID`). CraftBot reads each key from that section first and falls back to an environment variable of the same name. When you provide a value, it overrides the shipped default for that integration. When you leave it unset, the embedded CraftOS application is used. See [`settings.json`](../core/configuration/config-json.md) for the file layout.

## Security

An account document grants whatever its tokens grant. A leaked `github.accounts.json` lets the holder act as every GitHub account you connected, within each token's scopes. A leaked OAuth credential lets the holder call the provider's API as you until the token is revoked. Treat the `.credentials/` directory as sensitive: do not commit it, do not copy it to shared storage, and remove it if you retire the machine.

### Revoking access

Disconnecting removes the local file but does not invalidate the token upstream. To revoke access completely:

| Service type | How to revoke |
|---|---|
| OAuth (Google, LinkedIn, Slack, Notion, Outlook, HubSpot) | Remove CraftBot's authorization in the provider's connected-apps or security settings, then reconnect |
| GitHub personal access token | Delete or regenerate the token at github.com/settings/tokens, then reconnect with the new token |
| Discord / Telegram bot token | Regenerate the token in the provider's developer portal, then reconnect |
| Twitter / X keys, Jira / Lark / LINE tokens | Rotate the key or token in the provider's console, then reconnect |

After revoking upstream, run the connect flow again to store a fresh credential.

## Next

- [Integrations](index.md): the full list of connectable services and how to connect them
- [MCP servers](mcp.md): credentials for external tool servers
- [`settings.json`](../core/configuration/config-json.md): the `oauth` section and other configuration
