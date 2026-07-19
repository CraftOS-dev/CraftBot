# Automated GitHub PR reviews

By the end of this guide, CraftBot reviews pull requests in a repository you choose and posts its findings as a comment on the PR. You can run it two ways: the agent reacts the moment someone tags it on a pull request, or it sweeps the repository on a schedule (for example every morning) and reviews any open PR it has not looked at yet. Both paths use the same GitHub actions and leave a human in control of merging.

This guide assumes a working CraftBot that you can chat with. If you have not installed it or run a first task, start with the [Quickstart](../start/quickstart.md).

## What you need

| Requirement | How to get it |
|---|---|
| A working CraftBot install | [Quickstart](../start/quickstart.md) |
| CraftBot in service mode | [Service mode](../start/service-mode.md), so the GitHub listener and any schedules keep running while you are away |
| A connected model provider | [Quickstart Step 2](../start/quickstart.md#step-2-connect-a-model-provider) |
| A GitHub personal access token with the `repo` scope | [GitHub integration](../integrations/github.md) |

Service mode matters here. The GitHub listener polls only while CraftBot runs, and a scheduled sweep fires only while the process is alive. If you run CraftBot in the foreground and close the terminal, neither approach works. See [Service mode](../start/service-mode.md).

## Step 1: connect GitHub

Generate a classic personal access token on GitHub with the `repo` scope, then connect it. The [GitHub integration](../integrations/github.md) page has the full walkthrough; the short version is:

1. Open [github.com/settings/tokens](https://github.com/settings/tokens), create a classic token, and select the `repo` scope. Copy the `ghp_...` value before you leave the page.
2. In chat, connect it:

```
/github login ghp_your_token_here
```

3. Confirm the connection:

```
/github status
```

`/github status` reports the connected username along with the current watch tag and watched repositories. The connected account is who the agent acts as for every call, so its review comments appear under that username. The `repo` scope is what lets the agent read pull request diffs and post review comments. Without it, reads and comments fail. For token storage and how `/cred status` reports it, see [Credentials](../integrations/credentials.md).

## Step 2: choose event-driven or scheduled

There are two ways to get the agent reviewing PRs, and they suit different situations.

| Approach | How the agent is triggered | Best when |
|---|---|---|
| Event-driven | The GitHub polling listener notices a notification for the connected account (a mention, a review request, or a reply) and dispatches it as a task. See [Triggers](../core/concepts/triggers.md). | You want a review the moment a teammate tags the agent or requests it as a reviewer on a specific PR. |
| Scheduled sweep | A [scheduled task](../core/concepts/scheduling.md) fires at a fixed time and the agent lists open PRs itself. | You want every open PR reviewed on a regular cadence without anyone having to tag the agent. |

The distinction comes from how the listener works. CraftBot polls your GitHub notifications every 15 seconds, and GitHub only produces a notification when the connected account is involved: a mention, an assignment, a review request, or a reply on a thread it participates in. The listener does not see every new PR in a repository on its own. So the event-driven path fits "review this PR, you were asked", and the scheduled path fits "review whatever is open right now". Many teams run both.

## Step 3: configure the watcher or the schedule

Pick the subsection that matches your choice from Step 2. You can set up both.

### Event-driven: configure the watcher

Two settings control what reaches the agent. Restrict the listener to the repository you care about, and set a tag that team members include when they want a review. From chat:

```
Only watch the acme/web repository on GitHub, and only react when a comment includes @craftbot.
```

The agent sets `watch_repos` to `acme/web` and `watch_tag` to `@craftbot`, using the `set_github_watch_repos` and `set_github_watch_tag` actions. You can also set both under **Settings → Integrations → GitHub**. The exact setting names and effects are:

| Setting | Value here | Effect |
|---|---|---|
| `watch_repos` | `acme/web` | Notifications from any other repository are dropped |
| `watch_tag` | `@craftbot` | Only comments containing the tag dispatch, and the text after the tag becomes the instruction the agent runs |

Now a teammate opens a pull request and leaves a comment that mentions the connected account:

```
@craftbot please review this PR
```

Because the mention notifies the connected account, the poll picks it up within about 15 seconds, and because the comment contains the watch tag, the listener dispatches "please review this PR" as a task scoped to that pull request. Requesting the connected account as a reviewer works the same way, since a review request also produces a notification.

The watch settings live in `github_config.json` next to the credential, and the listener re-reads them on every poll, so changes apply without reconnecting. For how listener events become tasks, see [Triggers](../core/concepts/triggers.md).

### Scheduled: set the sweep

Ask for a recurring review in plain language:

```
Every day at 9am, review any open pull requests in acme/web that I have not
reviewed yet, and post your review as a comment on each one.
```

The agent creates a schedule with the `schedule_task` action and the expression `every day at 9am`, storing the instruction so it runs unattended each morning. When it fires, the agent lists the open PRs itself rather than waiting for a notification, which is why the sweep catches PRs nobody tagged it on.

Verify and manage the schedule from chat:

```
What do you have scheduled?
```

```
Pause the daily PR review.
```

These map to the `scheduled_task_list` and `schedule_task_toggle` actions. Because a real code review is multi-step work, set the schedule to run as a complex task so it plans and checks its work. Schedule expressions, one-time versus recurring runs, and what happens after downtime are all covered in [Scheduling](../core/concepts/scheduling.md).

## Step 4: what the review does

However the task starts, the agent works through the pull request with the GitHub pull request actions, which live in the `github_pulls` action set and load when the task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md). A typical pass looks like this:

1. Identify the target. On the event-driven path the PR is the one that was tagged. On the scheduled path the agent calls `list_github_prs` to list open pull requests in the watched repository.
2. Read the change. `get_github_pr` returns the PR details and diff stats, and `list_github_pr_files` lists the changed files so the agent can read what actually changed.
3. Form findings. The agent reads the diff and notes correctness problems, missing tests, unclear names, and anything risky.
4. Post the review. For a plain summary comment, the agent uses `add_github_comment`. For a formal review with a `COMMENT` event, it uses `create_github_pr_review`, and for a note anchored to a specific file and line it uses `create_github_pr_review_comment`.

The full list of pull request actions is on the [GitHub integration](../integrations/github.md#pull-requests) page. To make reviews more consistent, pair the task with a code-review skill so the agent follows the same checklist every time. Attach one by name when you ask, or enable it so the automatic selector can pick it. See [Skills](../core/concepts/skills.md).

A one-off request that exercises the same actions, useful for testing before you automate:

```
Review PR acme/web#128 and post your findings as a comment.
```

## Step 5: scope and safety

A reviewer that can also merge is a reviewer you have to supervise closely. Keep the setup narrow and read-mostly.

- Restrict the repositories. Set `watch_repos` to the exact repositories the agent should touch, so a stray mention in an unrelated repo never starts a review. On the scheduled path, name the repository in the instruction.
- Review only. Ask the agent to post comments and reviews, not to approve or merge. Do not instruct it to auto-approve. A review that only comments cannot merge code on its own, which keeps the decision with a person.
- Keep a human in the loop. Treat the agent's review as a first pass. A maintainer reads it, decides what to act on, and merges. The agent surfaces problems; you approve.
- Use the identifier convention. Issues and pull requests are always addressed as `owner/repo#number`, for example `acme/web#128`. Use that form in requests so the agent targets the right PR.

If you ever do want the agent to merge, make it an explicit, separate request for one PR at a time (for example "merge acme/web#131 with a squash merge") rather than part of the standing review instruction.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| The agent never reacts to a tagged PR | The watcher is not configured, or CraftBot is not in service mode | Run `/github status` to check `watch_repos` and `watch_tag`; confirm the process is running with `python craftbot.py status` |
| The agent reacts but cannot post its review | The token is missing the `repo` scope | Regenerate a classic token with `repo` and run `/github login <new_token>`; retrying the same call does not help |
| A review appears on the wrong repository | `watch_repos` is empty or too broad | Set `watch_repos` to the exact `owner/repo` in **Settings → Integrations → GitHub** |
| The scheduled sweep never fires | CraftBot was offline at 9am, or the schedule is paused | Recurring schedules are not back-filled; keep CraftBot in [service mode](../start/service-mode.md) and check `scheduled_task_list` |
| Tagged comments are ignored | The comment does not contain the watch tag, or the account was not notified | Include the exact `watch_tag` text, or request the connected account as a reviewer |
| "Bad credentials" errors | The token expired or was revoked | Generate a new token and run `/github login <new_token>` |

## Next

- [GitHub integration](../integrations/github.md): every GitHub action, the full watch configuration, and setup detail.
- [Scheduling](../core/concepts/scheduling.md): schedule expressions and how to manage recurring tasks.
- [Triggers](../core/concepts/triggers.md): how listener events and scheduled fires become tasks.
- [Write your first skill](first-skill.md): package a review checklist the agent follows every time.
