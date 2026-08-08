# Write a custom integration

An integration connects the agent to an external service such as a messaging platform or a SaaS API. It lives in the `craftos_integrations` package and is built from three pieces bound by composition: a spec that both other pieces share, a handler that owns the auth lifecycle, and a client that owns the runtime lifecycle. A separate set of `@action` wrappers exposes the client's methods to the agent. This page walks through all of them in order.

The canonical recipe is in `craftos_integrations/README.md`. Read it before you start a real integration. This page is the developer-facing summary of that recipe with links into the rest of the docs.

## Architecture

Every integration declares three objects:

| Object | Base class | Owns | Registered by |
|---|---|---|---|
| `IntegrationSpec` | frozen dataclass | The name, `platform_id`, credential dataclass, and credential filename shared by the other two | assigned as a class attribute |
| Handler | `IntegrationHandler` | Auth lifecycle: `login`, `logout`, `status`, and the connect dispatchers | `@register_handler("<name>")` |
| Client | `BasePlatformClient` | Runtime lifecycle: `connect`, `send_message`, and optional `start_listening` / `stop_listening` | `@register_client` |

The handler and client do not share a base class. They collaborate by both holding the same `IntegrationSpec` instance. That is the composition the framework relies on. Both classes register themselves through decorators, and `autoload_integrations()` imports every module under `integrations/` at startup so those decorators fire. Modules and folders whose names start with an underscore are skipped by the autoloader, which is how shared helper modules stay out of the discovery path.

Because discovery is decorator-driven, adding an integration requires no edit to any central registry, manager, or `__init__.py`. You drop the files in place and restart the host.

## Directory layout

An integration is two folders. The platform package holds the handler and client. The action surface holds the `@action` wrappers.

```
craftos_integrations/integrations/<name>/
├── __init__.py            # handler + client (both decorators fire here)
├── INTEGRATION.md         # identifier shapes, auth gotchas, config flags
└── _internal_helper.py    # optional; underscore prefix skips the autoloader

app/data/action/integrations/<name>/
└── <name>_actions.py      # one @action wrapper per client method
```

The two files have different audiences. The `__init__.py` serves the human who connects the account and the listener that receives inbound events. The `<name>_actions.py` serves the agent calling the API on the user's behalf. You need both for the integration to be usable.

## Step 1: Define the spec

The spec is a single frozen dataclass instance shared by the handler and the client. Declare it once alongside the credential dataclass that holds the stored token.

```python
from dataclasses import dataclass
from .. import IntegrationSpec


@dataclass
class AsanaCredential:
    access_token: str = ""
    workspace_id: str = ""


ASANA = IntegrationSpec(
    name="asana",          # handler registry key, also the slash command
    platform_id="asana",   # client registry key; defaults to name
    cred_class=AsanaCredential,
    cred_file="asana.json",
)
```

## Step 2: Implement the handler

The handler subclasses `IntegrationHandler`, carries `spec = ASANA`, and declares UI metadata. Pick the `auth_type` first because it determines the rest of the shape:

| `auth_type` | Meaning |
|---|---|
| `token` | The user pastes a raw token or API key |
| `oauth` | Browser OAuth through `OAuthFlow` |
| `both` | An `invite` OAuth path and a `login` token path |
| `interactive` | QR scan or phone code |
| `token_with_interactive` | Both token and interactive |

Implement `login`, `logout`, and `status`. The `login` method validates the credential against the real API, then persists it with `save_credential`. Register the class with `@register_handler`.

```python
from typing import List, Tuple
from .. import (
    IntegrationHandler, register_handler,
    has_credential, save_credential, remove_credential,
)
from ..helpers import request as http_request


@register_handler(ASANA.name)
class AsanaHandler(IntegrationHandler):
    spec = ASANA
    display_name = "Asana"
    description = "Tasks and projects"
    auth_type = "token"
    icon = "asana"
    fields = [
        {"key": "access_token", "label": "Personal Access Token",
         "placeholder": "1/12345...", "password": True},
    ]
    connect_help = [
        "Open https://app.asana.com/0/my-apps",
        "Click 'Create new token', name it, and copy the token",
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        token = args[0] if args else ""
        if not token:
            return False, "Personal access token is required."
        result = http_request(
            "GET", "https://app.asana.com/api/1.0/users/me",
            headers={"Authorization": f"Bearer {token}"}, expected=(200,),
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
```

