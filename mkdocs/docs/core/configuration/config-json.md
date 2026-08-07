# settings.json

`app/config/settings.json` is CraftBot's main runtime configuration: agent name, model providers, API keys, feature toggles, endpoints. This page documents every section. Most of it is editable from the browser Settings UI or slash commands. Hand-edit only when scripting or working headless.

!!! note "Not the root config.json"
    The repository root also has a small `config.json` holding launcher state for `run.py`/`install.py` (the `use_conda` flag). It is not runtime configuration. Everything on this page lives in `app/config/settings.json`.

## How it's read and written

- `app/config.py` (`get_settings()`) reads the file and caches it in memory. A parallel `SettingsManager` singleton in `agent_core` merges it over built-in defaults.
- A **config watcher** hot-reloads the file within seconds of a change, with no restart for most edits. An LLM call already in flight finishes on the old config. The next call uses the new one. The `model` block is the exception: the live LLM client is rebuilt only by a reinitialize (`/provider`, a Settings → Model save, or a restart), never by the hot reload alone.
- The Settings UI, slash commands (`/provider`, …), the onboarding wizard, and the agent itself all write to this file.
- **Pitfall:** a JSON syntax error doesn't crash anything. The reload fails and the *previous* config stays active. Read the file back after hand-editing.

Missing keys fall back to code defaults, so a minimal file works. The defaults below come from `_get_default_settings()` in `app/config.py` and the per-subsystem getters.

## `version`

| Key | Default | What it does |
|---|---|---|
| `version` | `"0.0.0"` | Legacy field. The app version now comes from the bundled `VERSION` file; this is only a last-resort fallback. Don't edit it. |

## `general`

Edited in **Settings → General**.

| Key | Default | What it does |
|---|---|---|
| `agent_name` | `"CraftBot"` | The agent's user-facing name, shown in the UI and used in prompts. |
| `os_language` | detected | Language code (`en`, `ja`, `zh`, …) detected from your OS locale on first launch; drives UI string localization (`app/i18n`). |

## `proactive`

Edited in **Settings → Proactive**.

| Key | Default | What it does |
|---|---|---|
| `enabled` | `true` | Master switch for [proactive mode](../modes/proactive.md). When `false`, the heartbeat and day/week/month planner schedules are skipped. |

## `memory`

Edited in **Settings → Memory**.

| Key | Default | What it does |
|---|---|---|
| `enabled` | `true` | Master switch for the [memory](../concepts/memory.md) pipeline and `memory_search`. |
| `max_items` | `200` | Item cap on `MEMORY.md`. Reaching it triggers a pruning pass during memory processing. |
| `prune_target` | `135` | Approximately how many of the oldest items the pruning pass consolidates or drops. |
| `item_word_limit` | `150` | Maximum words per distilled memory item. |

## `model`

Edited in **Settings → Model** or via `/provider`.

| Key | Default | What it does |
|---|---|---|
| `llm_provider` | `"anthropic"` | Text-model provider for all reasoning. Valid names: [LLM providers](../providers/llm.md). |
| `vlm_provider` | `"anthropic"` | Vision-model provider (screenshots, image understanding). Falls back to `llm_provider` if unset. |
| `image_gen_provider` | `"openai"` | Image generation provider. Falls back to `vlm_provider`. |
| `video_gen_provider` | `"gemini"` | Video generation provider. Falls back to `image_gen_provider`, then `gemini`. |
| `llm_model` / `vlm_model` / `image_gen_model` / `video_gen_model` | `null` | Explicit model ID per interface. `null` means the provider's registry default. |
| `slow_mode` | `false` | Throttles LLM requests through a rate limiter — for providers with strict quotas. |
| `slow_mode_tpm_limit` | `30000` | Tokens-per-minute budget the rate limiter enforces when `slow_mode` is on. |

## `api_keys`

Edited in **Settings → Model** or `/provider <name> <key>`.

