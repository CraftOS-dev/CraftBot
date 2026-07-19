# Agent bundles and profiles

An agent profile is the portable part of a CraftBot agent: its personality files, enabled skills, enabled MCP servers, and Living UI apps, packaged into a single `.craftbot` file. Exporting a profile lets you move your configured agent to another machine or share it. Importing a profile turns a stock CraftBot into a configured specialist in one step.

An **agent bundle** is a pre-built profile authored for a specific role (CEO agent, senior Python engineer, finance agent, and others). CraftOS publishes 42 of them in the [CraftBot Agent Bundles repository](https://github.com/CraftOS-dev/craftbot-agent-bundles), free to download and import.

## Example bundles

The 42 bundles are grouped by domain. Each one wires the agent with the skills, MCP servers, and operating rules a senior practitioner of that role uses, so the agent executes the work rather than only describing it. A sample:

| Bundle | Domain | What it does |
|---|---|---|
| `ceo-agent` | Executive | Drafts strategy documents, board packs, and investor updates, and tracks OKRs. |
| `finance-agent` | Finance | Builds FP&A models, runs capital-allocation analysis, and drafts term sheets. |
| `project-manager` | Operations | Writes charters, work-breakdown structures, Gantt schedules, and status reports. |
| `senior-python-engineer` | Engineering | Reviews Python code, debugs failures, and proposes optimizations. |
| `devops-engineer` | Engineering | Works with containers, Kubernetes, infrastructure-as-code, and GitOps pipelines. |
| `marketing-agent` | Marketing | Plans campaigns and produces content across channels. |
| `seo-specialist` | Marketing | Audits sites, researches keywords, and drafts on-page and technical SEO fixes. |
| `sales-agent` | Sales | Researches prospects, drafts outreach, and maintains pipeline records. |
| `data-analyst` | Research | Queries data, runs analysis, and turns results into reports and charts. |
| `legal-counsel` | Legal | Reviews contracts, flags risk, and drafts standard clauses. |
| `recruiter` | People | Writes job descriptions, sources candidates, and screens applicants. |
| `personal-assistant` | Personal | Manages your inbox, calendar, and day-to-day tasks. |

The repository lists all 42 with a description of each, spanning executive and strategy, engineering, marketing and growth, sales and customer, content and documentation, research and analytics, legal and compliance, and people and product roles.

## What a profile contains

A `.craftbot` file is a ZIP archive. It carries the parts of an agent that are portable between installs:

| Included | Notes |
|---|---|
| Personality files | `SOUL.md`, `USER.md`, and the other `agent_file_system` markdown that defines behavior. See [Agent file system](agent-file-system.md). |
| Enabled skills | The skill folders you have enabled. Skills already present on the target install are not re-shipped. See [Skills](skills.md). |
| Enabled MCP servers | Server definitions from `mcp_config.json`, with secret environment values stripped out. See [MCP servers](../../integrations/mcp.md). |
| Living UI apps | Any apps you built. See [Living UI](../../living-ui/index.md). |
| `manifest.json` and `README.md` | Bundle metadata and a human-readable summary of the contents. |

Four things are deliberately **never** included, so a bundle is safe to share:

- API keys and provider credentials.
- OAuth tokens and integration secrets.
- Personal memory (`MEMORY.md` and the memory index).
- Conversation history.

## Importing a profile

You import a profile from the browser interface.

1. Open **Settings → General** and choose **Import Agent Profile**.
2. Select or drag in a `.craftbot` file. To use a pre-built bundle, download one from the [agent bundles repository](https://github.com/CraftOS-dev/craftbot-agent-bundles) first (see [Using a pre-built bundle](#using-a-pre-built-bundle) below).
3. CraftBot inspects the bundle and shows a preview: which skills and MCP servers it contains, which of those you already have installed, and which MCP servers need environment values (API keys) that were stripped on export.
4. Choose an import mode:

| Mode | Effect on existing personality files |
|---|---|
| **Merge and Replace** | Applies the bundle's skills, MCP servers, and apps, and replaces the personality files the bundle provides. Files the bundle does not include are left alone. |
| **Overwrite** | Replaces the personality files with the bundle's versions. |

5. Confirm. CraftBot installs the bundle's skills into your `skills/` directory and enables them, adds its MCP servers (disabled until you supply the missing keys), applies the personality files, and registers any Living UI apps.

### What import does not change

- **Your model and provider stay the same.** A bundle's `agent.yaml` names a recommended model, but importing never switches your configured provider or API key. Set the model yourself from **Settings → Model** if you want the recommended one. See [LLM providers](../providers/llm.md).
- **Your existing credentials stay.** The importer only adds skills, servers, personality files, and apps. It does not touch your keys or connected integrations.
- **Skills are added, not deleted.** If a skill folder already exists, the importer keeps it and reports it as skipped rather than overwriting your version.

After import, the agent typically asks a few questions about your routines and proposes recurring tasks for `PROACTIVE.md`. See [Proactive mode](../modes/proactive.md).

### Using a pre-built bundle

1. Open the [CraftBot Agent Bundles repository](https://github.com/CraftOS-dev/craftbot-agent-bundles).
2. Open the `bundles/` folder and download the file for the role you want. Files are named `<role>-<date>.craftbot`, for example `ceo-agent-20260611.craftbot`. The most recent date is the current version.
3. Import it with the steps above.
4. Fill in API keys for the MCP servers you actually plan to use. The preview lists exactly which servers need keys. You do not need to configure servers for tools you will not use.

The repository lists all 42 bundles grouped by domain (executive, engineering, marketing, sales, research, legal, and others), each with a description of what it does.

## Exporting your own profile

Once you have configured an agent you like, you can export it.

1. Open **Settings → General** and choose **Export Agent Profile**.
2. Optionally add a description. CraftBot writes a `.craftbot` file named `craftbot-<agent-name>-<timestamp>.craftbot`.

The export includes only enabled skills and enabled MCP servers, so the file stays small and does not carry the roughly 157 disabled default servers or machine-specific command paths. Secrets are stripped, so the recipient supplies their own keys.

Use export to move your agent to another machine, back up a configuration before experimenting, or share a persona you built. To publish a polished persona to the public repository, follow the authoring and submission process in [Create an agent bundle](../../develop/custom-agent.md).

## Next

- [Create an agent bundle](../../develop/custom-agent.md): author your own persona and publish it to the repository
- [Agent bundle config](../configuration/agent-config-yaml.md): the `agent.yaml` manifest fields
- [Skills](skills.md) and [MCP servers](../../integrations/mcp.md): the two capability layers a bundle carries
