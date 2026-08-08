# Write your first skill

By the end of this guide you have a working skill named `standup-notes` that turns a few rough notes about your day into a clean standup update (Done, Today, Blockers) and posts back the formatted result. You invoke it by typing `/standup-notes` in chat. Along the way you learn the file format, how arguments flow in from the slash command, and how to enable and test what you built.

This guide is the hands-on walkthrough. For the field-by-field reference (every frontmatter key, the token cap, packaging), see [Write a CraftBot skill](../develop/skills/craftbot-skill.md). For how a skill is chosen and injected at runtime, see the [Skills concept page](../core/concepts/skills.md).

A skill adds no new capability. It gives the agent a written strategy for a workflow it could already run, so the result is consistent every time. That is what makes a repeated request worth packaging once.

## What you need

| Requirement | How to get it |
|---|---|
| A working CraftBot install | [Quickstart](../start/quickstart.md) |
| A text editor for the `skills/` directory | Any editor; the file is plain markdown |
| A repeated workflow worth packaging | This guide uses a daily standup update as the example |

You do not need to write any code. A skill is a markdown file.

## Step 1: create the skill folder

A skill is a directory under `skills/` whose name is the skill id, containing a file named `SKILL.md`. Create the folder for this one:

```
skills/
  standup-notes/
    SKILL.md
```

Two rules the loader enforces, so get them right now:

- The file must be named `SKILL.md` in uppercase. The loader scans each folder under `skills/` for exactly that name and ignores a folder without it.
- The folder name is the skill id. Keep it lowercase with hyphens (`standup-notes`), because that is what becomes the slash command.

## Step 2: write SKILL.md

A `SKILL.md` file has two parts: an optional YAML frontmatter block between `---` lines that holds the metadata, and the markdown body after it that holds the instructions the agent reads. Put this in `skills/standup-notes/SKILL.md`:

```markdown
---
name: standup-notes
description: Turn rough notes about the user's day into a formatted standup update with Done, Today, and Blockers sections. Use this whenever the user asks for a standup, a daily update, a status update, or wants their notes cleaned into that shape, even if they do not say "standup" explicitly. Produces three short markdown sections.
argument-hint: "[rough notes about your day]"
user-invocable: true
action-sets: [file_operations]
---

# Standup Notes

Turn the user's rough notes into a short, well-formed standup update.
```

Only two fields are doing essential work here.

