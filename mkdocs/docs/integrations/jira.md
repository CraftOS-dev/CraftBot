# Jira

The Jira integration connects the agent to your Jira Cloud site with your account email and an API token. The agent can work with issues, comments, worklogs, attachments, issue links, projects, boards, sprints, and epics, and a polling listener turns issue updates into events the agent reacts to.

## Requirements

| Requirement | Details |
|---|---|
| Jira Cloud site | Your site host, for example `mycompany.atlassian.net` |
| Atlassian account email | The address you log into Jira with. The agent acts as this account for every API call |
| API token | Create one at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |
| Project permissions | The account needs Browse Projects on any project the agent reads, and edit rights for actions that change issues |
| Network access | CraftBot calls your site over HTTPS at `https://<domain>/rest/api/3` |

## Setup

1. Open [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) and click **Create API token**.
2. Label the token (for example `CraftBot`) and copy the value. Atlassian shows it once.
3. Note your Jira site host, the part before `.atlassian.net` in your Jira URL.
4. In CraftBot, open **Settings → Integrations → Jira**, fill in **Jira Domain**, **Email**, and **API Token**, and connect. From chat, `/jira login <domain> <email> <api_token>` does the same thing, for example `/jira login mycompany.atlassian.net you@example.com <api_token>`.
5. Verify with `/jira status`. It shows the connected account plus any watch tag and watched labels.

`/jira logout` removes the credential and stops the listener.

## How it connects

**Authentication.** Every API call sends your email and API token as HTTP Basic authentication to your site at `https://<domain>/rest/api/3`. At login CraftBot validates the credentials against your Jira profile (`/myself`), falling back from API version 3 to 2 if needed, and stores the domain, email, and token in the credential store as `jira.json`. See [Credentials](credentials.md).

**Polling listener.** While connected, CraftBot polls your Jira site every 10 seconds. Each poll runs a JQL search for issues updated since the last poll (`updated >= <last poll time>`) ordered oldest first, and dispatches each new issue version once. Issues are de-duplicated by key and update timestamp. After a poll error the listener waits 15 seconds and retries.

