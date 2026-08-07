# Skills

A skill is a directory under `skills/` that holds a `SKILL.md` file. The `SKILL.md` teaches the agent a repeatable workflow in plain markdown: the steps to follow, the actions to reach for first, and what a finished result looks like. A skill adds no code and no new capability. It shapes how the agent applies the actions it already has. That is the difference between a skill and an [action](../custom-action.md), where an action is a Python function that gives the agent a capability it did not have before. For how a skill is selected and injected into a task at runtime, see the [Skills concept page](../../core/concepts/skills.md). This page and the ones below it are the authoring guide.

CraftBot ships 195 bundled skills. A curated set is enabled by default (`pdf`, `docx`, `xlsx`, `pptx`, `file-format`, the `living-ui-*` family, and a few more) and the rest are discovered but dormant until you enable them.

## Three ways to author a skill

You reach a working skill by one of three routes, depending on where the workflow comes from.

| Route | You do this when | Read |
|---|---|---|
| Write one yourself | You know the workflow and want to encode it directly. | [Write a CraftBot skill](craftbot-skill.md) |
| Import or adapt an external one | A skill already exists in another project, a shared folder, or an agent bundle. | [External skills](external-skill.md) |
| Generate one from a completed task | The agent just did the work once and you want to keep the approach. | [Generating a skill from a task](craftbot-skill.md#generating-a-skill-from-a-task) |

The first two routes produce a `SKILL.md` you own and edit. The third route hands the drafting to the bundled `craftbot-skill-creator` skill, which reads the trace of a task you already ran and writes the new `SKILL.md` for you. All three end in the same place: a folder under `skills/` that the agent can select.

## Skill anatomy at a glance

Every skill is one folder. Only the `SKILL.md` is required.

| Part | Required | Purpose |
|---|---|---|
| `SKILL.md` | Yes | The instructions injected into the task. Optionally opens with YAML frontmatter, followed by the markdown body. |
| YAML frontmatter | No | Declares `name`, `description`, `argument-hint`, `user-invocable`, `allowed-tools`, and `action-sets`. Omit it and the agent derives `name` from the folder and `description` from the first body paragraph. |
| Supporting files | No | `REFERENCE.md`, `scripts/`, `assets/`, and similar files that sit next to `SKILL.md`. They are never injected. The body tells the agent to read them with `read_file` when it needs them. |
| Location | Yes | `skills/<name>/`, where the folder name is the skill id. |

A minimal skill is a single folder with a single markdown file and no frontmatter at all. Everything else is there to keep a large workflow readable and to keep bulk reference material out of the task context until the moment it is used.

## Next

- [Write a CraftBot skill](craftbot-skill.md): the full `SKILL.md` format, argument substitution, action sets, and a copyable example.
- [External skills](external-skill.md): install a skill authored elsewhere, and vet it before you enable it.
- [Skills concept page](../../core/concepts/skills.md): how a skill is selected, injected each turn, and swapped mid-task.
- [Custom action](../custom-action.md): add a capability with code rather than a workflow with instructions.
