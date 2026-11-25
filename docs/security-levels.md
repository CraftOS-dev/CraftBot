# Security levels and approvals

Settings > Security controls how much the agent is allowed to do on its own. The default, **Standard** with **Auto mode on**, never prompts and refuses nothing ordinary. Raise the level or turn Auto mode off when you want more protection. A few protections have no reason to be off and are not settings; see [Always on](#always-on-at-every-level).

## Auto mode and approvals

**Auto mode on** (default): the agent acts without asking.

**Auto mode off**: actions that can do real damage wait for you. An approval card appears in the chat (in the browser and the terminal) showing the action and what it will run, with three choices:

- **Allow once**: run this call.
- **Allow for this session**: run this action without asking again in this chat.
- **Deny**: the action is not run, and the agent is told not to retry it.

An action asks first when it can do one of the things selected under "Ask before":

| Effect | Examples |
| --- | --- |
| Running commands or code | Shell and PowerShell commands, Agent App builds |
| Sending messages or changing outside services | Posting, emailing, filling web forms, writing to GitHub or Jira |
| Changing CraftBot's own setup | Schedules, cron jobs, integrations |
| Using stored credentials | API requests with a saved key, signing in to websites |
| Creating or changing files | Asked only at Strict, or when you select it |

At Enhanced and Strict, once the agent has read outside content in a run (a web page, an email, a message from someone else, an online tool's result), any action with an effect asks first. That content may contain instructions planted for the agent.

When nobody can answer, the action is refused and the agent tells you why. This happens when:

- a schedule or cron job started the run;
- you are writing from a chat app such as Telegram;
- no CraftBot window or terminal is open.

Unanswered cards are denied after the timeout (5 minutes by default).

How an action is classified comes from what the action declares about itself (its effects), never from its name or the text of its arguments. MCP tools are classified from their standard `readOnlyHint` and `openWorldHint` annotations. An MCP tool without annotations is treated as one that changes outside services.

## Levels

| Protection | Standard (default) | Enhanced | Strict |
| --- | --- | --- | --- |
| Start MCP servers only as saved in Settings | Off | On | On |
| Ask after outside content (when Auto mode is off) | Off | On | On |
| Keep the agent's file tools away from keys and security settings | Off | On | On |
| File tools write only in the workspace | Off | Off | On |
| Web tools reach public internet only, every redirect checked | First request only (as before) | On | On |
| Third-party page reader (r.jina.ai) | On | On | Off |
| Keep CraftBot's keys out of tools: MCP servers get only basic system variables plus their own; commands get your environment without CraftBot's keys | Off | On | On |
| Write full prompts to logs | On | Off | Off |
| Delete old logs and recorded AI calls | Never | After 90 days | After 30 days |

Changing any single setting shows the level as **Custom**; **Reset** returns to the level's defaults. Your own lists (extra protected paths, allowed folders, allowed domains, email senders) and Auto mode are kept when you switch levels.

**Allowed email senders** (under Email) lets only the listed addresses' Gmail and Outlook messages reach the agent. Empty, the default, lets every inbox email through. A sender address can be forged, so the list narrows what arrives; marking outside content and approvals still apply to what gets through.

## Always on, at every level

- **Destructive commands are refused**, whatever Auto mode says: deleting `/`, a folder directly under it or your home folder, recursively changing their owner or permissions, writing to or formatting a disk, and fork bombs (Hermes Agent's unconditional floor).
- **Outside content is marked as data**: web pages, online tool results and messages from other people reach the model inside markers with a random id, so they read as information, not instructions.
- **CraftBot's own secrets are masked in logs**, and error tracebacks never print variable values.
- **The security audit log** records approvals, refusals and settings changes.
- **Discord owners are matched by user ID.** The first owner matched by unique username has their ID recorded; display names and role names never grant owner authority (an older "Self roles" entry now counts as a third-party role).
- Files that hold keys (`settings.json`, `mcp_config.json`, `security.json`, credentials) are readable by your user only.
- A profile bundle can update an MCP server's settings, but it never receives your saved keys for a server whose command or address it changed.
- The interface's session token is served only to CraftBot's own page in a browser. The terminal client reads it from an owner-only file.

## Security check and audit log

**Security check** lists the state of this installation with a Fix button where a safe fix exists: file permissions, whether the interface is reachable from the network, the audit chain, whether every inbox email or Discord message reaches the agent, MCP servers changed outside Settings, and MCP servers that download the newest package version at each start.

The **audit log** (`.security/audit.jsonl`) records approvals, refusals and settings changes, never prompts or secrets. Each line carries a hash of the line before it, so the check reports where the log was edited or cut.

## What the protections do not cover

- The file and network guards cover the agent's file and web tools, not commands it runs in a shell. Approving commands (Auto mode off) is what covers the shell.
- The destructive-command floor judges the parsed command (program, arguments, and for disks the target's file type), reading it as a shell does: quotes, comments, line continuations, one command per line and here-document text as data. It catches the worst mistakes, not every harmful command; approving commands covers the rest.
- The network guard checks every address a name resolves to and every redirect, and connects to the address it checked. Through a proxy you configured, the proxy makes the connection, so only the checks apply.
- Marking outside content lowers the chance that the agent follows planted instructions; it does not remove it.

## Performance

At the default settings the security gate adds about 1 µs per action and masking secrets about 3 µs per log line (`tests/test_security_standard_unchanged.py`). The higher levels add a path check per file operation and a name lookup per web request. Audit records are written on a background thread.

## For developers: declaring what an action does

Every built-in action declares its effects in the `@action` decorator. A test fails for any action that does not.

```python
@action(
    name="post_report",
    effects=["send_external"],   # [] for a read-only action
    result_source="network",     # when the result is outside content
    ...
)
```

Effects are `execute`, `write_files`, `send_external`, `change_agent` and `use_credentials`. An undeclared action is treated as `execute`. An integration action's write operations are recognized from the `irreversible` and `parallelizable=False` markers it already sets.