**Watch configuration.** Two settings filter what reaches the agent. If **watch labels** is set, the poll adds a `labels = ...` clause to the JQL, so only issues carrying at least one watched label are considered. If a **watch tag** is set (for example `@craftbot`), only issues whose latest comment contains the tag dispatch, and the text after the tag becomes the instruction the agent executes. With no tag set, every matching issue update dispatches with its summary, status, and latest comment. See [Configuration](#configuration).

**Identifiers.** Issues are addressed by key, for example `PROJ-123`, not a numeric ID. Assignees and watchers are Atlassian account IDs, so the agent resolves a name to an account ID with `search_jira_users` before assigning. When the agent responds to an issue event, it posts a comment on that issue.

## What the agent can do

The 61 Jira actions are grouped into action sets (`jira_issues`, `jira_comments`, `jira_sprints`, and so on) that the agent loads as a task needs them. See [Actions and action sets](../core/concepts/actions-and-action-sets.md).

### Issues

| Action | Purpose |
|---|---|
| `search_jira_issues` | Search issues with JQL, returning lean fields by default |
| `get_jira_issue` | Get one issue by key, lean fields by default |
| `create_jira_issue` | Create a new issue in a project |
| `update_jira_issue` | Update fields (summary, priority, labels) on an existing issue |
| `delete_jira_issue` | Delete an issue, optionally cascading to subtasks |
| `get_jira_transitions` | List the status transitions available for an issue |
| `transition_jira_issue` | Move an issue to a new status by transition ID |
| `assign_jira_issue` | Assign an issue to a user by account ID |
| `add_jira_labels` | Add labels to an issue without removing existing ones |
| `remove_jira_labels` | Remove labels from an issue |
| `get_jira_issue_watchers` | List the watchers on an issue |
| `add_jira_issue_watcher` | Add a user as a watcher on an issue |
| `remove_jira_issue_watcher` | Remove a watcher from an issue |

### Comments

| Action | Purpose |
|---|---|
| `add_jira_comment` | Add a comment to an issue |
| `get_jira_comments` | Get comments on an issue |
| `update_jira_comment` | Edit the body of an existing comment |
| `delete_jira_comment` | Delete a comment from an issue |

### Attachments

| Action | Purpose |
|---|---|
| `add_jira_attachment` | Upload a local file as an attachment on an issue |
| `get_jira_attachment` | Get metadata for a specific attachment by ID |
| `delete_jira_attachment` | Delete an attachment by ID |
| `download_jira_attachment` | Download an attachment's bytes to a local file path |

### Worklogs

| Action | Purpose |
|---|---|
| `add_jira_worklog` | Log time spent on an issue |
| `get_jira_worklogs` | Get the worklog entries for an issue |
| `update_jira_worklog` | Edit an existing worklog entry |
| `delete_jira_worklog` | Delete a worklog entry |

### Issue links

| Action | Purpose |
|---|---|
| `create_jira_issue_link` | Link two issues together (for example Blocks, Relates) |
| `get_jira_issue_link` | Get a specific issue link by ID |
| `delete_jira_issue_link` | Delete a specific issue link |
| `list_jira_issue_link_types` | List the available issue link types |

### Projects and metadata

| Action | Purpose |
|---|---|
| `list_jira_projects` | List accessible projects |
| `get_jira_project` | Get information about a single project |
| `search_jira_users` | Search users by name or email to find an account ID |
| `list_jira_priorities` | List available issue priorities |
| `list_jira_issue_types` | List available issue types |
| `list_jira_versions` | List versions (fix versions) for a project |
| `create_jira_version` | Create a new version for a project |
| `update_jira_version` | Update a version, for example mark it released or archived |
| `delete_jira_version` | Delete a version |
| `list_jira_components` | List components for a project |
| `create_jira_component` | Create a new component within a project |
| `delete_jira_component` | Delete a project component |
| `list_jira_project_statuses` | List the status workflow for a project, grouped by issue type |

### Boards, sprints, and epics

| Action | Purpose |
|---|---|
| `list_jira_boards` | List Agile boards, optionally filtered by project or type |
| `get_jira_board` | Get details of a specific board |
| `get_jira_board_issues` | List issues currently on a board |
| `get_jira_board_sprints` | List sprints on a board, optionally filtered by state |
| `get_jira_board_backlog` | Get the backlog issues for a board |
| `get_jira_sprint` | Get details of a specific sprint |
| `get_jira_sprint_issues` | List issues in a sprint |
| `create_jira_sprint` | Create a new sprint on a board |
| `update_jira_sprint` | Update a sprint's name, state, goal, or dates |
| `delete_jira_sprint` | Delete a sprint |
| `move_issues_to_jira_sprint` | Move one or more issues into a sprint |
| `move_issues_to_jira_backlog` | Move issues back to the backlog |
| `get_jira_epic` | Get details of an epic |
| `get_jira_epic_issues` | List the child issues of an epic |
| `move_issues_to_jira_epic` | Move issues to an epic, or unlink them with `none` |

### Listener settings

| Action | Purpose |
|---|---|
| `set_jira_watch_tag` | Set the mention tag the listener requires in comments |
| `get_jira_watch_tag` | Get the current watch tag |
| `set_jira_watch_labels` | Set which labels the listener watches for |
| `get_jira_watch_labels` | Get the current label filter |

## Example requests

```
List the open bugs in project PROJ assigned to me and summarize the three oldest.
```

```
Create a Task in PROJ titled "Login page 500s on Safari", label it bug, and set priority High.
```

```
Move PROJ-142 to In Progress and add a comment that I'm picking it up.
```

```
Assign PROJ-142 to Alice Chen and add it to the active sprint.
```

```
Log 2h 30m of work on PROJ-142 with the note "implemented retry logic".
```

```
Only react to Jira issues labeled agent-task, and only when someone tags @craftbot.
```

## Configuration

Both settings live in **Settings → Integrations → Jira** and are stored in `jira_config.json` next to the credential. The listener re-reads them on every poll, so changes apply without reconnecting. You can also change them from chat, which uses the `set_jira_watch_tag` and `set_jira_watch_labels` actions.

| Setting | Type | Default | Effect |
|---|---|---|---|
| Watch tag (`watch_tag`) | text, e.g. `@craftbot` | empty | Only issues whose latest comment contains this tag trigger events. The text after the tag becomes the instruction. Empty = react to all matching issue updates |
| Watched labels (`watch_labels`) | list of labels | empty | Only issues carrying at least one of these labels trigger. Empty = watch every updated issue |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Cannot connect" or a 404 at login | Wrong domain host | Use the host from your Jira URL, for example `mycompany.atlassian.net`. Retrying the same value does not help |
| 401 Unauthorized | Bad or expired API token, or an email that does not match the token owner | Create a new token and run `/jira login <domain> <email> <new_token>`. The token acts as your own user and cannot impersonate |
| "Issue does not exist" on a known issue | The account lacks Browse Projects on that project | Ask a project admin to grant permission. Retrying does not help |
| 403 on an edit or transition | The account can view but not modify the issue | Request edit rights, or a project admin can adjust the permission scheme |
| Agent stops reacting to issue events | `watch_tag` or `watch_labels` is filtering them out | Check both settings in **Settings → Integrations → Jira** |
| `assign_jira_issue` fails or assigns the wrong person | An assignee is an account ID, not a display name | The agent resolves the name with `search_jira_users` first, then assigns by account ID |

## Next

- [GitHub](github.md): dev workflow tracking with the same watch-tag listener pattern
- [Notion](notion.md): pages and databases, without a listener
- [Credentials](credentials.md): where tokens are stored and how `/cred status` reports them
- [Triggers](../core/concepts/triggers.md): how listener events become tasks
