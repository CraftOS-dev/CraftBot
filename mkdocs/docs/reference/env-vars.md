# Environment variables

This page lists every environment variable CraftBot reads, grouped by the subsystem that consults it. Each table cites the module that reads the variable so you can verify the behavior in source.

## How CraftBot uses the environment

CraftBot does not auto-load a `.env` file. There is no `load_dotenv` call anywhere in the application code, and the `.env` references that exist in the tree are file-index and search exclusion lists, not loaders. Variables are read only from the real process environment.

Provider API keys are **not** configured through the environment. `get_api_key()` in `app/config.py` and `get_api_key_for_provider()` in `app/ui_layer/settings/provider_settings.py` read keys from `settings.json` under `api_keys`. The model factory (`agent_core/core/models/factory.py`) receives the key as a call parameter and, per its module contract, does no environment reading. `settings.json` is the source of truth for provider keys. Set them through onboarding, the `/provider` command, or Settings → Model, all of which write `settings.json`.

Environment variables are the primary mechanism only where a value has no `settings.json` home: runtime and behavior flags, the Python and SSL startup shims, the Living UI bridge, and the shared OAuth client credentials that ship embedded in release builds. Environment variables act as a fallback below `settings.json` in two further cases: AWS Bedrock credentials and the two subscription OAuth client IDs.

The precedence for each configurable value is therefore:

| Value | First source | Fallback |
|---|---|---|
| Provider API keys and base URLs | `settings.json` (`api_keys`, `endpoints`) | none (the environment is not consulted) |
| AWS Bedrock credentials and region | `settings.json` (`aws_credentials`, `endpoints.aws_region`) | AWS env vars, then the boto3 credential chain |
| Subscription OAuth client IDs | `settings.json` (`oauth`) | environment variable |
| Shared integration OAuth or app credentials | environment variable | embedded release credential |
| Runtime flags, startup shims, Living UI bridge | environment variable | code default |

## Provider API key identifiers

These names are the conventional identifiers for each provider's key. They are declared in `agent_core/core/models/provider_config.py` and mirrored in `app/ui_layer/settings/model_settings.py`, where the settings interface uses them as labels. The running application does **not** read the key value from these variables. Store the key in `settings.json` under `api_keys.<name>` instead. Setting only the environment variable does not configure a provider.

| Variable | Declared in | settings.json key |
|---|---|---|
| `OPENAI_API_KEY` | provider_config.py, model_settings.py | `api_keys.openai` |
| `ANTHROPIC_API_KEY` | provider_config.py, model_settings.py | `api_keys.anthropic` |
| `GOOGLE_API_KEY` | provider_config.py, model_settings.py | `api_keys.google` |
| `BYTEPLUS_API_KEY` | provider_config.py, model_settings.py | `api_keys.byteplus` |
| `XAI_API_KEY` | provider_config.py, model_settings.py | `api_keys.grok` |
| `DEEPSEEK_API_KEY` | provider_config.py, model_settings.py | `api_keys.deepseek` |
| `MOONSHOT_API_KEY` | provider_config.py, model_settings.py | `api_keys.moonshot` |
| `MINIMAX_API_KEY` | provider_config.py, model_settings.py | `api_keys.minimax` |
| `ZAI_API_KEY` | provider_config.py, model_settings.py | `api_keys.glm` |
| `SAKANA_API_KEY` | provider_config.py, model_settings.py | `api_keys.fugu` |
| `OPENROUTER_API_KEY` | provider_config.py, model_settings.py | `api_keys.openrouter` |

The provider base-URL identifiers have the same status. `get_base_url()` in `app/config.py` reads the URL from `settings.json` under `endpoints`, not from these variables.

| Variable | Declared in | settings.json key |
|---|---|---|
| `BYTEPLUS_BASE_URL` | provider_config.py | `endpoints.byteplus_base_url` |
| `REMOTE_MODEL_URL` | provider_config.py, model_settings.py | `endpoints.remote_model_url` |
| `OPENROUTER_BASE_URL` | provider_config.py | `endpoints.openrouter_base_url` |

One runtime exception exists for `OPENAI_API_KEY`. The Discord voice feature (`craftos_integrations/integrations/discord/_discord_voice.py`) reads it from the environment as a fallback for its audio transcription key when no key is passed in through `ConfigStore.extras`. This path is unrelated to LLM provider selection.

## AWS Bedrock credentials

Read by `get_aws_credentials()` and the Bedrock branch of `get_base_url()` in `app/config.py`. Each value falls back from `settings.json` to the environment variable, then to the boto3 default credential chain. This is a genuine environment fallback.

