# Custom agent

An agent bundle is a packaged persona you install into a CraftBot with one click. A single bundle carries an identity (who the agent is and how it decides), an authoring record of the model it was built against, a list of enabled skills, a list of MCP servers, the persona and role documents, and the skill packs the agent ships with. Importing a bundle turns a blank CraftBot into a CEO agent, a finance controller, an ads specialist, or any other role without you writing a system prompt.

CraftBot ships 42 prebuilt bundles under `agent_bundle/agents/`, and users import more from the [CraftBot Agent Bundles repository](https://github.com/CraftOS-dev/craftbot-agent-bundles). This page covers how to author your own bundle from scratch: the files it contains, the manifest that declares it, the workflow that produces it, the tooling that validates and builds it, and how to publish it to the public repository. For the manifest field table, see [Agent bundle agent.yaml](../core/configuration/agent-config-yaml.md). For the user-facing import and export flow, see [Agent bundles and profiles](../core/concepts/agent-bundles.md). For skill authoring, see [Write a CraftBot skill](skills/craftbot-skill.md) and the [Skills overview](../core/concepts/skills.md).

## What an agent bundle contains

A bundle is one folder that produces one `.craftbot` file. The folder holds the source you edit. The `.craftbot` file is the zip a recipient imports. The bundle carries five kinds of content:

| Content | Where it lives | What it does |
|---|---|---|
| Identity | `soul.md` | Always-loaded persona and decision rules. Becomes `SOUL.md` on import. |
| Deep reference | `role.md` | Grep-only playbooks and tool references. Appended to `AGENT.md` on import. |
| Manifest | `agent.yaml` | Declares name, slug, category, tier, model, skills, MCP servers, and sources. |
| Skill packs | `skills/<name>/SKILL.md` | Bundled strategy the agent works through. Copied into the recipient's `skills/`. |
| MCP server list | `agent.yaml` `mcp_servers` | Names of MCP servers the agent expects, resolved against CraftBot's catalog. |

The bundle never carries API keys, OAuth secrets, memory, conversation history, or personal data. Secret-looking values in MCP server configs are stripped at build time, and the recipient fills in their own after import.

## Bundle directory structure

Each agent lives in its own folder under `agent_bundle/agents/<slug>/`. The `ads-specialist` bundle is a complete worked example:

```
agent_bundle/agents/ads-specialist/
├── agent.yaml        # Manifest — what the agent is and ships with
├── soul.md           # Persona + decision rules — becomes SOUL.md, always in context
├── role.md           # Deep playbooks + SOTA tool reference — becomes AGENT.md, grepped on demand
├── USE_CASES.md      # What the agent covers and what it can execute (ships, not in context)
├── SOURCES.md        # Section-to-source provenance map (ships, not in context)
├── reference/        # Downloaded research + INVENTORY.md + SOTA_USE_CASES.md
└── skills/           # Bundled skill packs, one <name>/SKILL.md each
```

Each file has a fixed role. `agent.yaml` declares the agent. `soul.md` and `role.md` hold the personality, split by how often the agent reads them. `USE_CASES.md` documents what the agent is for and where its honest gaps are. `SOURCES.md` maps every section of `soul.md` and `role.md` back to a file in `reference/`. `reference/` holds the downloaded research the content traces to, plus `INVENTORY.md` (a list of every downloaded file) and `SOTA_USE_CASES.md` (the per-use-case tool mapping that drives the manifest). `skills/` holds the skill packs the bundle ships.

## The agent.yaml manifest

`agent.yaml` is the single declaration of what the agent is and what it delivers. The full field table lives in [Agent bundle agent.yaml](../core/configuration/agent-config-yaml.md). The key fields are:

| Field | What it declares |
|---|---|
| `name` | Display name shown in the import preview. |
| `slug` | Kebab-case ID. Must match the folder name and names the built `dist/<slug>.craftbot`. |
| `category` | Domain grouping (`marketing`, `engineering`, `research`, and so on). |
| `tier` | `general` for a whole-domain agent, `specialized` for a single deep role. |
| `description` | One paragraph of intent, hand-off rules to sibling agents, and hard convictions. |
| `tags` | Discovery keywords. |
| `model.llm_provider`, `model.llm_model` | The provider and model the agent was authored and tested against. Authoring metadata only. |
| `enabled_skills` | A flat list of skill names the agent works through. |
| `mcp_servers` | MCP server names the agent expects. Each must exist in `app/config/mcp_config.json`. |
| `sources` | A list of `{name, url, used_for}` entries recording what informed which capability. |

The `model` block records the provider and model the author built against. It is not shipped in the bundle and importing never switches the recipient's provider. Treat it as a note, not a setting.

## soul.md and role.md

The personality splits across two files by how often the agent reads them.

`soul.md` is loaded into the agent's context on every turn, so every line costs tokens on every turn. It carries only content that changes a turn-by-turn decision: identity, purpose, entry procedures, core operating rules, mode-specific decisions, decision tables, communication style, and output format. It ends with a standard footer that self-initializes proactive behavior on the first conversation with a new user. The methodology targets 200 to 350 lines. `verify.py` warns above 400 lines and hard-fails above 600.

The persona intro at the top of `soul.md` follows a mandatory rule that `verify.py` enforces. The intro must be action-verb-first. It lists concrete verbs (`write`, `build`, `run`, `ship`, `query`, `fetch`, `post`, `render`, `deploy`, and similar) paired with the specific artifact and tool. The validator scans the first 20 lines for banned advisory verbs (`covers`, `owns`, `leans on`, `relies on`, `expertise spans`, `mastery of`, `advise`, `guide`, `suggest`, and others). If it finds a banned verb and counts fewer than four action verbs, the check hard-fails. Agents whose slug contains `advisor` or `consultant` are exempt because their advisory framing is in the name.

`role.md` is appended to `AGENT.md`, which is not loaded into default context. The agent greps it when the `soul.md` summary is not enough. Use searchable H2 and H3 headings the agent will look up by literal string, such as "Antipattern catalog", "Code review playbook", or "SOTA tool reference". `role.md` carries the factual capability lists, step-by-step procedures, antipattern pairs, reference patterns, and deep examples that would waste tokens if they sat in `soul.md`. `verify.py` requires `role.md` to contain a SOTA reference heading.

Citations do not go inline. A separate `SOURCES.md` maps each section back to its `reference/` file. `verify.py` hard-fails if it finds a `[from:` or `[merged:` tag in `soul.md` or `role.md`.

## The authoring workflow

The methodology in `agent_bundle/METHODOLOGY.md` defines the canonical process. Follow it in order:

1. **Plan the agent.** Add a row to `PROGRESS.md` with the slug, display name, tier, category, and a one-line intent.
2. **Research and download references.** Pull four to eight related agent definitions and eight to fifteen matching skill packs from upstream sources into `reference/`. Save verbatim content, not summaries.
3. **Build the inventory and pause.** Write `reference/INVENTORY.md` listing every downloaded file with its source URL, then show it to the user for approval before writing any personality content. The inventory is the proof that the content is researched rather than invented.
4. **Map use cases and research the state of the art.** Enumerate every reasonable use case a senior practitioner of the role handles (aim for 15 or more), then research the current best execution path for each and record it in `reference/SOTA_USE_CASES.md`. Each row names a concrete tool, library, API, or MCP and an execution mechanism, with a confidence mark. Target 90 percent or more fulfillment.
5. **Compose `agent.yaml`.** Walk the use-case table row by row. Every matched MCP goes into `mcp_servers`, and every matched skill pack goes into `enabled_skills`.
6. **Compose `soul.md` and `role.md`.** Keep decision rules in `soul.md` and reference material in `role.md`. Pressure-test every `soul.md` line by asking whether the agent would decide worse without it.
7. **Write `SOURCES.md`.** Map each section of `soul.md` and `role.md` back to a source file.
8. **Write `USE_CASES.md`.** Document what the agent covers, a per-use-case execution table, the honest gaps, a fulfillment verdict, and when to use or not use the agent.
9. **Update `PROGRESS.md` and verify.** Record the final skill count, MCP count, and fulfillment percentage, then run `verify.py`.

## Bundled skills

The `enabled_skills` list is the agent's most important capability lever. Each name resolves in two places, in order:

1. `agent_bundle/agents/<slug>/skills/<name>/`, a skill pack authored specifically for this agent.
2. `<repo>/skills/<name>/`, a shared CraftBot skill in the repository's top-level `skills/` folder.

Whichever resolves first is copied verbatim into the bundle. Every shipped skill folder lands physically inside the `.craftbot` zip, so the recipient never depends on having a skill pre-installed. Author agent-specific packs under `skills/<name>/` when the strategy is unique to this agent's craft. Use the shared pool for broad skills reused across many agents. To author a pack, follow [Write a CraftBot skill](skills/craftbot-skill.md). Each pack needs a `SKILL.md` with valid YAML frontmatter whose `name` matches the folder name.

CraftBot system skills (those whose frontmatter declares `user-invocable: false`, such as the memory processor, heartbeat processor, and planners) are force-included in every bundle by the build step regardless of what `agent.yaml` lists. This guarantees an imported agent keeps its core runtime workflows.

## Validating with verify.py

`verify.py` runs the quality gates before a build. Run it against one agent or all of them:

```bash
cd agent_bundle
python verify.py ads-specialist    # verify one agent
python verify.py                   # verify all agents
```

The validator reports two tiers. Hard failures block the build. Soft warnings only trim unresolved entries from the shipped manifest so the bundle promises exactly what it ships. The hard-fail conditions are:

- `agent.yaml` is missing, fails to parse, or lacks `name`, `slug`, `tier`, or `category`.
- `soul.md` is missing or exceeds 600 lines.
- `role.md` is missing or lacks a SOTA reference heading.
- `USE_CASES.md`, `SOURCES.md`, or `reference/SOTA_USE_CASES.md` is missing.
- A bundled `SKILL.md` is missing, empty, has malformed YAML frontmatter, or declares a `name` that differs from its folder name.
- An MCP server named in `agent.yaml` exists in the catalog but has a broken transport shape (`stdio` without a `command`, or `sse`/`http` without a `url`).
- `soul.md` contains an inline `[from:` or `[merged:` citation tag.
- The persona intro fails the operator-framing check (a banned advisory verb with fewer than four action verbs).
- The `soul.md` PROACTIVE self-init footer is missing.
- Fulfillment in `reference/SOTA_USE_CASES.md` falls below 90 percent.

Names in `enabled_skills` or `mcp_servers` that do not resolve produce soft warnings. The build trims them so the manifest never advertises what it cannot deliver.

## Building the bundle

`build.py` runs `verify.py` first, then packages the folder into `dist/<slug>.craftbot`:

```bash
cd agent_bundle
python build.py ads-specialist     # verify + build one agent
python build.py                    # build every agent
python build.py --skip-verify      # build without the pre-build verify pass
```

The `.craftbot` is a zip with a fixed layout. It holds `manifest.json`, a generated `README.md`, `profile/SOUL.md` (from `soul.md`), `profile/AGENT.md` (the base operations manual followed by `role.md`), a `skills/` folder with an `enabled.json` list plus each shipped skill folder, and `mcp/servers.json` with the resolved server configs and their secret values blanked. Rebuilding the same agent overwrites the prior file so `dist/` stays clean.

## Importing a bundle

A user imports a `.craftbot` from **Settings → General**, which calls the profile bundle importer. Two modes are available:

- **Merge and Replace** (additive). The bundle's skills, MCP servers, and personality files are written in, and the bundle wins on name conflicts. Skills and MCP servers the user already had that the bundle does not ship are left in place.
- **Overwrite** (strict adoption). The local skills folder, MCP config, and Living UI state are wiped first, then the bundle is installed as the entire agent identity.

On import, each shipped skill folder is copied into the recipient's `skills/` directory and enabled in `skills_config.json`. System skills are force-enabled in every mode so the agent never loses its core workflows. MCP servers are added to the catalog after a shape check, with their secret env values left blank for the recipient to fill in.

Two things are never applied on import. The agent name is shown in the preview for context but is not adopted, so the recipient keeps their own name. The `model` block is authoring metadata and does not switch the recipient's provider or model. Restart CraftBot after importing so every change takes effect.

## Publishing to the agent-bundles repository

The [CraftBot Agent Bundles repository](https://github.com/CraftOS-dev/craftbot-agent-bundles) is the public catalogue users browse and import from. It is a separate repository from CraftBot itself, published under the MIT license. It carries the same `agents/`, `build.py`, `verify.py`, and `METHODOLOGY.md` layout described on this page, plus a `bundles/` folder holding the compiled `.craftbot` files that users download. To contribute a bundle, you author it in a fork of that repository, build it, and open a pull request.

The submission steps:

1. **Fork the repository** and clone your fork.
2. **Author the agent** under `agents/<slug>/`, following the workflow in the [authoring workflow](#the-authoring-workflow) section above. The repository ships the same `METHODOLOGY.md`, `_templates/`, `verify.py`, and `build.py`, so the local process is identical.
3. **Add a row to `PROGRESS.md`** recording the slug, display name, tier, category, final skill count, MCP count, and fulfillment percentage.
4. **Pass every gate.** Run `python verify.py <slug>` until all checks pass. A pull request that fails verification will not be accepted. The gates are the same ones listed in [Validating with verify.py](#validating-with-verifypy).
5. **Build the distributable.** Run `python build.py <slug>` to produce the `.craftbot`, then place the built file in `bundles/` named `<slug>-<YYYYMMDD>.craftbot`. The date stamp is the version. Leave older date-stamped builds in place so existing links keep working.
6. **Open a pull request** against the repository with the new `agents/<slug>/` source, the `bundles/<slug>-<date>.craftbot` file, and the `PROGRESS.md` row.

Two rules govern the content:

- **Cite your sources.** The bundle's `SOURCES.md` and `reference/INVENTORY.md` must record where the persona's content came from. The repository is research-backed, and a bundle that cannot show its provenance fails review.
- **Attribute upstreams.** The MIT license lets anyone fork, repackage, and resell bundles. If your bundle draws on the repository's own upstream reference agents, keep the attribution the methodology requires.

Because the bundle carries no secrets (keys and OAuth tokens are stripped at build time and personal memory and history are never included), a published `.craftbot` is safe to distribute. Confirm this before submitting by inspecting the built zip: it should contain `manifest.json`, `README.md`, `profile/`, `skills/`, and `mcp/servers.json` with blank secret values, and nothing else.

## Next

- [Agent bundles and profiles](../core/concepts/agent-bundles.md): the user-facing import and export flow.

- [Agent bundle agent.yaml](../core/configuration/agent-config-yaml.md): the full manifest field reference.
- [Write a CraftBot skill](skills/craftbot-skill.md): author the skill packs a bundle ships.
- [Skills overview](../core/concepts/skills.md): how enabled skills reach the agent's prompt.
