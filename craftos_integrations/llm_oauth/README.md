# LLM subscription OAuth

Connect a consumer ChatGPT Plus/Pro/Team or SuperGrok subscription and have
CraftBot consume that quota instead of a paid API key.

## What this module is

This is not a normal integration. There is no `BasePlatformClient`, no
listener machinery, and nothing shows up in the integrations grid. It's an
auth-only backend that the LLM model factory consults before constructing
an OpenAI client. If a subscription is connected for a given provider, the
factory builds the client in subscription mode (different base URL, bearer
token sourced from OAuth, extra headers); otherwise it falls back to the
stored API key.

```
agent_core/core/models/factory.py
        │
        │  _get_oauth_bearer(provider)
        ▼
craftos_integrations/llm_oauth/tokens.py
        │
        │  routes to provider backend
        ▼
chatgpt.py  /  grok.py
        │
        ├── OAuthFlow (PKCE, loopback browser callback)
        └── credentials_store (.credentials/<provider>_oauth.json)
```

## Supported providers

| Provider | Status | Notes |
|---|---|---|
| **ChatGPT** Plus/Pro/Team | Works end-to-end | Chat Completions calls are translated to Codex Responses API via [`ChatGPTSubscriptionClient`](../../../../agent_core/core/models/chatgpt_subscription_client.py). Multi-turn history accumulation on this path is handled in [`interface.py`](../../../../agent_core/core/impl/llm/interface.py) so `store=false` doesn't break sub-agent continuity or prefix caching. |
| **Grok** SuperGrok / X Premium+ | Works end-to-end | Subscription tokens hit the same `api.x.ai/v1` host as API-key mode, so no call-shape change is needed. |
| **Anthropic** Pro/Max | **Intentionally not implemented** | Anthropic explicitly forbade third-party OAuth subscription use in Feb 2026 (ToS update + server-side block). Adding it would break within weeks and violate ToS. Anthropic stays API-key-only. |

## Settings UI surface

```
app/ui_layer/settings/model_settings.py
    PROVIDER_INFO[openai].supports_subscription_oauth = True
    PROVIDER_INFO[grok].supports_subscription_oauth = True

    get_model_settings()  returns subscription_oauth: {
      openai: {connected, email, plan, expires_in_seconds},
      grok:   {connected, email, plan, expires_in_seconds},
    }

app/ui_layer/settings/provider_settings.py
    connect_subscription(provider)
    disconnect_subscription(provider)
    get_subscription_status(provider)
```

## Storage

```
<project_root>/.credentials/
    openai_chatgpt_oauth.json    # access_token, refresh_token, id_token, account_id, plan, ...
    grok_oauth.json              # access_token, refresh_token, expires_at, email, ...
```

Files are written with 0600 perms by `credentials_store`. The factory does
not cache tokens in memory — `tokens.get_bearer(provider)` re-reads on
every LLM-client construction so disconnect/reconnect propagates without
a process restart.

## OAuth specifics

### ChatGPT

- **client_id**: `app_EMoamEEZ73f0CkXaXp7hrann` (Codex CLI's public client; the entire ecosystem reuses it). Override via `oauth.OPENAI_OAUTH_CLIENT_ID` in settings.json once it's rotated.
- **authorize**: `https://auth.openai.com/oauth/authorize`
- **token**: `https://auth.openai.com/oauth/token`
- **callback**: `http://localhost:1455/auth/callback`
- **scopes**: `openid profile email offline_access`
- **PKCE**: S256
- **Entitlement**: parsed from `id_token` JWT claim `https://api.openai.com/auth.chatgpt_plan_type`. Free accounts are rejected at login time.
- **API base** (subscription mode): `https://chatgpt.com/backend-api/codex`
- **Required headers**: `Authorization: Bearer …`, `chatgpt-account-id`, `OpenAI-Originator: codex_cli_rs`, `OpenAI-Beta: responses=experimental`

### Grok

- **client_id**: `opencode-grok-auth` (ecosystem-standard public ID). Override via `oauth.GROK_OAUTH_CLIENT_ID` once we register our own with xAI.
- **OIDC discovery**: `https://auth.x.ai/.well-known/openid-configuration` (token endpoint is read from here)
- **authorize** (fallback): `https://auth.x.ai/oauth2/authorize`
- **token** (fallback): `https://auth.x.ai/oauth2/token`
- **callback**: `http://127.0.0.1:56121/callback`
- **scopes**: `openid profile email offline_access`
- **PKCE**: S256
- **API base**: `https://api.x.ai/v1` (same as API-key mode)
- **Required headers**: `Authorization: Bearer …`

## Caveats

1. **ChatGPT call shape** — the subscription backend serves Responses API only. Until `agent_core/core/impl/llm/interface.py` is taught to call `client.responses.create()` when `auth_mode == "subscription"`, ChatGPT subscription calls will 404. The OAuth + refresh + storage layers are complete and tested-shaped; this is the follow-up.
2. **Codex client_id reuse risk** — OpenAI can rotate `app_EMoamEEZ73f0CkXaXp7hrann` or add client attestation at any time and brick reused-ID tools. The API-key fallback always remains available.
3. **xAI client registration** — file with xAI to register a CraftBot-owned desktop client. Until then we ride the ecosystem-standard public ID.
4. **Grok tool-augmented calls** — `web_search`, `x_search`, `code_execution` still bill the user's underlying xAI account at $5/1k calls. Subscription only covers token inference. Surfaced in the connect-success message.
5. **No live quota endpoints** on either provider. Quota exhaustion shows up as 429s; surface those to the user.
6. **Model availability narrows** under subscription auth. `PROVIDER_INFO[<provider>].subscription_models` lists what's reachable; UI should hide non-subscription models when the OAuth toggle is active.

## Manual smoke test

```python
import asyncio
from craftos_integrations import configure
from craftos_integrations.llm_oauth import tokens

configure(project_root=".")

# Open browser, sign in:
asyncio.run(tokens.connect("grok"))  # or "openai"

# Inspect the stored credential:
print(tokens.status("grok"))

# What the factory will see:
print(tokens.get_bearer("grok"))  # (access_token, base_url, extra_headers)

# Disconnect:
print(tokens.disconnect("grok"))
```
