# Commands

Commands are slash-prefixed inputs (`/help`, `/provider anthropic sk-...`, `/skill enable pdf`) that the [UI layer](../interfaces/ui-layer.md) intercepts before anything reaches the agent. They're how you configure providers, integrations, skills, and MCP servers (instantly, without spending tokens or waking the agent) and they work identically in the [browser](../interfaces/browser.md) and the [CLI](../interfaces/cli.md).

<div class="grid cards" markdown>

- :material-book-alphabet:{ .lg .middle } __[Built-in commands](builtin.md)__

    ---

    The complete reference: every command, alias, and subcommand.

- :material-console-line:{ .lg .middle } __[CLI-anything](cli-anything.md)__

    ---

    The bundled skill that automates desktop apps (GIMP, Blender, LibreOffice, ...) through cross-platform command-line harnesses.

</div>

## How dispatch works

When you submit input, the UI controller offers it to the command executor first. Input starting with `/` is split into a name and arguments, resolved against the command registry (aliases included, case-insensitive), and executed; the result comes back as a system message. Anything not starting with `/` goes to the agent as a normal chat message.

An unknown command like `/frobnicate` returns `Unknown command`. It is **not** forwarded to the agent. Commands and conversation are handled separately.

In the browser, typing `/` opens an autocomplete listing everything registered, so you rarely need to memorize names. In the CLI, `/help` prints the same list.

## Four kinds of commands

The registry is populated from four sources at startup:

| Kind | Examples | Where they come from |
|---|---|---|
| **Built-in** | `/help`, `/provider`, `/mcp`, `/skill`, `/cred`, `/update` | Shipped in `app/ui_layer/commands/builtin/` — always present |
| **Integration** | `/gmail`, `/slack`, `/telegram_bot`, `/notion` | One per available [integration](../../integrations/index.md), each with `connect` / `disconnect` / `status` plus integration-specific subcommands |
| **Skill** | `/pdf`, `/docx`, `/pptx` | One per **enabled** [skill](../concepts/skills.md); registered and unregistered live as you toggle skills |
| **Agent-provided** | varies | Commands the agent runtime registers programmatically, wrapped into the same registry |

Built-in and integration commands run immediately in the UI layer. Skill commands are different: `/pdf merge these three files` doesn't run UI code. It routes your text to the agent with that skill pre-selected, and the argument text is substituted into the skill's instructions via `$ARGUMENTS`. It's a shortcut for "do this task, using this skill."

## The commands you'll actually use

```
/help                      # list every command; /help mcp for details on one
/provider [name] [key]     # view or switch the LLM provider
/mcp list                  # manage MCP servers
/skill list                # manage skills
/cred status               # see which integrations are connected
/update --check            # check for a new CraftBot version
/clear                     # clear the chat        /reset   # reset agent state
/exit                      # shut down
```

The full catalogue with every subcommand is in [Built-in commands](builtin.md).

## Related

- [Interfaces](../interfaces/index.md): where you type commands
- [UI layer](../interfaces/ui-layer.md): the registry and executor behind dispatch
- [Skills](../concepts/skills.md): the packages behind skill slash commands
- [MCP](../../integrations/mcp.md): what `/mcp` manages
