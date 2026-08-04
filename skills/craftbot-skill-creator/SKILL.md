---
name: craftbot-skill-creator
description: "Create a brand-new reusable skill from a single completed task. Read the per-task SKILL_SOURCE markdown the handler wrote, distil the workflow into a generalised SKILL.md, save it at skills/<name>/SKILL.md. Use this when CraftBot has spawned a 'Create Skill' workflow task and you need to author the new skill end-to-end without user interaction."
user-invocable: false
action-sets:
  - file_operations
  - core
---

# CraftBot Skill Creator

Author a reusable skill from one completed task. The handler that spawned this task already gathered everything you need into a single markdown file — read it, generalise it, write the new skill, send the user a one-message summary, end the task. The handler has already posted "Creating skill `<name>`…" in chat for you, so do not duplicate that message. Your only chat message is the final presentation right before `end_turn`. Do not iterate with test cases. Do not run subagents.

## What you receive

Your task instruction contains five lines (the two paths are **absolute** — pass them verbatim to `read_file` / `write_file`, do NOT prepend or modify any prefix):

```
Source file (read this — absolute path, use verbatim): <absolute path to SKILL_SOURCE_<id>.md>
Target file (write the new SKILL.md here — absolute path, use verbatim): <absolute path to skills/<name>/SKILL.md>
Mode: create
Skill name: <kebab-case-name>
```

> ⚠️ Do not invent your own path for the target file. The handler has already placed it at the correct location under the project's `skills/` directory; using the literal value of `Target file:` puts the SKILL.md where the framework will discover it. A common mistake is generalising the source's `agent_file_system/` prefix onto the target — that lands the new skill in the wrong directory and CraftBot will never see it.

`SKILL_SOURCE_<task_id>.md` has YAML frontmatter (`mode`, `target_skill`, `source_task_id`, `generated_at`) and these body sections, in order:

- `## Task name` — the short task title shown in the action panel. Treat this as a one-line summary of what the user wanted, not a verbatim instruction (the original instruction is not retained on disk after the source task ends).
- `## Outcome` — status, created/ended timestamps, the skills the source task had attached, and any internal `workflow_id`.
- `## Action trace` — every action and reasoning item the source agent emitted, in order, with `input`, `output`, `error`, and duration. **This is your primary evidence** — it is the durable record of what actually happened, kept in `actions.db`.

`create` mode means there is no existing SKILL.md for the target name; you write a fresh one.

The Task name and the action trace together are enough to reconstruct the workflow. Treat the trace as the ground truth — the name is just a hint about user intent.

## What you produce

Two artefacts, in order:

