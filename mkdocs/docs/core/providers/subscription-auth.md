# Subscription authentication

If you already pay for ChatGPT Plus/Pro/Team or SuperGrok, CraftBot can run on that subscription's quota instead of a metered API key. You sign in through the provider's own OAuth page in your browser, and no key is created or copied.

## How it works

Subscription auth is a layer in front of the model factory. Before building a client for OpenAI or Grok, CraftBot checks whether a subscription credential exists on disk. If it does, the client is built in subscription mode (OAuth bearer token, provider-specific endpoint and headers) and **the stored API key is bypassed**. If not, it falls back to the API key as usual.

| Provider | Qualifying plans | Endpoint in subscription mode |
|---|---|---|
| **OpenAI (ChatGPT)** | Plus, Pro, Team (Enterprise/Business also accepted) | `https://chatgpt.com/backend-api/codex` — CraftBot translates its calls to the Responses API this backend serves |
| **Grok (xAI)** | SuperGrok, X Premium+ | `https://api.x.ai/v1` — same host as API-key mode |

A free ChatGPT account can complete the sign-in, but you'll get a warning and every model call will fail until you upgrade or switch back to API-key auth.

The Codex backend serves everything CraftBot needs: the agent's action decisions ride ordinary JSON-mode completions, which work transparently. Only native tool-calls and streaming are unsupported there, and CraftBot uses neither on this path, so agent behavior under a subscription matches API-key mode.

**Model list narrows.** Under a ChatGPT subscription only the Codex-accepted models are reachable: `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, and `gpt-5.3-codex-spark`. If your configured model isn't one of them, CraftBot substitutes `gpt-5.4` and logs a warning. Set one of the accepted models in Settings → Model to silence it. Grok subscriptions serve `grok-4-0709` and `grok-3`.

## Connect

1. Open **Settings → Model** and select **OpenAI** or **Grok (xAI)** as the provider.
2. Click **Sign in with ChatGPT** / **Sign in with Grok**. Your browser opens the provider's login page (PKCE OAuth, so CraftBot never sees your password).
3. Sign in and approve. The provider redirects to a local loopback listener (`http://localhost:1455/auth/callback` for ChatGPT, `http://127.0.0.1:56121/callback` for Grok) and CraftBot captures the credential.
4. If the browser shows a "copy this code" page instead of redirecting (this happens in some browser contexts), paste the code into the field that appears in Settings. The result is the same.
5. The success message confirms the connected account and plan (e.g. "ChatGPT Pro connected as you@example.com"). CraftBot switches the provider to subscription mode immediately.

**Checkpoint:** Settings → Model shows the subscription as connected with your email and plan, and a `hello` in chat gets a reply without any API key configured.

## Disconnect

Click **Disconnect** next to the subscription status in Settings → Model. This deletes the local credential. There's no server-side session to revoke; the refresh token simply expires on its own. Calls fall back to your stored API key, if any. If a model was mid-task when you disconnect, it fails with an explicit "subscription disconnected" message rather than an opaque provider error. Save your model settings (or reconnect) to switch cleanly.

## Token storage and security

- Credentials live in `<project_root>/.credentials/` (`openai_chatgpt_oauth.json` and `grok_oauth.json`) written with `0600` permissions (owner-only).
- Files hold the access token, refresh token, and account metadata (email, plan). They never leave your machine.
- Access tokens are short-lived. CraftBot refreshes proactively when a token has under 5 minutes left, and re-resolves the bearer **on every request**, so long-running tasks never fail on a token that expired mid-flight.
- Nothing is cached in memory as the source of truth. The file is re-read on every client construction, so disconnecting from one place propagates everywhere without a restart.
- The `auth_mode` entry in `settings.json` (`{"openai": "subscription"}`) is informational only, used to highlight the right toggle in Settings; the factory decides based on whether the credential file exists.

## Interaction with API keys

Both can coexist. A stored API key stays in `settings.json` while a subscription is connected. The subscription simply wins. This means:

- Saving a new API key while connected has **no effect on inference** until you disconnect the subscription.
- Disconnecting instantly reverts to the API key with no reconfiguration.
- Quota exhausted mid-month? Disconnect, and metered API billing takes over.

One cost caveat for Grok: server-side tools (`web_search`, `x_search`, `code_execution`) still bill your underlying xAI account per call. The subscription covers token inference only.

## Why there is no Anthropic subscription option

Anthropic's terms of service explicitly forbid third-party applications from using Claude Pro/Max OAuth tokens, and the restriction is enforced server-side (since February 2026). CraftBot deliberately does not implement it. It would violate the ToS and break within weeks. Anthropic is API-key-only. Get a key at [console.anthropic.com](https://console.anthropic.com).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser opens but Connect never completes | The loopback callback didn't fire — port `1455` (ChatGPT) or `56121` (Grok) is busy, or the provider showed a code page | Free the port and retry, or use the paste-back field in Settings when the code page appears |
| Repeated sign-in loop | A stale pending attempt | Click Connect again to start a fresh attempt, then complete it in one go |
| "ChatGPT connected — this account has no Plus/Pro/Team plan" | Free-tier account | Upgrade the subscription, or use an API key instead |
| Calls fail with `429` after working fine | Subscription quota exhausted — neither provider exposes a live quota endpoint, so this is how you find out | Wait for the quota window to reset, or disconnect and fall back to an API key |
| Grok: `400` "OAuth2 access token could not be validated" | Expired/revoked token (xAI returns 400, not 401) | Reconnect from Settings → Model |
| "subscription session expired and refresh failed" | Refresh token no longer valid | Reconnect from Settings → Model |
| Configured model silently changed (OpenAI) | Model not in the Codex-accepted list; `gpt-5.4` substituted | Pick `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, or `gpt-5.3-codex-spark` in Settings |

## Related

- [LLM providers](llm.md): the full provider matrix, including API-key setup for OpenAI and Grok
- [Quickstart step 2](../../start/quickstart.md#step-2-connect-a-model-provider): first-time provider setup
- [settings.json](../configuration/config-json.md): where `auth_mode` and `api_keys` live
- [Provider troubleshooting](../../reference/troubleshooting/providers.md): rate limits and model errors in general
