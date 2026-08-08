# craftos_integrations

A plug-and-play package of 19 external integrations (Discord, Slack, Telegram Bot + User, GitHub, Jira, Notion, LinkedIn, Outlook, Twitter, WhatsApp Web/Business, LINE, Lark, plus per-service Google: Gmail / Calendar / Drive / Docs / YouTube) that any Python host can drop in.

The package owns:

- **Auth flows** — OAuth (with PKCE), invite, interactive (QR), or raw tokens.
- **Runtime clients** — REST/Gateway/WebSocket/MTProto/Node-bridge, polling listeners.
- **Credential storage** — JSON files in `<project_root>/.credentials/`.
- **A registry + autoloader** — drop a file in `integrations/`, restart, done.
- **A common-ops facade** — `send_message(integration, …)`, `is_connected(…)`, `list_integrations()`, etc.
- **A standard envelope + REST helpers** — every method returns `{ok, result}` or `{error, details}`; `helpers.request`/`arequest` wrap httpx and emit that shape.

The `integrations/` subfolder is **optional**: if a host ships the framework with no bundled integrations (or a consumer deletes the folder), the package still imports, `initialize_manager()` still boots, and every facade call returns a graceful `{"error": "Unknown integration: ..."}` instead of crashing. Drop in only the integrations you want.

The package owns **no UI opinions**. The host wires its own settings page / slash commands / listener callback.

---

## Quick start

```python
import asyncio, os
from pathlib import Path
from craftos_integrations import (
    configure,
    initialize_manager,
    get_handler,
    send_message,
)


async def on_message(payload: dict) -> None:
    # payload keys: source, integrationType, contactId, contactName,
    #               messageBody, channelId, channelName, messageId,
    #               is_self_message, raw
    print(f"[{payload['source']}] {payload['contactName']}: {payload['messageBody']}")


async def main():
    configure(
        project_root=Path.cwd(),
        oauth={
            "GITHUB_CLIENT_ID": os.getenv("GITHUB_CLIENT_ID"),
            "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
            "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET"),
            # ...etc
        },
    )

    # Boot the listener (starts every platform that has stored credentials)
    manager = await initialize_manager(on_message=on_message)

    # Auth via slash-command-style handler dispatch
    ok, msg = await get_handler("github").handle("login", ["<personal_access_token>"])
    print(msg)

    # Send a message via any integration through the facade
    await send_message("slack", recipient="C12345", text="hi from the agent")


asyncio.run(main())
```

---

## Architecture

```
                       ┌──────────────────────────────────────┐
   configure() ──────▶ │             ConfigStore              │ ◀── (env vars fallback)
                       │   project_root, oauth, logger, …     │
                       └──────────────────────────────────────┘
                                      ▲
                                      │ read by everything
       ┌──────────────────────────────┴──────────────────────────────┐
       │                                                             │
┌──────────────┐                                            ┌──────────────────┐
│ Auth side    │                                            │ Runtime side     │
│              │                                            │                  │
│ IntegrationHandler  ─◀── @register_handler("name")        │ BasePlatformClient
│  ├── login                                                │  ├── connect
│  ├── logout                                               │  ├── send_message
│  ├── status                                               │  ├── start_listening
│  ├── invite       (composes OAuthFlow)                    │  ├── stop_listening
│  ├── connect_token  (default impl on the ABC)             │  └── has_credentials
│  ├── connect_oauth                                        │       ▲
│  └── connect_interactive                                  │       │ @register_client
│                                                           │       │
│       ▲                                                   │       │
│       │ both reference the same IntegrationSpec           │       │
│       │   (composition, not inheritance)                  │       │
│       ▼                                                   │       │
│ IntegrationSpec(name, platform_id, cred_class, cred_file) ────────┘
└──────────────┬─────────────────────────────────┬──────────────────┘
               │                                 │
       persists creds to                  manager starts/stops listeners
               ▼                                 ▼
       ┌──────────────────┐           ┌──────────────────────┐
       │ <project_root>/  │           │ ExternalCommsManager │
       │   .credentials/  │           │  ├── start_platform  │
       │     <name>.json  │           │  ├── stop_platform   │
       └──────────────────┘           │  └── on_message ─────┴──▶ host callback
                                      └──────────────────────┘
```

Two ABCs per integration — `IntegrationHandler` (auth lifecycle) and `BasePlatformClient` (runtime lifecycle) — bound by composition through a shared `IntegrationSpec`. Both register via decorators; the autoloader walks `integrations/` and triggers them.

---

## Setup

### 1. `configure(...)` — call once at startup

```python
configure(
    project_root: Path = Path.cwd(),     # where .credentials/ lives
    logger: logging.Logger = None,        # falls back to stdlib if None
    oauth: dict[str, str] = None,         # OAuth client IDs/secrets (see table below)
    oauth_runner: Callable = None,        # override the bundled localhost server
    onboarding_hook: Callable = None,     # optional: called on first connect
    extras: dict = None,                  # arbitrary host-supplied context
)
```

Anything not passed falls back to **environment variables** with the same name. So a host that prefers env-only setup can call `configure(project_root=...)` alone.

### 2. `initialize_manager(on_message=...)` — boot the listener

```python
manager = await initialize_manager(on_message=callback, auto_start=True)
```

- Walks the `integrations/` folder via `autoload_integrations()`.
- For each registered platform that supports listening AND has stored credentials, starts a listener.
- Routes incoming messages through the standardized payload (see below) into your `on_message`.

### 3. Incoming-message payload contract

```python
{
    "source": "Discord",  # human display name (handler.display_name)
    "integrationType": "discord",  # platform_id
    "contactId": "<sender id>",
    "contactName": "<sender display name>",
    "messageBody": "<text>",
    "channelId": "<channel/chat id>",
    "channelName": "<channel/chat name>",
    "messageId": "<platform message id>",
    "is_self_message": False,
    "raw": {...},  # full original platform event
}
```

---

## Configuration: OAuth env vars

Every OAuth-capable integration reads its credentials via `ConfigStore.get_oauth(KEY)` — first checking the dict you passed to `configure(oauth=...)`, then falling back to `os.environ[KEY]`.

