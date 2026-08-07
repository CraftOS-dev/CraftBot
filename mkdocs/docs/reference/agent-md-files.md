# Agent markdown files

The agent's home directory, `agent_file_system/`, holds a fixed set of markdown files that store the agent's identity, its knowledge of you, its recurring tasks, and its records of what has happened. On first run the directory is seeded from the templates in `app/data/agent_file_system_template/`, and `/reset` restores the markdown files from those templates.

This page is the per-file format reference. It documents each file's sections, frontmatter, who maintains it, whether you may edit it, and how it is used at runtime. For how the files relate to each other (which are yours to edit, which are the agent's working notes, which are harness records) and the workspace layout, read the [Agent file system](../core/concepts/agent-file-system.md) concept page. This reference complements that page rather than repeating it.

## File summary

| File | Who writes it | May you edit it? | Injected into the prompt? |
|---|---|---|---|
| `AGENT.md` | Ships with CraftBot; agent appends learned fixes | Yes, carefully | No. The system prompt carries only a map of the file system; the agent greps this file on demand |
| `SOUL.md` | You (agent only on your explicit request) | Yes | Yes, verbatim in the system prompt on every turn |
| `USER.md` | Onboarding wizard; agent after confirming with you | Yes | Yes, verbatim in the system prompt on every turn |
| `FORMAT.md` | You | Yes | No. Read on demand before the agent generates a file |
| `GLOBAL_LIVING_UI.md` | You | Yes | No. Read on demand when a Living UI project is built |
| `PROACTIVE.md` | `recurring_*` actions and the planners | Prefer the actions; keep the marker comments | No. Read by the proactive workflows |
| `MEMORY.md` | Memory processor (nightly job) | No | No. Surfaces through `memory_search` retrieval |
| `EVENT.md` | Event stream manager | No | No |
| `EVENT_UNPROCESSED.md` | Event stream manager | No | No. Read by the nightly memory run |
| `MISSION_INDEX_TEMPLATE.md` | Static template | No | No |

The injection facts match the [Context engine](../core/concepts/context-engine.md): the system prompt embeds `USER.md` and `SOUL.md` verbatim and includes a map of the file system, but not the full text of `AGENT.md`. Distilled memory reaches the agent through retrieval, described in [Memory](../core/concepts/memory.md). The files marked "No" under editing are harness-managed. Their formats are contracts that other subsystems depend on, so read them freely but do not hand-edit them.

## AGENT.md

The agent's operations manual, versioned and grep-indexed.

**Frontmatter.** A YAML block with two keys:

```yaml
---
version: 6
purpose: agent operations manual
---
```

The `version` increments as the manual gains content. `purpose` is a fixed label.

**Structure.** After the frontmatter the file opens with a one-line instruction (`Grep ## <topic> to load what you need`) and an `## Index` section. The index sits between `<!-- index -->` and `<!-- /index -->` comment markers and maps common tasks to the heading that answers them, for example `add MCP server → ## MCP` or `handle an error → ## Errors`. The rest of the file is one `## <Topic>` section per subject: `## Runtime`, `## MCP`, `## Skills`, `## Integrations`, `## Models`, `## Sub-Agents`, `## Tasks`, `## Documents`, `## Living UI`, `## Proactive`, `## Configs`, `## Errors`, `## Files`, `## Actions`, `## File System`, `## Workspace`, `## Self-Improvement`, `## Self-Edit`, and `## Glossary`. The shipped file is large (over 250 KB).

**Who maintains it.** It ships with CraftBot. The agent appends operational fixes it learns under the matching topic heading and bumps `version`.

**Edit guidance.** You may edit it, carefully. Keep the frontmatter and the `## <Topic>` headings intact, because the index and the agent's grep-by-topic access both depend on the heading names, and keep the index markers in place.

**Runtime use.** The file is not injected into the prompt in full. The system prompt's file-system section points at it, and the agent greps `## <topic>` to load only the section it needs for the current turn. It is also indexed for memory search.

## SOUL.md

Persistent personality and behavior that apply to every task.

**Structure.** Freeform markdown, no frontmatter. The template uses `# Soul` followed by `## Personality`, `## Tone`, `## Behavior`, and `## Quirks`, each a short bullet list. Keep it terse.

**Who maintains it.** You. The agent edits it only when you explicitly ask, and it confirms before saving.