The `fields` list drives the connect form and defines the order in which values arrive in `login`. The `connect_help` list is the numbered guidance shown when the user asks where to find the credential.

## Step 3: Implement the client

The client subclasses `BasePlatformClient`, carries the same `spec`, and holds one method per API endpoint. Each method returns the standard envelope from the HTTP helpers, which is `{"ok": True, "result": ...}` on success and `{"error": ..., "details": ...}` on failure. Register it with `@register_client`.

```python
from typing import Any, Dict
from .. import BasePlatformClient, register_client, load_credential
from ..helpers import Result, request as http_request


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
        cred = self._load()
        return http_request(
            "POST", f"https://app.asana.com/api/1.0/tasks/{recipient}/stories",
            headers={"Authorization": f"Bearer {cred.access_token}"},
            json={"data": {"text": text}},
            transform=lambda d: d.get("data"),
        )

    def list_tasks(self, project_gid: str, per_page: int = 30) -> Result:
        cred = self._load()
        return http_request(
            "GET", "https://app.asana.com/api/1.0/tasks",
            headers={"Authorization": f"Bearer {cred.access_token}"},
            params={"project": project_gid, "limit": per_page},
        )
```

Use `helpers.request` for synchronous calls and `helpers.arequest` for async ones. Both wrap httpx and emit the standard envelope. Pass `expected=(...)` to override the accepted status codes, `transform=` to reshape the body, and `timeout=` to override the default. Do not invent a third result shape. The action-side helpers translate this envelope into the agent-facing response.

At this point the platform package is done. Restart the host and `get_handler("asana")` and `get_client("asana")` both resolve.

## Step 4: Add the agent actions

The client is not yet visible to the agent. Add `@action` wrappers at `app/data/action/integrations/asana/asana_actions.py`, one per client method. Each wrapper resolves the client at runtime through `run_client` from `_helpers.py`, which checks credentials, calls the method, and wraps the envelope into the agent-facing `{"status": ...}` shape.

```python
from agent_core import action


@action(
    name="list_asana_tasks",
    description="List tasks in an Asana project by GID. Returns task GIDs, names, and assignees.",
    action_sets=["asana_tasks", "asana"],
    input_schema={
        "project_gid": {"type": "string", "description": "Asana project GID.", "example": "1234567890"},
        "per_page": {"type": "integer", "description": "Max results (default 30, max 100).", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_asana_tasks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "asana", "list_tasks",
        project_gid=input_data["project_gid"],
        per_page=input_data.get("per_page", 30),
    )
```

The `run_client` import goes inside the function body. A top-level import raises `NameError` at call time because the registry runs each action's extracted source on its own, where module-level names are out of scope. This rule is covered in full in [Write a custom action](custom-action.md#import-rule-for-helpers). Set `parallelizable=False` on every action that mutates state, and set `irreversible=True` on sends and posts.

Group actions into sets prefixed with the integration name. Use one fine-grained set per resource noun, such as `asana_tasks` and `asana_projects`, and add a single umbrella set named for the integration, such as `asana`, on the high-value actions. The agent loads the umbrella when the user says "use Asana" and loads a fine-grained set only when the task needs it. For the action-writing details, read [Write a custom action](custom-action.md).

## Credentials and config storage

Two file types live side by side in `<project_root>/.credentials/`. The credential file `<name>.json` holds the token or session. The optional config file `<name>_config.json` holds post-connect runtime settings such as watch filters. Both are written with restrictive permissions, and each is the dataclass serialized to JSON.

| Function | Purpose |
|---|---|
| `save_credential(filename, instance)` | Write a credential dataclass to `<filename>` |
| `load_credential(filename, cls)` | Read it back into `cls`, or `None` if absent |
| `has_credential(filename)` | Whether the credential file exists |
| `remove_credential(filename)` | Delete the credential file |

