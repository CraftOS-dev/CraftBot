# Provider issues

This page covers model provider problems: authentication, unavailable models, rate limits, local Ollama servers, subscription sign-in, Amazon Bedrock, and image or video calls. Each area lists symptoms with their cause and fix. Provider settings live under **Settings → Model**, and provider errors are recorded in `logs/<run>/all.log`. See [Logs](../../core/concepts/logs.md). For the provider list and how to configure each one, see [LLM providers](../../core/providers/llm.md).

## Authentication

An auth failure appears immediately, usually on startup or on the first call. Most causes are a wrong or malformed key, or a key that does not match the selected provider.

| Symptom | Cause | Fix |
|---|---|---|
| `401`, `authentication_error`, or `invalid_api_key` right away | The key is wrong, has leading or trailing whitespace, or is set in the wrong environment variable | Re-enter the key. Trim spaces, and confirm you used the right variable, such as `ANTHROPIC_API_KEY` versus `OPENAI_API_KEY` |
| Auth fails even though the key looks correct | The key is valid but for a different provider than the one selected | Match the key to the selected provider. A key for one vendor never authenticates against another |
| Grok returns `400` on every call, not `401` | xAI signals a rejected or expired bearer with a `400`, not the usual `401` | Test the key with the connection test in **Settings → Model**. If you connect Grok through a subscription, reconnect it |
| A newly saved OpenAI or Grok key is ignored | A connected subscription takes precedence over an API key for that provider | Disconnect the subscription in **Settings → Model**, then save the key |

The connection test in **Settings → Model** sends a tiny request against your exact configured provider and model, so it separates a bad key from a bad model before the agent hits either at real use.

## Model not found or not available

A model error means the model ID is misspelled or is not enabled on your account. The provider and key can be correct while the specific model is not.

| Symptom | Cause | Fix |
|---|---|---|
| `model_not_found` or a similar error on startup or first call | The model override is a typo, or that model is not enabled on your account | Set a known model in **Settings → Model**, or clear the override to use the provider's default. Run the connection test, which validates the exact model ID |
| The default model works but a specific one you chose does not | Some models are gated by tier or region on the provider side | Pick a model your account can access. The provider's own console lists what is enabled for you |

## Rate limits and slow mode

Rate limiting shows up as `429` errors or as repeated failures that make the agent back off. CraftBot can throttle itself to stay under a provider's per-minute limit.

| Symptom | Cause | Fix |
|---|---|---|
| `429 Too Many Requests` in the logs | You exceeded the provider's rate limit | Enable slow mode, which adds client-side throttling. Set `{ "model": { "slow_mode": true, "slow_mode_tpm_limit": 30000 } }` in `settings.json`, and lower the limit if you still hit it |
| The agent stops and backs off after several errors | Five consecutive provider errors trip the failure guard, and the agent pauses to avoid hammering a failing endpoint | Check the provider's status page, verify the key, and wait a few minutes for the guard to reset. A restart also clears it |
| Rate limits recur constantly on a trial tier | Some providers apply strict per-minute caps on free or trial tiers | Lower the throughput with slow mode, or move to a provider with a more generous tier. See [LLM providers](../../core/providers/llm.md) |

## Ollama and remote models

The remote provider talks to an Ollama server, which defaults to `http://localhost:11434`. It needs no API key, but the server must be running and the model must be pulled.

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` to the Ollama URL | The server is not running | Start it with `ollama serve` on the host, and confirm the URL and port. The default port is `11434` |
| A remote Ollama server is unreachable from another machine | Ollama binds to `127.0.0.1` only by default | Set `OLLAMA_HOST=0.0.0.0:11434` on the server, and use the host's address in the URL, such as `http://192.168.1.10:11434` |
| The agent runs a different model than you configured | The requested model is not pulled, so CraftBot auto-corrects to the first available one and logs an `[OLLAMA]` warning | Pull the model you want with `ollama pull <model>`, then set that exact name. The auto-correct only picks a fallback when your choice is not present |

## Subscription sign-in

A ChatGPT or SuperGrok subscription authorizes through the browser and refreshes its own token. The tokens are short-lived and are re-resolved on every request, so an expired token is normal and handled automatically.

| Symptom | Cause | Fix |
|---|---|---|
| Sign-in opens the browser but loops back without connecting | The OAuth exchange did not complete | Retry the sign-in from **Settings → Model**. Read the `logs/<run>/all.log` lines around the attempt for the provider's error |
| A connected ChatGPT subscription rejects every model | The account is on the free tier, which has no Codex entitlement, so the backend refuses all models | Upgrade to a Plus, Pro, or Team plan, disconnect the subscription, or switch back to API-key auth. See [Subscription auth](../../core/providers/subscription-auth.md) |
| A subscription that worked stops with a quota or model rejection | The account hit a usage limit, or the requested model is not on the subscription's list | Try a different model from the subscription list, wait for the quota to reset, or switch to API-key auth |

## Amazon Bedrock

Bedrock does not use an API key. It reads AWS credentials through the standard boto3 credential chain, and it needs a region.

| Symptom | Cause | Fix |
|---|---|---|
| Bedrock fails to authenticate | No AWS credentials are resolvable, or they lack Bedrock access | Provide an access key and secret in **Settings → Model**, or make them available through the standard AWS credential chain. Confirm the identity is allowed to call Bedrock |
| A Bedrock model errors with a region or access problem | The region is wrong, or the model is not enabled in that region | Set the region that has the model enabled, and enable the model in the Bedrock console for that region |

## Images and video

Image and video actions route through the vision or media provider, which can differ from your text model. Failures are usually the wrong model, an oversized image, or a content policy block.

| Symptom | Cause | Fix |
|---|---|---|
| `describe_image` or a similar action fails with a processing error | The configured vision model is not vision-capable | Set a vision-capable model for image actions in **Settings → Model**. See [VLM and media](../../core/providers/vlm-and-media.md) |
| An image action fails on a large image | Some providers cap image size around a few megabytes | Resize or compress the image before the action runs |
| An image action returns a content policy error | The provider blocked the image content | Read the error text, which names the reason. Use a different image or provider |
| A video action fails or is unavailable | The selected provider does not offer that capability | Configure a provider that supports the media action. See [VLM and media](../../core/providers/vlm-and-media.md) |

## Next

- [LLM providers](../../core/providers/llm.md): the provider list, the `/provider` command, and slow mode
- [Subscription auth](../../core/providers/subscription-auth.md): ChatGPT and SuperGrok sign-in
- [VLM and media](../../core/providers/vlm-and-media.md): vision, image, and video providers
