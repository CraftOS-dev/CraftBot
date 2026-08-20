# Built-in commands

Every slash command shipped with CraftBot, with its aliases, subcommands, and behavior. All of them work in both [interfaces](../interfaces/index.md). The one marked otherwise says so.

At a glance:

| Command | Aliases | What it does |
|---|---|---|
| [`/help [command]`](#help) | `/h`, `/?` | List commands, or detail one |
| [`/clear`](#clear) | `/cls` | Clear the current chat session |
| [`/reset`](#reset) | — | Reset agent state and clear history |
| [`/exit`](#exit) | `/quit`, `/q` | Shut down CraftBot |
| [`/menu`](#menu) | — | Open the settings menu (browser only) |
| [`/provider [name] [key]`](#provider) | — | View or change the LLM provider |
| [`/mcp <subcommand>`](#mcp) | — | Manage MCP servers |
| [`/skill <subcommand>`](#skill) | — | Manage skills |
| [`/cred <subcommand>`](#cred) | — | Credentials and integration status |
| [`/update [--check]`](#update) | `/upgrade` | Check for and install updates |
| [`/tokens`](#tokens) | — | Show this session's token usage |

Beyond these, the registry also holds [integration commands](#integration-commands) (`/gmail`, `/slack`, ...) and [skill commands](#skill-commands) (`/pdf`, `/docx`, ...), covered at the end.

## /help

```
/help              # list all commands with descriptions and aliases
/help mcp          # usage, subcommands, and examples for one command
```

The leading slash on the argument is optional (`/help mcp` and `/help /mcp` both work). Skill shortcuts are hidden from the main list to keep it short. `/skill list` shows them.

## /clear

Clears the conversation of the session it's typed in: the persisted chat messages plus the agent-side session state (event stream, todos, run budgets), so a restart won't resurrect the cleared chat. Other sessions, dashboard data, and the session's lifetime [token counters](#tokens) are unaffected. Use it when one conversation is cluttered. Use [`/reset`](#reset) when the *agent* needs a fresh start.

## /reset

Resets the agent to its initial state: deletes extra chat sessions, clears Main, and clears Living UI chat history (Living UI **apps** are kept unless you choose that option in Settings → Reset Agent). It also restores the agent's markdown files in `agent_file_system/` from their templates, rebuilds the memory index, and clears dashboard usage data. Workspace outputs are wiped too. Saved settings and credentials are **not** affected. Feedback arrives as system messages while the reset runs in the background.

## /exit

Stops the agent cleanly and ends the session. In [service mode](../../start/service-mode.md) the service manager may restart it. Use `python craftbot.py stop` to keep it down.

## /menu

Opens the settings menu. Browser only, and hidden from the `/help` list. In the CLI it points you to `/help` instead. (In practice you'll click **Settings** in the sidebar; the command exists mainly for keyboard-first use.)

## /provider

View or switch the LLM provider without opening settings.

```
/provider                        # show current provider and masked API key
/provider anthropic              # switch provider (keeps any stored key)
/provider anthropic sk-ant-...   # switch and set the key in one line
```

Bare `/provider` masks the key as its first four and last four characters (`sk-a...abcd`).

Accepted names:

| Name | Provider | Key |
|---|---|---|
| `openai` | OpenAI | `OPENAI_API_KEY` |
| `gemini` | Google Gemini | `GOOGLE_API_KEY` |
| `anthropic` | Anthropic | `ANTHROPIC_API_KEY` |
| `byteplus` | BytePlus | `BYTEPLUS_API_KEY` |
| `deepseek` | DeepSeek | `DEEPSEEK_API_KEY` |
| `grok` | Grok (xAI) | `XAI_API_KEY` |
| `glm` | Z.ai (GLM) | `ZAI_API_KEY` |
| `fugu` | Sakana (Fugu) | `SAKANA_API_KEY` |
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` |
| `remote` | Ollama (local) | none |

The change is saved to `settings.json` and the LLM client reinitializes immediately, with no restart — a genuine provider change also resets the per-session model caches, while re-running the command with nothing changed is a no-op. Switching providers clears any model override so the new provider starts on its default model. Model selection, base URLs, and subscription login live in **Settings → Model**; see [LLM providers](../providers/llm.md).

## /mcp

Manage [MCP servers](../../integrations/mcp.md). `/mcp` with no arguments prints usage.

| Subcommand | Does |
|---|---|
| `list [--all]` | List enabled servers; `--all` includes disabled ones |
| `add <name> --transport stdio -- <cmd...>` | Add a stdio server (everything after `--` is the launch command) |
| `add <name> --transport http <url>` | Add an HTTP server |
| `add-json <name> '<json>'` | Add a server from a JSON config block |
| `remove <name>` | Remove a server |
| `enable <name>` / `disable <name>` | Toggle a server without removing it |
| `env <name> <key> <value>` | Set an environment variable for a server |

```
/mcp add myserver --transport stdio -- python server.py
/mcp add remote-tools --transport http https://example.com/mcp
/mcp env myserver API_KEY my-secret-key
/mcp list --all
```

The browser's **Settings → MCPs** page edits the same configuration.

## /skill

Manage [skills](../concepts/skills.md). `/skill` with no arguments prints usage.

| Subcommand | Does |
|---|---|
| `list [--all]` | List enabled skills; `--all` includes disabled ones |
| `info <name>` | Description, version, author, path, and the skill's actions |
| `enable <name>` / `disable <name>` | Toggle a skill — this also registers/unregisters its slash command |
| `install <path>` | Install from a local directory |
| `install <git-url>` | Install from a GitHub/GitLab URL |
| `create <name> [description]` | Scaffold a new skill |
| `remove <name>` | Remove a skill |
| `reload` | Re-scan skills from disk |
| `dirs` | Show the directories scanned for skills |

```
/skill info pdf
/skill enable cli-anything
/skill install https://github.com/user/skill.git
/skill create my_skill "My custom skill"
```

## /cred

Read-only overview of credentials and integrations. Connecting happens with the [per-integration commands](#integration-commands) or **Settings → Integrations**.

| Subcommand | Does |
|---|---|
| `list` | Every integration with connected / not connected |
| `status` | Same, with account names for connected integrations and a connected count |
| `integrations` | Every available integration with its `/command` and description |

## /update

```
/update            # check GitHub for a newer version and install it
/update --check    # check only, don't install
```

An update pulls the latest code, installs dependencies, and restarts CraftBot automatically, streaming progress as system messages. If you're already current, it says so.

## /tokens

Prints the cumulative token usage of the chat it's typed in, as a system message:

```
Session token usage
  Input:  79,022
  Cached: 312,455
  Output: 5,770
  Total:  84,792
```

**Input** is genuinely new prompt tokens (cache reads excluded), **Cached** is prompt tokens served from the provider's cache, and **Total** is Input + Output. Totals accumulate across every run in the session and survive restarts and [`/clear`](#clear) (clearing wipes the conversation, not the session's lifetime counters). A brand-new chat that hasn't sent a message yet reports zeros. Sessions created before this command existed start counting from their next run.

## Integration commands

Every available [integration](../../integrations/index.md) registers its own command named after itself: `/gmail`, `/slack`, `/discord`, `/telegram_bot`, `/notion`, and so on (run `/cred integrations` for the live list). Each supports:

```
/<integration>              # help, including integration-specific subcommands
/<integration> connect      # start the connect flow (token, OAuth, or interactive/QR)
/<integration> disconnect
/<integration> status       # connection state and accounts
```

Token-based integrations take their credentials as arguments, like `/telegram_bot connect <token>` (running `connect` bare tells you which fields it needs). OAuth ones open the provider's flow. Interactive ones (like WhatsApp Web) walk you through it. Some handlers add extra subcommands (QR login, invites), listed in that integration's help. Details per service are on the [integration pages](../../integrations/index.md).

## Skill commands

Every **enabled** skill is also a slash command: `/pdf`, `/docx`, `/xlsx`, and whatever else you've enabled. These don't run UI code. They hand your text to the agent with that skill pre-selected:

```
/pdf merge report-a.pdf and report-b.pdf into final.pdf
```

Arguments flow into the skill's instructions through `$ARGUMENTS` substitution (skills can also grab positional pieces with `$ARGUMENTS[0]`, `$1`, ...). Invoked bare, the agent asks what you need. Enabling or disabling a skill registers or removes its command immediately, and a skill whose name collides with an existing command is skipped. They're hidden from `/help`. See them with `/skill list` or the browser's `/` autocomplete.

## Related

- [Commands overview](index.md): how dispatch works
- [CLI-anything](cli-anything.md): the desktop-app automation skill
- [UI layer](../interfaces/ui-layer.md): the registry these commands live in
- [Credentials](../../integrations/credentials.md): where connected secrets are stored