| Integration       | Auth type   | Required keys                                                            |
|-------------------|-------------|--------------------------------------------------------------------------|
| github            | token       | (none — user pastes a personal access token)                             |
| jira              | token       | (none — user supplies domain + email + API token)                        |
| twitter           | token       | (none — user supplies 4 OAuth1 keys)                                     |
| discord           | token       | (none — user pastes a bot token)                                         |
| whatsapp_business | token       | (none — user supplies access token + phone_number_id)                    |
| line              | token       | (none — user pastes channel access token + channel secret)               |
| lark              | token       | (none — user supplies App ID + App Secret from open.larksuite.com)       |
| telegram_bot      | token       | optional `TELEGRAM_SHARED_BOT_TOKEN`, `TELEGRAM_SHARED_BOT_USERNAME` for `invite` flow |
| telegram_user     | interactive | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`                                   |
| whatsapp_web      | interactive | (none — uses Node bridge + QR scan)                                      |
| gmail / google_* | oauth+PKCE  | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (shared across all five Google integrations) |
| outlook           | oauth+PKCE  | `OUTLOOK_CLIENT_ID`                                                      |
| linkedin          | oauth       | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`                           |
| notion            | both        | `NOTION_SHARED_CLIENT_ID`, `NOTION_SHARED_CLIENT_SECRET` (only for `invite`) |
| slack             | both        | `SLACK_SHARED_CLIENT_ID`, `SLACK_SHARED_CLIENT_SECRET` (only for `invite`) |

The discord voice helper additionally reads `extras["openai_api_key"]` (or `OPENAI_API_KEY` env) for STT/TTS.

---

## Per-integration runtime config

Some integrations expose **runtime knobs** the user tunes after connecting — Discord's `mention_only`, GitHub's `watch_tag` / `watch_repos`, Twitter's `watch_tag`, WhatsApp Web's `self_messages_only`, etc. The package provides a uniform, schema-driven way to declare these on the handler, persist them to disk, and surface them to UI hosts.

### Shape: declare two attributes on the handler

```python
@dataclass
class DiscordConfig:
    mention_only: bool = False
    third_party_usernames: List[str] = field(default_factory=list)


@register_handler(DISCORD.name)
class DiscordHandler(IntegrationHandler):
    spec = DISCORD
    display_name = "Discord"
    auth_type = "token"
    fields = [{"key": "bot_token", "label": "Bot Token", "password": True}]

    config_class = DiscordConfig
    config_fields = [
        {
            "key": "mention_only",
            "label": "Only when @-mentioned",
            "type": "checkbox",
            "help": "Drop messages that don't @-mention the bot.",
        },
        {
            "key": "third_party_usernames",
            "label": "Allowed users",
            "type": "list",
            "placeholder": "alice, bob",
            "help": "Comma-separated Discord usernames or display names.",
        },
    ]
```

Both attributes are optional. An integration without `config_class` doesn't expose a configure UI — empty by default.

### Field types

Each entry in `config_fields` is a dict with these keys:

| Key            | Required | Notes                                                                 |
|----------------|----------|-----------------------------------------------------------------------|
| `key`          | yes      | Dataclass field name; the value gets written to ``<name>_config.json`` |
| `label`        | yes      | Human-readable label shown in the UI                                  |
| `type`         | yes      | One of `text`, `textarea`, `list`, `checkbox`, `select`, `number`     |
| `placeholder`  | no       | Hint text inside the input                                            |
| `help`         | no       | Description shown under the field                                     |
| `options`      | only `select` | Array of `{value, label}` choice objects                         |

The backend coerces incoming UI values to the dataclass field types — `checkbox` to bool, `list` from `"a, b, c"` strings into `["a","b","c"]`, `number` parses to int/float, etc.

### Storage

Config is persisted at `<project_root>/.credentials/<name>_config.json` — same directory as credentials, with a `_config.json` suffix:

```
.credentials/
├── discord.json              ← credential (token, etc.)
├── discord_config.json       ← runtime config (mention_only, allowlists)
├── github.json
├── github_config.json
└── ...
```

Unknown keys in older config files are silently dropped on load, and missing fields fall back to dataclass defaults — so adding/removing a field is one line and doesn't break existing installs.

### Reading config from your client

Use `craftos_integrations.load_config` inside `start_listening` or message handlers:

```python
from craftos_integrations import load_config


async def _handle_message(self, data):
    cfg = load_config("discord_config.json", DiscordConfig) or DiscordConfig()
    if cfg.mention_only and not bot_was_mentioned:
        return
    ...
```

Reading fresh on each message keeps config changes effective without a restart.

### Host-side facade

Three async-friendly helpers on `craftos_integrations` parallel the credential ones:

```python
from craftos_integrations import (
    get_config,  # current values as a plain dict (defaults if no file yet)
    update_config,  # write new values; coerces per the schema
    get_config_schema,  # the config_fields list, for rendering a settings form
)

get_config("discord")
# → {"mention_only": False, "third_party_usernames": []}

ok, msg = update_config(
    "discord", {"mention_only": True, "third_party_usernames": "alice, bob"}
)
# Backend coerces the string into ["alice", "bob"] and persists

get_config_schema("discord")
# → [{"key": "mention_only", "label": "Only when @-mentioned", "type": "checkbox", ...}, ...]
```

### Inline connect help (the `?` popover)

Independent of `config_class`, handlers can declare a `connect_help: List[str]` for "where do I find these credentials" guidance shown in the connect modal:

```python
@register_handler(LINE.name)
class LineHandler(IntegrationHandler):
    ...
    connect_help = [
        "Open LINE Developers Console: developers.line.biz/console",
        "Sign in with your LINE account",
        "Create a Provider, then create a Messaging API channel inside it",
        "Channel Secret → Basic settings tab → 'Channel secret' field",
        "Channel Access Token → Messaging API tab → 'Issue' button (long-lived)",
    ]
```

Steps surface to UI hosts via `get_metadata(integration)["connect_help"]` and are rendered as a numbered list when the user clicks the `?` icon in the connect dialog.

---

## Auth: three ways to connect

Every handler exposes three **dispatchers** on the ABC. Hosts call the one that matches the integration's `auth_type`:

| Dispatcher                                  | Used by `auth_type`              |
|---------------------------------------------|----------------------------------|
| `connect_token(integration, creds_dict)`    | `token`, `both`, `token_with_interactive` |
| `connect_oauth(integration)`                | `oauth`, `both`                  |
| `connect_interactive(integration)`          | `interactive`, `token_with_interactive` |

