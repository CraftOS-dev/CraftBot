# GitHub

The GitHub integration connects the agent to your GitHub account with a personal access token. The agent can work with issues, pull requests, repositories, files, releases, and CI workflows, and a polling listener turns GitHub notifications into events the agent reacts to.

## Requirements

| Requirement | Details |
|---|---|
| GitHub account | The agent acts as this account for every API call |
| Personal access token (classic) | Generate at [github.com/settings/tokens](https://github.com/settings/tokens) with the `repo` scope |
| `workflow` scope | Optional — needed only for the workflow actions (trigger, cancel, re-run) |
| Network access | CraftBot calls `api.github.com` over HTTPS |

## Setup

1. Open [github.com/settings/tokens](https://github.com/settings/tokens) and click **Generate new token → Generate new token (classic)**.
2. Select the `repo` scope. Add `workflow` if you want the agent to trigger or manage GitHub Actions runs.
3. Copy the `ghp_...` token before leaving the page. GitHub shows it once.
4. In CraftBot, open **Settings → Integrations → GitHub**, paste the token into **Personal Access Token**, and connect. From chat, `/github login <personal_access_token>` does the same thing.
5. Verify with `/github status`. It shows the connected username plus any watch tag and watched repos.

`/github logout` removes the credential and stops the listener.

## How it connects

**Authentication.** Every API call sends your token as a bearer token to `api.github.com`. At login CraftBot validates the token against your user profile and stores the token and username in the credential store as `github.json`. See [Credentials](credentials.md).

**Polling listener.** While connected, CraftBot polls your GitHub notifications every 15 seconds. The poll requests unread notifications for threads you participate in: mentions, assignments, review requests, and replies on issues or PRs you are involved with. Unchanged polls return early via `If-Modified-Since`, and each notification is dispatched exactly once. After a poll error the listener waits 30 seconds and retries.

**Watch configuration.** Two settings filter what reaches the agent. If **watch repos** is set, notifications from repositories outside the list are dropped. If a **watch tag** is set (for example `@craftbot`), only notifications whose latest comment contains the tag dispatch, and the text after the tag becomes the instruction the agent executes. With no tag set, every participating notification dispatches with its reason and latest comment. See [Configuration](#configuration).

**Replies.** When the agent responds to a GitHub event, it posts a comment on the issue or pull request. Issues and PRs are always addressed as `owner/repo#number` (for example `acme/web#42`).

## What the agent can do

The 107 GitHub actions are grouped into action sets (`github_issues`, `github_pulls`, `github_repos`, and so on) that the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Issues

| Action | Purpose |
|---|---|
| `list_github_issues` | List issues for a repository |
| `get_github_issue` | Get details of a specific issue or PR by number |
| `create_github_issue` | Create a new issue |
| `update_github_issue` | Update issue fields (title, body, state, labels, assignees, milestone) |
| `close_github_issue` | Close an issue |
| `lock_github_issue` | Lock conversation on an issue |
| `unlock_github_issue` | Unlock a previously locked issue |
| `list_github_issue_events` | List timeline events (labeled, assigned, closed) for an issue or PR |

### Issue and PR comments

| Action | Purpose |
|---|---|
| `add_github_comment` | Add a comment to an issue or PR |
| `list_github_issue_comments` | List comments on an issue or PR |
| `update_github_comment` | Edit the body of an existing comment |
| `delete_github_comment` | Delete a comment |

### Labels, assignees, and milestones

| Action | Purpose |
|---|---|
| `add_github_labels` | Add labels to an issue or PR without removing existing ones |
| `set_github_labels` | Replace all labels on an issue or PR with the given set |
| `remove_github_label` | Remove a single label from an issue or PR |
| `add_github_assignees` | Add assignees to an issue or PR |
| `remove_github_assignees` | Remove assignees from an issue or PR |
| `list_github_repo_labels` | List all labels defined in a repository |
| `create_github_label` | Define a new label in a repository |
| `update_github_label` | Rename or recolor an existing label |
| `delete_github_label` | Delete a label from a repository |
| `list_github_milestones` | List milestones in a repository |
| `create_github_milestone` | Create a milestone |
| `update_github_milestone` | Edit a milestone (title, state, description, due date) |
| `delete_github_milestone` | Delete a milestone |

### Pull requests

| Action | Purpose |
|---|---|
| `list_github_prs` | List pull requests for a repository |
| `get_github_pr` | Get details of a pull request (merge status, refs, diff stats) |
| `create_github_pr` | Open a pull request |
| `update_github_pr` | Update a pull request (title, body, state, base branch) |
| `merge_github_pr` | Merge a pull request (merge, squash, or rebase) |
| `list_github_pr_files` | List files changed in a pull request |
| `list_github_pr_commits` | List commits on a pull request |
| `request_github_pr_reviewers` | Request reviews from users or teams |
| `remove_github_pr_reviewers` | Cancel a pending review request |
| `create_github_pr_review` | Create a pending or submitted review (approve, request changes, comment) |
| `list_github_pr_reviews` | List reviews on a pull request |
| `submit_github_pr_review` | Submit a pending review with an event |
| `list_github_pr_review_comments` | List inline (file-line) review comments |
| `create_github_pr_review_comment` | Create an inline comment on a specific file line |

### Repositories

| Action | Purpose |
|---|---|
| `list_github_repos` | List repositories for the connected user |
| `get_github_repo` | Get repository metadata (default branch, description, stars) |
| `create_github_repo` | Create a new repository |
| `update_github_repo` | Update repository settings (name, visibility, default branch, archive) |
| `delete_github_repo` | Delete a repository — irreversible, requires admin scope |
| `fork_github_repo` | Fork a repository under your account or an organization |
| `list_github_forks` | List forks of a repository |
| `list_github_collaborators` | List collaborators and their permissions |
| `add_github_collaborator` | Invite a user as a collaborator |
| `remove_github_collaborator` | Remove a collaborator |
| `get_github_readme` | Get the README of a repository |
| `list_github_topics` | Get the topic tags on a repository |
| `set_github_topics` | Replace the topic tags on a repository |

### Files, branches, and commits

| Action | Purpose |
|---|---|
| `get_github_file` | Read a file by path (returns content and its `sha`) |
| `create_or_update_github_file` | Create or update a single file via the API, no clone needed |
| `delete_github_file` | Delete a file (requires the current `sha`) |
| `list_github_branches` | List branches in a repository |
| `get_github_branch` | Get one branch (name, SHA, protection state) |
| `create_github_branch` | Create a branch pointing at an existing commit SHA |
| `delete_github_branch` | Delete a branch |
| `list_github_commits` | List commits, optionally filtered by path or author |
| `get_github_commit` | Get one commit with changed files, patches, and stats |
| `compare_github_commits` | Compare two commits, branches, or tags |

### Releases and tags

| Action | Purpose |
|---|---|
| `list_github_releases` | List releases of a repository |
| `get_github_release` | Get a release by ID, by tag, or the latest |
| `create_github_release` | Create a release, draft, or prerelease |
| `update_github_release` | Edit an existing release |
| `delete_github_release` | Delete a release (the underlying tag stays) |
| `list_github_tags` | List tags in a repository |

### Reactions

| Action | Purpose |
|---|---|
| `add_github_issue_reaction` | React to an issue (+1, heart, rocket, and so on) |
| `add_github_comment_reaction` | React to an issue or PR comment |
| `add_github_pr_review_comment_reaction` | React to an inline review comment |
| `delete_github_issue_reaction` | Remove a reaction from an issue |
| `delete_github_comment_reaction` | Remove a reaction from a comment |
| `delete_github_pr_review_comment_reaction` | Remove a reaction from an inline review comment |

### Search

| Action | Purpose |
|---|---|
| `search_github_issues` | Search issues and PRs with GitHub search syntax |
| `search_github_repos` | Search repositories (for example `language:python stars:>1000`) |
| `search_github_code` | Search code across repositories |
| `search_github_users` | Search GitHub users |
| `search_github_commits` | Search commit messages |

### Users, follows, and stars

| Action | Purpose |
|---|---|
| `get_github_authenticated_user` | Get the connected user's profile |
| `get_github_user` | Get any user's public profile |
| `list_github_user_repos` | List a user's public repositories |
| `follow_github_user` | Follow a user |
| `unfollow_github_user` | Unfollow a user |
| `list_github_followers` | List your followers |
| `list_github_following` | List users you follow |
| `star_github_repo` | Star a repository |
| `unstar_github_repo` | Unstar a repository |
| `list_github_starred` | List repositories you have starred |
| `list_github_stargazers` | List users who starred a repository |

### Gists

| Action | Purpose |
|---|---|
| `list_github_gists` | List your gists |
| `get_github_gist` | Get a gist with full file contents |
| `create_github_gist` | Create a gist from a filename-to-content mapping |
| `update_github_gist` | Update a gist's description or files |
| `delete_github_gist` | Delete a gist |

### Notifications

| Action | Purpose |
|---|---|
| `list_github_notifications` | List your notifications (unread by default) |
| `mark_github_notifications_read` | Mark all notifications as read |
| `mark_github_notification_read` | Mark a single notification thread as read |

### Workflows

| Action | Purpose |
|---|---|
| `list_github_workflows` | List CI workflows defined in a repository |
| `list_github_workflow_runs` | List workflow runs, filtered by workflow, branch, or status |
| `get_github_workflow_run` | Get details of a single run by ID |
| `trigger_github_workflow` | Trigger a `workflow_dispatch` event |
| `cancel_github_workflow_run` | Cancel an in-progress run |
| `rerun_github_workflow_run` | Re-run a completed run |
| `get_github_workflow_run_logs_url` | Get the download URL for a run's logs |

### Listener settings

| Action | Purpose |
|---|---|
| `set_github_watch_tag` | Set the mention tag the listener requires in comments |
| `set_github_watch_repos` | Restrict the listener to specific repositories |

## Example requests

```
List the open issues in acme/web and summarize the three oldest.
```

```
Create an issue in acme/web titled "Login page 500s on Safari" and label it bug.
```

```
Review PR acme/web#128 and leave inline comments on anything that looks wrong.
```

```
Merge acme/web#131 with a squash merge.
```

```
Re-run the latest failed workflow run in acme/web and tell me the result.
```

```
Only react to GitHub events from acme/web, and only when someone tags @craftbot.
```

## Configuration

Both settings live in **Settings → Integrations → GitHub** and are stored in `github_config.json` next to the credential. The listener re-reads them on every poll, so changes apply without reconnecting. You can also change them from chat, which uses the `set_github_watch_tag` and `set_github_watch_repos` actions.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Watch tag (`watch_tag`) | text, e.g. `@craftbot` | empty | Only comments containing this tag trigger events. The text after the tag becomes the instruction. Empty = react to all participating notifications |
| Watched repos (`watch_repos`) | list of `owner/repo` | empty | Only events from these repositories trigger. Empty = every repo the token can access |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Bad credentials" or 401 | Token expired or revoked | Generate a new token on GitHub and run `/github login <new_token>` |
| 403, or 404 on a repo you can open in the browser | Token lacks a scope | Regenerate the token with `repo` (and `workflow` if needed). Retrying the same call does not help |
| Agent stops reacting to repo events | `watch_tag` or `watch_repos` is filtering them out | Check both settings in **Settings → Integrations → GitHub** |
| Rate limit errors | GitHub allows 5000 authenticated requests per hour | Wait for the limit window to reset, or batch the work |
| `trigger_github_workflow` fails | The workflow YAML has no `workflow_dispatch` trigger, or the token lacks `workflow` scope | Add the trigger to the workflow, or regenerate the token |
| Updating a file fails with a `sha` error | The file already exists and the current `sha` was not supplied | The agent reads the file with `get_github_file` first to obtain the `sha` |

## Next

- [Jira](jira.md): issue tracking on Atlassian with the same watch-tag listener pattern
- [Credentials](credentials.md): where tokens are stored and how `/cred status` reports them
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
