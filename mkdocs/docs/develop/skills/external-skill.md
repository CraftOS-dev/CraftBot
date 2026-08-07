# External skills

An external skill is one you did not write for this CraftBot install. It might come from another CraftBot project, a shared folder, a profile bundle a teammate sent you, or an agent bundle that carries its own skills. Because a skill is just a folder with a `SKILL.md`, adopting one is mostly a matter of getting that folder into `skills/` and enabling it. This page covers where external skills come from, how to install and enable them, why skills from other ecosystems load without changes, and how to vet one before you turn it on.

## What counts as an external skill

Any skill whose folder was authored somewhere other than your own `skills/` directory is external. Three sources are common.

- **Copied folders.** A `skills/<name>/` folder you took from another project or a shared drive.
- **Profile bundles.** A `.craftbot` profile bundle packages an agent's enabled skills alongside its personality files. When you import a bundle, the importer copies each skill folder from the bundle into your `skills/` directory and enables it. Skills whose frontmatter sets `user-invocable: false` are treated as CraftBot-essential and are force-enabled in every import mode, so an import never strips the agent of a workflow it depends on.
- **Agent bundles.** An agent bundle can carry its own skills under `agent_bundle/agents/<slug>/skills/`. Those skills resolve for that agent first, and fall back to the shared repo `skills/` directory when the agent-owned folder does not define them.

In every case the unit is the same: a folder with a `SKILL.md` inside.

## Installing an external skill

There are two paths, depending on what you were handed.

To install a loose skill folder, copy it into `skills/`:

```bash
cp -r ~/Downloads/awesome-skill skills/awesome-skill
```

Then rescan with `/skill reload` (or reload from **Settings → Skills**), which discovers the folder without a restart. New skills arrive dormant unless your `enabled_skills` whitelist is empty, so enable the one you want:

```
/skill enable awesome-skill
```

`/skill install <path-or-git-url>` does the copy and reload for you from a local path or a git URL. To adopt a whole profile bundle instead of a single skill, import the `.craftbot` file from the settings screen and pick Replace or Overwrite. The importer handles the copy and the enabling for every skill in the bundle. For the enable rule and the full `/skill` surface, see [Installing and enabling](craftbot-skill.md#installing-and-enabling).

### Name conflicts

A skill is keyed by its `name`, which is normalized to lowercase with underscores turned into hyphens. So `My_Skill` and `my-skill` resolve to the same id. If two folders normalize to the same name, only one survives discovery and the other is shadowed. Give each external skill a distinct folder name and `name` before you enable it, so an import does not silently overwrite a skill you already rely on.

## Compatibility and format

CraftBot loads any folder that contains a `SKILL.md`. It does not require the frontmatter that CraftBot's own fields use. When a `SKILL.md` has no `---` block, the loader takes the whole file as the instruction body, derives `name` from the folder, and derives `description` from the first non-heading paragraph (a leading blockquote marker is stripped). This is exactly the shape many skills from other ecosystems take: a title, a one-line tagline, and a body of instructions with no metadata block.

The practical result is that a minimal, hand-written `SKILL.md` works as-is:

```markdown
# Release Notes

> Turn a list of merged PRs into grouped release notes.

Read the merged pull requests for the named repo, group them by type,
and write the result as markdown.
```

CraftBot-specific behavior only kicks in when the frontmatter is present. An external skill that omits `action-sets` still runs, but it will not auto-include any action sets, so make sure the task has the actions it needs or add an `action-sets` block yourself. An external skill that omits `user-invocable` defaults to invocable, so it appears as a slash command once enabled. Adapting an external skill to CraftBot is usually a matter of adding a frontmatter block with a sharp `description` and the right `action-sets`, as described in [Write a CraftBot skill](craftbot-skill.md#frontmatter-fields).

## Vetting before enabling

A skill is instructions, not sandboxed code, but those instructions can direct the agent to run actions on your behalf: shell commands, file writes, network calls, and integration actions. Treat an external skill the way you would treat a script from an unknown author, and review it before you enable it.

- **Read the `SKILL.md` body.** Look for steps that run shell commands, delete or move files, send data to an external endpoint, or touch credentials. Confirm they match what the skill claims to do.
- **Check the supporting files.** Open any `scripts/` or bundled helpers the body tells the agent to run. Those execute with your privileges.
- **Check `action-sets` and `allowed-tools`.** A skill that declares far broader action sets than its stated purpose needs is worth a second look.
- **Prefer a pinned version.** When you pull a skill from git, take a specific commit or tag rather than a moving branch, so the instructions cannot change under you.

The bundled `skill-vetter` skill automates a first pass of this review. Enable it and point it at a skill folder to get a structured report on what actions the skill would run and where the risks are, before you enable the skill itself. It does not replace reading the file, but it surfaces the parts worth reading first.

## Next

- [Write a CraftBot skill](craftbot-skill.md): the `SKILL.md` format you adapt an external skill into.
- [Skills concept page](../../core/concepts/skills.md): how an enabled skill is selected and injected at runtime.
- [Skills overview](index.md): the three authoring routes at a glance.