```python
from craftos_integrations import (
    connect_token,
    connect_oauth,
    connect_interactive,
    disconnect,
)

# Token — host collects field values matching handler.fields
ok, msg = await connect_token("github", {"access_token": "ghp_..."})

# OAuth — opens the browser, captures the redirect on localhost:8765
ok, msg = await connect_oauth("google")

# Interactive — e.g. WhatsApp QR scan, Telegram phone-code
ok, msg = await connect_interactive("whatsapp_web")

# Disconnect
ok, msg = await disconnect("github")
```

By default each dispatcher **also starts the listener** for the platform on success. Pass `start_listener=False` to skip.

For UI-driven flows where you want metadata (display name, fields, auth type) to render a settings form:

```python
from craftos_integrations import list_metadata, get_metadata, integration_registry

list_metadata()  # all integrations as a list
get_metadata("slack")  # single integration
integration_registry()  # snapshot dict {id: metadata}
```

---

## Adding a new integration

An integration is **two folders** that get auto-wired — no central registry edits, no frontend changes (UI metadata flows from `get_metadata()`):

1. **Platform package** — `craftos_integrations/integrations/<name>/__init__.py` holds the auth handler + runtime client. The autoloader walks this folder at startup and the `@register_handler` / `@register_client` decorators do the rest.
2. **Action surface** — `app/data/action/integrations/<name>/<name>_actions.py` holds the `@action`-decorated wrappers the agent calls. One wrapper per client method.

The two files have separate audiences: file 1 is for the **human** connecting the account and the **listener** receiving inbound events; file 2 is for the **agent** calling the API on the user's behalf. You need both.

### Recipe at a glance

For a production-level integration, produce in this order:

| # | Output | Where |
|---|--------|-------|
| 1 | Pick `auth_type`, declare credential `fields` + `connect_help` | handler in `__init__.py` |
| 2 | Implement `login` / `logout` / `status` against the real API | handler |
| 3 | Optional: `config_class` + `config_fields` for post-connect knobs | handler |
| 4 | Build the client — one method per endpoint, using `helpers.arequest`, returning `Result` | client in `__init__.py` |
| 5 | Optional: `start_listening` / `stop_listening` (webhook / polling / WebSocket) | client |
| 6 | Write `INTEGRATION.md` — identifier shape, silent-drop config flags, auth gotchas | integration root |
| 7 | Mirror each client method as an `@action` wrapper with sub-set + umbrella tags | `<name>_actions.py` |
| 8 | Verify — import check + AST action-count audit + live smoke test | see "Verification" |

**Don't ship halfway.** An integration that can `list_*` but not `update_*` / `delete_*` / `reply_*` is the #1 source of agent failure: the LLM picks the integration confidently, then can't complete the user's intent. Mirror the full verb set the API exposes. The detailed "production-level expectations" subsection below makes this concrete.

The sources to mine for the API surface, in preference order: an **OpenAPI / Swagger spec** when the vendor publishes one (auto-generates method signatures), an existing `skills/<name>-api/SKILL.md` if one is in this repo, then the **official REST reference docs** (always cross-check version numbers and base URL).

### Choosing an auth strategy

Decide this **before** you start scaffolding either example below. The decision determines whether you write a token handler or an OAuth handler, whether to embed shared client credentials, and how the connect modal looks.

#### Default rule

If the vendor offers user-authorization OAuth (the user grants OUR app scoped access to THEIR account), **use OAuth and ship our client credentials embedded** so the user experience is one-click. We do this today for Google (5 services), LinkedIn, Outlook, plus the OAuth-invite paths on Slack and Notion. The embedded credentials live at [agent_core/core/credentials/embedded_credentials.py](../agent_core/core/credentials/embedded_credentials.py) and are surfaced via `ConfigStore.get_oauth(key)`.

Low friction matters: every extra step in the connect modal (register a developer app, find the API token page, label and copy multiple values) loses users.

#### Hard exception — when shipping our credentials would expose OUR account or app

DO NOT ship our credentials when using them effectively means the user is operating **our** account, **our** app, or **our** quotas. Two failure modes:

1. **Identity-pooling.** Our credentials carry an identity that's shared across every user. Discord bot tokens are the canonical case: a bot token IS the bot account. If multiple users connected through ONE shared CraftBot bot token, they'd all act AS the same bot — same name, same avatar, same rate-limit budget, same reputation, same fate if one user gets it banned. Compare to Slack: OAuth installs OUR app into the user's *workspace*, but each install gets its OWN scoped bot token isolated to that workspace. Slack's OAuth is safe; Discord's would not be.

2. **Operational-pooling.** Our credentials carry rate limits, billing, or suspension risk that's pooled across every user, even when the per-call identity is correct. Twitter is the canonical case: OAuth-with-our-credentials would post tweets correctly from each user's account (identity is fine), but Twitter's rate limits and pricing tiers are billed **per-APP, not per-user** — the free tier is 1500 posts/month TOTAL across all users, paid tiers run $200–$5000/month, and X suspends apps aggressively. One heavy user breaks it for everyone; one TOS violation suspends everyone at once.

Either failure mode → **the user must supply their own credentials**, even if it adds friction.

#### Decision test — three questions

For any new integration, answer all three before picking an auth path:

1. **Whose identity acts?** When the API call goes out, does the API see the *user's* identity (their email, their workspace, their Atlassian tenant) or *our* shared identity?
   - User's identity → OAuth-with-our-credentials is safe on this axis.
   - Our shared identity → user must bring their own credentials.

2. **Whose rate limits / quotas apply?** When two different users both use the integration heavily, are their quotas counted separately at the API, or summed against one shared bucket?
   - Counted separately per user-account → safe.
   - Summed against one bucket per OAuth app → user must bring their own (unless the per-app limits are so generous that pooling is invisible — e.g. Google Workspace).

3. **Whose app gets suspended if abused?** If one user does something the vendor doesn't like (spam, scraping, automated content), does the vendor suspend the user's account or our developer app?
   - The user's account → safe.
   - Our developer app (taking down every other user) → user must bring their own.

If any answer is "ours", the user MUST supply their own credentials. All three "user's" → ship our credentials and make it one-click.

