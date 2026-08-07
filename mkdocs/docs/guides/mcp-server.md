# Add an MCP server

This guide connects an external Model Context Protocol (MCP) server to CraftBot and puts its tools in front of the agent. When you finish, the server's tools appear as ordinary actions the agent can select and call during a task, so you extend what the agent can do without writing an integration.

An MCP server is an external process that exposes a set of tools. When CraftBot connects to one, it discovers each tool and registers it as a regular [action](../core/concepts/actions-and-action-sets.md), grouped into an action set the agent loads when a task needs it. From the agent's side there is no difference between an MCP tool and a built-in action. Both are called the same way and selected the same way. The mechanics are covered in [MCP servers](../integrations/mcp.md).

## What you need

| Requirement | Details |
|---|---|
| A working CraftBot | Finish the [Quickstart](../start/quickstart.md) so the agent replies in the browser |
| The server's launch details | Its command and arguments (for a local server) or its URL (for a remote one) |
| Any credential the server needs | Some servers require an API key or token supplied as an environment variable |
| The runtime the server needs | Local servers usually launch through `npx` (Node.js) or `uvx`/`python`, which must be installed and on your PATH |

This guide uses the official filesystem server as the worked example, since it needs no credential and installs on demand through `npx`.

## Step 1: add the server

Servers live in `app/config/mcp_config.json`, and the `/mcp` command edits that file for you from chat.

For a local (stdio) server, the quickest form launches a command directly:

```
/mcp add filesystem --transport stdio -- npx -y @modelcontextprotocol/server-filesystem .
```

Everything after `--` is the launch command. This adds a server named `filesystem` that CraftBot starts as a child process.

When you want precise control over the command, its arguments, environment, or a remote URL, use `add-json` and pass a full config object:

```
/mcp add-json filesystem '{"transport":"stdio","command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","."],"description":"Read, write, and manage files"}'
```

The written entry looks like this in `mcp_config.json`:

```json
{
  "name": "filesystem",
  "description": "Read, write, and manage files",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
  "env": {},
  "enabled": true
}
```

The config fields:

| Field | Applies to | Meaning |
|---|---|---|
| `name` | all | Unique identifier. Becomes the action-set name and part of each tool name |
| `transport` | all | `stdio` to launch a local process, or `sse` / `websocket` for a remote server |
| `command`, `args`, `env` | `stdio` | The executable, its arguments, and environment variables for a local server |
| `url` | `sse`, `websocket` | The remote server endpoint |
| `enabled` | all | Whether CraftBot connects to this server |

**Remote servers use `add-json`.** The `/mcp add --transport http <url>` form is shown in the command's help, but CraftBot only accepts the `stdio`, `sse`, and `websocket` transports, so an `http` entry fails validation and is not added. To register a remote server, pass a `url` with a valid transport through `add-json`:

```
/mcp add-json sentry '{"transport":"sse","url":"https://sentry.example.com/mcp/sse"}'
```

The full field reference is in [MCP servers](../integrations/mcp.md#server-configuration).

## Step 2: supply credentials

The filesystem server needs no credential, so you can skip ahead. Many servers do need one, supplied as an environment variable rather than typed into the tool call.

Set a variable on a server with `/mcp env`:

```
/mcp env github GITHUB_PERSONAL_ACCESS_TOKEN ghp_your_token_here
```

This writes the key into the server's `env` object in the config. For a stdio server the values are passed as environment variables to the launched process. Fill in every required key before you enable the server, so it can authenticate on its first connection. Keep real secrets in the config only on a machine you control, the same as any other credential.

## Step 3: enable and verify the tools

List your servers to confirm the entry exists:

```
/mcp list          # enabled servers
/mcp list --all    # include disabled ones with their status
```

Enable the server so CraftBot connects to it:

```
/mcp enable filesystem
```

On connection, CraftBot lists the server's tools and registers each one as an action. Two naming rules let you find them:

- Each tool becomes an action named `mcp_<server>_<tool>`. The filesystem server's `read_file` tool registers as `mcp_filesystem_read_file`. The server prefix keeps names from colliding across servers.
- Every tool from the server joins one action set named `mcp_<server>`. The filesystem server's tools all land in the `mcp_filesystem` action set.

To confirm the tools registered, ask the agent what it can do with the server, or open **Settings → MCP** and check that the server shows as connected with its action set listed. If the server connected but no tools appeared, it usually needs setup or a credential first. See the troubleshooting table.

**Checkpoint:** `/mcp list` shows the server enabled, and its tools exist as `mcp_<server>_<tool>` actions.

## Step 4: use the new tools

MCP tools are not forced into every task. They live in their `mcp_<server>` action set, which is selected for a task only when the task needs it, the same way any other action set is chosen at task creation. So the way to use a new server is to ask for something that clearly needs its capability, and the agent loads the set. How that selection works is described in [Actions and action sets](../core/concepts/actions-and-action-sets.md).

Ask for work that uses the server. For the filesystem server:

```
List the markdown files in my notes folder and tell me which one
was edited most recently.
```

The agent recognizes the request needs file tools, selects the `mcp_filesystem` action set for the task, and calls the server's tools to answer. You can watch the calls in the browser's action panel, where MCP actions appear alongside built-in ones.

## Step 5: manage servers

All management runs through the same `/mcp` command or the settings page, and every change is picked up without a restart.

| Command | Effect |
|---|---|
| `/mcp list` | List enabled servers; add `--all` for disabled ones and their status |
| `/mcp enable <name>` | Enable a server so it connects |
| `/mcp disable <name>` | Disable a server so it stops connecting |
| `/mcp remove <name>` | Remove a server from the config entirely |
| `/mcp env <name> <KEY> <VALUE>` | Set an environment variable, such as an API token |

The same servers appear under **Settings → MCP**, which lists each one with its transport, enabled state, and action set. You enable, disable, and edit environment variables there through the same functions the commands use. A server whose launch path is not valid on your operating system is marked so you can see why it will not start.

Every one of these actions writes `mcp_config.json`, and CraftBot watches that file. When it changes, CraftBot disconnects servers that were removed or disabled, connects newly enabled ones, and re-registers all tools. You do not restart CraftBot to pick up a change, whether you made it through a command, the settings page, or by editing the file by hand.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Server never connects, no tools appear | The launch runtime is missing (`npx`/Node.js, `uv`, or Python not installed or not on PATH) | Install the runtime the server needs, then re-enable it. Check the logs for lines tagged `[MCP]` |
| Server connects but exposes no tools | It started but needs setup or a credential first | Provide the required `env` values with `/mcp env`, then disable and re-enable it |
| Tool calls fail with an auth error | A required key in the server's `env` is empty or wrong | Set it with `/mcp env <name> <KEY> <VALUE>`, then reconnect |
| A remote server will not add or start | It was added with an invalid transport | Use `/mcp add-json` with a `url` and transport `sse` or `websocket`, not `--transport http` |
| Tools do not show up in a task | The server's action set was not selected for that task | Confirm the server is enabled with `/mcp list`, and ask for its capability explicitly so the `mcp_<server>` set is loaded |

## Next

- [MCP servers](../integrations/mcp.md): the full configuration reference and the bundled server catalog
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how MCP tools load into a task
- [Integrations](../integrations/index.md): connect built-in services that ship their own actions and listeners
