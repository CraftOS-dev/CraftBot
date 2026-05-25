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
from craftos_integrations import configure, initialize_manager, get_handler, send_message

async def on_message(payload: dict) -> None:
    # payload keys: source, integrationType, contactId, contactName,
    #               messageBody, channelId, channelName, messageId,
    #               is_self_message, raw
    print(f"[{payload['source']}] {payload['contactName']}: {payload['messageBody']}")

async def main():
    configure(
        project_root=Path.cwd(),
        oauth={
            "GITHUB_CLIENT_ID":    os.getenv("GITHUB_CLIENT_ID"),
            "GOOGLE_CLIENT_ID":    os.getenv("GOOGLE_CLIENT_ID"),
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
    "source":          "Discord",                # human display name (handler.display_name)
    "integrationType": "discord",                # platform_id
    "contactId":       "<sender id>",
    "contactName":     "<sender display name>",
    "messageBody":     "<text>",
    "channelId":       "<channel/chat id>",
    "channelName":     "<channel/chat name>",
    "messageId":       "<platform message id>",
    "is_self_message": False,
    "raw":             { ... },                  # full original platform event
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
        {"key": "mention_only", "label": "Only when @-mentioned", "type": "checkbox",
         "help": "Drop messages that don't @-mention the bot."},
        {"key": "third_party_usernames", "label": "Allowed users", "type": "list",
         "placeholder": "alice, bob",
         "help": "Comma-separated Discord usernames or display names."},
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
    get_config,         # current values as a plain dict (defaults if no file yet)
    update_config,      # write new values; coerces per the schema
    get_config_schema,  # the config_fields list, for rendering a settings form
)

get_config("discord")
# → {"mention_only": False, "third_party_usernames": []}

ok, msg = update_config("discord", {"mention_only": True, "third_party_usernames": "alice, bob"})
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
from craftos_integrations import connect_token, connect_oauth, connect_interactive, disconnect

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

list_metadata()                # all integrations as a list
get_metadata("slack")          # single integration
integration_registry()         # snapshot dict {id: metadata}
```

---

## Adding a new integration

One file. Drop it in `craftos_integrations/integrations/<name>.py`. The autoloader picks it up at startup.

### Minimal token-only example (e.g. Asana)

```python
# craftos_integrations/integrations/asana.py
from dataclasses import dataclass, field
from typing import List, Tuple

from .. import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    has_credential, load_credential, save_credential, remove_credential,
    register_client, register_handler,
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
    icon = "asana"                                              # Lucide icon name or frontend brand-SVG key
    fields = [
        {"key": "access_token", "label": "Personal Access Token",
         "placeholder": "1/12345...", "password": True},
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
        {"key": "project_filter", "label": "Watched projects", "type": "list",
         "placeholder": "GID1, GID2",
         "help": "Comma-separated Asana project GIDs. Empty = watch all."},
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        # `args` is the credential values in field-declaration order
        # (the default connect_token() on the ABC builds it from a dict)
        token = args[0] if args else ""
        if not token:
            return False, "Personal access token is required."

        result = http_request(
            "GET", "https://app.asana.com/api/1.0/users/me",
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
            "POST", f"https://app.asana.com/api/1.0/tasks/{recipient}/stories",
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
        save_credential(self.spec.cred_file, AsanaCredential(
            access_token=result["access_token"],
        ))
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
