# LLM providers

The LLM handles every plan, reply, and tool call the agent makes. CraftBot supports 13 providers behind one interface. Switching is a single setting, and every provider has a working default model, so a key (or a running Ollama server) is all you need.

## The full matrix

| Provider | `llm_provider` value | Key | Default LLM model | Endpoint / notes |
|---|---|---|---|---|
| **Anthropic** | `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | The default provider |
| **OpenAI** | `openai` | `OPENAI_API_KEY` | `gpt-5.2-2025-12-11` | Also works with a ChatGPT Plus/Pro/Team [subscription](subscription-auth.md) |
| **Google Gemini** | `gemini` | `GOOGLE_API_KEY` | `gemini-2.5-pro` | API base and version overridable; also the default video-generation provider |
| **BytePlus** | `byteplus` | `BYTEPLUS_API_KEY` | `seed-2-0-pro-260328` | Default base `https://ark.ap-southeast.bytepluses.com/api/v3`, overridable |
| **Ollama (local)** | `remote` | None — just a server URL | `llama3.2:3b` | Default `http://localhost:11434`; free, fully local |
| **Grok (xAI)** | `grok` | `XAI_API_KEY` | `grok-3` | `https://api.x.ai/v1`; also works with a SuperGrok [subscription](subscription-auth.md) |
| **DeepSeek** | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` | `https://api.deepseek.com`; text only, no vision |
| **Moonshot** | `moonshot` | `MOONSHOT_API_KEY` | `kimi-k2.5` | `https://api.moonshot.cn/v1`; geo-restricted — see quirks |
| **MiniMax** | `minimax` | `MINIMAX_API_KEY` | `MiniMax-Text-01` | `https://api.minimax.chat/v1`; geo-restricted — see quirks |
| **Z.ai (GLM)** | `glm` | `ZAI_API_KEY` | `glm-5.2` | `https://api.z.ai/api/paas/v4`, OpenAI-compatible |
| **Sakana (Fugu)** | `fugu` | `SAKANA_API_KEY` | `fugu` | `https://api.sakana.ai/v1`, OpenAI-compatible; LLM only |
| **OpenRouter** | `openrouter` | `OPENROUTER_API_KEY` | `anthropic/claude-sonnet-4.5` | `https://openrouter.ai/api/v1`; one key, hundreds of models |
| **AWS Bedrock** | `bedrock` | AWS credentials (no single key) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Region instead of a base URL, default `us-east-1` |

The key names above are the conventional identifiers shown in the settings interface and in [Environment variables](../../reference/env-vars.md). The values themselves are stored in `settings.json` under `api_keys`.

## Choosing a provider

| You want | Pick | Why |
|---|---|---|
| Best out-of-box agent quality | **Anthropic**, **OpenAI**, or **Gemini** | Flagship hosted models; CraftBot's prompt-caching paths are tuned for them |
| Zero cost, full privacy | **Ollama** (`remote`) | Runs on your hardware, no key, no tokens billed — quality depends on the model you run |
| One key, many models | **OpenRouter** | Access Claude, GPT, Gemini, Kimi, and more through a single account; models are addressed as `vendor/model` slugs |
| Pay with a subscription you already have | **OpenAI** or **Grok** in subscription mode | Your ChatGPT Plus/Pro/Team or SuperGrok quota powers the agent — see [Subscription authentication](subscription-auth.md) |
| Existing AWS billing / compliance | **Bedrock** | Claude models under your AWS account, IAM roles, and region controls |
| Low-cost hosted | **DeepSeek**, **GLM**, **Moonshot**, **MiniMax** | Cheap and capable; check the quirks below for vision support and geo-restrictions |

One caveat for budget picks: DeepSeek and Fugu have no vision model, so image-understanding actions won't run unless you set a separate [VLM provider](vlm-and-media.md).

## Setting provider, key, and model

Three ways, all writing to the same `settings.json`:

