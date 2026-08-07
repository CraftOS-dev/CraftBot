# Reference

Lookup material for the agent: enums, schemas, variable names, and answers you check rather than read end to end. Each page here is a catalogue, structured so you can scan for one row and leave. When you want the concept behind one of these tables, follow the link from the page back into [Core](../core/index.md), where the same subject is explained rather than tabulated.

## Reference pages

| Page | What it lists |
|---|---|
| [Event types](events.md) | The 13 `EventType` values the event stream emits, the fields on each event record, and how the UI routes them. |
| [Environment variables](env-vars.md) | Every variable the agent reads at startup, its default, and what it overrides. |
| [Agent MD files](agent-md-files.md) | The markdown files under `agent_file_system/`: their schema, purpose, and which ones you edit. |
| [FAQ](faq.md) | Short answers to recurring questions about setup, behaviour, and limits. |
| [Troubleshooting](troubleshooting/index.md) | Symptom-to-fix tables for runtime, connections, and provider problems. |

## References that live in Core

Two reference tables sit inside the Core section because they document a concept explained on the same page:

- [Default actions](../core/concepts/default-actions.md): the full catalogue of built-in actions, grouped by domain. The action model that produces `action_start` and `action_end` events is on the same page.
- [Settings](../core/configuration/config-json.md): every key in the settings file, its type, default, and effect. The [Configuration](../core/configuration/index.md) overview maps which file owns which setting.

## How to use this section

Start from the symptom or the name you already have. If you know the variable, open [Environment variables](env-vars.md) and search for it. If you see an event kind in a log line and want to know what emitted it, open [Event types](events.md). If a file under `agent_file_system/` looks unfamiliar, [Agent MD files](agent-md-files.md) names its fields. The pages assume you already understand the concept and want the exact value, so they are dense and table-first by design.

For anything that reads as a "why" rather than a "what", the Core pages carry the explanation and link forward to the matching reference here. The two directions are deliberate: Core teaches, Reference confirms. If a table here leaves you unsure what a value does, the concept page it links back to is the place that says why the value exists and when to change it.

Each reference page is generated from or kept in step with the source it documents, so the names, defaults, and enum values match the running agent rather than a prose description of it. Where a page cites a source file, that file is the authority; the table restates it for quick reading.

## Next

- Learning the system rather than looking something up? Read [Core](../core/index.md).
- New to CraftBot? Do the [Quickstart](../start/quickstart.md) first.
- Hitting an error right now? Go straight to [Troubleshooting](troubleshooting/index.md).
