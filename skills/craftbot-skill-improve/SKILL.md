---
name: craftbot-skill-improve
description: "Refine an existing CraftBot skill using evidence from one completed task that used it. Read the per-task SKILL_SOURCE markdown the handler wrote, diff it against the existing SKILL.md, apply surgical edits to skills/<target>/SKILL.md. Use this when CraftBot has spawned an 'Improve Skill' workflow task and you need to refine the skill's accuracy or token efficiency without redesigning it."
user-invocable: false
action-sets:
  - file_operations
  - core
---

# CraftBot Skill Improver

Refine one existing skill using evidence from one task that used it. The handler that spawned this task already gathered everything you need into a single markdown file — read it, diff it against the live skill, apply small surgical edits, send the user a one-message summary of the changes, end the task. The handler has already posted "Improving skill `<name>`…" in chat for you, so do not duplicate that message. Your only chat message is the final presentation right before `task_end`. Do not iterate with test cases. Do not run subagents.

## What you receive

Your task instruction contains five lines (the two paths are **absolute** — pass them verbatim to `read_file` / `stream_edit`, do NOT prepend or modify any prefix):

```
Source file (read this — absolute path, use verbatim): <absolute path to SKILL_SOURCE_<id>.md>
Target file (edit this — absolute path, use verbatim): <absolute path to skills/<existing-name>/SKILL.md>
Mode: improve
Skill name: <existing-skill-name>
```

> ⚠️ Do not invent your own path for the target file. Using the literal value of `Target file:` ensures `stream_edit` modifies the actual installed SKILL.md.

`SKILL_SOURCE_<task_id>.md` has YAML frontmatter (`mode: improve`, `target_skill`, `source_task_id`, `generated_at`) and these body sections:

- `## Task name` — the short task title shown in the action panel. A one-line summary of intent, not a verbatim instruction.
- `## Outcome` — status, created/ended timestamps, the skills the source task had attached, and any internal `workflow_id`.
- `## Action trace` — every action and reasoning item, in order, with `input`, `output`, `error`, and duration. **This is your primary evidence** — it is the durable record of what actually happened.
- `## Existing SKILL.md` — the verbatim contents of `skills/<target>/SKILL.md` *as captured at the moment the workflow started*.

The target skill exists. Your job is to edit it in place. The action trace is the evidence; the existing SKILL.md is what you are diffing against.

## What you produce

Two artefacts, in order:

1. **Targeted edits** to exactly one file: the path given by `Target file:` in your task instruction (an absolute path under the project's `skills/` directory). Pass that path verbatim to `stream_edit`. Do not do a whole-file rewrite of it — that clobbers the rest of the file. Do not write any other files. Do not change the directory layout. Do not delete bundled resources in `scripts/`, `references/`, or `assets/`.
2. **One presentation message** to the user via `send_message`, immediately after the edits and immediately before `task_end`. See *Presentation message* below for the format.

Do not send any chat message other than the single presentation one — the handler has already posted the "Improving skill …" acknowledgement.

## Improvement constraints — what makes this different from creation

These four rules are the heart of *improve* mode. Read them before drafting.

1. **Do not redesign the skill.** The existing skill encodes a tested workflow. Your job is *refinement*, not rewriting. Drastic restructuring regresses use cases that this single source task never exercised.
   *Why:* one task is a sample size of one. The skill has likely been used many times before; you are seeing one slice.

2. **Optimise for accuracy AND token efficiency.** A change is justified if and only if it does one of:
   - **Prevents a class of mistake** the source task hit (and that the existing skill did not warn about), OR
   - **Shortens** the skill without removing meaning (kill filler, redundant restatements, dead bullets).
   *Why:* both quality and prompt-cost matter. Skills are loaded into context every time they trigger.

3. **Prefer surgical edits over wholesale rewrites.** One `stream_edit` per change. Each edit replaces or inserts a small contiguous range. If you are about to replace half the file, stop — that is redesign, not refinement.
   *Why:* small diffs are reviewable and reversible by humans afterwards.

4. **Do not invent pitfalls.** If the source task ran cleanly, do not add speculative warnings. If the trace shows the existing pitfall warnings are wrong, fix or remove them.
   *Why:* unfounded warnings dilute real ones; agents start ignoring the section.

## How to think about improvements

These come straight from Anthropic's skill-improver guidance and apply here verbatim.

- **Generalise from the feedback.** The skill will be invoked many more times than just this one task. If a fix only works for the source task's specific scenario, it's overfitting. Prefer changes that handle a *class* of cases, not the literal symptoms you saw.
- **Keep the prompt lean.** Read the action trace, not just the final outputs. If the existing skill told the agent to do something that the trace shows was wasted effort, removing that instruction is a valid improvement.
- **Explain the why.** When you add a rule, add a `*Why:* …` line right after it. When you sharpen an existing rule, preserve any existing `*Why:*` line — those are gold.
- **Look for repeated work.** If the action trace shows the agent independently wrote the same helper logic the existing skill could have bundled, mention it in the skill body so a human author knows to bundle it later. Do *not* attempt to create `scripts/` files yourself — that's outside this workflow's scope.

## CraftBot frontmatter — what you can and cannot change

CraftBot skills have four frontmatter fields:

| Field | Allowed change in *improve* mode |
|---|---|
| `name` | **Never change.** The directory name and the agent's task instruction depend on it. |
| `description` | Edit only if the source task evidence proves the current description is wrong (e.g., the agent triggered the skill for a use case the description should explicitly cover). Apply the *pushy* pattern: what + when, with example user phrasings. |
| `user-invocable` | Almost never change. Flip only if you have hard evidence the current value is wrong. |
| `action-sets` | Add a set only if the trace shows the agent actually called actions from it that the skill expects. Remove a set only if the existing skill never references its actions and the trace confirms it goes unused. |

## Anatomy reminder

```
skills/<skill-name>/
├── SKILL.md           ← edit this only
├── scripts/           ← do not modify in this workflow
├── references/        ← do not modify in this workflow
└── assets/            ← do not modify in this workflow
```

Bundled resources may exist for the target skill. Leave them alone. If the source trace suggests one of them is outdated, mention it in `## Common pitfalls` so a human can revisit.

## Workflow

Use `task_update_todos` at the start to track these. Mark each completed before moving on.

1. **Read the SOURCE.** `read_file` on the path from your task instruction. Note the action trace, errors, summary, and the verbatim existing SKILL.md.
2. **Re-read the live target.** `read_file` on `skills/<target-skill>/SKILL.md`. The SOURCE may be milliseconds stale; the live file is authoritative for line offsets when you `stream_edit`.
3. **Diff in your head.** Two questions:
   - What did the source task do that the existing skill *does not document* (and should)?
   - What did the source task do that the existing skill *says to do but evidence shows is wrong / extra*?
4. **Plan a small edit list.** Each entry is one of: *add a pitfall*, *trim a redundant step*, *sharpen wording for accuracy*, *shrink wording for tokens*. Aim for 1–4 edits. If you find yourself listing 10, you are redesigning — pick the highest-leverage few and stop.
5. **Apply edits.** One `stream_edit` per item in the list. Re-read the file between edits if line offsets have shifted significantly.
6. **Send the presentation message** via `send_message`. See *Presentation message* below.
7. **`task_end`** with a one-line summary of what changed.

## Mistake-scanning — what to surface as new pitfalls

Walk the action trace once. For each signal, decide whether the existing skill already warns about it. If yes, no edit needed. If no, consider adding to `## Common pitfalls`.

**Surface (task-specific) signals not already covered:**

- Two consecutive same-action calls with different parameters → wrong mental model first time. Add a pitfall describing the right first-pass parameters.
- Output that shows the agent went the wrong direction → add a pitfall describing the direction to take.
- Mid-workflow context-file reads → suggest front-loading via a step in `## General Steps` instead of a pitfall.
- Search/query that returned too many or wrong results → add a pitfall about query specificity.

**Ignore (generic) signals:**

- File-not-found, path issues, permissions, OS quirks, network timeouts, rate limits, JSON parse errors. Same exclusions as in *create* mode.

If `## Common pitfalls` does not exist in the target skill and you have at most one task-specific signal to add, prefer to fold it into `## General Steps` as a sharpening of an existing step rather than creating a whole new section.

## Token-efficiency heuristics

When trimming, prefer to delete:

- Redundant restatement of the same rule in two sections.
- Filler phrases ("It is important to note that…", "As mentioned above…", "Please ensure that you…").
- Examples that demonstrate the same case as another example.
- ALL-CAPS imperatives whose content is already covered by an imperative sentence elsewhere.

When trimming, do **not** delete:

- The frontmatter or any of its required fields.
- The Definition of Done section (or whatever named section serves that role).
- Real pitfalls that warn about a class of mistake.
- `*Why:* …` reasoning lines — those are how future agents handle edge cases the rule didn't anticipate.

## Definition of Done (for this workflow itself)

You are done when all of these are true:

1. `skills/<target-skill>/SKILL.md` has been modified, or you have decided no edit is justified and the presentation message says so.
2. The frontmatter still parses as valid YAML and `name` is unchanged.
3. The skill's body still covers what it did before — you didn't remove a load-bearing section.
4. Net line-count change is within roughly ±25%. Net negative is fine and often better.
5. No specific values from the source task have leaked into the skill (no concrete dates, names, IDs, URLs, paths, file contents).
6. You have sent the presentation message via `send_message` (see below).
7. You have called `task_end` with a one-line summary of what changed (e.g., "Added pitfall about over-broad search queries; trimmed redundant restatement of the date-filter rule").

## Presentation message — required, exactly once

After applying the edits and immediately before `task_end`, call `send_message` once with a short summary of what changed. Aim for 3–6 short lines. Adapt this template — do not copy verbatim:

```
✏️ Improved the **<skill-name>** skill.
Changes:
- <one-line description of edit 1>
- <one-line description of edit 2>
The skill is now more accurate / leaner / better at <specific behaviour>.
```

If you decided no edit was justified, send a brief "no changes — the existing skill already covers the workflow cleanly" message instead.

Rules:
- Reference the skill by name in backticks or bold.
- Summarise edits at the *behaviour* level ("now warns about over-broad searches"), not the *line* level ("inserted line at offset 47").
- Do NOT mention the source task by name or include any specific values from it.
- Keep it brief and confirmatory.
- The handler has already posted "Improving skill `<name>`…" in chat, so do not duplicate that or send any other chat message during the workflow.

## Allowed Actions

`read_file`, `stream_edit`, `send_message`, `task_update_todos`, `task_end`.

A whole-file rewrite is forbidden in this workflow — see *Improvement constraints* above.

## Forbidden

- More than one `send_message` call. The presentation message above is the only one.
- `create_file`, `write_file` — those overwrite. Use `stream_edit`.
- `web_search`, `run_shell` — outside `file_operations` + `core`.
- Writing or modifying any file outside `skills/<target-skill>/SKILL.md`.
- Renaming the skill directory or the `name` frontmatter field.
- Deleting bundled resources in `scripts/`, `references/`, or `assets/`.

## Example: a worked diff

Existing skill `pr-weekly-summary` (excerpt):

```markdown
## General Steps

1. Confirm the repository and date window from the user's request.
2. Fetch merged PRs.
3. Group by author and write the digest.
```

Source task evidence: the action trace shows two `web_search` calls — the first without a date filter (returned hundreds of results), the second narrowed down. The existing skill never warned about query breadth.

Reasonable edits (two `stream_edit` calls):

1. Sharpen step 2 of `## General Steps` to:
   ```
   2. Fetch merged PRs filtered by the requested date window — broad queries return too many results.
   ```
2. Append to (or create) `## Common pitfalls`:
   ```
   - Searches without an explicit date window return too many results. Pin the window in the first query.
   ```

Edits *not* to apply:

- Inserting the specific repository name from the source task.
- Inserting the specific date range used in the source task.
- Inserting an "expected results count" hint based on the source task's count.
- Restructuring `## General Steps` from numbered list into prose because the source agent worked through it differently.
- Deleting the `## Output Format` section because the source task happened not to need it.

## When to make no edits at all

It is fine — and sometimes correct — to apply zero edits. If the action trace is perfectly linear, has no errors or re-actions, and the existing skill already covers everything the trace exhibits, the right answer is to call `task_end` with a summary like "Reviewed evidence; no improvement justified — existing skill already covers the workflow cleanly." Adding speculative content would harm the skill.
