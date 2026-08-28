# Configuration

Everything that shapes CraftBot's behavior lives in plain local files inside the repository. Nothing is stored in the cloud. This page maps what lives where, so you change the right file (or better, the right Settings page) for the thing you want.

## The configuration map

| Surface | Location | What it controls |
|---|---|---|
| **Runtime settings** | `app/config/settings.json` | The main config: agent name, model providers, API keys, memory/proactive toggles, endpoints. Full reference: [settings.json](config-json.md) |
| **Feature configs** | `app/config/*.json` | One file per subsystem: MCP servers, skills, schedules, Telegram/WhatsApp listeners, onboarding state. Table below in [settings.json](config-json.md#other-files-in-appconfig) |
| **Agent identity** | `agent_file_system/*.md` | Who the agent *is*: personality (`SOUL.md`), what it knows about you (`USER.md`), long-term memory, standing instructions. See [Agent .md files](../../reference/agent-md-files.md) |
| **Agent bundles** | `agent_bundle/agents/<slug>/agent.yaml` | Manifests for the prebuilt specialist agents (`.craftbot` bundles). Reference: [Agent bundle agent.yaml](agent-config-yaml.md) |
| **Integration credentials** | `.credentials/` | OAuth tokens and refresh state per connected platform. See [Credentials](../../integrations/credentials.md) |
| **Environment variables** | OS env | Fallbacks for OAuth client IDs, AWS credentials, and provider keys. Complete table: [Environment variables](../../reference/env-vars.md) |
| **Launcher state** | `config.json` (repo root) | Install-time flag for `run.py`/`install.py` (`use_conda`). Not runtime config; don't confuse it with `settings.json` |

## Which file to edit

| I want to… | Do this | File touched |
|---|---|---|
| Switch model provider or set a key | `/provider anthropic sk-ant-...` or **Settings → Model** | `settings.json` |
| Point at a local Ollama server | **Settings → Model** → Remote provider | `settings.json` → `endpoints.remote_model_url` |
| Rename the agent | **Settings → General** | onboarding state / `settings.json` → `general.agent_name` |
| Turn proactive mode on/off | **Settings → Proactive** | `settings.json` → `proactive.enabled` |
| Tune or disable memory | **Settings → Memory** | `settings.json` → `memory.*` |
| Add or enable an MCP server | `/mcp` or **Settings → MCP** | `mcp_config.json` |
| Enable or disable a skill | `/skill` or **Settings → Skills** | `skills_config.json` |
| Add a recurring schedule | Ask the agent, or **Settings → Proactive** (see [Scheduling](../concepts/scheduling.md)) | `scheduler_config.json` |
| Change the agent's personality | Edit `agent_file_system/SOUL.md` | `SOUL.md` |
| Connect Telegram, Slack, Gmail… | **Settings → Integrations** | `.credentials/` |
| Install a specialist agent | Import a `.craftbot` bundle in **Settings → General** (see [agent.yaml](agent-config-yaml.md)) | skills, MCP config, `SOUL.md`/`AGENT.md` |

## Prefer the UI over hand-editing

Nearly every setting has a browser Settings page (General, Model, Memory, Proactive, MCP, Skills, Integrations) or a slash command (`/provider`, `/mcp`, `/skill`, `/cred`). Use those when you can: they validate input and keep bookkeeping fields consistent. Hand-editing is fine too: a config watcher hot-reloads `settings.json`, `mcp_config.json`, `skills_config.json`, and `scheduler_config.json` within seconds, no restart needed. But a JSON syntax error silently keeps the *old* config active, so read the file back after editing.

You can also just ask the agent. It has full knowledge of these files and edits them with the same care (its own reference for every schema ships in `agent_file_system/AGENT.md`).

## Precedence for credentials

`settings.json` is the source of truth the runtime reads. Environment variables act as a fallback or override for specific credentials only: OAuth client IDs/secrets (env → embedded defaults), AWS credentials and region (`settings.json` → `AWS_*` env), and subscription-login client IDs. The complete env table is in [Environment variables](../../reference/env-vars.md). Don't scatter keys across both layers; pick `settings.json` unless you have a reason not to.

## Next

- [settings.json](config-json.md): every section and key, with defaults and effects
- [Agent bundle agent.yaml](agent-config-yaml.md): the specialist-agent manifest format
- [Onboarding](../../start/onboarding.md): the wizard that writes most of this for you on first run
