# Contributing

CraftBot is open source and welcomes contributions: bug reports, documentation fixes, tests, and code. This page covers how to set up a development copy of the project, the branch and pull request workflow the maintainers use, and the lint and smoke checks your change has to pass before it merges. It follows the repository's `CONTRIBUTING.md`. For the structure of the code you are changing, read [Architecture](architecture.md).

## Development setup

1. Fork [CraftOS-dev/CraftBot](https://github.com/CraftOS-dev/CraftBot) on GitHub.
2. Clone your fork and enter the directory:

    ```shell
    git clone https://github.com/<your-github-username>/CraftBot.git
    cd CraftBot
    ```

3. Install dependencies:

    ```shell
    python install.py
    ```

    `install.py` installs the core Python dependencies with pip. Pass `--conda` to create and use an isolated conda environment instead, and add `--mamba` to solve that environment with mamba for a faster install. Configuration is read from `app/config/settings.json`, not from a `.env` file.

4. Run CraftBot from source:

    ```shell
    python run.py --cli
    ```

    `python run.py --cli` starts CraftBot as a terminal chat, which is the lightest loop for developing and testing actions. `python run.py` starts the browser interface instead. Both run in the foreground and stop when you close the terminal. On first launch you pick a model provider and add an API key; see the [Quickstart](../start/quickstart.md) for the walkthrough.

## Branch and PR workflow

Base every branch on `dev`. Do not branch from `main` or `staging`. The project promotes changes in one direction, `dev` to `staging` to `main`, and you never push directly to `staging` or `main`.

Create your branch off `dev`:

```shell
git checkout -b feat/your-feature-name
```

Name it `type/short-description` in kebab-case. The types are `feat`, `fix`, `chore`, `refactor`, `docs`, and `hotfix` (for example `feat/discord-role-sync` or `fix/webhook-retry-loop`). Keep one branch to one focused change. If it grows past roughly 400 lines or two days of work, split it, and delete the branch after it merges.

Commit messages follow the format `<type> <#issue if one exists>: <summary>`, with the summary in imperative mood ("add", not "added") and 72 characters or fewer. Sign off each commit and push to your fork:

```shell
git add .
git commit -s -m "feat: add discord role sync"
git push origin feat/your-feature-name
```

Every commit should pass lint and byte-compile on its own, so run the checks in [Running tests and lint](#running-tests-and-lint) before you commit.

Open the pull request against `dev`, and fill in the What / Why / How to test template. The project's rules for a PR:

- Open it as a **Draft** until it is ready for review.
- Keep the diff under roughly 400 lines where you can. Large PRs go stale and hide bugs.
- Self-review your own diff before you request review.
- A PR needs at least one approval before it merges, and no self-merging on shared branches.
- PRs are squash-merged into `dev` to keep history clean.
- Resolve every review conversation before merging. If CI is red, fix it rather than merging around it.

## Running tests and lint

CraftBot uses [ruff](https://docs.astral.sh/ruff/) for both formatting and linting, plus a byte-compile smoke check that catches broken imports and syntax errors ruff misses. Run both locally before you push.

Install ruff once:

```shell
pip install ruff
```

Format and lint the tree:

```shell
ruff format .        # auto-format your code
ruff check .         # lint
ruff check . --fix   # apply the fixes ruff can make automatically
```

Run the smoke check:

```shell
python -m compileall -q app agent_core agents decorators skills
```

The repository ships a `.ruff.toml` that excludes `app/data/living_ui_template/` (Jinja templates, not valid Python) and ignores E402 for a few files where import ordering is deliberate. Prefer moving an import over adding a new ignore entry, and explain the ignore in your commit if you genuinely need one.

These same checks run in CI. The `.github/workflows/staging-lint.yml` workflow runs `ruff format --check .`, `ruff check .`, and the `compileall` smoke check automatically when changes reach the `staging` branch. That workflow does not run on your `dev` pull request, so running the commands above locally is what keeps your change green as it is promoted toward `staging` and `main`.

## Project layout

The code splits into a reusable `agent_core` engine, the `app` runtime that wires it to interfaces and integrations, `agents` for agent bundles, `decorators`, and `skills`. For the full annotated directory tree and the data-flow walkthroughs, see [Architecture](architecture.md).

## Getting help

- **Discord.** Join the [community server](https://discord.gg/ZN9YHc37HG) for real-time discussion and questions. This is usually the fastest way to get an answer.
- **Issue tracker.** Report bugs or propose features on the [issue tracker](https://github.com/CraftOS-dev/CraftBot/issues). Search before opening to avoid duplicates, keep one problem per issue, and reference the issue from your PR with `Closes #123`.

## Next

- New to the codebase? Read [Architecture](architecture.md) for the runtime map.
- Adding a capability? Start with a [Custom action](custom-action.md) or a [CraftBot skill](skills/craftbot-skill.md).
- Back to the section overview? See [Develop](index.md).