| Variable | Read by | Purpose / default |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | app/config.py | Access key when `aws_credentials.access_key_id` is empty. |
| `AWS_SECRET_ACCESS_KEY` | app/config.py | Secret key when `aws_credentials.secret_access_key` is empty. |
| `AWS_SESSION_TOKEN` | app/config.py | Optional session token when `aws_credentials.session_token` is empty. |
| `AWS_REGION` | app/config.py | Region fallback when `endpoints.aws_region` is empty. Consulted after `AWS_DEFAULT_REGION`. |
| `AWS_DEFAULT_REGION` | app/config.py | Region fallback when `endpoints.aws_region` is empty. Checked before `AWS_REGION`. Effective default `us-east-1`. |

`AWS_REGION` is also the `base_url_env` name carried through the model factory plumbing for the Bedrock provider.

## Subscription OAuth client IDs

Read through `ConfigStore.get_oauth()` in `craftos_integrations/config.py`, which checks the `settings.json` `oauth` block first and falls back to the environment variable. Set these only if the provider rotates its published client ID before a CraftBot release ships the new value.

| Variable | Read by | Purpose |
|---|---|---|
| `OPENAI_OAUTH_CLIENT_ID` | craftos_integrations/integrations/llm_oauth/chatgpt.py | Overrides the ChatGPT subscription OAuth client ID. |
| `GROK_OAUTH_CLIENT_ID` | craftos_integrations/integrations/llm_oauth/grok.py | Overrides the Grok (SuperGrok) subscription OAuth client ID. |

## Shared integration OAuth and app credentials

CraftBot ships shared OAuth client credentials embedded in release builds. `get_credential()` in `agent_core/core/credentials/embedded_credentials.py` checks the environment variable first and falls back to the embedded value, so the environment variable takes priority over the embedded credential. The two Telegram bot variables are read directly with `os.environ.get` in `app/config.py`. To use your own OAuth app registration for an integration instead of the shared client, fill the `settings.json` `oauth` block rather than these variables.

| Variable | Read by | Purpose |
|---|---|---|
| `GOOGLE_CLIENT_ID` | app/config.py (get_credential) | Google Workspace OAuth client ID (Gmail, Calendar, Drive). |
| `GOOGLE_CLIENT_SECRET` | app/config.py (get_credential) | Google Workspace OAuth client secret. |
| `LINKEDIN_CLIENT_ID` | app/config.py (get_credential) | LinkedIn OAuth client ID. |
| `LINKEDIN_CLIENT_SECRET` | app/config.py (get_credential) | LinkedIn OAuth client secret. |
| `OUTLOOK_CLIENT_ID` | app/config.py (get_credential) | Microsoft / Outlook app registration client ID (PKCE, no secret). |
| `SLACK_SHARED_CLIENT_ID` | app/config.py (get_credential) | Slack OAuth client ID. |
| `SLACK_SHARED_CLIENT_SECRET` | app/config.py (get_credential) | Slack OAuth client secret. |
| `NOTION_SHARED_CLIENT_ID` | app/config.py (get_credential) | Notion OAuth client ID. |
| `NOTION_SHARED_CLIENT_SECRET` | app/config.py (get_credential) | Notion OAuth client secret. |
| `HUBSPOT_SHARED_CLIENT_ID` | app/config.py (get_credential) | HubSpot OAuth client ID. |
| `HUBSPOT_SHARED_CLIENT_SECRET` | app/config.py (get_credential) | HubSpot OAuth client secret. |
| `TELEGRAM_SHARED_BOT_TOKEN` | app/config.py (os.environ) | Shared Telegram bot token for the Bot connection. |
| `TELEGRAM_SHARED_BOT_USERNAME` | app/config.py (os.environ) | Shared Telegram bot username for the Bot connection. |
| `TELEGRAM_API_ID` | app/config.py (get_credential) | Telegram MTProto API ID for the User (login) connection. |
| `TELEGRAM_API_HASH` | app/config.py (get_credential) | Telegram MTProto API hash for the User (login) connection. |

## Memory and embeddings

| Variable | Read by | Purpose / default |
|---|---|---|
| `MEMORY_EMBEDDING_MODEL` | agent_core/core/impl/memory/manager.py | Sentence-transformers model for memory embeddings. Default `BAAI/bge-small-en-v1.5`. Set to `default` for ChromaDB's bundled ONNX MiniLM. |
| `TOKENIZERS_PARALLELISM` | agent_core/core/impl/action/executor.py | CraftBot sets this to `false` at import to silence the Hugging Face tokenizers fork warning. It is assigned by the app, not read from your value. |

## Prompt cache tuning

Read by the LLM cache config in `agent_core/core/llm/cache/config.py`. These are the effective values the cache layer uses. The `cache` block in `settings.json` documents the same defaults, but changing cache behavior requires setting these variables.

