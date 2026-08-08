# Skills

A **skill** is a package of written instructions (a workflow, a checklist, domain knowledge) that gets injected into the agent's prompt for the duration of a task. Where an [action](actions-and-action-sets.md) gives the agent a new *capability*, a skill gives it a *strategy* for using capabilities it already has. CraftBot ships 195 skills. A curated handful are enabled by default and the rest are one command away.

## Overview
A skill adds no actions. The `pdf` skill tells the agent how to approach PDF work: which action to use first, which pitfalls to avoid, and what a good result looks like. Because skills are just markdown, writing one requires no code, and the agent can even write its own (see [creating skills from tasks](#creating-skills-from-tasks)).

A skill enters a task in one of two ways:

| Path | How it works |
|---|---|
| **Automatic** | At task creation, an LLM call reads the map of `{skill name: description}` for all enabled skills and picks the best match, or none. Selection is capped at **one skill per task** to keep the context focused. |
| **Slash command** | Every enabled, user-invocable skill is registered as `/<skill-name>` (type `/` in chat to see them). Invoking `/pdf report.pdf` skips LLM selection entirely; the skill is force-attached and your arguments flow into it. |

Either way, the skill's `action-sets` recommendations are merged into the task's [action sets](actions-and-action-sets.md), so a skill that needs shell access brings the `shell` set with it.

## What a skill looks like

A skill is a folder in `skills/` containing a `SKILL.md`, optionally with supporting files alongside:

```
skills/
  my-skill/
    SKILL.md          # frontmatter + instructions
    REFERENCE.md      # optional supporting files, read on demand
    scripts/...
```

`SKILL.md` starts with optional YAML frontmatter:

```markdown
---
name: my-skill
description: One line the selection LLM reads to decide when this skill applies
argument-hint: "<file> [options]"
user-invocable: true
action-sets: [file_operations, shell]
---

Instructions in plain markdown. When invoked as /my-skill some args,
$ARGUMENTS expands to "some args" and $0, $1, ... to individual words.
```

| Frontmatter key | Purpose |
|---|---|
| `name` | Identifier (normalized to lowercase-hyphens); defaults to the folder name |
| `description` | What the selection LLM sees; defaults to the first paragraph of the body |
| `argument-hint` | Usage hint shown for the slash command |
| `user-invocable` | Whether `/<name>` is registered (default `true`) |
| `allowed-tools` | Restrict which actions the skill may use |
| `action-sets` | Action sets to auto-include when this skill is selected |

Frontmatter is entirely optional. A bare markdown file in a folder is a valid skill. Supporting files aren't injected into the prompt. The instructions tell the agent to `read_file` them when needed, which keeps big reference material out of the context until it's actually used.

This page covers how skills behave at runtime. For the full authoring guide (conventions, testing, packaging) see [Write a CraftBot skill](../../develop/skills/craftbot-skill.md).

## How instructions reach the agent

Once a task has a skill, the skill's instructions are injected into the task state on **every turn**, wrapped in an `<active_skills>` block the agent is told to follow. The injection is capped at **16,000 tokens** (~64 KB of text). Anything beyond that is truncated at a paragraph boundary with an explicit truncation marker. In practice the cap is generous (the largest bundled skill is around half of it) but it's the reason skill bodies should delegate bulk reference material to supporting files instead of inlining it.

Selection happens once, at task creation, but it isn't final. Two `core` actions let the agent adjust mid-task:

- `list_skills` lists all enabled skills and their descriptions.
- `use_skill` **replaces** the currently active skill with another. It's a swap, not a stack: the previous skill leaves the prompt. When the agent only needs to *consult* another skill's instructions without switching, it reads that skill's `SKILL.md` with `read_file` instead.

## Managing skills

Three surfaces, one source of truth:

| Surface | What you can do |
|---|---|
| `/skill` command | `list`, `info <name>`, `enable`/`disable <name>`, `install <path-or-git-url>`, `create <name>`, `remove <name>`, `reload`, `dirs` |
| **Settings → Skills** | The same operations in the browser UI |
| `app/config/skills_config.json` | The persisted state both of the above write to |

The config file has four fields: `project_skills_dir` (default `skills/`), `auto_load`, `enabled_skills`, and `disabled_skills`. The enable logic matters: an **empty** `enabled_skills` list means *everything not explicitly disabled is enabled*. A **non-empty** list acts as a whitelist. CraftBot ships with a whitelist of about a dozen skills (`pdf`, `docx`, `xlsx`, `pptx`, `file-format`, the `living-ui-*` family, `craftbot-skill-creator`, and a few more). The other ~180 are discovered but dormant until you enable them.

Changes are hot-reloaded: `/skill reload` (or editing via the UI) rescans the skills directory without restarting the agent, and new folders dropped into `skills/` appear on the next reload.

!!! tip "Fewer enabled skills = better selection"
    The automatic selector chooses from the descriptions of *enabled* skills only. A tight, relevant set of enabled skills makes selection more accurate and keeps the selection prompt small. Enable what you use and leave the rest disabled.

## Creating skills from tasks

The bundled `craftbot-skill-creator` skill (enabled by default) turns a completed task into a reusable skill: ask the agent to "save what you just did as a skill" and it distills the workflow it followed into a new `SKILL.md` under `skills/`, ready for `/skill reload`. This is the cheapest way to build a skill library: do the work once interactively, then freeze the successful approach.

For writing skills by hand, or packaging skills for others, see the [skill authoring guide](../../develop/skills/craftbot-skill.md).

!!! note "Implementation files"
    Parsing and discovery: `agent_core/core/impl/skill/loader.py`. Lifecycle and the 16k cap: `agent_core/core/impl/skill/manager.py`. Selection at task creation: `app/internal_action_interface.py`. Per-turn injection: `agent_core/core/impl/context/engine.py`. Slash-command registration: `app/ui_layer/controller/ui_controller.py`.

## Next

- [Write a CraftBot skill](../../develop/skills/craftbot-skill.md): the full authoring guide
- [Actions and action sets](actions-and-action-sets.md): the capabilities skills orchestrate
- [Task sessions](task-sessions.md): the task lifecycle skills attach to
- [Agent loop](agent-loop.md): where skill instructions enter each turn