| Key | Default | What it does |
|---|---|---|
| `openai` | `""` | OpenAI API key. |
| `anthropic` | `""` | Anthropic API key. |
| `google` | `""` | Gemini API key. The Gemini provider reads `google` — there is no `gemini` key. |
| `byteplus` | `""` | BytePlus (Volc Engine) key. |
| `openrouter` | `""` | OpenRouter key. |

Other providers (`deepseek`, `minimax`, `moonshot`, `grok`, `glm`, `fugu`) store their keys under their own names in this map when you set them. Two exceptions: **Bedrock** has no API key (it uses [`aws_credentials`](#aws_credentials)) and **Remote (Ollama)** needs no key at all. OpenAI and Grok can alternatively use [subscription login](../providers/subscription-auth.md) instead of a key.

## `endpoints`

Edited in **Settings → Model** (the remote URL field) or by hand.

| Key | Default | What it does |
|---|---|---|
| `remote_model_url` | `""` | Base URL for the **Remote** provider (Ollama). Empty means `http://localhost:11434`. |
| `byteplus_base_url` | `https://ark.ap-southeast.bytepluses.com/api/v3` | BytePlus API endpoint. |
| `google_api_base` | `""` | Override for the Gemini API base URL. |
| `google_api_version` | `""` | Override for the Gemini API version. |
| `openrouter_base_url` | `""` | OpenRouter endpoint. Empty means `https://openrouter.ai/api/v1`. |
| `aws_region` | `"us-east-1"` | AWS region for the Bedrock provider. Falls back to `AWS_DEFAULT_REGION`/`AWS_REGION` env vars. |

## `aws_credentials`

Used only by the **Bedrock** provider. Managed from **Settings → Model** when Bedrock is selected.

| Key | Default | What it does |
|---|---|---|
| `access_key_id` | `""` | AWS access key. Falls back to `AWS_ACCESS_KEY_ID` env var. |
| `secret_access_key` | `""` | AWS secret key. Falls back to `AWS_SECRET_ACCESS_KEY`. |
| `session_token` | `""` | Optional session token. Falls back to `AWS_SESSION_TOKEN`. |
| *(all empty)* | | boto3's default credential chain applies — an EC2/ECS IAM role still works. |

## `oauth`

Bring-your-own OAuth apps for integration connect flows. CraftBot ships shared OAuth clients (embedded in release builds, overridable by [env vars](../../reference/env-vars.md)). Fill these blocks only to use your own app registration instead.

| Key | Default | What it does |
|---|---|---|
| `google.client_id` / `google.client_secret` | `""` | Your Google Cloud OAuth app for Gmail / Calendar / Drive connect flows. |
| `linkedin.client_id` / `linkedin.client_secret` | `""` | Your LinkedIn OAuth app. |
| `slack.client_id` / `slack.client_secret` | `""` | Your Slack OAuth app. |
| `notion.client_id` / `notion.client_secret` | `""` | Your Notion OAuth integration. |
| `outlook.client_id` | `""` | Your Microsoft app registration (PKCE — no secret needed). |

The ChatGPT and Grok **subscription logins** use their own OAuth clients. Those accept `OPENAI_OAUTH_CLIENT_ID` / `GROK_OAUTH_CLIENT_ID` overrides set as environment variables (see [Subscription authentication](../providers/subscription-auth.md)).

## `auth_mode`

| Key | Default | What it does |
|---|---|---|
| `<provider>` | *(absent)* | `"subscription"` or `"api_key"` per provider. Written automatically when you connect or disconnect a subscription login; the Settings UI reads it to show which auth is active. Don't hand-edit — connect/disconnect instead. |

## `web_search`

| Key | Default | What it does |
|---|---|---|
| `google_cse_id` | `""` | Google Custom Search Engine ID for the `web_search` action. |

## `cache`

Prompt-cache tuning for providers with explicit cache APIs (BytePlus prefix/session caches; Anthropic uses a fixed 5-minute ephemeral TTL regardless).

| Key | Default | What it does |
|---|---|---|
| `prefix_ttl` | `3600` | TTL in seconds for the system-prompt prefix cache. |
| `session_ttl` | `7200` | TTL in seconds for per-session cache state (long runs). |
| `min_tokens` | `500` | Prompts below this size skip caching. |

The LLM layer reads its effective values from the matching `CACHE_PREFIX_TTL` / `CACHE_SESSION_TTL` / `CACHE_MIN_TOKENS` environment variables (same defaults); set those if you need to actually change cache behavior.

## `browser`

| Key | Default | What it does |
|---|---|---|
| `port` | `7926` | The backend WebSocket port the browser UI connects to. The operative control is the launcher: `python run.py --backend-port 8926` (which sets the `BROWSER_PORT` env var the adapter reads). |
| `startup_ui` | `false` | Reserved. The launcher controls startup-output suppression via the `BROWSER_STARTUP_UI` env var. |

## `file_index`

| Key | Default | What it does |
|---|---|---|
| `prewarm_all_drives` | `true` | Pre-warms the `find_files` index for all local drives at startup, so the agent's first file search is fast. Set `false` on machines with many/slow drives. |

## `gui`

Legacy block. GUI (desktop screen-control) mode is not part of the runtime, so these keys have no effect; they remain in the file for compatibility.

| Key | Default | What it does |
|---|---|---|
| `enabled` | `true` | Ignored by the runtime. |
| `use_omniparser` / `omniparser_url` | `false` / `http://127.0.0.1:7861` | Ignored by the runtime. |

## `api_keys_configured`

| Key | Default | What it does |
|---|---|---|
| `<provider>` | `false` | Bookkeeping booleans reflecting which `api_keys` entries are non-empty; the UI reads them. If you hand-set a key, flip the matching boolean too. |

## Constants not in the JSON

A few limits are Python constants. Change them by editing the file:

| Constant | Default | Purpose |
|---|---|---|
| `DEFAULT_MAX_ACTIONS_PER_TASK` (`agent_core/core/state/types.py`) | `150` | Per-run action cap; at 100% the agent pauses on a Continue/Stop choice |
| `DEFAULT_MAX_TOKEN_PER_TASK` (`agent_core/core/state/types.py`) | `6,000,000` | Per-run token budget; counts only uncached tokens, same Continue/Stop gate |
| `PROCESS_MEMORY_AT_STARTUP` (`app/config.py`) | `False` | Run memory processing at launch |
| `MEMORY_PROCESSING_SCHEDULE_HOUR` (`app/config.py`) | `3` | Hour (0–23) of the daily memory distillation |

## Other files in app/config/

`settings.json` has siblings, one per subsystem:

| File | Purpose | Who edits it |
|---|---|---|
| `mcp_config.json` | [MCP server](../../integrations/mcp.md) definitions: name, transport, command/URL, env, enabled flag. Hot-reloaded. | `/mcp`, **Settings → MCP** |
| `skills_config.json` | Which [skills](../concepts/skills.md) are enabled/disabled, plus `auto_load`. Hot-reloaded. | `/skill`, **Settings → Skills** |
| `scheduler_config.json` | All [schedules](../concepts/scheduling.md) — including the built-in memory-processing and heartbeat entries. Hot-reloaded. | The agent's scheduling actions, **Settings → Proactive** |
| `external_comms_config.json` | Telegram and WhatsApp listener config (tokens, mode, auto-reply). Other platforms keep credentials in `.credentials/` instead. Not hot-reloaded — hand-edits need a restart. | **Settings → Integrations** |
| `onboarding_config.json` | [Onboarding](../../start/onboarding.md) completion flags, your name, the agent's name. Not hot-reloaded. | The onboarding flow only — don't hand-edit |
| `connection_test_models.json` | Cheap model IDs used per provider for the "test connection" check. | You, rarely — when a test model is deprecated |

## Related

- [Environment variables](../../reference/env-vars.md): the complete env-var table (OAuth clients, AWS, provider keys)
- [LLM providers](../providers/llm.md): valid provider names, key names, default models
- [Agent bundle agent.yaml](agent-config-yaml.md): configuration for packaged specialist agents
- [Onboarding](../../start/onboarding.md): the wizard that fills the model and key sections for you