- `user-invocable: true` is what registers the skill as the `/standup-notes` slash command and offers it in the picker. It is the default, so you could omit it, but set it explicitly while you are learning. Setting it to `false` hides the skill from the command list, which you want only for silent background workflows.
- `description` is the single line the automatic selector reads to decide whether this skill fits a task. Write two things into it: what the skill does, and when to use it, including a few phrasings a user might actually type. A bare line like `Format a standup` tends to lose to a more directive description. See [writing a description that triggers](../develop/skills/craftbot-skill.md#writing-a-description-that-triggers).

Frontmatter is optional. A folder with a bare markdown file and no `---` block is still a valid skill; the loader fills in `name` from the folder name and `description` from the first body paragraph. You are writing the frontmatter explicitly because you want a good description and a slash command.

## Step 3: write the instructions

The body is the working part of the skill. It is injected into the task on every turn, wrapped in a block the agent is told to follow. Write it as if you are briefing a competent operator who knows the tools but not this particular workflow. Replace the one-line body from Step 2 with real steps:

```markdown
# Standup Notes

Turn the user's rough notes into a short, well-formed standup update.

## When to use

- The user asks for a standup, a daily update, or a status update.
- The user hands you a few informal notes about what they did and are doing.

## Steps

1. Read the raw notes in `$ARGUMENTS`. If the notes are empty, ask the user
   for a one-line summary of their day before continuing.
2. Sort each item into one of three buckets: Done (finished), Today (in
   progress or planned), or Blockers (anything waiting on someone or unclear).
3. Rewrite each item as one short, past-or-present-tense line. Keep the user's
   meaning; drop filler words.
4. Output the three sections in the format below. Omit a section only if it
   has no items, except always keep Blockers so nothing hides.

## Output format

    **Done**
    - <item>

    **Today**
    - <item>

    **Blockers**
    - <item, or "None">

## Notes

- Keep it under about ten lines total. A standup is a summary, not a report.
- Do not invent work the user did not mention.
```

A few practices this shows, drawn from the bundled skills:

- Use imperative, present-tense steps ("Read the notes", not "you should read the notes").
- State the goal and constraints, then trust the agent for the small gaps. You do not need to enumerate every keystroke.
- Give a short reason for a non-obvious rule ("always keep Blockers so nothing hides"), so the agent handles edge cases the rule did not spell out.
- For a longer workflow, move bulk reference material into a supporting file next to `SKILL.md` and tell the agent to `read_file` it on demand. Supporting files are not injected into the prompt, so they cost nothing until the agent opens them. Read `skills/pdf/SKILL.md`, `skills/day-planner/SKILL.md`, and `skills/craftbot-skill-creator/SKILL.md` to see the range.

Keep the body focused. The injected instructions are capped at 16,000 tokens (roughly 64 KB). Past that, the loader truncates at a paragraph boundary and appends a visible marker. The cap is generous, but it is the reason to push long tables and appendices into supporting files.

## Step 4: give it arguments

The reason to add arguments is so the slash command can carry input. When a skill is invoked with text after its name, the loader substitutes placeholders in the body before injecting it. There are three forms:

| Placeholder | Expands to |
|---|---|
| `$ARGUMENTS` | The full argument string, verbatim |
| `$ARGUMENTS[N]` | The Nth whitespace-separated word, zero-indexed |
| `$N` | Shorthand for `$ARGUMENTS[N]`, also zero-indexed |

The skill already uses `$ARGUMENTS` in Step 1 of its instructions, which is the right choice here because you want the whole free-text note, not individual words. Invoke it like this:

```
/standup-notes shipped the login fix, reviewing two PRs, blocked on the staging deploy
```

Inside the body, `$ARGUMENTS` expands to the whole string `shipped the login fix, reviewing two PRs, blocked on the staging deploy`, and the agent sorts it into the three sections.

The numbered forms are for workflows that expect positional inputs. Because they are zero-indexed, `$0` is the first word (`shipped` in the example above), `$1` is the second (`the`), and so on. An index past the end of the argument list expands to an empty string rather than erroring, so an optional trailing argument is safe to reference. The `argument-hint` you set advertises the expected shape next to the slash command; keep it truthful so the hint matches what the body reads.

## Step 5: enable and test

CraftBot ships with an enabled whitelist, so a skill you author stays dormant until you add its name. Getting from the file on disk to a working `/standup-notes` is two steps:

1. Reload discovery so CraftBot sees the new folder:

```
/skill reload
```

2. Enable it by name:

```
/skill enable standup-notes
```

Both of these also exist under **Settings → Skills**, and both write the same `app/config/skills_config.json` file (the enabled name lands in `enabled_skills`). Confirm it registered:

```
/skill list
```

Then invoke it with real input:

```
/standup-notes finished the auth refactor, writing tests today, waiting on design for the settings page
```

Invoking a skill by its slash command force-attaches it to the new task and skips automatic selection, so you are testing exactly this skill. You should get back three sections with your items sorted into Done, Today, and Blockers.

## Step 6: iterate

The first version is rarely the final one. Editing a skill is just editing the file:

1. Open `skills/standup-notes/SKILL.md` and change the instructions or the format.
2. Run `/skill reload` so the change is picked up. You do not need to restart the agent.
3. Invoke `/standup-notes` again with the same input and compare.

Common adjustments: tighten the output format, add a rule for a case the agent handled poorly, or sharpen the `description` if the automatic selector is not attaching the skill when you expect it to. Change one thing at a time so you can tell what improved.

## Generating a skill from a task

You do not have to write every skill by hand. When a task finishes, its detail panel offers a **Create Skill** button. Name the new skill and CraftBot captures the finished task's action trace, generalizes it (stripping the specific repository, dates, and file paths the original run used), and writes a fresh `skills/<name>/SKILL.md` for you using the bundled `craftbot-skill-creator` skill. You can trigger the same flow from chat by asking the agent to save what it just did as a skill.

This is often the fastest way to build a library: run the workflow once interactively, confirm it worked, then freeze it. The generated file is an ordinary `SKILL.md`, so you review and edit it exactly as you edited the one in this guide. For the full detail, see [Generating a skill from a task](../develop/skills/craftbot-skill.md#generating-a-skill-from-a-task).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| The skill does not show in `/skill list` | It is not enabled, or discovery has not run | Run `/skill reload`, then `/skill enable standup-notes` |
| The skill still does not appear after reloading | The file is not named `SKILL.md` in uppercase, or is not directly inside the skill folder | Rename it to exactly `SKILL.md` under `skills/standup-notes/` |
| The skill loads but has no slash command | `user-invocable` is set to `false` | Set `user-invocable: true` and run `/skill reload` |
| The whole file fails to load | The frontmatter is not a valid YAML mapping (often a value with an unquoted colon) | Quote any value containing a colon, for example `description: "Format: standup"` |
| Placeholders stay as literal `$ARGUMENTS` in the output | The skill was invoked with no arguments, or the placeholder is misspelled | Pass text after the command, and check for exact `$ARGUMENTS` / `$0` spelling |
| The automatic selector never picks the skill on its own | The `description` is too vague | Rewrite it to name what it does and when to use it, then reload |

## Next

- [Write a CraftBot skill](../develop/skills/craftbot-skill.md): the full field reference, the token cap, and packaging.
- [Skills concept page](../core/concepts/skills.md): selection, per-turn injection, and mid-task skill swaps.
- [Actions and action sets](../core/concepts/actions-and-action-sets.md): the capabilities a skill declares in `action-sets`.
- [Automated GitHub PR reviews](github-pr-review.md): a guide that pairs a skill with an integration.
