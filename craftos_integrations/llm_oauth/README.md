# LLM subscription OAuth

Connect a ChatGPT, SuperGrok, or Claude subscription and have
CraftBot consume that quota instead of a paid API key.

## What this module is

This is not a normal integration. There is no `BasePlatformClient`, no
listener machinery, and nothing shows up in the integrations grid. It's an
authentication backend that the LLM model factory consults before constructing
a client. Connected OpenAI-compatible subscriptions use an OAuth bearer,
provider headers and a subscription endpoint. Connected Claude subscriptions
use a Claude Code CLI client. Otherwise the factory uses the stored API key.

```
agent_core/core/models/factory.py
        │
        │  _get_oauth_bearer(provider)
        ▼
craftos_integrations/llm_oauth/tokens.py
        │
        │  routes to provider backend
        ▼
chatgpt.py  /  grok.py  /  claude_code.py
        │
        ├── OAuthFlow (PKCE, loopback browser callback)
        └── credentials_store (.credentials/<provider>_oauth.json)
```

Claude Code owns its tokens. `claude_code.py` stores only CraftBot's opt-in
and the factory constructs a CLI client rather than requesting a bearer.

## Supported providers

| Provider | Status | Notes |
|---|---|---|
| **ChatGPT** Plus/Pro/Team | Works end-to-end | Chat Completions calls are translated to Codex Responses API via [`ChatGPTSubscriptionClient`](../../../../agent_core/core/models/chatgpt_subscription_client.py). Multi-turn history accumulation on this path is handled in [`interface.py`](../../../../agent_core/core/impl/llm/interface.py) so `store=false` doesn't break sub-agent continuity or prefix caching. |
| **Grok** SuperGrok / X Premium+ | Works end-to-end | Subscription tokens hit the same `api.x.ai/v1` host as API-key mode, so no call-shape change is needed. |
| **Claude** subscription via Claude Code | Implemented; live inference depends on the CLI account's access | Uses the official, unmodified Claude Code CLI for login and inference. CraftBot never reads or stores Claude OAuth tokens. API-key mode remains available. |

### Claude subscription setup

1. Install the official [Claude Code CLI](https://code.claude.com/docs/en/setup) on the machine running CraftBot. CraftBot finds `claude` on its PATH, or in the native installer's `~/.local/bin` when CraftBot was started before the install. Windows npm installations also need `node` on PATH.
2. In Settings → Model, select **Anthropic** and click **Sign in with Claude**. The same option is available during onboarding. It works like ChatGPT's sign-in: the button shows a spinner while CraftBot runs `claude auth login` for a **separate CraftBot login profile**, the CLI opens one sign-in tab, and approving there redirects to the CLI's local callback. The CLI exchanges the code with its own PKCE verifier and stores the tokens; CraftBot connects as soon as the CLI reports success. If the profile is already signed in, Connect succeeds without a browser. An unapproved sign-in is stopped after 5 minutes, and clicking Connect again replaces it. This needs a browser on the machine running CraftBot. On a remote server, Claude's page shows a code instead, which CraftBot doesn't accept; use an API key there.
3. Use **Test connection** to verify the selected model.
4. **Disconnect signs out** with `claude auth logout` in CraftBot's private profile, verifies that it is logged out, and then removes the connection flag. Your standalone Claude Code login is untouched. Reconnecting starts a new browser sign-in. A logout/verification failure retains the connection flag and reports an error.

Claude Code owns credentials and refresh inside `<CraftBot state>/.credentials/claude_code/`. Every login, status, logout and inference subprocess receives this absolute path as `CLAUDE_CONFIG_DIR`, overriding inherited profile settings without changing the parent environment. CraftBot stores only `{"enabled": true, "profile_version": 1}` in `.credentials/anthropic_claude_code.json`; `tokens.get_bearer("anthropic")` never exports a token. Tokens are written and read by the official CLI, never copied from the standalone login or sent to the Anthropic SDK. Old shared-login flags are ignored until the user signs in to the separate profile.

Inference uses documented CLI print mode, with built-in tools, MCP configuration, hooks and session persistence disabled. CraftBot retains its own agent loop. Text and images are supported; multi-turn history is sent as a labelled transcript in a single user message. CLI startup adds latency to each request. API-specific cache markers and temperature are not forwarded; usage and cache counts come from the CLI result. CLI model availability and subscription limits apply, and inference errors never silently fall back to a paid API key.

See the [CLI reference](https://code.claude.com/docs/en/cli-reference) and [Anthropic's authentication guidance](https://code.claude.com/docs/en/legal-and-compliance) for the supported Claude Code route.

Browser test results, screenshots and remaining acceptance steps are in the
[Claude subscription validation report](../../docs/CLAUDE_CODE_VALIDATION.md).

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
