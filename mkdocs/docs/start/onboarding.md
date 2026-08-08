# Onboarding

Onboarding is how CraftBot goes from a fresh install to an agent that can work for *you specifically*. It has two distinct phases, and each stores your answers in a different place:

- **Hard onboarding** is a six-step setup wizard shown on first launch. It configures the things the agent cannot run without (a model provider) plus identity and preferences. Everything it collects is written to config files.
- **Soft onboarding** is a get-to-know-you interview the agent itself runs as its first task, right after the wizard finishes. It's a normal conversation. Your answers are distilled into `agent_file_system/USER.md`, which the agent reads on every prompt from then on.

You can skip most of it and configure everything later from Settings, but the two provider steps are required, and finishing the profile steps noticeably improves how the agent communicates with you.

## Hard onboarding: the setup wizard

The wizard runs the first time you launch CraftBot (browser and CLI both present it, and the flow is the same). Six steps, in order:

### 1. Select LLM provider *(required)*

Pick the provider whose model the agent will use. The wizard offers: OpenAI, Google Gemini, BytePlus, Anthropic, DeepSeek, MiniMax, Moonshot, Grok (xAI), Z.ai (GLM), Sakana (Fugu), and Ollama (local, self-hosted). If a provider is already configured in settings, it's pre-selected.

A few providers not shown in the wizard (OpenRouter, AWS Bedrock) can be configured afterwards in **Settings → Model**. The full list with key names and default models is in [LLM providers](../core/providers/llm.md).

### 2. API key *(required)*

Paste the key for the provider you chose. It's stored in `app/config/settings.json` under `api_keys` and never leaves your machine except in requests to that provider.

- If you chose **Ollama**, there is no key. You point CraftBot at your server URL instead (default `http://localhost:11434`).
- If you have a **ChatGPT Plus/Pro/Team** or **SuperGrok** subscription, you can skip API billing entirely and log in with the subscription instead. Set that up afterwards in **Settings → Model**. See [Subscription authentication](../core/providers/subscription-auth.md).

### 3. Agent identity

Name your agent (default: CraftBot) and optionally give it an avatar. The name is what the agent calls itself across all interfaces and connected platforms.

### 4. User profile *(skippable)*

A compact form that seeds the agent's picture of you:

| Field | Options / behavior |
|---|---|
| Language | Full language list, pre-selected from your OS locale |
| Location | Auto-detected from your IP (editable); used for timezone- and locale-aware behavior |
| Tone | Casual · Formal · Friendly · Professional |
| Proactivity | **Low**: wait for instructions · **Medium**: suggest when relevant · **High**: proactively suggest things |
| Approval required for | Sending messages on your behalf · Creating/modifying schedules · Modifying files · Purchases/payments · All actions |
| Preferred platform | Telegram · WhatsApp · Discord · Slack · the CraftBot interface |

The approval setting matters most: it defines which categories of action the agent must ask you about before doing. Start stricter. You can loosen it later as trust builds.

### 5. Recommended skills *(skippable)*

Toggle a starter set of [skills](../core/concepts/skills.md), packaged step-by-step workflows the agent loads when a task calls for them. Items marked **Setup required** depend on an MCP server you haven't configured yet. They'll activate once you add it ([MCP servers](../integrations/mcp.md)).

### 6. Connect external apps *(skippable)*

Connect Gmail, Slack, GitHub, Notion, or any other [integration](../integrations/index.md) right in the wizard, or skip and do it anytime from **Settings → Integrations**.

Every step except the two provider steps can be skipped, and you can go back to earlier steps while the wizard is open. When you finish, the wizard marks itself complete and hands off to soft onboarding.

## Soft onboarding: the agent's interview

Immediately after the wizard, the agent starts a short conversational task: it greets you by name and interviews you about identity details, how you like to communicate, what you're working toward, and how hands-on you want it to be. This is a normal chat. Answer as much or as little as you want.

This phase has two effects:

1. **Your answers persist.** The agent writes them into `agent_file_system/USER.md` (and agent-behavior notes into `AGENT.md`). `USER.md` is injected into the agent's context on every single prompt, which makes it the highest-leverage file in the system for shaping behavior.
2. **It doesn't block anything.** You can give the agent real work mid-interview. It routes your task normally and returns to the interview later.

You can also edit `USER.md` directly at any time. It's plain markdown, and the agent picks up changes immediately. See [Agent file system](../core/concepts/agent-file-system.md).

## Where everything is stored

| What | File |
|---|---|
| Completion state (hard/soft done, timestamps), your name, agent name, avatar | `app/config/onboarding_config.json` |
| Provider, API keys, model settings | `app/config/settings.json`; see [Settings](../core/configuration/config-json.md) |
| Enabled skills | `app/config/skills_config.json` |
| Integration credentials | `.credentials/`; see [Credentials](../integrations/credentials.md) |
| Your profile (soft onboarding answers) | `agent_file_system/USER.md` |

## Changing things later

You almost never need to re-run the wizard, because every setting it touches has a permanent home:

- **Provider or key:** `/provider <name> <key>` in chat, or **Settings → Model**.
- **Agent name / language:** **Settings → General**.
- **Skills:** `/skill` command or **Settings → Skills**.
- **Integrations:** **Settings → Integrations**, or `/cred` to inspect what's connected.
- **Your profile:** edit `agent_file_system/USER.md` directly, or just tell the agent ("from now on, keep answers short") and let it update its own files.

To force the wizard to run again from scratch, stop CraftBot and reset the completion flags in `app/config/onboarding_config.json` (set `hard_completed` to `false`), then restart. Setting `soft_completed` to `false` re-triggers the interview instead.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Wizard doesn't appear on first launch | Onboarding already marked complete (e.g. reused config) | Reset flags in `app/config/onboarding_config.json`, restart |
| Can't proceed past API key | Key invalid for the chosen provider | Test the key in the provider's console; check for pasted whitespace |
| Skill shows "Setup required" | It depends on an unconfigured MCP server | Add the server in [MCP servers](../integrations/mcp.md), then enable the skill |
| Agent never started the interview | Soft onboarding flag already set, or the task was interrupted | Set `soft_completed` to `false` in `onboarding_config.json`, restart |
| Location detected wrong | IP geolocation is approximate | Edit the field in the wizard, or fix it later in `USER.md` |

## Next

- [Your first task](first-task.md): put the configured agent to work
- [Settings reference](../core/configuration/config-json.md): every field the wizard wrote
- [Memory](../core/concepts/memory.md): how the agent keeps learning about you after onboarding