The config functions mirror these as `save_config`, `load_config`, `has_config`, and `remove_config`, with filenames ending in `_config.json`. To expose runtime knobs, declare a `config_class` dataclass and a `config_fields` render schema on the handler, then read the current values inside the client with `load_config` on each inbound message. Reading fresh each time keeps config changes effective without a restart. Unknown keys in an older config file are dropped on load and missing fields fall back to defaults, so adding or removing a field does not break existing installs. Where credentials are stored and how they are reported is covered in [Credentials](../integrations/credentials.md).

## OAuth with OAuthFlow

For an OAuth integration, compose an `OAuthFlow` instance on the handler instead of writing the browser dance yourself. Set `auth_type = "oauth"` and call `self.oauth.run()` from `login`.

```python
from .. import OAuthFlow


@register_handler(ASANA.name)
class AsanaHandler(IntegrationHandler):
    spec = ASANA
    auth_type = "oauth"
    fields: list = []

    oauth = OAuthFlow(
        client_id_key="ASANA_CLIENT_ID",
        client_secret_key="ASANA_CLIENT_SECRET",
        auth_url="https://app.asana.com/-/oauth_authorize",
        token_url="https://app.asana.com/-/oauth_token",
        userinfo_url="https://app.asana.com/api/1.0/users/me",
        scopes="default",
        use_pkce=True,
    )

    async def login(self, args) -> tuple:
        result = await self.oauth.run()
        if "error" in result and not result.get("access_token"):
            return False, f"Asana OAuth failed: {result['error']}"
        save_credential(self.spec.cred_file,
                        AsanaCredential(access_token=result["access_token"]))
        return True, "Asana connected"
```

`OAuthFlow.run()` opens the browser, captures the redirect on the bundled localhost callback, exchanges the code for tokens, and optionally fetches user info. Set `use_pkce=True` for the PKCE code exchange, which the Google integrations use.

Whether to embed shared client credentials or require the user to bring their own depends on identity, quota, and suspension scope. When the API call carries the user's own identity and the user's own quota and suspension risk, embed the CraftBot client credentials for a one-click connect and name the env keys with a `_SHARED_` infix. When your credentials would act as one shared identity across all users, or pool rate limits and suspension risk across all users, the user must supply their own credentials. The README works through Discord, Jira, and Twitter as the canonical cases. See [Credentials](../integrations/credentials.md) for how the two paths surface.

## Listeners and triggers

A client that receives inbound events overrides `supports_listening` to return `True` and implements `start_listening(callback)` and `stop_listening()`. When a connect succeeds, the manager resolves the client, and if it supports listening and has credentials, calls `start_listening`. The client polls, opens a WebSocket, or spawns its bridge, normalizes each inbound event into a `PlatformMessage`, and passes it to the callback. The manager forwards the normalized payload to the host, which turns it into an agent trigger. Stopping is symmetric through `stop_listening`. How a received message becomes a task is covered in [Triggers](../core/concepts/triggers.md).

Give the client a stored cursor or timestamp so a restarted listener does not replay old events, and back off after a poll error rather than retrying in a tight loop. The Slack client in `craftos_integrations/integrations/slack/__init__.py` is a complete polling reference.

## Production checklist

Before you call an integration done, confirm the following from the README:

- Enumerate the vendor's full endpoint surface, then trim to what an agent would use. Write the dropped categories into an exclusion comment at the bottom of `<name>_actions.py`.
- Mirror the full verb set on every primary noun. An integration that can `list` but not `update`, `delete`, or `reply` is the top cause of agent failure.
- Return the standard envelope from every client method, and set `parallelizable=False` on every write action.
- Add pagination to every list action with a `per_page` parameter defaulting to 30 and capped at 100.
- Pick one canonical identifier shape per resource and document it in each action `description`.
- Populate `connect_help` with three to five verified steps, and write `INTEGRATION.md` with identifier rules and known auth failure modes.
- Verify with an import-and-register check, an action-count audit over the actions file, and a live smoke test that runs one action per set against a real account.

## Next

- [Integrations](../integrations/index.md): the catalogue of shipped integrations and their action sets
- [Credentials](../integrations/credentials.md): where tokens are stored and how the two auth paths surface
- [Write a custom action](custom-action.md): the `@action` decorator, schemas, and the helper import rule