1. **One file** at the path given by `Target file:` in your task instruction (an absolute path under the project's `skills/` directory). Pass that path verbatim to `write_file` (or `create_file`). The directory does not exist yet; `write_file` creates the parent directory in the same call.
2. **One presentation message** to the user via `send_message`, immediately after the file is written and immediately before `end_turn`. See *Presentation message* below for the format.

Do not write any other files. Do not send any chat message other than the single presentation one — the handler has already posted the "Creating skill …" acknowledgement.

## Capture intent — from the source task

You will not interview the user. The source task IS the workflow you are codifying. Read `SKILL_SOURCE_<task_id>.md` once with `read_file`, then answer these four questions for yourself before drafting:

1. **What should this skill enable CraftBot to do?** Use the `## Task name` as a hint, then walk the `## Action trace` to see what the agent actually accomplished. Generalise: strip the specific subject ("PRs in repo X" → "summarise PRs in a repository"). The skill must be reusable across many invocations.
2. **When should this skill trigger?** What user phrases or contexts would lead someone to want this workflow next time? Be concrete in the description (see *Description* below).
3. **What is the output format?** Look at the final write/output actions in the trace. The skill should specify the same shape so future invocations produce comparable results.
4. **What is the shortest happy path?** The source agent may have re-queried, backtracked, or self-corrected. Walk the trace and identify the *one* sequence that gets to the outcome. Earlier dead-ends do not belong in the skill body — but a `## Common pitfalls` section can mention them so future runs avoid them too.

If the source task has very thin evidence (one or two actions, no real workflow), still write a useful skill — but keep the body short and honest. Don't pad.

## Anatomy of a CraftBot skill

```
skills/<skill-name>/
├── SKILL.md           (required)
│   ├── YAML frontmatter
│   └── Markdown body
├── scripts/           (optional — executable helpers)
├── references/        (optional — long docs the agent can read on demand)
└── assets/            (optional — templates, fixtures)
```

You will only write `SKILL.md` in this workflow. The optional directories exist for skills authored by hand; do not create them here even if the source task touched many helper scripts. (If you notice strong repeated work in the trace, mention it in `## Common pitfalls` so a human author can come back and bundle it later.)

## Frontmatter — the four fields

CraftBot extends Anthropic's standard frontmatter (`name`, `description`) with two local fields (`user-invocable`, `action-sets`) — both required.

```yaml
---
name: <kebab-case-skill-name>
description: <one paragraph — see Description below>
user-invocable: true
action-sets:
  - <action-set-1>
  - <action-set-2>
---
```

| Field | What it means | How to fill it |
|---|---|---|
| `name` | Stable kebab-case identifier. Must match the directory name. | Use the value from your task instruction verbatim. |
| `description` | The primary triggering signal — what the skill does AND when to use it. | See *Description* below. |
| `user-invocable` | Whether a user can pick this skill from the skill picker. | `true` for almost every new skill. Set `false` only if the skill is a silent backend workflow (memory processing, etc.) — that is not the case here. |
| `action-sets` | Action-set names the skill actually uses. | Match the source task's `Action sets` line in SKILL_SOURCE. Drop any that the action trace shows were never actually called. The `core` set is auto-included by the framework — do not list it. |

### Description — make it pushy

CraftBot tends to *under-trigger* skills it isn't sure about. A bare functional description like "Summarise GitHub PRs" loses to a skill with the same purpose but a more directive description. Aim for two parts: what + when. Use ~50–120 words.

Bad (too thin, won't trigger):

```
description: Summarise GitHub PRs.
```

Good (does the job):

```
description: Summarise the recent GitHub pull requests in a repository, grouped by author. Use this whenever the user asks for a PR digest, weekly engineering summary, "what shipped this week", or a code-review activity report — even if they don't say "PR" explicitly. Produces a markdown summary with one section per author and a one-line entry per PR.
```

The "Use this whenever…" clause is what fixes under-triggering. Include 2–4 phrasings the user might actually type, plus the output shape.

## Body — sections to include

The body is markdown loaded into context whenever the skill triggers. Keep it **under ~300 lines** for a one-task-derived skill (Anthropic's general ceiling is 500). If the workflow seems to need more, that is a sign you are over-fitting to the source task.

Include these sections, in this order. Skip optional ones if they have nothing useful to say.

1. **`# <Title-Case Name>` + one-paragraph overview.** What the skill enables. What kind of input it expects. What it produces.
2. **`## When to use`** *(optional but recommended)*. Bullet list of trigger scenarios. The description already covers this; this section is for nuance — domains, adjacent cases, "use this instead of X when…".
3. **`## Definition of Done`**. Numbered list of observable conditions that mark the task complete. Future agents will use this to decide whether to call `end_turn`.
4. **`## General Steps`**. Numbered list. The shortest happy path, derived from the source action trace. One imperative sentence per step. No specific values. No code.
5. **`## Output Format`** *(if the skill produces structured output)*. The exact template the agent should write. Use a fenced code block.
6. **`## Examples`** *(0–2 examples)*. Realistic input → output pairs. Strip identifying details. Each example should be ~5–15 lines, not pages.
7. **`## Common pitfalls`** *(only if the source trace contained real evidence)*. Bullet list. Each bullet: the symptom you saw, then the avoidance. See *Mistake-scanning* below.
8. **`## Allowed Actions`**. Comma-separated list of action names the skill expects to use, drawn from the source action trace.

Do **not** include sections for: testing, evaluation, packaging, description optimization. Those are the human author's job. The single SKILL.md is your only deliverable.

## Writing style

Apply these from Anthropic's skill-creator guidance. They matter more than any individual section.

- **Imperative form.** "Read the file" — not "you should read the file" or "the file must be read".
- **Explain the why** for non-obvious rules. A short `*Why:* …` line after a rule lets future agents handle edge cases the rule didn't anticipate. Rules without rationale rot.
- **Avoid heavy-handed MUSTs.** ALL-CAPS imperatives are a yellow flag. If you wrote `MUST` or `NEVER`, ask whether explaining the underlying reasoning would do the job better.
- **Theory of mind.** The agent reading this skill is competent. Tell it the goal and the constraints; trust it to fill in the gaps. Don't enumerate every micro-step.
- **Generalise.** No specific dates, names, IDs, URLs, paths copied from the source task. Concrete numbers from the source become "the relevant <thing>" or are dropped entirely. *Why:* concrete values rot the moment the skill runs against new data.
- **Lean.** Each sentence should pull weight. After your first draft, re-read it and delete anything you wouldn't miss.
- **No placeholder data.** If the source task used a specific spreadsheet, describe the *role* the spreadsheet played, not its column names — those will differ next time.

## Mistake-scanning — the `## Common pitfalls` section

Walk the action trace once with this question: *did the source agent waste time or take a wrong direction that future agents could be warned away from?*

**Surface (task-specific) signals:**

- Two consecutive calls to the same action with different parameters → the agent had the wrong mental model first time. Tell the new skill what the right first parameters look like.
- An output row whose content shows the agent went the wrong direction (e.g., wrong domain, wrong filter), prompting a corrective re-action.
- Mid-workflow context-file reads (USER.md, MEMORY.md) → front-load these in the skill so future runs don't pause to look things up.
- Search/query that came back with too many or wrong results, prompting a more specific re-query → tell the new skill what makes the query specific enough.

**Ignore (generic) signals:**

- File-not-found, path-not-resolved, permission-denied — infrastructure, not workflow knowledge.
- OS-specific errors (path separators, line endings, encoding).
- Network timeouts, rate limits, transient HTTP errors.
- JSON/parse errors any task could hit.

**If the trace is clean** (no errors, no re-actions, perfectly linear) → omit the `## Common pitfalls` section. Don't invent pitfalls. Speculative warnings dilute real ones.

## Definition of Done (for this workflow itself)

You are done when all of these are true:

1. `skills/<skill-name>/SKILL.md` exists at the path your task instruction specified.
2. The frontmatter has all four fields and parses as YAML.
3. `name` matches `<skill-name>`. `description` follows the *pushy* pattern above. `action-sets` lists only sets the source task actually used.
4. The body has at minimum a one-paragraph overview, `## Definition of Done`, `## General Steps`, and `## Allowed Actions`.
5. No specific values from the source task leak into the skill (no concrete dates, names, IDs, URLs, paths, file contents).
6. Total body length is reasonable for the workflow's complexity (~80–300 lines is the right ballpark).
7. You have sent the presentation message via `send_message` (see below).
8. You have called `end_turn` with a one-line summary.

## Presentation message — required, exactly once

After writing the SKILL.md and immediately before `end_turn`, call `send_message` once with a short summary the user can read at a glance. Aim for 3–6 short lines. Adapt this template — do not copy verbatim:

```
✨ Created the **<skill-name>** skill.
What it does: <one-sentence summary of the workflow it captures>.
When it'll trigger: <one short example phrase from the description>.
You can invoke it on future tasks via the skill picker.
```

Rules:
- Reference the skill by name in backticks or bold so it stands out.
- Do NOT paste the SKILL.md body. The user can open the file.
- Do NOT mention the source task by name or include any specific values from it (consistent with the no-leak rule).
- Keep it brief and confirmatory — this is an "it's done" message, not a tutorial.
- The handler has already posted "Creating skill `<name>`…" in chat, so do not duplicate that or send any other chat message during the workflow.

## Allowed Actions

`read_file`, `create_file` (or `write_file`), `stream_edit`, `send_message`, `update_todos`, `end_turn`.

`stream_edit` is only needed if you want to refine the file you just created — write it correctly the first time and you won't need it.

## Forbidden

- More than one `send_message` call. The presentation message above is the only one — anything else is noise.
- `web_search`, `run_shell` — outside `file_operations` + `core`.
- Writing or modifying any file outside `skills/<skill-name>/`.
- Overwriting an existing skill. (The handler refuses to spawn this workflow if the directory already exists; if you somehow find one there, end the task immediately rather than overwriting.)

## Example: a complete worked output

Source task (paraphrased): the user asked the agent to summarise the recent GitHub PRs in some repository. The action trace shows two `web_search` calls (the first too broad), one `read_file` of a USER.md to fetch the user's preferred summary length, and one `create_file` writing the final markdown digest.

A reasonable `skills/pr-weekly-summary/SKILL.md`:

```markdown
---
name: pr-weekly-summary
description: Summarise the recent pull requests in a GitHub repository, grouped by author. Use this whenever the user asks for a PR digest, "what shipped this week", a code-review activity report, or a weekly engineering summary — even if they don't say "PR" explicitly. Produces a markdown summary with one section per author.
user-invocable: true
action-sets:
  - file_operations
  - web_research
---

# PR Weekly Summary

Produce a markdown digest of recent pull requests in a GitHub repository, grouped by author. Use the user's preferred summary length from USER.md if present.

## When to use

- The user asks "what shipped this week?", "PR digest", "code review summary".
- The user names a repository and a time window and asks for a status overview.

## Definition of Done

1. A markdown file exists at the requested output path (or, if none requested, in the workspace root).
2. PRs are grouped by author and ordered by merge date within each author.
3. Each PR has a one-line entry: title, number, link.
4. Empty author groups are omitted.

## General Steps

1. Read USER.md to pick up the user's preferred summary verbosity if present.
2. Confirm the repository and date window from the user's request. Default window is the last 7 days if unspecified.
3. Fetch merged PRs in the window with `web_search`. Always include the date filter in the first query — broad queries return too many results.
4. Group PRs by author; within each group, order by merge date descending.
5. Write the markdown digest with `create_file`.
6. `end_turn` with a one-line summary.

## Output Format

```
# PR digest for <repository> (<window>)

## <Author>
- #<number> <title> — <merge-date> — <link>

## <Author>
- ...
```

## Common pitfalls

- Searches without an explicit date window return too many results. Pin the window in the first query.

## Allowed Actions

`web_search`, `read_file`, `create_file`, `update_todos`, `end_turn`.
```

Notice what is *not* in this output: the specific repository name, the specific week, the count of PRs found, the actual author names, the path of the python script the source agent wrote. All of those would have rotted by the next invocation.
