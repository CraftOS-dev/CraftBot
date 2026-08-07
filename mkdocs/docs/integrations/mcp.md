# MCP servers

The [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) is an open standard that lets an external process expose tools to an AI application. CraftBot connects to MCP servers you configure, discovers the tools each one offers, and registers every tool as a regular [action](../core/concepts/actions-and-action-sets.md). Once registered, an MCP tool is called by the agent exactly like a built-in action, so an MCP server is a way to add capabilities without writing an integration.

## What CraftBot ships with

CraftBot comes with a large catalog of MCP servers already listed in the config file, covering messaging, finance, media, smart home, browser automation, and more. Almost all of them are disabled by default. Two are enabled out of the box: a filesystem server and the Playwright browser server. You enable the others as you need them, and most require you to install a runtime or supply a credential first.

## Server configuration

MCP servers are configured in `app/config/mcp_config.json`. The file has a top-level `mcp_servers` array and an `auto_connect` flag that controls whether enabled servers connect at startup. Each server entry looks like this:

```json
{
  "mcp_servers": [
    {
      "name": "filesystem",
      "description": "Read, write, and manage files and directories",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
      "env": {},
      "enabled": true
    },
    {
      "name": "sentry",
      "description": "Query Sentry issues",
      "transport": "sse",
      "url": "https://sentry.example.com/mcp/sse",
      "enabled": false
    }
  ]
}
```

The fields:

| Field | Applies to | Meaning |
|---|---|---|
| `name` | all | Unique server identifier. Becomes the action-set name and part of each tool name |
| `description` | all | Human-readable summary shown in the server list |
| `transport` | all | One of `stdio`, `sse`, or `websocket` |
| `command`, `args`, `env` | `stdio` | How to launch the local server process and its environment variables |
| `url` | `sse`, `websocket` | The remote server endpoint |
| `enabled` | all | Whether CraftBot connects to this server |
| `action_set_name` | all | Optional. Overrides the default action-set name, which is `mcp_<name>` |

CraftBot supports three transports. Use `stdio` to launch a local server as a child process, which is how the community npm and Python servers run. Use `sse` or `websocket` to connect to a remote server over a URL. Server entries that fail validation (an unknown transport, a `stdio` server with no command, a remote server with no URL) are skipped with a warning, and the remaining servers still load.

`mcp_config.json` is watched for changes. When you edit it, or when a command changes it, CraftBot reloads the file, disconnects servers that were removed or disabled, connects newly enabled servers, and re-registers all tools. You do not restart CraftBot to pick up a change.

## Managing servers with the /mcp command

The `/mcp` command manages the config file from chat:

| Command | Effect |
|---|---|
| `/mcp list` | List enabled servers. Add `--all` to include disabled ones with their status |
| `/mcp add <name> --transport stdio -- <command...>` | Add a local stdio server, taking the launch command after `--` |
| `/mcp add-json <name> '<json>'` | Add a server from a full JSON config object, including remote `sse` or `websocket` servers with a `url` |
| `/mcp remove <name>` | Remove a server from the config |
| `/mcp enable <name>` | Enable a server so it connects |
| `/mcp disable <name>` | Disable a server so it stops connecting |
| `/mcp env <name> <KEY> <VALUE>` | Set an environment variable on a server, such as an API token |

Because every change writes the config file and the file is watched, each command takes effect without a restart. Use `/mcp add-json` when the server needs a `url`, custom `env`, or extra arguments, since the plain `/mcp add` form only wires a stdio launch command.

## Settings page

The MCP servers also appear under **Settings → MCP**, listing each configured server with its transport, enabled state, and action set. From there you enable or disable a server and edit its environment variables through the same functions the `/mcp` command uses. Servers whose launch path is not valid on your operating system (for example a macOS-only server viewed on Windows) are marked so you can see why they will not start.

## How tools become actions

When CraftBot connects to a server, it lists the server's tools and converts each one into an action:

- **Action name.** Each tool is registered as `mcp_<server>_<tool>`. The filesystem server's `read_file` tool becomes the action `mcp_filesystem_read_file`. The server prefix keeps names from colliding across servers.
- **Action set.** Every tool from a server joins one action set named `mcp_<server>` (or the server's `action_set_name` if set). The filesystem server's tools all land in the `mcp_filesystem` set.
- **Input schema.** The tool's MCP JSON Schema is translated into CraftBot's action input schema. Properties keep their type and description, entries in the schema's `required` list are marked required, `enum` values are carried over, and a property `default` becomes the field's example.
- **Description.** Each action's description is prefixed with `[MCP:<server>]` followed by the tool's own description, so the agent can see which server a tool came from when it chooses actions.

The result is that MCP tools sit in the action registry next to built-in and integration actions, and the router treats them the same way.

## Selection at task creation

MCP tools are not loaded into every task. They live in their `mcp_<server>` action sets, and those sets are selected for a task the same way any other action set is. When a task needs a server's tools, its action set is loaded, and the tools become available to the agent for that task. Enabling many servers therefore does not bloat every task, because a set only counts against a task once it is selected. See [Actions and action sets](../core/concepts/actions-and-action-sets.md) for how selection works.

## Per-server environment variables

Servers that need a secret read it from the `env` object in their config. Most catalog entries ship with the required keys present but empty, such as `GITHUB_PERSONAL_ACCESS_TOKEN` or `FIRECRAWL_API_KEY`. Fill them in before enabling the server, either by editing the file or with `/mcp env <name> <KEY> <VALUE>`. For a stdio server the values are passed as environment variables to the launched process. Keep real secrets in the config file only on a machine you control, the same as any other credential.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Server never connects, no tools appear | The launch runtime is missing (Node.js/`npx`, `uv`, or Python not installed or not on PATH) | Install the runtime the server needs, then re-enable the server. Check the run logs for lines tagged `[MCP]` |
| Server connects but exposes no tools | The server started but reported an empty tool list, often because it needs setup or a credential first | Read the server's description for its setup steps, provide any required `env` values, then reconnect |
| Tool calls fail with an auth error | A required credential in the server's `env` is empty or wrong | Set it with `/mcp env <name> <KEY> <VALUE>`, then reconnect |
| A configured server does not appear or will not start | Its entry failed validation, or its launch path is not valid on your operating system | Run `/mcp list --all`, check the config for a missing `command` or `url`, and confirm the server supports your OS |
| Tools do not show up in a task | The server's action set was not selected for that task | Confirm the server is enabled with `/mcp list`, and ask for its capability explicitly so the `mcp_<server>` set is loaded |

## Next

- [Integrations](index.md): connect built-in services that expose actions and listeners
- [Credentials](credentials.md): how tokens and OAuth credentials are stored
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how MCP tools load into a task
