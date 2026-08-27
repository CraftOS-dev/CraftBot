# Write a custom integration

An integration connects the agent to an external service such as a messaging
platform or a SaaS API. It lives in the `craftos_integrations` package as one
folder holding two objects: a **provider** that declares everything the
framework needs to know, and a **client** that talks to the API. A separate set
of `@action` wrappers exposes the client's methods to the agent. This page
walks through all of them in order.

The canonical recipe is in `craftos_integrations/README.md`. Read it before you
start a real integration. This page is the developer-facing summary of that
recipe with links into the rest of the docs.

## Architecture

| Object | Owns | Registered by |
|---|---|---|
| Provider | Metadata, auth, account identity, token refresh, operations, listener | listed in `providers/__init__.py::default_providers()` |
| Client (`BasePlatformClient`) | The API surface: `connect`, `send_message`, the REST methods, optional `start_listening` / `stop_listening` | `@register_client` |
| `IntegrationSpec` | The client's name, `platform_id`, credential dataclass and filename | assigned as a class attribute |

The provider is what the framework talks to. The client is what the agent's
actions talk to. They meet at `Provider.build_client(credential, persist)`,
which returns a client bound to **one account's** credential — clients never
read credential files themselves, which is what makes multi-account work.

`autoload_integrations()` imports `providers/<name>/client.py` at startup so
`@register_client` fires. Adding an integration therefore needs exactly one
central edit: appending your provider to `default_providers()`.

## Directory layout

An integration is two folders. The provider package holds the framework side.
The action surface holds the `@action` wrappers.

```
craftos_integrations/providers/<name>/
├── provider.py            # the contract: metadata, auth, identity, listener
├── client.py              # the API client (@register_client fires here)
├── operations.py          # optional; agent-facing operation schemas
├── listener.py            # optional; a poll loop, if the client has none
├── INTEGRATION.md         # identifier shapes, auth gotchas, config flags
├── GUIDANCE.md            # optional; just-in-time agent guidance
└── _internal_helper.py    # optional; underscore prefix, reached via the provider

app/data/action/integrations/<name>/
└── <name>_actions.py      # one @action wrapper per client method
```

The two folders have different audiences. The provider folder serves the human
who connects the account and the listener that receives inbound events. The
`<name>_actions.py` serves the agent calling the API on the user's behalf. You
need both for the integration to be usable.

## Step 1: Define the spec and credential

Declare the credential dataclass and the spec once, at the top of `client.py`.

```python
from dataclasses import dataclass

from ... import IntegrationSpec


@dataclass
class AsanaCredential:
    access_token: str = ""
    workspace_id: str = ""


ASANA = IntegrationSpec(
    name="asana",
    platform_id="asana",  # client registry key; defaults to name
    cred_class=AsanaCredential,
    cred_file="asana.json",
)
```

## Step 2: Implement the client

The client owns the API surface. It must **not** read credentials from disk —
`has_credentials` and `_load` answer from the credential the provider injects.

```python
from typing import Optional

from ... import BasePlatformClient, register_client
from ...helpers import Result, request as http_request

ASANA_API = "https://app.asana.com/api/1.0"


@register_client
class AsanaClient(BasePlatformClient):
    spec = ASANA
    PLATFORM_ID = ASANA.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[AsanaCredential] = None

    def has_credentials(self) -> bool:
        return self._cred is not None

    def _load(self) -> AsanaCredential:
        if self._cred is None:
            raise RuntimeError("client used before bind_credential()")
        return self._cred

    async def connect(self) -> None:
        self._load()
        self._connected = True

    def list_tasks(self, project_gid: str, per_page: int = 30) -> Result:
        return http_request(
            "GET",
            f"{ASANA_API}/tasks",
            headers={"Authorization": f"Bearer {self._load().access_token}"},
            params={"project": project_gid, "limit": per_page},
            expected=(200,),
            transform=lambda d: d.get("data", []),
        )
```

## Step 3: Implement the provider

The provider declares the UI metadata, proves a credential works, and derives a
stable **account identity** from it. Pick the `auth_type` first because it
determines the rest of the shape.

| `auth_type` | Implement | Connect path |
|---|---|---|
| `token` | `verify_token` | Host collects `fields`, provider verifies |
| `oauth` | `oauth_spec` | `IntegrationSystem.add_account()` runs the flow |
| `both` | both | Either |
| `interactive` | a bespoke flow | e.g. WhatsApp Web's QR session |