#### Worked examples — discord, jira, twitter

The three integrations that are most often asked "why aren't these OAuth?":

| Integration | OAuth available? | Q1: identity | Q2: quota | Q3: suspension | Verdict |
|-------------|------------------|--------------|-----------|----------------|---------|
| **Jira** | Yes — Atlassian 3LO for Jira Cloud | Per-user (refresh token tied to the user's Atlassian account) | Per-user (Atlassian rate-limits per tenant) | Per-user (Atlassian suspends per tenant; marketplace-app suspension is rare and recoverable) | ✅ **Migrate to OAuth-with-our-credentials**. Reason it's not done today is just that we haven't registered the Atlassian developer-console app. Dual-path: 3LO for Jira Cloud, token for Jira Server / Data Center (3LO doesn't exist there). |
| **Discord** | Yes — OAuth bot install | ❌ Shared (the bot token IS the actor; every install acts AS our one shared bot) | ❌ Shared (Discord rate-limits per bot application across all servers) | ❌ Shared (one TOS violation suspends our bot everywhere) | ❌ **Keep user-supplied bot token.** Current model gives each user their own bot persona, isolated rate limits, isolated risk. Migrating to shared-bot OAuth would be a regression for power users and a footgun for everyone. |
| **Twitter / X** | Yes — OAuth 1.0a and OAuth 2.0 PKCE | ✅ Per-user (tweets post from the user's account) | ❌ Shared (rate limits and pricing tiers are per-APP; free tier is 1500 posts/month TOTAL) | ❌ Shared (X suspends apps aggressively; one user's behavior takes down all others) | ❌ **Keep user-supplied 4-key model.** Identity check passes but operational-pooling fails hard. Each user under their own developer app is the only safe topology. |

#### Quick decision matrix for new integrations

| Vendor situation | Auth to use |
|------------------|-------------|
| OAuth available, **per-user** identity AND quota AND suspension scope | OAuth + ship our client credentials embedded (one-click). Examples today: Google, LinkedIn, Outlook, Slack (invite), Notion (invite). |
| OAuth available, per-user identity, **but shared quota / shared suspension risk** | User supplies their own OAuth app credentials. Examples today: Twitter (if we ever support OAuth login). |
| OAuth available, **but our credentials act as a shared identity** | User supplies their own credentials. Examples today: Discord (bot token). |
| No OAuth — vendor only offers PAT / API token | User supplies their own. Examples today: GitHub, Jira Server, Lark, LINE, WhatsApp Business. |
| No OAuth, no PAT — only interactive client login | Interactive flow (QR scan, phone code). We can embed vendor "app keys" (e.g. `TELEGRAM_API_ID`/`API_HASH`) when they're per-app authentication scaffolding, not per-user identity — the user's session token is still separate. Examples today: WhatsApp Web (no keys needed), Telegram User. |

#### Operational guidance

- **When in doubt, default to "user supplies their own".** Migrating user-supplied → shared-credentials later is easy (drop our credentials in the embedded registry, update `connect_help`, the existing user-supplied path keeps working as the alternative). Migrating shared-credentials → user-supplied later is a credential rotation event for every existing user.

- **Dual-path is the safest hedge.** When in doubt and OAuth is available, ship `auth_type="both"` (like Slack and Notion): OAuth-with-our-credentials for the easy path, user-token paste for power users / enterprise. The token path is also the fallback when our shared OAuth app is unreachable (rate-limited, suspended, mid-rotation).

