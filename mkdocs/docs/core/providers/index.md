# Providers

CraftBot ships no bundled model. You connect it to a provider you choose, and everything the agent does runs on that connection. This section covers what's supported, how to switch, and how authentication works, including using a ChatGPT or SuperGrok subscription instead of an API key.

## One interface per capability

The agent doesn't use one model for everything. Each capability has its own interface, its own provider setting, and its own default model:

| Capability | What it does | Provider setting | Default |
|---|---|---|---|
| **LLM** | Reasoning, planning, conversation, tool selection | `model.llm_provider` | `anthropic` |
| **VLM** | Understanding images and video frames | `model.vlm_provider` | Follows the LLM provider |
| **Image generation** | The `generate_image` action | `model.image_gen_provider` | `openai` |
| **Video generation** | The `generate_video` action | `model.video_gen_provider` | `gemini` |
| **Embeddings** | Vector memory | Follows the configured provider | Provider-specific model |

This separation is what lets you mix: Claude for reasoning, Gemini for video generation, a local Ollama model for embeddings. Each capability falls back sensibly when you don't set it: the VLM follows your LLM provider, and image and video generation default to the providers that actually support them.

## Switching is a setting

There is no code to touch. The active provider, model overrides, and keys all live in `app/config/settings.json` under `model.*` and `api_keys`. See [settings.json](../configuration/config-json.md) for the schema. Three ways to change them:

1. **Onboarding wizard**: the first-launch flow, where you pick a provider and paste a key.
2. **`/provider` command**: `/provider anthropic sk-ant-...` switches provider and key in one line from chat.
3. **Settings → Model**: the full surface, with per-capability providers, model overrides, base URLs, connection testing, and subscription sign-in.

Changes made through the wizard, the command, or Settings reinitialize the model client immediately, with no restart. If you hand-edit `settings.json`, restart the agent to pick it up.

Every provider has a default model, so picking a provider is enough to start. Set an explicit model only when you want something other than the default. `model.llm_model`, `model.vlm_model`, and friends override per capability.

## Where credentials live

API keys are stored in `settings.json` on your machine. Nothing is sent anywhere except to the provider you configured. Each provider's key is labeled by its conventional name (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, ...); the full list is in [Environment variables](../../reference/env-vars.md). AWS Bedrock is the exception: it has no single key and uses AWS credentials (from settings or the standard AWS credential chain).

Two providers also support **subscription sign-in** instead of a key: a ChatGPT Plus/Pro/Team plan or a SuperGrok / X Premium+ plan can power CraftBot directly through OAuth. Tokens are stored locally in `.credentials/`. See [Subscription authentication](subscription-auth.md).

## In this section

<div class="grid cards" markdown>

- :material-brain:{ .lg .middle } __[LLM providers](llm.md)__

    ---

    All 13 providers with keys, default models, and endpoints, plus how to choose, per-provider quirks, slow mode, and troubleshooting.

- :material-eye-outline:{ .lg .middle } __[VLM and media](vlm-and-media.md)__

    ---

    Vision models, image generation, and video generation: which providers support what, and which actions use each.

- :material-account-key:{ .lg .middle } __[Subscription authentication](subscription-auth.md)__

    ---

    Run CraftBot on a ChatGPT or SuperGrok subscription instead of an API key.

</div>

## Related

- [Quickstart step 2](../../start/quickstart.md#step-2-connect-a-model-provider): connect your first provider
- [settings.json](../configuration/config-json.md): the `model.*`, `api_keys`, and `endpoints` schema
- [Provider troubleshooting](../../reference/troubleshooting/providers.md): rate limits, model errors, failures
