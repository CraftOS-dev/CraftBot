# Agent bundle agent.yaml

CraftBot ships 42 prebuilt specialist agents (ads specialist, data analyst, DevOps engineer, recruiter, and more) as source folders under `agent_bundle/agents/<slug>/`. Each folder's `agent.yaml` is the manifest that declares what the agent is and what it ships with. This page is the reference for reading and tweaking one. The full authoring workflow (building your own from scratch) lives at [Custom agent](../../develop/custom-agent.md).

## Anatomy of a bundle folder

```
agent_bundle/agents/ads-specialist/
├── agent.yaml        # This manifest
├── soul.md           # Persona + convictions — becomes SOUL.md, always in context
├── role.md           # Deep reference playbooks — becomes AGENT.md, grepped on demand
├── USE_CASES.md      # What the agent covers (authoring doc, not shipped)
├── SOURCES.md        # Section → source provenance map (authoring doc, not shipped)
├── reference/        # Downloaded research the content traces back to
└── skills/           # Bundled skill packs, one <name>/SKILL.md each
```

The split between `soul.md` and `role.md` is deliberate: `soul.md` is the always-loaded identity (kept under a ~400-line budget; the build hard-fails past 600), while `role.md` holds the deep playbooks the agent greps into context only when the persona summary isn't enough.

## agent.yaml fields

| Field | Type | What it does |
|---|---|---|
| `name` | string | Display name (e.g. `Performance Ads Specialist`). Required. |
| `slug` | string | Kebab-case ID; must match the folder name. Names the built `dist/<slug>.craftbot`. Required. |
| `category` | string | Domain grouping: `marketing`, `engineering`, `research`, … Required. |
| `tier` | `general` \| `specialized` | `general` = broad domain agent (`marketing-agent`); `specialized` = deep single role (`ads-specialist`). Required. |
| `description` | string | One paragraph: end-to-end intent, hand-off rules to sibling agents, hard convictions. Shown in the bundle preview on import. |
| `tags` | list | Discovery keywords. |
| `model.llm_provider`, `model.llm_model` | string | The provider/model the agent was authored and tested against. **Metadata only** — it is not shipped in the bundle and importing never switches the recipient's provider (see [settings.json](config-json.md)). |
| `enabled_skills` | list | Skill names the agent works through — bundled packs plus CraftBot defaults (see below). |
| `mcp_servers` | list | MCP server names the agent expects. Every name must exist in `app/config/mcp_config.json` — see [MCP](../../integrations/mcp.md). |
| `sources` | list of `{name, url, used_for}` | Provenance: which reference material informed which capability. |

### How enabled_skills resolve

Each name is looked up in two places, in order:

1. `agent_bundle/agents/<slug>/skills/<name>/`: a **bundled** skill pack that ships inside the `.craftbot`
2. `<repo>/skills/<name>/`: a **CraftBot default** skill already on the recipient's install, listed in the bundle's manifest but not copied

A name found in neither is a soft warning: `verify.py` reports it and `build.py` trims it from the shipped manifest, so a bundle only ever advertises what it actually delivers. Every bundled skill folder must contain a `SKILL.md`. A bundled `SKILL.md` with malformed YAML frontmatter is a hard build failure.

### How mcp_servers resolve

Names are matched against the server catalog in `app/config/mcp_config.json`. At build time the full server entries are copied into the bundle **with secret-looking env values stripped**. The recipient enables each server and fills in their own API keys after import. Unresolved names are soft-warned and trimmed, and a resolved entry with a broken transport shape (e.g. `stdio` without a `command`) is a hard failure.

## Build, verify, import

```bash
cd agent_bundle
python verify.py ads-specialist    # quality gates only
python build.py ads-specialist     # verify + build dist/ads-specialist.craftbot
python build.py                    # build all agents
```

`verify.py` runs the quality gates: required manifest fields, `soul.md`/`role.md` presence and line budgets, `USE_CASES.md`/`SOURCES.md` presence, skill and MCP resolution, frontmatter parsing, and no leftover citation tags. Hard failures block the build; soft warnings only trim.

The built `.craftbot` is a zip containing `manifest.json`, a generated `README.md`, `profile/SOUL.md` (from `soul.md`), `profile/AGENT.md` (from `role.md`), `skills/` (an `enabled.json` list plus each bundled skill folder), and `mcp/servers.json`. It deliberately excludes API keys, OAuth secrets, memory, and personal data.

Import a `.craftbot` from **Settings → General**. Two modes: **merge** (additive, where the bundle wins on name conflicts for skills, MCP servers, and personality files) and **overwrite** (wipes local skills, MCP config, and Living UI state, then adopts the bundle as the entire agent identity). Restart after importing for everything to take effect. The bundle's agent name is shown in the preview but never applied.

## Tweaks that make sense on an existing bundle

- **Trim `enabled_skills` / `mcp_servers`** before building, if you want a leaner import. The manifest is the single place to cut scope.
- **Edit `soul.md`** to adjust tone or hand-off rules. Keep it action-first and under the line budget, then re-run `verify.py`.
- **Add a skill pack**: create `skills/<name>/SKILL.md` in the bundle folder and list the name under `enabled_skills`.
- **Don't** rename `slug` without renaming the folder, and don't point `mcp_servers` at names absent from `mcp_config.json`. Both get flagged by `verify.py`.

## The other config.yaml: runtime agent bundles

Separate from `.craftbot` bundles, `agents/<name>/` folders (e.g. `agents/personal_assistant/`, `agents/dog_agent/`) hold code-level `AgentBase` subclasses with a much simpler `config.yaml`, loaded by the agent's `from_bundle()` classmethod:

```yaml
# agents/dog_agent/config.yaml
data_dir: agents/dog_agent/data/
rag_dir: rag_docs
rag_namespace: dog_agent_knowledge
llm_provider: byteplus
max_tokens: 16000
```

| Field | What it does |
|---|---|
| `data_dir` | Per-agent [agent file system](../concepts/agent-file-system.md) root, replacing the shared one |
| `rag_dir` | Folder of RAG docs inside the bundle, indexed into memory at startup |
| `rag_namespace` | ChromaDB namespace keeping this agent's vectors isolated |
| `llm_provider` / `model` | Provider/model override for this agent; unset falls back to [`settings.json`](config-json.md) |
| `max_tokens` | Max tokens per response |

All fields are optional. This format is for building your own agent in code. The walkthrough is [Custom agent](../../develop/custom-agent.md).

## Related

- [Custom agent](../../develop/custom-agent.md): build your own bundle end to end
- [settings.json](config-json.md): the runtime config bundles fall back to
- [LLM providers](../providers/llm.md): valid `llm_provider` values
- [Skills](../concepts/skills.md) and [MCP](../../integrations/mcp.md): what the manifest's two lists plug into
