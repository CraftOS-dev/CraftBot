# Write a CraftBot skill

A skill teaches the agent how to run a workflow it could already run in principle but would run better with guidance. You write it as a `SKILL.md` file in a folder under `skills/`. This page covers the file format field by field, how arguments flow into a skill, how a skill pulls in the action sets it needs, and how to install and enable it. For how a skill is chosen for a task and injected on each turn, see the [Skills concept page](../../core/concepts/skills.md). For adding a new capability with code instead, see [Custom action](../custom-action.md).

## SKILL.md structure

A skill is a directory whose name is the skill id, containing a `SKILL.md` file and any supporting files it references:

```
skills/
  daily-standup/
    SKILL.md          # frontmatter + instructions
    REFERENCE.md      # optional, read on demand
    scripts/
      collect.sh      # optional helper
```

`SKILL.md` has two parts. An optional YAML frontmatter block at the top, delimited by `---` lines, holds the metadata. Everything after the closing `---` is the markdown body, which is the instruction text the agent reads:

```markdown
---
name: daily-standup
description: Produce a short daily standup summary from recent events and git activity.
argument-hint: "[repo-path]"
user-invocable: true
action-sets: [file_operations, shell]
---

# Daily Standup

When this skill is active, follow these steps.

1. Read the last 24 hours of events from EVENT.md.
2. Run `git log --since='24 hours ago' --oneline` in the target repo.
3. Write three sections: Done yesterday, Plan for today, Blockers.
```

Frontmatter is optional. The parser treats a file that has no `---` block as pure body text. When frontmatter is absent, the loader fills in the required fields for you: `name` becomes the folder name, and `description` becomes the first non-heading paragraph of the body (with a leading blockquote marker stripped, capped at 200 characters). A single markdown file with a heading and a one-line tagline is a valid, discoverable skill. Many bundled agent skills are written this way.

## Frontmatter fields

The loader recognizes six fields. Each has a hyphenated form (`argument-hint`) and accepts the underscore form (`argument_hint`) as an alias.