**1. Onboarding wizard**: the first-launch flow walks you through provider and key. Re-run it any time from [onboarding](../../start/quickstart.md#step-2-connect-a-model-provider).

**2. The `/provider` command**, fastest from chat:

```
/provider                      # show current provider and key status
/provider deepseek             # switch provider
/provider openai sk-...        # switch provider and set the key in one line
```

`/provider` covers `openai`, `gemini`, `anthropic`, `byteplus`, `deepseek`, `grok`, `glm`, `fugu`, `openrouter`, and `remote`. Moonshot, MiniMax, and Bedrock are configured through Settings → Model instead.

**3. Settings → Model** offers the full surface: provider dropdown, API key field, model pickers for LLM and VLM separately, base-URL / AWS-credential fields where relevant, a connection test, and subscription sign-in. Saving reinitializes the model client immediately.

You can also hand-edit `settings.json` (restart afterwards):

```json
{ "model": { "llm_provider": "openai", "llm_model": "gpt-5.2-2025-12-11" } }
```

`llm_model: null` means "use the provider's default from the registry". Switching providers clears any model override so the new provider starts on its own default. Per-capability overrides (`vlm_model`, `image_gen_model`, `video_gen_model`) work the same way (see [settings.json](../configuration/config-json.md)).

**Connection testing.** The test in Settings → Model sends a tiny request against your exact configured model, so a typo in the model ID fails at test time instead of at first real use. When no model is set it uses a known-good default from `app/config/connection_test_models.json`. If a provider deprecates its test model, update that file.

## Per-provider quirks

- **Gemini**: override the API base and version via `endpoints.google_api_base` and `endpoints.google_api_version` in `settings.json` (useful for proxies or early API versions).
- **BytePlus**: the base URL defaults to the international ModelArk endpoint (`ark.ap-southeast.bytepluses.com`); override via `endpoints.byteplus_base_url`. Model IDs use dated build suffixes (`seed-2-0-pro-260328`), not the China-region `doubao-*` naming.
- **Ollama (`remote`)**: no key. Point `endpoints.remote_model_url` at your server (default `http://localhost:11434`). If the configured model isn't pulled, CraftBot queries the server's model list and falls back to the first available model rather than failing, logging a warning.
- **Moonshot / MiniMax**: their direct APIs are geo-restricted for most international users. If you have no direct key but an OpenRouter key is configured, CraftBot automatically routes these providers through OpenRouter (translating model IDs to OpenRouter slugs, e.g. `kimi-k2.5` → `moonshotai/kimi-k2.5`).
- **OpenRouter**: models use `vendor/model` slugs. The endpoint field is intentionally hidden in Settings since it's fixed for almost everyone. Power users can set `endpoints.openrouter_base_url` in `settings.json` by hand.
- **Bedrock**: no API key. Credentials come from `settings.json` (`aws_credentials`: access key, secret, optional session token) or fall back to the standard AWS chain (`AWS_ACCESS_KEY_ID` env vars, IAM role, SSO profile). The region lives in `endpoints.aws_region` (default `us-east-1`). The default model uses the `us.` cross-region inference-profile prefix, since Claude 4.x on Bedrock rejects the bare `anthropic.*` IDs. Users in EU/APAC regions should change `us.` to `eu.` / `ap.`.
- **OpenAI / Grok**: when a subscription is connected, it takes precedence over the stored API key, and the reachable model list narrows. See [Subscription authentication](subscription-auth.md).
- **GLM / Fugu**: OpenAI-compatible APIs with nothing special beyond the key. Fugu is text-only.

## Slow mode

Rate-limited plans (trial tiers, free quotas) can hit 429s under agent workloads, since a single task fires many LLM calls in quick succession. Slow mode throttles client-side:

```json
{ "model": { "slow_mode": true, "slow_mode_tpm_limit": 30000 } }
```

When enabled, CraftBot tracks token usage in a sliding 60-second window and blocks each LLM call until there's capacity under the tokens-per-minute limit. You'll see `[SLOW MODE] Rate limit approaching... Waiting Ns` in the logs. The default limit is 30,000 TPM. Tune it to your provider's published quota. Off by default.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401` / authentication / invalid key error | Wrong key, or key doesn't match the selected provider | Re-run `/provider <name> <key>`; verify the key in the provider's own console |
| Grok returns `400` on every call | xAI signals rejected/expired bearers with 400, not 401 | Test the key in Settings → Model; if using a subscription, reconnect it |
| Model-not-found error | Model override typo, or the default model isn't enabled on your account | Run the connection test (it validates the exact model ID); set an explicit model in Settings → Model |
| `429 Too Many Requests` | Provider rate limit | Enable [slow mode](#slow-mode); lower the TPM limit; or switch providers |
| Moonshot / MiniMax unreachable | Geo-restricted direct API | Add an OpenRouter key — CraftBot proxies these providers through it automatically |
| Ollama: connection refused | Server not running, or wrong URL | `ollama serve`, then check `endpoints.remote_model_url` |
| New API key saved but ignored (OpenAI / Grok) | A connected subscription takes precedence over the key | Disconnect the subscription in Settings → Model, then save |
| Repeated failures, agent backs off | 5 consecutive LLM errors trip the failure guard | See [Provider troubleshooting](../../reference/troubleshooting/providers.md) |

## Related

- [VLM and media](vlm-and-media.md): vision, image generation, video generation
- [Subscription authentication](subscription-auth.md): ChatGPT / SuperGrok sign-in instead of a key
- [settings.json](../configuration/config-json.md): full `model.*` / `api_keys` / `endpoints` schema
- [Environment variables](../../reference/env-vars.md): the key-name reference
- [Provider troubleshooting](../../reference/troubleshooting/providers.md): deeper failure diagnosis
