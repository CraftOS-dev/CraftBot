# Develop

This section is for extending CraftBot rather than driving it. Extending means adding new capability to the agent and its runtime: a single action that calls your code, a skill that packages a repeatable workflow, an integration that connects a new external service, or an agent bundle with its own personality and knowledge. It also means understanding the architecture the agent runs on, so your addition lands in the right place and loads the way the built-in ones do. Every extension point below follows the same shape: you write plain Python or a small bundle of files, register it, reload, and the agent can use it. Read [Architecture](architecture.md) first if you want the map before you build; jump straight to a build page if you already know what you need.

## Extension points

<div class="grid cards" markdown>

- :material-sitemap-outline:{ .lg .middle } __[Architecture](architecture.md)__

    ---

    How the `agent_core` engine, the `app` runtime, and their data flows fit together. Read this first.

- :material-lightning-bolt-outline:{ .lg .middle } __[Custom action](custom-action.md)__

    ---

    Write one action: a Python function with input and output schemas the agent can call.

- :material-toolbox-outline:{ .lg .middle } __[Skills overview](skills/index.md)__

    ---

    What a skill is, when to write one, and where skills live on disk.

- :material-file-document-edit-outline:{ .lg .middle } __[Write a CraftBot skill](skills/craftbot-skill.md)__

    ---

    Scaffold a skill, define its actions and prompt, reload, and test it end to end.

- :material-source-branch:{ .lg .middle } __[External skills](skills/external-skill.md)__

    ---

    Load community-built or shared skills from disk without adding them to the repo.

- :material-package-variant:{ .lg .middle } __[Custom agent](custom-agent.md)__

    ---

    Subclass `AgentBase` into a bundle with its own personality, RAG docs, and actions.

- :material-connection:{ .lg .middle } __[Custom integration](custom-integration.md)__

    ---

    Add a new external service (a messaging platform or SaaS API) to the integration framework.

- :material-git:{ .lg .middle } __[Contributing](contributing.md)__

    ---

    Development setup, the branch and PR workflow, and how to run lint and smoke tests locally.

</div>

## Which extension point do I need?

Match your goal to the page that covers it.

| Your goal | Extension point | Page |
|---|---|---|
| Give the agent one new tool that calls your code or an API | A custom action | [Custom action](custom-action.md) |
| Package a repeatable workflow (actions plus prompt instructions) the agent loads on demand | A skill | [Write a CraftBot skill](skills/craftbot-skill.md) |
| Reuse a skill someone else wrote, or share yours across machines | An external skill | [External skills](skills/external-skill.md) |
| Connect a new external service with authentication and a listener | An integration | [Custom integration](custom-integration.md) |
| Ship a dedicated agent with its own persona and knowledge base | An agent bundle | [Custom agent](custom-agent.md) |
| Import tools from an existing MCP server instead of writing code | An MCP connection | [MCP servers](../integrations/mcp.md) |
| Understand where any of the above plugs into the runtime | Architecture reference | [Architecture](architecture.md) |

Actions are the primitive underneath every extension point. A skill groups actions, an integration adds actions plus a connection and listener, and an agent bundle can ship its own actions alongside a personality. When you are unsure whether you need an action or a skill, start with a [custom action](custom-action.md) and promote it to a skill once you have more than one related action to package.

## Related

- [Actions and action sets](../core/concepts/actions-and-action-sets.md): how the agent selects from the actions you register.
- [Skills](../core/concepts/skills.md): how the agent decides which skill to load for a task.
- [Actions catalogue](../core/concepts/default-actions.md): every built-in action, as a baseline for what you can reuse.

## Next

- New to the codebase? Read [Architecture](architecture.md) for the runtime map.
- Building your first extension? Start with a [Custom action](custom-action.md).
- Ready to open a pull request? Follow [Contributing](contributing.md).
