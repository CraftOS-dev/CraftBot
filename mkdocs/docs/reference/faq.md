# FAQ

Frequently asked questions about CraftBot, grouped by topic. Every answer links to the page that covers it in full.

## Cost and models

### Does CraftBot cost money?

CraftBot itself is free and open source under the [MIT license](https://github.com/CraftOS-dev/CraftBot/blob/main/LICENSE). You bring your own model, so what you pay is whatever your chosen provider charges. If you use a hosted API such as Anthropic or OpenAI, you pay that provider per token. If you run a local model through [Ollama](../core/providers/llm.md), you spend zero tokens and pay nothing beyond your own hardware and electricity. There is no CraftBot subscription and no account with CraftOS to buy.

### Which model should I use?

The default provider is Anthropic Claude, and it is a good starting point for out-of-box agent quality. CraftBot supports 13 providers behind one setting, including OpenAI, Google Gemini, xAI Grok, DeepSeek, OpenRouter, and AWS Bedrock. Every provider ships a working default model, so a key is all you need to start. For zero cost and full privacy, run a local model through Ollama. The full matrix, default models, and a "you want / pick / why" table are on [LLM providers](../core/providers/llm.md).

### Can I use my ChatGPT or Grok subscription instead of an API key?

Yes, for OpenAI and Grok. If you already pay for ChatGPT Plus, Pro, or Team, or for SuperGrok, CraftBot can run on that subscription's quota. You sign in through the provider's own OAuth page in your browser, and no API key is created or copied. When a subscription is connected it takes precedence over any stored key, and the reachable model list narrows to what that subscription serves. See [Subscription authentication](../core/providers/subscription-auth.md) for the connect steps. There is no Anthropic subscription option, because Anthropic's terms forbid third-party apps from using Claude Pro or Max tokens. Anthropic is API-key only.

### Does it work offline?

Only with a local model. If you run Ollama on your machine, the agent's reasoning happens without any internet connection. Every hosted provider (Anthropic, OpenAI, and the rest) needs internet, because each call goes to that provider's servers. Integrations and web research also need internet, since they reach external services. So a local model gives you offline reasoning, but tasks that touch the web or a connected app still require a connection.

## Privacy and data

### Where is my data stored?

Everything stays on your machine, inside the CraftBot project folder. The agent's files (its memory, profile, and task outputs) live in `agent_file_system/`. Configuration and API keys live in `app/config/settings.json`. Integration credentials live in `.credentials/`. Logs live in `logs/`. The memory vector index lives in `chroma_db_memory/`. The only thing that ever leaves your machine is what you configure it to send: model calls to your provider, and requests to the integrations you connect.

### Does CraftBot send my data anywhere?

Only to the two destinations you set up yourself. Your prompts, and the context the agent needs to reason, go to the model provider you configured. Data for a connected integration goes to that service (for example, a message you ask it to post goes to Slack). Nothing is sent to CraftOS or any central server. With a local Ollama model and no integrations, nothing leaves your machine at all.

### How do I delete my data or reset the agent?

The `/reset` command returns the agent to its initial state. It clears the current task, action history, and conversation context, deletes the agent's markdown files in `agent_file_system/` and restores them from templates, and wipes the chat view. Saved settings and credentials are not touched, and Living UI projects are preserved. To clear memory specifically, the interface's memory settings can remove individual items or reset `MEMORY.md` from its template. To remove everything, delete the project clone from disk. See [`/reset`](../core/commands/builtin.md#reset).

### Is my API key safe?

Your keys are stored locally in `app/config/settings.json` and stay on your machine. Integration credentials sit in `.credentials/`, which CraftBot creates with owner-only permissions (`0700` on the directory, `0600` on each file) on a best-effort basis where the operating system supports it. Keys are not bundled into release builds and are not sent to CraftOS. Keep the project folder off shared drives and out of version control, and treat `.credentials/` as sensitive. See [Credentials](../integrations/credentials.md).

## Running it

### Do I need to keep a terminal open?

No. Service mode runs CraftBot as a background process that starts when you log in and keeps running after you close the terminal and the browser tab. Scheduled tasks, proactive work, and integration listeners all keep going. Install it with `python craftbot.py install`, then manage it with `status`, `start`, `stop`, and `restart`. See [Service mode](../start/service-mode.md).

### Can I run it on a server or access it remotely?

Yes. Install CraftBot on an always-on machine so schedules fire even with your laptop closed. The interface binds to localhost, so reach it over an SSH port-forward or a private network such as Tailscale rather than exposing the port. There is no built-in authentication on the interface, so anyone who can reach the port controls your agent. Never expose the port directly to the internet. The [Service mode security notes](../start/service-mode.md#security-notes) cover this in full.

### Can multiple people use one CraftBot?

Not through a single shared instance. CraftBot installs per user, with separate configuration and credentials, so two accounts on one machine can each run their own. The interface has no authentication and no notion of separate logged-in users, so do not put it in front of a group by exposing the port. Give each person their own install instead.

### Does it need Node.js?

Only for the browser interface, which is the default mode and needs Node.js 18 or newer. The command-line interface needs no Node.js at all. Launch it with `python run.py --cli` for the same agent underneath. Full prerequisites are on [Install](../start/install.md).

## Capabilities

### What can the agent actually do?

The agent has more than 1,100 built-in actions covering file operations, shell commands, web research, document conversion, and image and video generation, plus deep per-integration coverage. It connects to services like Gmail, Slack, Discord, GitHub, Notion, and Stripe, runs 195 bundled skills for repeatable workflows, and can build and operate its own web apps through Living UI. See the [actions catalogue](../core/concepts/default-actions.md), [Integrations](../integrations/index.md), and [Living UI](../living-ui/index.md).

### How is this different from ChatGPT or a chat assistant?

A chat assistant answers you. CraftBot executes tasks with real tools. It plans a request into steps, runs actions you can watch fire one by one, remembers your preferences across sessions through [memory](../core/concepts/memory.md), and proposes work on its own schedule once you enable proactive mode (always asking before it acts). It can also build working software and keep operating it. And it runs on your own machine rather than a vendor's servers.

### Can I add my own capabilities?

Yes, at several layers. You can write skills to teach the agent repeatable workflows, add custom actions, build integrations to new services, and package specialist agents as bundles. The [Develop](../develop/index.md) section documents each path.

### Is my data used to train models?

That depends entirely on the provider you choose, and it is that provider's policy, not CraftBot's. CraftBot stores nothing centrally and has no training pipeline of its own. If training on your data is a concern, check your provider's data-use terms, or run a local model through Ollama so nothing leaves your machine.

## Troubleshooting

### The agent will not respond or something broke. What do I check?

Start with [Troubleshooting](troubleshooting/index.md), which walks through the common failures: the interface not loading, `hello` getting no reply, authentication errors, and tasks that hang. The fastest first checks are `python craftbot.py status` to confirm the service is running and `python craftbot.py logs` to read recent output.

## Next

- [Troubleshooting](troubleshooting/index.md): step-by-step fixes for the common failures
- [Learning path](../start/learning-path.md): pick a reading track for what you want to build
- [Discord](https://discord.gg/ZN9YHc37HG): ask the community