- **`_SHARED_` naming convention.** Env-var keys for credentials we ship use a `_SHARED_` infix (e.g. `SLACK_SHARED_CLIENT_ID`, `NOTION_SHARED_CLIENT_SECRET`) to signal "this is the CraftBot app, not user-supplied". Use the same naming for any new shared-credentials integration. (Earlier integrations like `GOOGLE_CLIENT_ID` / `LINKEDIN_CLIENT_ID` / `OUTLOOK_CLIENT_ID` predate the convention and remain unprefixed — but they're also ours-to-share.)

- **Embedded credentials are not secrets.** Anything in [embedded_credentials.py](../agent_core/core/credentials/embedded_credentials.py) ships in the binary and can be extracted with `base64 -d`. Use this layer ONLY for OAuth client credentials (which are designed to be public-ish — the security depends on the redirect-URI and the user's consent, not on the client_id staying secret). Never embed user data tokens, server-side API keys, or anything that grants access without a user-driven OAuth consent step.

### Minimal token-only example (e.g. Asana)

```python
# craftos_integrations/integrations/asana.py
from dataclasses import dataclass, field
from typing import List, Tuple

from .. import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    has_credential,
    load_credential,
    save_credential,
    remove_credential,
    register_client,
    register_handler,
)
from ..helpers import Result, request as http_request
from ..logger import get_logger

logger = get_logger(__name__)


@dataclass
class AsanaCredential:
    access_token: str = ""
    workspace_id: str = ""


ASANA = IntegrationSpec(
    name="asana",
    platform_id="asana",
    cred_class=AsanaCredential,
    cred_file="asana.json",
)


@dataclass
class AsanaConfig:
    project_filter: List[str] = field(default_factory=list)


@register_handler(ASANA.name)
class AsanaHandler(IntegrationHandler):
    spec = ASANA
    display_name = "Asana"
    description = "Tasks and projects"
    auth_type = "token"
    icon = "asana"  # Lucide icon name or frontend brand-SVG key
    fields = [
        {
            "key": "access_token",
            "label": "Personal Access Token",
            "placeholder": "1/12345...",
            "password": True,
        },
    ]

    # Inline help shown in the connect modal's ``?`` popover
    connect_help = [
        "Open https://app.asana.com/0/my-apps",
        "Click 'Create new token' → name it, copy the token",
    ]

    # Optional runtime config — schema-driven UI for post-connect knobs.
    # Omit both attrs if your integration has no runtime settings.
    config_class = AsanaConfig
    config_fields = [
        {
            "key": "project_filter",
            "label": "Watched projects",
            "type": "list",
            "placeholder": "GID1, GID2",
            "help": "Comma-separated Asana project GIDs. Empty = watch all.",
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        # `args` is the credential values in field-declaration order
        # (the default connect_token() on the ABC builds it from a dict)
        token = args[0] if args else ""
        if not token:
            return False, "Personal access token is required."

        result = http_request(
            "GET",
            "https://app.asana.com/api/1.0/users/me",
            headers={"Authorization": f"Bearer {token}"},
            expected=(200,),
        )
        if "error" in result:
            return False, f"Asana auth failed: {result['error']}"
        me = (result["result"] or {}).get("data", {})

        save_credential(self.spec.cred_file, AsanaCredential(access_token=token))
        return True, f"Asana connected as {me.get('name', 'unknown')}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Asana credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed Asana credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Asana: Not connected"
        return True, "Asana: Connected"


@register_client
class AsanaClient(BasePlatformClient):
    spec = ASANA
    PLATFORM_ID = ASANA.platform_id

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> AsanaCredential:
        cred = load_credential(self.spec.cred_file, AsanaCredential)
        if cred is None:
            raise RuntimeError("No Asana credentials. Use /asana login first.")
        return cred

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        # Asana doesn't really do "send_message" — repurpose for adding a comment to a task
        cred = self._load()
        return http_request(
            "POST",
            f"https://app.asana.com/api/1.0/tasks/{recipient}/stories",
            headers={"Authorization": f"Bearer {cred.access_token}"},
            json={"data": {"text": text}},
            transform=lambda d: d.get("data"),
        )
```

That's it. No edits to `manager.py`, no central registry, no `__init__.py` changes. Restart the host, `get_handler("asana")` resolves, settings UI renders the form from `fields`.

#### About `helpers.request` / `Result`

The package ships a thin `httpx` wrapper at `craftos_integrations.helpers`. It owns the standard envelope so every integration returns the same shape:

```python
# Success
{"ok": True, "result": <transformed body>}

# Failure (HTTP non-2xx, network error, exception)
{"error": "<message>", "details": "<response text or omitted>"}
```

Both shapes are codified as TypedDicts (`Ok`, `Err`, `Result`) — you just import `Result` and use it as the return annotation. `request` is the sync wrapper; `arequest` is the async one. Pass `expected=(...)` to override the success status set (default `(200, 201)`), `transform=` to reshape the parsed body, and `timeout=` to override the 15s default.

Three integrations (Slack, Telegram Bot, Notion) layer file-private wrappers on top of `request`/`arequest` because their wire envelope differs (Slack/Telegram bake `ok: bool` into the body, Notion returns errors as parsed JSON bodies). That's the only reason to deviate from the helper.

### OAuth example (using `OAuthFlow`)

For OAuth integrations, **compose** an `OAuthFlow` instance on the handler instead of writing the auth dance:

```python
from .. import OAuthFlow


@register_handler(ASANA.name)
class AsanaHandler(IntegrationHandler):
    spec = ASANA
    display_name = "Asana"
    description = "Tasks and projects"
    auth_type = "oauth"
    fields: List = []

    oauth = OAuthFlow(
        client_id_key="ASANA_CLIENT_ID",
        client_secret_key="ASANA_CLIENT_SECRET",
        auth_url="https://app.asana.com/-/oauth_authorize",
        token_url="https://app.asana.com/-/oauth_token",
        userinfo_url="https://app.asana.com/api/1.0/users/me",
        scopes="default",
    )

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"Asana OAuth failed: {result['error']}"
        info = result.get("userinfo", {}).get("data", {})
        save_credential(
            self.spec.cred_file,
            AsanaCredential(
                access_token=result["access_token"],
            ),
        )
        return True, f"Asana connected as {info.get('name')}"
```

`OAuthFlow.run()` opens the browser, captures the callback on localhost:8765, exchanges the code for tokens, and (optionally) fetches the userinfo. Supports PKCE, HTTPS callback, custom auth params.

### Auth types reference

| `auth_type`              | Meaning                                                                |
|--------------------------|------------------------------------------------------------------------|
| `token`                  | Raw token / API key paste                                              |
| `oauth`                  | Browser OAuth (uses `OAuthFlow` and the bundled localhost server)     |
| `both`                   | Has both an `invite` (OAuth) **and** a `login` (token) path           |
| `interactive`            | QR code scan or phone code (e.g. WhatsApp Web, Telegram user)         |
| `token_with_interactive` | Has both                                                              |

### Folder layout per integration

Each integration lives in its own folder under `integrations/`. The handler + client go in `__init__.py`, docs in `INTEGRATION.md`, and any supporting modules sit alongside with an **underscore prefix** so the autoloader skips them. Helpers shared by multiple integrations (`_google_common.py`, `_lark_common.py`) stay at the `integrations/` root.

```
craftos_integrations/integrations/
├── _google_common.py          ← shared by gmail / google_* (autoloader skips)
├── _lark_common.py            ← shared by lark / lark_* (autoloader skips)
├── discord/
│   ├── __init__.py            ← handler + client
│   ├── INTEGRATION.md
│   └── _discord_voice.py      ← skipped by autoloader
├── telegram_user/
│   ├── __init__.py
│   ├── INTEGRATION.md
│   └── _telegram_mtproto.py   ← skipped by autoloader
├── whatsapp_web/
│   ├── __init__.py
│   ├── INTEGRATION.md
│   ├── _bridge_client.py      ← skipped by autoloader
│   ├── bridge.js              ← Node sidecar
│   └── package.json
├── github/
│   └── __init__.py
└── ... (one folder per integration)
```

### File 2: agent actions (the `@action` wrappers)

File 1 lets a human connect the account and lets the listener receive inbound events. File 2 is what makes the integration **usable by the agent**. It lives at:

```
app/data/action/integrations/<name>/<name>_actions.py
```

Each function is decorated with `@action(...)` and resolves the client at runtime via `run_client` / `with_client` from [app/data/action/integrations/_helpers.py](app/data/action/integrations/_helpers.py). The helpers own the boilerplate (resolve the client, check credentials, await the method, wrap the result envelope, record a metric).

The 80% case — single client-method call:

```python
# app/data/action/integrations/asana/asana_actions.py
from agent_core import action


@action(
    name="list_asana_tasks",
    description="List tasks in an Asana project. Returns task GIDs, names, completed flag, and assignee.",
    action_sets=["asana_tasks", "asana"],
    input_schema={
        "project_gid": {
            "type": "string",
            "description": "Asana project GID.",
            "example": "1234567890",
        },
        "completed_since": {
            "type": "string",
            "description": "ISO timestamp; 'now' excludes completed.",
            "example": "now",
        },
        "per_page": {
            "type": "integer",
            "description": "Max results (default 30, max 100).",
            "example": 30,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_asana_tasks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "asana",
        "list_tasks",
        project_gid=input_data["project_gid"],
        completed_since=input_data.get("completed_since"),
        per_page=input_data.get("per_page", 30),
    )
```

**Critical: helper imports MUST go inside the function body.** Putting `from app.data.action.integrations._helpers import run_client` at the top of the module causes a `NameError: name 'run_client' is not defined` at action-invocation time — the `@action` decorator's runtime dispatch loses module-level imports. Every existing integration imports helpers inline; do the same. If you forget and your actions raise NameError at call time even though the module loads cleanly, this is why.

```python
# WRONG — module-top import, will NameError at call time
from app.data.action.integrations._helpers import run_client


@action(...)
async def my_action(input_data):
    return await run_client(...)


# RIGHT — import inside the function body
@action(...)
async def my_action(input_data):
    from app.data.action.integrations._helpers import run_client

    return await run_client(...)


@action(
    name="create_asana_task",
    description="Create a new task in an Asana project. Returns the new task GID.",
    action_sets=["asana_tasks", "asana"],
    input_schema={
        "project_gid": {
            "type": "string",
            "description": "Asana project GID.",
            "example": "1234567890",
        },
        "name": {
            "type": "string",
            "description": "Task title.",
            "example": "Ship Q3 report",
        },
        "notes": {
            "type": "string",
            "description": "Task description (Markdown).",
            "example": "",
        },
        "assignee": {
            "type": "string",
            "description": "Assignee user GID or email.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_asana_task(input_data: dict) -> dict:
    return await run_client(
        "asana",
        "create_task",
        project_gid=input_data["project_gid"],
        name=input_data["name"],
        notes=input_data.get("notes", ""),
        assignee=input_data.get("assignee") or None,
    )
```

What every `@action` must get right:

- **`name`** — globally unique, snake_case, verb-first (`list_*`, `get_*`, `create_*`, `update_*`, `delete_*`, `send_*`, `reply_*`). Include the integration name (`list_asana_tasks`, not `list_tasks`) — names collide across integrations otherwise.
- **`description`** — one sentence. The LLM reads this to decide whether to call the action. State WHAT it does, WHICH identifier it expects, and WHAT it returns. "Updates a task" is bad; "Update an Asana task by GID (name, notes, completed, assignee)." is good.
- **`action_sets`** — see "Action set conventions" below. Always at least the fine-grained set; add the umbrella for high-value actions.
- **`input_schema` / `output_schema`** — keys map 1:1 to `input_data` dict keys. Always include `example` values; the agent uses them as hints when constructing arguments.
- **`parallelizable=False`** — set on every action that mutates state (create / update / delete / send / reply / move / archive). Read actions can stay parallelizable (the default).

When a single `run_client` call isn't enough — paging, multi-step payload building, sequenced API calls — use `with_client` instead:

```python
@action(name="archive_completed_asana_tasks", ...)
async def archive_completed_asana_tasks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    async def _go(client):
        tasks = await client.list_tasks(project_gid=input_data["project_gid"], completed=True)
        for t in tasks.get("result", []):
            await client.update_task(t["gid"], archived=True)
        return {"archived": len(tasks.get("result", []))}
    return await with_client("asana", _go)
```

For bespoke result shapes (or when you need to do real pre/post-processing on the result), grab the client manually with `get_client_or_error` — it returns `(client, error_dict)` so you can short-circuit on the credential check and then build whatever envelope you need. See [github_actions.py:3514](app/data/action/integrations/github/github_actions.py#L3514) for an example.

### Action set conventions (sub-sets + umbrella)

The agent doesn't load every action up front — it loads the **action sets** it needs for the current task. For an integration with 50+ actions this matters a lot for token cost. The convention, refined across the 16 expansions (GitHub: 107 actions, Telegram: 76, Jira: 61, Twitter: 46, Notion: 29), is:

1. **Prefix every set with the integration name.** Never use bare verbs like `messages` or `tasks` — always `asana_tasks`, `asana_projects`, `asana_users`. Prevents collisions across integrations and makes it obvious in logs which integration a set belongs to.

2. **One fine-grained set per resource category.** Group by the noun the action operates on, not the verb. For Asana that would be roughly:

   | Sub-set | Covers |
   |---------|--------|
   | `asana_tasks` | Task CRUD + complete/uncomplete/move/duplicate/dependencies |
   | `asana_projects` | Project + sections CRUD, project templates, project briefs |
   | `asana_comments` | Stories / comments on tasks and projects |
   | `asana_attachments` | Upload / list / delete attachments |
   | `asana_users` | User lookup, workspace + team membership |
   | `asana_teams` | Team CRUD + membership |
   | `asana_tags` | Tag CRUD, tag/untag |
   | `asana_custom_fields` | Custom field definitions + values |
   | `asana_webhooks` | Webhook CRUD (for inbound events) |
   | `asana_search` | Typeahead + saved searches + advanced search |
   | `asana_goals` | Goals, goal relationships, progress |
   | `asana_time_tracking` | Time tracking entries |
   | `asana_listener` | Runtime knobs for the listener (set watch project, set polling interval) |

3. **One umbrella set covering the high-value ~20%.** Add the integration name (`"asana"`) as a second tag on the actions most users will actually want — typically:
   - Primary-noun CRUD: list/get/create/update/delete on tasks
   - Primary-noun comments (add a comment, list comments)
   - Search
   - 1–2 actions per remaining major category

   ```python
   action_sets = ["asana_tasks", "asana"]  # in the umbrella — high-value
   action_sets = ["asana_tasks"]  # niche — fine-grained only
   ```

   Target umbrella size: **15–25 actions**. The agent loads the umbrella by default when the user says "use Asana"; the fine-grained sets get loaded only when the user says something specific like "manage Asana webhooks".

4. **Listener / config actions go in `<name>_listener`** (or `<name>_notifications` if there's already a notification surface). Never put them in the noun sets — they're operational, not domain operations. Examples: `set_asana_watch_projects`, `set_asana_polling_interval`.

5. **Document what you intentionally dropped.** At the bottom of `<name>_actions.py`, leave a comment block listing the API surface you chose NOT to expose, with one line per category explaining why. See [github_actions.py:3576](app/data/action/integrations/github/github_actions.py#L3576) for the canonical exclusion block. This prevents the next person (or the next session) from re-litigating the same scope decision.

### Production-level expectations

"Production" means the integration is good enough to be the user's daily driver for that service, not a tech demo. Concretely:

1. **Coverage: enumerate the full official surface, then trim.** Before writing code, list every endpoint group in the vendor's docs. For Asana that's Tasks, Projects, Sections, Workspaces, Users, Teams, Stories, Tags, Custom Fields, Webhooks, Portfolios, Goals, Attachments, Time Tracking, Status Updates, Project Templates, Project Memberships, Project Briefs, Organization Exports, Audit Log API. For each: would an agent realistically use this? Keep tasks/projects/comments/attachments/webhooks/search/goals. Drop billing, enterprise admin, audit log, org exports. Write the dropped list into the exclusion block.

2. **Match the established scale.** The 16 expanded integrations cluster around **30–75 actions**. Fewer than 30 almost always means you missed the edit/delete/reply/attachment surface. Don't ship `list_*` + `create_*` and call it done.

3. **Mirror the API's verb set on every primary noun.** For every list/get/create, also expose update/delete unless the API genuinely doesn't support it. Lifecycle gaps (can read but can't reply, can send but can't edit, can post a comment but can't delete it) are what made the 16 backlog items necessary in the first place — don't recreate them on new integrations.

4. **Standard envelope everywhere.** Every client method returns the `Result` envelope from `helpers.request` / `arequest` (`{ok, result}` or `{error, details}`). Action wrappers translate that to `{status: success|error, ...}` via `run_client`. Don't invent a third shape. The three integrations that wrap `request` (Slack, Telegram Bot, Notion) do so only because their wire envelope already bakes in an `ok` field — that's the only valid reason to deviate.

5. **Pagination on every list action.** `per_page` parameter (default 30, max 100). When the API exposes a cursor/offset/next-token, surface it in the output — the agent chains list calls.

6. **Identifier discipline.** Pick one canonical identifier shape per resource and document it in the action `description`. GitHub: `owner/repo#number`. Notion: dashed UUIDs. Asana: numeric GIDs as strings (NOT ints — they overflow JS). Linear: identifier strings like `ENG-123`. Inconsistency here turns into "agent constructs an ID and the API 404s" failures.

7. **`connect_help` always populated.** Users need a 3–5 step recipe for "where do I find this token / app ID / etc." Test the steps yourself by following them in a fresh browser session before shipping. Outdated steps are worse than no steps.

8. **`INTEGRATION.md` at the integration root.** One page of gotchas: identifier shape rules, silent-drop config flags (like GitHub's `watch_tag`), session-level facts (e.g. "username is on the credential, don't ask the user"), known auth failure modes (e.g. "403 means token lacks scope, retrying won't help"). See [github/INTEGRATION.md](craftos_integrations/integrations/github/INTEGRATION.md) for shape.

9. **Token / rate-limit hygiene.** If the API has known rate limits, document them in `INTEGRATION.md` and bake a sensible default into the client (back-off, polling interval). The polling integrations (GitHub at 15s, others vary) tune this per-API.

10. **Concurrency-safe writes.** Anywhere the client mutates remote state, the matching action MUST set `parallelizable=False`. Otherwise the runtime will fan out duplicate creates.

### Verification

Before declaring an integration done, run these three checks. Don't skip any.

1. **Imports cleanly and registers** — both must print `True`:

   ```bash
   python -c "
   from craftos_integrations import autoload_integrations, get_handler, get_client
   autoload_integrations(force=True)
   print('handler:', get_handler('<name>') is not None)
   print('client :', get_client('<name>') is not None)
   "
   ```

   If either is False, a decorator didn't fire — usually because the module raised on import. Check the autoloader warning log line.

2. **AST action-count audit** — confirms the sub-set / umbrella distribution matches the design:

   ```bash
   python -c "
   import ast, collections
   src = open('app/data/action/integrations/<name>/<name>_actions.py').read()
   tree = ast.parse(src)
   counts = collections.Counter()
   total = 0
   for node in ast.walk(tree):
       if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'action':
           total += 1
           for kw in node.keywords:
               if kw.arg == 'action_sets':
                   for s in kw.value.elts:
                       counts[s.value] += 1
   for set_name, n in sorted(counts.items()): print(f'  {set_name:32s} {n}')
   print(f'  TOTAL @action: {total}')
   "
   ```

   Expected shape: the umbrella set should be 15–25; fine-grained sets sum to the total; no set under 3 actions (merge it if so).

3. **Live smoke test** — the only check that catches "the code runs but the API doesn't actually accept what we send". Connect with a real account and run one action per sub-set:

   ```
   /<name> login <credential>
   # In chat:
   "list my recent <thing>"                       → list_<name>_<thing>, returns real data
   "create a test <thing> called 'smoke test'"    → create_<name>_<thing>
   "comment 'hi' on that <thing>"                 → add_<name>_comment
   "delete the test <thing>"                      → delete_<name>_<thing>
   ```

   Hand the user a checklist of 5–10 representative prompts (one per sub-set) before claiming the integration is done. Without a live smoke test, "production-ready" is a guess.

---

## Public API reference

### Setup
- `configure(*, project_root, logger, oauth, oauth_runner, onboarding_hook, extras)` — call once at startup
- `initialize_manager(*, on_message, auto_start=True) -> ExternalCommsManager`
- `get_external_comms_manager() -> ExternalCommsManager | None`

### Registry
- `autoload_integrations(force=False)` — walks `integrations/`, imports every file (decorators fire)
- `register_client`, `register_handler(name)` — decorators
- `get_client(platform_id)` / `get_handler(name)` — singleton per registered class
- `get_all_clients()` / `get_all_handlers()`
- `get_registered_platforms()` / `get_registered_handler_names()`

### Common ops (the facade)
- `send_message(integration, recipient, text, **kw) -> dict` (async)
- `is_connected(integration) -> bool`
- `list_connected() -> list[str]` — names of platforms that have stored credentials
- `list_all() -> list[str]` — every registered integration
- `disconnect(integration, account_id=None) -> (bool, str)` (async)
- `status(integration) -> (bool, str)` (async)

### Connect dispatchers (auto-start listener on success)
- `connect_token(integration, creds: dict, *, start_listener=True) -> (bool, str)`
- `connect_oauth(integration, *, start_listener=True) -> (bool, str)`
- `connect_interactive(integration, *, start_listener=True) -> (bool, str)`

### Metadata
- `get_metadata(integration) -> dict | None`
  - Shape: `{id, name, description, auth_type, fields, icon, has_config, config_fields, connect_help}`
  - `has_config: bool` — True when the handler declared a `config_class`
  - `config_fields: list[dict] | None` — the runtime-config render schema (None when no config)
  - `connect_help: list[str] | None` — inline setup steps for the `?` popover
- `list_metadata() -> list[dict]`
- `integration_registry() -> dict[str, dict]`
- `get_integration_info(integration) -> dict` (async; metadata + live `connected` + `accounts`)
- `list_integrations() -> list[dict]` (async)
- `parse_status_accounts(msg) -> list[dict]`

### Per-integration runtime config (post-connect knobs)
- `get_config(integration) -> dict | None` — current values; defaults when no file yet; `None` if no `config_class` declared
- `update_config(integration, values: dict) -> (bool, str)` — coerces values per the schema, persists
- `get_config_schema(integration) -> list[dict] | None` — the `config_fields` list, for rendering a form

### Sync flavors (for synchronous callers)
- `list_integrations_sync()`
- `get_integration_info_sync(integration)`
- `get_integration_fields(integration)`
- `get_integration_auth_type(integration)`
- `get_integration_accounts(integration)`

### Credentials
- `save_credential(filename, dataclass_instance)`
- `load_credential(filename, cls) -> instance | None`
- `has_credential(filename) -> bool`
- `remove_credential(filename) -> bool`

### Config (same on-disk layout, `_config.json` suffix)
- `save_config(filename, dataclass_instance)` — filename should end in `_config.json`
- `load_config(filename, cls) -> instance | None`
- `has_config(filename) -> bool`
- `remove_config(filename) -> bool`

### OAuth helper
- `OAuthFlow(*, client_id_key, client_secret_key, auth_url, token_url, userinfo_url=None, scopes, use_pkce=False, use_https=False, ...)`
- `REDIRECT_URI` / `REDIRECT_URI_HTTPS` — the bundled callback URLs

### HTTP helpers (package-internal, used by every REST integration)
- `from craftos_integrations.helpers import request, arequest, Result, Ok, Err`
- `request(method, url, *, headers, json, params, data, files, expected=(200, 201), transform=None, timeout=15.0) -> Result` — sync httpx wrapper
- `arequest(...) -> Result` — async variant
- `Result` — `Ok | Err` TypedDict union for return annotations

### Discovery
- `PLATFORM_TO_ACTION_SET` / `ACTION_SET_SEND_ACTIONS` — for an action router
- `get_connected_messaging_platforms() -> list[str]`
- `get_messaging_actions_for_platforms(platforms) -> list[str]`

### WhatsApp Web QR (non-blocking UIs)
- `from craftos_integrations.integrations.whatsapp_web import (start_qr_session, check_qr_session_status, cancel_qr_session)`

---

## Listener wiring details

When a successful connect happens, the `connect_token/oauth/interactive` dispatchers automatically call `manager.start_platform(handler.spec.platform_id)`. The manager:

1. Resolves the registered `BasePlatformClient` for that `platform_id`.
2. If `client.supports_listening` is True and `client.has_credentials()` is True, calls `client.start_listening(callback)`.
3. The client polls / connects via WebSocket / spawns its bridge, normalizes incoming events to a `PlatformMessage`, and the manager forwards the normalized dict to `on_message`.

Stop ordering is symmetric: `manager.stop_platform(...)` → `client.stop_listening()` → cancels the poll loop / closes the gateway.

---

## Where credentials live

```
<project_root>/.credentials/
├── github.json               github_config.json            ← optional runtime-config sibling
├── gmail.json                gmail_config.json
├── google_calendar.json      …
├── google_docs.json
├── google_drive.json
├── google_youtube.json
├── slack.json
├── discord.json              discord_config.json
├── jira.json                 jira_config.json
├── linkedin.json
├── notion.json
├── outlook.json
├── twitter.json              twitter_config.json
├── line.json                 line_config.json
├── lark.json
├── telegram_bot.json         telegram_bot_config.json
├── telegram_user.json        telegram_user_config.json
├── whatsapp_business.json
├── whatsapp_web.json         whatsapp_web_config.json
└── whatsapp_wwebjs_auth/     ← WhatsApp Web's wwebjs session (browser profile dir)
```

Two file types live side-by-side: `<name>.json` holds the credential (token, OAuth refresh token, session) and `<name>_config.json` holds the optional post-connect runtime config (watch tags, allowlists, filters). Both are written with mode `0600`; the directory is `0700`. Format is the dataclass serialized via `asdict()`.

---

## Glossary

| Term                     | Meaning                                                                |
|--------------------------|------------------------------------------------------------------------|
| `IntegrationSpec`        | Frozen dataclass shared between handler and client (composition glue) |
| `IntegrationHandler`     | Auth lifecycle ABC: login / logout / status / invite / connect_*      |
| `BasePlatformClient`     | Runtime lifecycle ABC: connect / send_message / start_listening / stop_listening |
| `PlatformMessage`        | Normalized incoming-message dataclass (every listener emits these)    |
| `ConfigStore`            | Singleton holding the host's setup (populated by `configure(...)`)    |
| `ExternalCommsManager`   | Owns active listeners + on_message routing                            |
| `OAuthFlow`              | Composition helper for OAuth handlers; runs the localhost callback server + token exchange |
| `autoload_integrations`  | Walks `integrations/` and imports every module (triggers decorators)  |
| `display_name` / `name` / `platform_id` | UI label / handler-registry key (slash command) / client-registry key |
| `Result` / `Ok` / `Err`  | TypedDicts for the standard `{ok, result} / {error, details}` envelope |
| `request` / `arequest`   | Sync/async httpx wrappers in `helpers/` that emit the standard envelope |