| Field | Type | Default | Purpose |
|---|---|---|---|
| `name` | string | folder name | Stable identifier. Normalized to lowercase, with underscores turned into hyphens and surrounding whitespace stripped. Keep it equal to the folder name to avoid confusion. |
| `description` | string | first body paragraph | The text the automatic selector reads to decide whether this skill fits a task. This is the field that most affects whether the skill ever gets used. |
| `argument-hint` | string | empty | A usage hint shown next to the slash command, for example `"<file> [options]"`. |
| `user-invocable` | boolean | `true` | Whether the skill is registered as a slash command and offered in the skill picker. Set it to `false` for silent backend workflows. |
| `allowed-tools` | list | empty | Restricts which actions the skill is allowed to call. Leave it empty to allow any action the task has loaded. |
| `action-sets` | list | empty | Action sets to auto-include when this skill is selected. See [Declaring action sets](#declaring-action-sets). |

If the frontmatter is present but is not a YAML mapping (for example a stray `description: Foo: bar` that YAML reads as a nested map), the loader rejects that file and the skill does not load. Keep values that contain a colon in quotes.

### Writing a description that triggers

The `description` is the one line the automatic selector sees for your skill among all enabled skills. A bare functional line such as `Summarise PRs` tends to lose to a more directive description with the same purpose. Write two parts: what the skill does, and when to use it. Name a few phrasings a user might actually type, and state the output shape. The bundled `pdf` skill is a good model: its description lists concrete operations (merge, split, extract text, fill forms) and the trigger condition (any mention of a `.pdf` file), so the selector attaches it reliably.

## Writing the instructions

The body is the working part of the skill. It is injected into the task and the agent is told to follow it. Write it as if you are briefing a competent operator who knows the tools but not this particular workflow.

- Use imperative, present-tense steps: "Read the file", not "you should read the file".
- State the goal and the constraints, then trust the agent to fill in the small gaps. You do not need to enumerate every keystroke.
- Give the reason for a non-obvious rule. A short "why" lets the agent handle an edge case the rule did not anticipate.
- Delegate bulk reference material to supporting files. Tell the agent to `read_file` a `REFERENCE.md` when it needs the detail, rather than inlining it.

Read a few bundled skills to see the range. `skills/pdf/SKILL.md` is a task cookbook with code snippets and a pointer to `REFERENCE.md` and `FORMS.md` for the long tail. `skills/day-planner/SKILL.md` is a decision-heavy workflow that spends most of its length on when not to act. `skills/craftbot-skill-creator/SKILL.md` is a workflow that itself writes skills. All three keep one clear happy path and push the exceptions to the margins.

## Argument substitution

When a skill is invoked with arguments, the loader substitutes placeholders in the body before injection. There are three forms:

| Placeholder | Expands to |
|---|---|
| `$ARGUMENTS` | The full argument string, verbatim. |
| `$ARGUMENTS[N]` | The Nth whitespace-separated word, zero-indexed. |
| `$N` | Shorthand for `$ARGUMENTS[N]`, also zero-indexed. |

An index that runs past the end of the argument list expands to an empty string rather than erroring.

Take a skill invoked from chat as `/report acme q3`. Inside the body:

```markdown
Generate the report for "$0" covering period "$1".
Full request was: $ARGUMENTS
```

expands to:

```
Generate the report for "acme" covering period "q3".
Full request was: acme q3
```

Here `$0` and `$ARGUMENTS[0]` both give `acme`, `$1` gives `q3`, and `$ARGUMENTS` gives the whole string `acme q3`. Use `$ARGUMENTS` when you want the raw request and the numbered forms when the workflow expects positional inputs. Advertise the expected shape with `argument-hint`.

## Declaring action sets

A skill orchestrates actions, and those actions live in [action sets](../../core/concepts/actions-and-action-sets.md) that a task loads as it needs them. List the sets your workflow depends on in `action-sets`. When the skill is selected for a task, those sets are merged into the task automatically, so a skill that shells out brings the `shell` set with it and a skill that writes files brings `file_operations`.

```yaml
action-sets: [file_operations, web]
```

List only the sets the workflow actually uses. The `core` set is always available, so there is no need to name it. If you also set `allowed-tools`, keep the two consistent: the actions you allow should come from the sets you declare.

## Making it slash-invokable

Every enabled skill with `user-invocable: true` (the default) is registered as `/<name>`. Typing `/` in chat lists the available skills, and invoking one force-attaches it to the new task and skips automatic selection. So a skill in `skills/daily-standup/` with `user-invocable: true` becomes `/daily-standup`, and `/daily-standup ./myrepo` runs it with `./myrepo` flowing into the argument placeholders.

Set `user-invocable: false` for a skill that should run only as part of a system workflow and never be picked by a user, such as a background planner or a memory processor. A non-invocable skill is not registered as a slash command and is not offered in the picker. This flag also marks the skill as CraftBot-essential for profile bundle imports, covered in [External skills](external-skill.md).

## Supporting files and the token cap

Files that sit next to `SKILL.md` are not injected into the task. The agent reads them on demand with `read_file`, which is why a skill can carry a large `REFERENCE.md` without paying for it on every turn. Point at supporting files by relative path from the skill folder.

The injected instruction text is capped at 16,000 tokens, roughly 64 KB. If a skill's body exceeds the cap, the loader truncates it at a paragraph boundary and appends a visible `[... instructions truncated due to length limit]` marker. The cap is generous, and the largest bundled skill sits well under it, but it is the reason to keep the body focused and move long tables, code libraries, and appendices into supporting files.

## Installing and enabling

To install a skill by hand, create its folder under `skills/` and drop the `SKILL.md` in. Discovery scans the `skills/` directory, so `/skill reload` (or reloading from **Settings → Skills**) picks up a new folder without restarting the agent.

Whether a discovered skill is active is controlled by `app/config/skills_config.json`:

```json
{
  "auto_load": true,
  "enabled_skills": ["pdf", "docx", "daily-standup"],
  "disabled_skills": []
}
```

The enable rule depends on `enabled_skills`. An empty list means every skill not named in `disabled_skills` is enabled. A non-empty list acts as a whitelist, so only the names in it are enabled. CraftBot ships with a whitelist, so a new skill you author stays dormant until you add its name. You do that in one of three equivalent ways, all of which write the same config file:

| Surface | Action |
|---|---|
| `/skill` command | `/skill enable <name>`, plus `list`, `info`, `disable`, `install`, `create`, `remove`, `reload`, `dirs`. |
| **Settings → Skills** | The same operations from the settings screen. |
| `skills_config.json` | Edit `enabled_skills` directly, then `/skill reload`. |

Keep the enabled set tight. The automatic selector chooses among the descriptions of enabled skills only, so a smaller, more relevant set makes selection more accurate. For the runtime detail of selection and the one-skill-per-task cap, see the [Skills concept page](../../core/concepts/skills.md#managing-skills).

## A complete example

Here is a full, minimal skill you can copy into `skills/changelog-entry/SKILL.md` and enable:

```markdown
---
name: changelog-entry
description: Draft a changelog entry from recent merged pull requests in a repository. Use this whenever the user asks for a changelog, release notes, a "what changed" summary, or a version bump note, even if they do not say "changelog" explicitly. Produces a markdown list grouped by change type.
argument-hint: "<repo> [since-tag]"
user-invocable: true
action-sets: [file_operations, shell]
---

# Changelog Entry

Draft a changelog entry for a repository from its recently merged pull
requests, grouped by type (Added, Changed, Fixed).

## When to use

- The user asks for a changelog, release notes, or a "what changed" summary.
- The user names a repository and, optionally, a tag to compare against.

## Steps

1. Determine the compare range. Use the tag in `$1` if given, otherwise
   the most recent tag in the repo at `$0`.
2. List merged PRs in the range with `git log` on the merge commits.
3. Group each entry under Added, Changed, or Fixed based on its title.
4. Write the result as markdown to `CHANGELOG_DRAFT.md` in the workspace.
5. Show the draft and stop. Do not commit or tag anything.

## Output format

    ## <version or date>

    ### Added
    - <entry>

    ### Fixed
    - <entry>

## Common pitfalls

- Do not invent entries when the range is empty. Write "No changes in range."
```

Save the file, run `/skill reload`, enable it with `/skill enable changelog-entry`, and invoke it with `/changelog-entry ./myrepo v1.2.0`.

## Generating a skill from a task

You do not have to write a skill from scratch. When a task finishes, its detail panel offers a **Create Skill** button. It opens a small dialog where you name the new skill. CraftBot then writes a source file that captures the finished task's action trace and spawns a workflow task running the bundled `craftbot-skill-creator` skill. That skill reads the trace, generalizes it (stripping the specific repository, dates, and file paths the original task used), and writes a fresh `skills/<name>/SKILL.md`. You can trigger the same flow from chat by asking the agent to save what it just did as a skill.

This is the cheapest way to build a library: run the workflow once interactively, confirm it worked, then freeze it. The generated skill is a normal `SKILL.md`, so you review and edit it exactly as you would a hand-written one. The button does not appear on system-spawned tasks (planners, memory processing, and the skill workflows themselves), because those are infrastructure rather than user workflows.

## Next

- [External skills](external-skill.md): install and vet a skill authored elsewhere.
- [Skills concept page](../../core/concepts/skills.md): selection, per-turn injection, and mid-task skill swaps.
- [Actions and action sets](../../core/concepts/actions-and-action-sets.md): the capabilities a skill declares and orchestrates.
- [Skills overview](index.md): the three authoring routes at a glance.