**Edit guidance.** This is the main personality knob. Adjust the tone, quirks, and standing rules here.

**Runtime use.** Injected verbatim into the system prompt on every turn (the Soul section). An edit takes effect on the very next LLM call with no restart, and it invalidates the cached prompt prefix once.

## USER.md

Your profile. Unlike `SOUL.md`, this file has a fixed schema.

**Structure.** No frontmatter. Fixed sections, each a labeled bullet list:

- `## Identity`: Full Name, Preferred Name, Email, Location, Timezone (inferred from location), Job.
- `## Communication Preferences`: Language, Preferred Tone, Response Style, Preferred Messaging Platform.
- `## Agent Interaction`: Prefer Proactive Assistance, Approval Required For.
- `## Life Goals`: free text.
- `## Personality`: free text describing you.

In the template every value is a `(Ask the users for info)` placeholder that onboarding replaces.

**Who maintains it.** The onboarding wizard seeds it on first launch. The agent writes durable, confirmed facts back after checking with you. One-off requests do not land here.

**Edit guidance.** Keep it current as your details change. Preserve the section headings and labels so the profile stays parseable.

**Runtime use.** Injected verbatim into the system prompt on every turn (the User profile section). The Language value drives the language instruction the engine adds to the prompt.

## FORMAT.md

Formatting standards the agent reads before it generates any file.

**Structure.** No frontmatter. The file opens with a short instruction, then a `## global` section, then one section per file type that overrides the global rules for that format.

- `## global`: `### Colors`, `### Typography`, `### Writing & Content`, `### General Layout`. These are the universal defaults.
- Per-filetype override sections: `## pptx`, `## docx`, `## xlsx`, `## pdf`, `## md`, `## html`. Each restates setup, typography, structure rules, and a "Common mistakes to avoid" list tuned for that format.

**Who maintains it.** You.

**Edit guidance.** Change a rule once here and every future document of that type follows. Put universal rules (brand color, writing style) under `## global` and format-specific rules under the matching type section.

**Runtime use.** Read on demand when the agent is about to produce a document. The per-filetype section takes precedence over `## global` for that format.

## GLOBAL_LIVING_UI.md

Global design preferences applied to every [Living UI](../living-ui/index.md) project.

**Structure.** No frontmatter. Sections:

- `## Design Preferences`: labeled values for Primary Color, Secondary Color, Accent Color, Background Style, Theme Mode, Font Family, Border Radius, and Spacing.
- `## Always Enforced`: a bullet list of hard rules the agent must follow in generated apps (error handling with visible feedback, design tokens, responsive layout, and so on).
- `## Optional Rules`: a checkbox list (`- [x]` / `- [ ]`) of features you can toggle per your preference.
- `## Custom Rules`: an empty area for your own checkbox rules.

**Who maintains it.** You.

**Edit guidance.** Set project-wide defaults here. Per-project answers gathered when a project is created override these values when they conflict.

**Runtime use.** Read on demand when a Living UI project is designed or built.

## PROACTIVE.md

Recurring proactive tasks plus the planner state. See [Proactive mode](../core/modes/proactive.md) for how the file is executed.

**Frontmatter.** A YAML block:

```yaml
---
version: "1.0"
last_updated: null  # Auto-updated by system (format: YYYY-MM-DDTHH:MM:SSZ)
---
```

`last_updated` is maintained by the system.

**Structure.** The file documents its own rules in comments, then provides these sections: `## How Proactive Tasks Work`, `## Decision Rubric` (a five-dimension score table), `## Permission Tiers` (tiers 0 through 3), `## Task Definitions`, and `## Goals, Plan, and Status`. The last section holds `### Long-Term Goals`, `### Current Focus`, `### Recent Accomplishments`, and `### Upcoming Priorities`, which the day, week, and month planners maintain.

**Task entry format.** Task definitions live between the `<!-- PROACTIVE_TASKS_START -->` and `<!-- PROACTIVE_TASKS_END -->` marker comments inside `## Task Definitions`. Each task is a `### [FREQUENCY] Task Name` heading followed by a YAML code block:

```yaml
id: morning_inbox_summary       # unique snake_case identifier
frequency: daily                # hourly | daily | weekly | monthly
time: "08:30"                   # HH:MM, 24-hour (recommended for daily and up)
day: monday                     # weekly: monday-sunday; monthly: date 1-31
enabled: true                   # true | false
priority: 50                    # 1-100, lower = higher priority
permission_tier: 1              # 0-3, see Permission Tiers
run_count: 0                    # auto: execution counter
conditions:                     # optional, e.g. weekdays_only
  - weekdays_only
instruction: |                  # required: detailed step-by-step spec
  1. Fetch unread emails from the last 24 hours.
  2. Compile a summary with Urgent / Important / FYI sections.
  3. Present the summary to the user via chat.
outcome_history: []             # auto: last 5 run results
```

`run_count` and `outcome_history` are maintained by the system; the rest you set. The instruction field determines execution quality, so write exact steps and name the sources.

**Who maintains it.** The `recurring_*` actions and the planners write this file. You can edit it directly, but the actions are the safer path.

**Edit guidance.** Keep the `<!-- PROACTIVE_TASKS_START -->` and `<!-- PROACTIVE_TASKS_END -->` markers in place. The parser locates task definitions by those comments, and removing them breaks parsing.

**Runtime use.** Read by the proactive heartbeat and the planners when a schedule fires. It is indexed for memory search.

## MEMORY.md

Distilled long-term memory.

**Structure.** `# Memory Log`, an explicit `Agent DO NOT edit this file.` line, an `## Overview` that states the file holds distilled items rather than raw events, and a `## Memory` section the processor appends to.

**Who maintains it.** The nightly memory processor only.

**Edit guidance.** Do not hand-edit it. The memory pipeline reads and writes it in a specific format, and manual edits create inconsistencies the retrieval layer cannot recover from.

**Runtime use.** Not injected into the prompt in full. Entries reach a task through `memory_search` retrieval, described in [Memory](../core/concepts/memory.md).

## EVENT.md

The append-only chronological event log.

**Structure.** `# Event Log`, an `Agent DO NOT edit this file.` line, an `## Overview`, and an `## Events` section that the event stream manager appends to.

**Who maintains it.** The event stream manager writes every significant event (actions, messages, errors) here as it happens.

**Edit guidance.** Do not hand-edit it. It is the ground truth other subsystems rely on. It auto-rotates when it grows past a size limit.

**Runtime use.** A record for auditing and for the memory pipeline, not for the agent to re-read wholesale.

## EVENT_UNPROCESSED.md

The staging buffer of events awaiting the nightly memory run.

**Structure.** `# Unprocessed Event Log`, an instruction line stating the agent must not append and may only delete processed events during memory processing, an `## Overview`, and an `## Unprocessed Events` section.

**Who maintains it.** The event stream manager appends here. The nightly memory run reads the buffer, distills what is worth keeping into `MEMORY.md`, and clears it.

**Edit guidance.** Do not hand-edit it. It is cleared after each successful memory run.

**Runtime use.** Input to the memory pipeline. It is indexed for memory search.

## MISSION_INDEX_TEMPLATE.md

The template for a multi-session mission's index file.

**Structure.** `# [Mission Name]`, a one-line description, then `## Goal`, `## Status` (Current phase, Last updated, Last task summary), `## Key Findings`, `## What's Been Tried`, `## Next Steps`, `## Resources & References`, and `## Constraints & Notes`. Every field is a placeholder to fill in.

**Who maintains it.** The template file itself is static. When a mission starts, the agent copies it to `workspace/missions/<name>/INDEX.md` and fills in that copy over the life of the mission.

**Edit guidance.** Do not treat the template as a live document. Edit the per-mission `INDEX.md` copy, not this file.

**Runtime use.** The `INDEX.md` copy is what a later task reads to restore mission context. The Key Findings section is the most load-bearing part.

## The workspace directory

Task outputs land under `agent_file_system/workspace/`, which has its own zones for deliverables, per-task scratch, missions, and Living UI projects with distinct lifecycles. That layout is documented in the [Agent file system](../core/concepts/agent-file-system.md#workspace) concept page and is not repeated here.

## Next

- [Agent file system](../core/concepts/agent-file-system.md): how these files relate and the workspace layout
- [Context engine](../core/concepts/context-engine.md): how `USER.md` and `SOUL.md` enter the prompt
- [Memory](../core/concepts/memory.md): how events become `MEMORY.md` facts and how they are retrieved
- [Proactive mode](../core/modes/proactive.md): how `PROACTIVE.md` is scheduled and executed