| Variable | Read by | Purpose / default |
|---|---|---|
| `CACHE_PREFIX_TTL` | cache/config.py | System-prompt prefix cache TTL in seconds. Default `3600`. |
| `CACHE_SESSION_TTL` | cache/config.py | Per-session cache TTL in seconds. Default `7200`. |
| `CACHE_MIN_TOKENS` | cache/config.py | Minimum prompt size to cache. Prompts below this skip caching. Default `500`. |

## Interface and launch

| Variable | Read by | Purpose / default |
|---|---|---|
| `BROWSER_PORT` | app/ui_layer/adapters/browser_adapter.py, app/living_ui/manager.py | Backend WebSocket port the interface connects to. Set by `run.py` from `--backend-port`. Default `7926`. |
| `VITE_PORT` | frontend build (exported by `run.py`) | Frontend dev-server port. Set by `run.py` from the resolved frontend port. |
| `VITE_BACKEND_PORT` | run.py | Backend port passed to the frontend build. Falls back to the launcher's backend port. |
| `BROWSER_STARTUP_UI` | app/main.py, app/ui_layer/adapters/browser_adapter.py | When `1`, prints startup UI output. Default `0` (suppressed). Set by the launcher. |
| `NO_COLOR` | app/cli/formatter.py | When set to any value, disables ANSI color in CLI output. |
| `USE_CONDA` | exported by run.py / install.py | Propagates the root `config.json` `use_conda` flag to spawned processes and activation scripts. Set by the launcher, not read within Python. |
| `INSTALL_REQUIREMENTS_AT_STARTUP` | agent_core/core/action_framework/loader.py | When `true`, installs missing action requirements during action loading. Default `false`. |

## Living UI bridge

Set by `app/living_ui/manager.py` on the Living UI backend subprocess and read by that backend's integration client (`app/data/living_ui_template/backend/services/integration_client.py`). They let a generated Living UI backend call CraftBot integrations.

| Variable | Read by | Purpose / default |
|---|---|---|
| `CRAFTBOT_BRIDGE_URL` | living_ui_template/backend/services/integration_client.py | Base URL of the CraftBot integration bridge. Set to `http://localhost:<BROWSER_PORT>`. Empty when unset. |
| `CRAFTBOT_BRIDGE_TOKEN` | living_ui_template/backend/services/integration_client.py | Auth token for bridge calls. Minted per project by the manager. Empty when unset. |

## Startup shims (Python and SSL)

CraftBot sets these during launch to stabilize encoding, output, and certificate handling. The SSL and warning shims in `app/main.py` use `setdefault`, so a value you set beforehand wins. The Python encoding and buffering variables are assigned on spawned processes by the launcher and the service unit files.

| Variable | Set by | Purpose / default |
|---|---|---|
| `PYTHONUTF8` | craftbot.py | Forces UTF-8 mode on spawned Python. Set to `1`. |
| `PYTHONIOENCODING` | craftbot.py, install.py | Standard stream encoding on spawned Python. Set to `utf-8`. |
| `PYTHONUNBUFFERED` | run.py, install.py, service unit files | Unbuffered stdout/stderr. Set to `1`. |
| `PYTHONWARNINGS` | app/main.py (setdefault) | Suppresses Python warnings during startup. Default `ignore`. |
| `SSL_CERT_FILE` | app/main.py (setdefault) | Points certificate verification at certifi's CA bundle on Windows. |
| `REQUESTS_CA_BUNDLE` | app/main.py (setdefault) | Points `requests` at certifi's CA bundle on Windows. |

## Setting environment variables

Because CraftBot does not read a `.env` file, set variables as real OS environment variables in the environment that launches the app.

- **Provider keys are the exception.** Do not set them in the environment. Use onboarding, `/provider <name> <key>`, or Settings → Model, which write `settings.json`. See [LLM providers](../core/providers/llm.md).
- **Windows.** Set a user or system variable with `setx NAME value`, or through System Properties → Environment Variables. Restart the launching shell so the new value is inherited.
- **macOS and Linux (shell).** `export NAME=value` in the shell that starts CraftBot, or add it to your shell profile.
- **Service and background runs.** A launched service does not inherit an interactive shell's environment. Under a systemd **user** service, variables you `export` in a shell are not visible to the service. Put the value in the unit file with an `Environment=` line, and keep provider keys in `settings.json` as usual. See [Service mode](../start/service-mode.md).

## Next

- [settings.json](../core/configuration/config-json.md): the JSON configuration that holds provider keys, endpoints, AWS credentials, and OAuth blocks.
- [LLM providers](../core/providers/llm.md): provider names, key locations, and default models.
- [Subscription authentication](../core/providers/subscription-auth.md): ChatGPT and Grok sign-in and the OAuth client-ID overrides.
- [Credentials](../integrations/credentials.md): integration OAuth flows and where connection tokens are stored.
- [Service mode](../start/service-mode.md): running CraftBot as a background service and the systemd environment caveat.
</content>
</invoke>
