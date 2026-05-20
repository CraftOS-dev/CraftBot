> [!IMPORTANT]
> **Note for contributors:** When branching out, create a new branch from the `dev` branch.

# 🚀 Welcome to **CraftBot**! 

You are seeing this probably because you want to contribute to our project, and we welcome you!
To ensure contributor feels welcome, we have this guide to help you get started and ensure your contributions can be efficiently integrated into the project.

## 🌟 Links

- [Discord Community](https://discord.gg/W8jdMKdE)  
- [Issue Tracker](https://github.com/CraftOS-dev/CraftBot/issues)

## 1. 🚀 Ways to Contribute

Here are all the things you to contribute to the community.

- 📝 Submitting bug reports or feature requests
- 💡 Improving documentation
- 🔍 Perform tests and fixing bugs
- 🛠️ Contributing code
- 🌐 Helping other users

## 📫 There are several ways to collaborate with the team and community:

### GitHub Collaboration
- [Open an issue](https://github.com/CraftOS-dev/CraftBot/issues) for bug reports, feature requests, or discussions
- Submit pull requests to contribute code or documentation
- Join ongoing discussions in existing issues and PRs

### Community Channels
- Join our [Discord community](https://discord.gg/W8jdMKdE) for real-time discussions
- Join our voice channel for direct communication.
- Participate in community events (if we have any).
- Get help from other community members

### Direct Contact
- Email: thamyikfoong@craftos.net
- For business inquiries or sensitive matters, please reach out directory via email
- For general questions, prefer public channels like GitHub issues or Discord

For faster responses, consider using our Discord channel where the whole community can help!

## 2. 🛠️ Development Setup

### Fork and Clone

1. Fork the [**CraftBot**](https://github.com/CraftOS-dev/CraftBot) repository
2. Clone your fork:
```shell
git clone https://github.com/<your-github-username>/CraftBot.git
cd CraftBot
```

---

# 📋 Workflow SOPs

Keep it simple. The point is shared rhythm, not bureaucracy.

## 3. 🌿 Branches

- Base off `dev`, never `main` or `staging`.
- Name: `type/short-description` — kebab-case.
  - Types: `feat`, `fix`, `chore`, `refactor`, `docs`, `hotfix`
  - Examples: `feat/discord-role-sync`, `fix/webhook-retry-loop`
- One branch = one focused change. If it grows past ~400 lines or two days of work, split it.
- Delete the branch after merge.

Flow: `dev` → `staging` → `main`. Never push directly to `staging` or `main`.

Create a new branch for your work:
```shell
git checkout -b feat/your-feature-name
```

To help fix a bug:
```shell
git checkout -b fix/bug-name
```

## 4. ✅ Commits

**Format:**
```
<type> <issue number if exists eg: #245>: <short summary in imperative mood>

<optional body — why, not what>
```

- Types: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `style`
- Summary ≤ 72 chars, no period, imperative ("add" not "added").
- Body explains **why** the change was needed if it's not obvious. The diff shows *what*.
- Commit often, but each commit should pass lint/build on its own.

**Good:**
- `fix: prevent duplicate role assignment on rejoin`
- `feat: add /ban-history slash command`

**Bad:**
- `update stuff`
- `WIP`
- `fixed the thing John mentioned`

Before committing, run the linter:
```shell
ruff format .
ruff check
```
Fix any issues, then:
```shell
git add .
git commit -s -m "feat: your descriptive message"
git push origin your-branch-name
```

## 5. 🔀 Pull Requests

**Title:** same format as a commit (`feat: …`, `fix: …`). Keep under ~70 chars.

**Description template:**
```markdown
## What
1-3 bullets on what changed.

## Why
The problem this solves or the goal. Link the issue: Closes #123

## How to test
Steps to verify locally. Include any env vars, seed data, or commands.

## Screenshots / Logs
If UI or behavior changed.
```

**Rules:**
- Open as **Draft** until it's ready for review.
- Keep PRs small — under ~400 lines of diff where possible. Big PRs get stale and miss bugs.
- Self-review your own diff before requesting review. Catch the obvious stuff first.
- At least 1 approval before merge. No self-merging on shared branches.
- Squash-merge into `dev` (keeps history clean). Merge-commit into `staging`/`main`.
- Resolve all conversations before merging.
- If CI is red, fix it — don't merge around it.

**Open a PR:**
- Go to the [**CraftBot** repository](https://github.com/CraftOS-dev/CraftBot)
- Click "Compare & Pull Request" and open a PR against `dev`
- Fill in the PR template with details about your changes

## 6. 🐛 Issues

**Bug template:**
```markdown
**What happened:**
**What I expected:**
**Steps to reproduce:**
1.
2.
**Environment:** (browser, OS, server, version/commit)
**Logs / screenshots:**
```

**Feature template:**
```markdown
**Problem:** What user pain are we solving?
**Proposal:** What should it do?
**Out of scope:** What we're *not* doing.
**Acceptance:** How we know it's done.
```

**Labels (use at least one):**
- `bug`, `feature`, `chore`, `docs`
- Priority: `p0` (drop everything), `p1` (this sprint), `p2` (soon), `p3` (whenever)
- `blocked`, `needs-info`, `good-first-issue`

**Rules:**
- Search before opening — avoid duplicates.
- One problem per issue. Split if it's two things.
- Assign yourself when you start working on it.
- Close with the PR (use `Closes #123` in the PR body).

---

## 7. 🤝 Community Guidelines

- Be respectful and inclusive
- Help others learn and grow
- Provide constructive feedback
- Ask questions when unsure
- Enjoy building agents

## 8. 📫 To Get Help

- Open an [issue](https://github.com/CraftOS-dev/CraftBot)
- Join our Discord community

Thank you for contributing to **CraftBot**! 🌟