```python
from dataclasses import asdict, fields
from typing import Any, Dict, List, Optional, Tuple

from ...contracts import OAuthSpec, Operation
from ...helpers import request as http_request
from .client import ASANA_API, AsanaClient, AsanaCredential

_CRED_FIELDS = {f.name for f in fields(AsanaCredential)}


class BoundAsanaClient(AsanaClient):
    def bind_credential(self, credential, persist) -> None:
        self._cred = AsanaCredential(
            **{k: v for k, v in credential.items() if k in _CRED_FIELDS}
        )
        self._persist = persist


class AsanaProvider:
    id = "asana"
    display_name = "Asana"
    description = "Tasks and projects"
    auth_type = "token"
    icon = "asana"
    fields = [
        {
            "key": "access_token",
            "label": "Personal Access Token",
            "placeholder": "1/1234...",
            "password": True,
        },
    ]
    connect_help = [
        "Open Asana: app.asana.com/0/my-apps",
        "Create a Personal Access Token and copy it",
    ]

    family = None
    client_cls = BoundAsanaClient

    def identity_of(self, credential: Dict[str, Any]) -> Optional[str]:
        gid = credential.get("user_gid")
        return gid.strip().lower() if isinstance(gid, str) and gid.strip() else None

    def oauth_spec(self) -> OAuthSpec:
        raise NotImplementedError("asana is token-only")

    def verify_token(self, credentials) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        token = (credentials.get("access_token") or "").strip()
        if not token:
            return False, "Access token is required.", None
        result = http_request(
            "GET",
            f"{ASANA_API}/users/me",
            headers={"Authorization": f"Bearer {token}"},
            expected=(200,),
        )
        if "error" in result:
            return False, f"Invalid token: {result['error']}", None
        me = (result.get("result") or {}).get("data", {})
        credential = asdict(AsanaCredential(access_token=token))
        credential["user_gid"] = me.get("gid", "")
        return True, f"Asana connected: {me.get('name', 'account')}", credential

    def build_client(self, credential, persist) -> Any:
        client = self.client_cls()
        client.bind_credential(credential, persist)
        return client

    async def refresh(self, credential) -> Optional[Dict[str, Any]]:
        return None  # PATs do not rotate

    def operations(self) -> List[Operation]:
        return []  # the action layer is the tool surface

    def guidance(self) -> str:
        return ""

    def make_listener(self, client, cursor, emit):
        return None  # no inbound events
```

`identity_of` is the one method to get right. It returns the stable key that
distinguishes two accounts of the same integration — an email, a workspace id,
a bot user id. Returning `None` is allowed: the core stores that credential
under the `UNIDENTIFIED` sentinel and upgrades the record in place on the first
re-auth that does yield an identity, so a second connect never silently
overwrites the first account.

Finally, add the provider to `default_providers()` in
`craftos_integrations/providers/__init__.py`.

## Step 4: Add the agent actions

The client is not yet visible to the agent. Add `@action` wrappers at `app/data/action/integrations/asana/asana_actions.py`, one per client method. Each wrapper resolves the client at runtime through `run_client` from `_helpers.py`, which checks credentials, calls the method, and wraps the envelope into the agent-facing `{"status": ...}` shape.

```python
from agent_core import action


@action(
    name="list_asana_tasks",
    description="List tasks in an Asana project by GID. Returns task GIDs, names, and assignees.",
    action_sets=["asana_tasks", "asana"],
    input_schema={
        "project_gid": {
            "type": "string",
            "description": "Asana project GID.",
            "example": "1234567890",
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
        per_page=input_data.get("per_page", 30),
    )
```

The `run_client` import goes inside the function body. A top-level import raises `NameError` at call time because the registry runs each action's extracted source on its own, where module-level names are out of scope. This rule is covered in full in [Write a custom action](custom-action.md#import-rule-for-helpers). Set `parallelizable=False` on every action that mutates state, and set `irreversible=True` on sends and posts.

Group actions into sets prefixed with the integration name. Use one fine-grained set per resource noun, such as `asana_tasks` and `asana_projects`, and add a single umbrella set named for the integration, such as `asana`, on the high-value actions. The agent loads the umbrella when the user says "use Asana" and loads a fine-grained set only when the task needs it. For the action-writing details, read [Write a custom action](custom-action.md).

## Credentials and config storage

Two file types live side by side in `<project_root>/.credentials/`. The account document `<name>.accounts.json` holds every connected account's credential. The optional config file `<name>_config.json` holds post-connect runtime settings such as watch filters. Both are written with restrictive permissions, and each is the dataclass serialized to JSON.

| Function | Purpose |
|---|---|
| `save_credential(filename, instance)` | Write a credential dataclass to `<filename>` |
| `load_credential(filename, cls)` | Read it back into `cls`, or `None` if absent |
| `has_credential(filename)` | Whether the credential file exists |
| `remove_credential(filename)` | Delete the credential file |

The config functions mirror these as `save_config`, `load_config`, `has_config`, and `remove_config`, with filenames ending in `_config.json`. To expose runtime knobs, declare a `config_class` dataclass and a `config_fields` render schema on the provider, then read the current values inside the client with `load_config` on each inbound message. Reading fresh each time keeps config changes effective without a restart. Unknown keys in an older config file are dropped on load and missing fields fall back to defaults, so adding or removing a field does not break existing installs. Where credentials are stored and how they are reported is covered in [Credentials](../integrations/credentials.md).

## OAuth providers

For an OAuth integration, declare `auth_type = "oauth"`, leave `fields` empty,
and return an `OAuthSpec` instead of implementing `verify_token`. The core runs
the browser flow, calls `identity_of` on the result, and stores the account.

```python
    auth_type = "oauth"
    fields = []

    def oauth_spec(self) -> OAuthSpec:
        return OAuthSpec(
            authorize_url="https://app.asana.com/-/oauth_authorize",
            token_url="https://app.asana.com/-/oauth_token",
            scopes=("default",),
            # Account choosers matter: without one, a second connect silently
            # re-authorises whichever account the browser is already signed
            # in to, and the user ends up with one account they cannot escape.
            extra_authorize_params={"prompt": "consent"},
            has_chooser=True,
        )
```

`OAuthSpec.has_chooser=False` is an explicit declaration that the provider's
OAuth has no chooser (LinkedIn is the shipped example). The conformance suite
requires one or the other, so a missing chooser param is always a decision
rather than an oversight.

Rotating tokens are handled by `refresh(credential)`, which returns the updated
credential dict. The core persists it against the right account; never write
it yourself.

Whether to embed shared client credentials or require the user to bring their
own depends on identity, quota, and suspension scope. When the API call carries
the user's own identity, quota and suspension risk, embed the CraftBot client
credentials for a one-click connect and name the env keys with a `_SHARED_`
infix. When your credentials would act as one shared identity across all users,
or pool rate limits and suspension risk, the user must supply their own. The
README works through Discord, Jira, and Twitter as the canonical cases. See
[Credentials](../integrations/credentials.md) for how the two paths surface.

## Listeners and triggers

A client that receives inbound events overrides `supports_listening` to return `True` and implements `start_listening(callback)` and `stop_listening()`. The provider's `make_listener(client, cursor, emit)` returns a `Listener` for one account; `ClientListenerAdapter` in `providers/_shared.py` wraps a client that already has its own loop. The `ListenerManager` starts one listener per (provider, account) with `listen` enabled and reconciles whenever accounts change. Each inbound event is normalized into a `PlatformMessage`, converted to the host payload shape, and delivered to the host's `EventSink`, which turns it into an agent trigger. How a received message becomes a task is covered in [Triggers](../core/concepts/triggers.md).

Give the client a stored cursor or timestamp so a restarted listener does not replay old events, and back off after a poll error rather than retrying in a tight loop. The Slack client in `craftos_integrations/providers/slack/client.py` is a complete polling reference.

## Production checklist

Before you call an integration done, confirm the following from the README:

- Enumerate the vendor's full endpoint surface, then trim to what an agent would use. Write the dropped categories into an exclusion comment at the bottom of `<name>_actions.py`.
- Mirror the full verb set on every primary noun. An integration that can `list` but not `update`, `delete`, or `reply` is the top cause of agent failure.
- Return the standard envelope from every client method, and set `parallelizable=False` on every write action.
- Add pagination to every list action with a `per_page` parameter defaulting to 30 and capped at 100.
- Pick one canonical identifier shape per resource and document it in each action `description`.
- Populate `connect_help` with three to five verified steps, and write `INTEGRATION.md` with identifier rules and known auth failure modes.
- Implement `identity_of` so two accounts of the same integration never collide, and declare an OAuth account chooser (or `has_chooser=False`) explicitly.
- Verify with an import-and-register check, an action-count audit over the actions file, and a live smoke test that runs one action per set against a real account.

## Next

- [Integrations](../integrations/index.md): the catalogue of shipped integrations and their action sets
- [Credentials](../integrations/credentials.md): where tokens are stored and how the two auth paths surface
- [Write a custom action](custom-action.md): the `@action` decorator, schemas, and the helper import rule
