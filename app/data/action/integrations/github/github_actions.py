from agent_core import action

# ------------------------------------------------------------------
# Issues
# ------------------------------------------------------------------

@action(
    name="list_github_issues",
    description="List issues for a GitHub repository.",
    action_sets=["github_issues", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "state": {"type": "string", "description": "Filter by state: open, closed, all.", "example": "open"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_issues(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_issues(
            input_data["repo"],
            state=input_data.get("state", "open"),
            per_page=input_data.get("per_page", 30),
        ),
    )


@action(
    name="get_github_issue",
    description="Get details of a specific GitHub issue or PR by number.",
    action_sets=["github_issues", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_issue(input_data["repo"], input_data["number"]),
    )


@action(
    name="create_github_issue",
    description="Create a new issue in a GitHub repository.",
    action_sets=["github_issues", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "title": {"type": "string", "description": "Issue title.", "example": "Bug: login fails"},
        "body": {"type": "string", "description": "Issue body (markdown).", "example": ""},
        "labels": {"type": "string", "description": "Comma-separated labels.", "example": "bug,urgent"},
        "assignees": {"type": "string", "description": "Comma-separated GitHub usernames to assign.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    labels = csv_list(input_data.get("labels", ""), default=None)
    assignees = csv_list(input_data.get("assignees", ""), default=None)
    return await with_client(
        "github",
        lambda c: c.create_issue(
            input_data["repo"],
            input_data["title"],
            body=input_data.get("body", ""),
            labels=labels,
            assignees=assignees,
        ),
    )


@action(
    name="update_github_issue",
    description="Update fields of a GitHub issue (title, body, state, labels, assignees, milestone). Use state='open' to reopen.",
    action_sets=["github_issues", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue number.", "example": 1},
        "title": {"type": "string", "description": "New title (optional).", "example": ""},
        "body": {"type": "string", "description": "New body (optional).", "example": ""},
        "state": {"type": "string", "description": "open or closed (optional).", "example": "open"},
        "labels": {"type": "string", "description": "Comma-separated labels — REPLACES existing (optional).", "example": ""},
        "assignees": {"type": "string", "description": "Comma-separated assignees — REPLACES existing (optional).", "example": ""},
        "milestone": {"type": "integer", "description": "Milestone number (optional, 0 to clear).", "example": 0},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    labels = csv_list(input_data["labels"], default=None) if "labels" in input_data else None
    assignees = csv_list(input_data["assignees"], default=None) if "assignees" in input_data else None
    return await with_client(
        "github",
        lambda c: c.update_issue(
            input_data["repo"], input_data["number"],
            title=input_data.get("title"),
            body=input_data.get("body"),
            state=input_data.get("state"),
            labels=labels,
            assignees=assignees,
            milestone=input_data.get("milestone"),
        ),
    )


@action(
    name="close_github_issue",
    description="Close a GitHub issue.",
    action_sets=["github_issues", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue number.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def close_github_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.close_issue(input_data["repo"], input_data["number"]),
    )


@action(
    name="lock_github_issue",
    description="Lock conversation on an issue. Reason: off-topic, too heated, resolved, spam.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue number.", "example": 1},
        "lock_reason": {"type": "string", "description": "off-topic, too heated, resolved, or spam.", "example": "resolved"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def lock_github_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.lock_issue(input_data["repo"], input_data["number"], lock_reason=input_data.get("lock_reason")),
    )


@action(
    name="unlock_github_issue",
    description="Unlock conversation on a previously-locked issue.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue number.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unlock_github_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.unlock_issue(input_data["repo"], input_data["number"]),
    )


@action(
    name="list_github_issue_events",
    description="List timeline events (labeled, assigned, closed, etc.) for an issue or PR.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_issue_events(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_issue_events(input_data["repo"], input_data["number"], per_page=input_data.get("per_page", 30)),
    )


# ------------------------------------------------------------------
# Comments
# ------------------------------------------------------------------

@action(
    name="add_github_comment",
    description="Add a comment to a GitHub issue or PR.",
    action_sets=["github_issues", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "body": {"type": "string", "description": "Comment body (markdown).", "example": "Fixed in commit abc123."},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_github_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_comment(input_data["repo"], input_data["number"], input_data["body"]),
    )


@action(
    name="list_github_issue_comments",
    description="List comments on a GitHub issue or PR.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_issue_comments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_issue_comments(input_data["repo"], input_data["number"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="update_github_comment",
    description="Edit the body of an existing issue/PR comment by comment_id.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "comment_id": {"type": "integer", "description": "Comment ID (from list_github_issue_comments).", "example": 1},
        "body": {"type": "string", "description": "New comment body (markdown).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.update_issue_comment(input_data["repo"], input_data["comment_id"], input_data["body"]),
    )


@action(
    name="delete_github_comment",
    description="Delete an issue/PR comment by comment_id.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "comment_id": {"type": "integer", "description": "Comment ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_issue_comment(input_data["repo"], input_data["comment_id"]),
    )


# ------------------------------------------------------------------
# Labels (on issue/PR)
# ------------------------------------------------------------------

@action(
    name="add_github_labels",
    description="Add labels to a GitHub issue or PR (additive — preserves existing labels).",
    action_sets=["github_issues", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "labels": {"type": "string", "description": "Comma-separated labels to add.", "example": "bug,priority-high"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_github_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    labels = csv_list(input_data["labels"])
    if not labels:
        return {"status": "error", "message": "No labels provided."}
    return await with_client(
        "github",
        lambda c: c.add_labels(input_data["repo"], input_data["number"], labels),
    )


@action(
    name="set_github_labels",
    description="Replace ALL labels on an issue/PR with the given set. Use add_github_labels for additive changes.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "labels": {"type": "string", "description": "Comma-separated labels — REPLACES existing.", "example": "bug,priority-high"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def set_github_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    labels = csv_list(input_data["labels"])
    return await with_client(
        "github",
        lambda c: c.set_issue_labels(input_data["repo"], input_data["number"], labels),
    )


@action(
    name="remove_github_label",
    description="Remove a single label by name from an issue/PR.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "name": {"type": "string", "description": "Label name to remove.", "example": "bug"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_github_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.remove_issue_label(input_data["repo"], input_data["number"], input_data["name"]),
    )


# ------------------------------------------------------------------
# Assignees
# ------------------------------------------------------------------

@action(
    name="add_github_assignees",
    description="Add assignees to an issue or PR (additive).",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "assignees": {"type": "string", "description": "Comma-separated usernames.", "example": "octocat,hubot"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_github_assignees(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    assignees = csv_list(input_data["assignees"])
    if not assignees:
        return {"status": "error", "message": "No assignees provided."}
    return await with_client(
        "github",
        lambda c: c.add_assignees(input_data["repo"], input_data["number"], assignees),
    )


@action(
    name="remove_github_assignees",
    description="Remove assignees from an issue or PR.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "assignees": {"type": "string", "description": "Comma-separated usernames to remove.", "example": "octocat"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_github_assignees(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    assignees = csv_list(input_data["assignees"])
    if not assignees:
        return {"status": "error", "message": "No assignees provided."}
    return await with_client(
        "github",
        lambda c: c.remove_assignees(input_data["repo"], input_data["number"], assignees),
    )


# ------------------------------------------------------------------
# Labels (repo-level: define / edit the labels themselves)
# ------------------------------------------------------------------

@action(
    name="list_github_repo_labels",
    description="List all labels defined in a repository.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_repo_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_repo_labels(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="create_github_label",
    description="Define a new label in a repository.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "name": {"type": "string", "description": "Label name.", "example": "good first issue"},
        "color": {"type": "string", "description": "6-char hex color without #.", "example": "0e8a16"},
        "description": {"type": "string", "description": "Optional description.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_label(
            input_data["repo"], input_data["name"],
            color=input_data.get("color", "ededed"),
            description=input_data.get("description", ""),
        ),
    )


@action(
    name="update_github_label",
    description="Rename or recolor an existing repo label.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "name": {"type": "string", "description": "Existing label name to edit.", "example": "bug"},
        "new_name": {"type": "string", "description": "New name (optional).", "example": ""},
        "color": {"type": "string", "description": "New 6-char hex color (optional).", "example": ""},
        "description": {"type": "string", "description": "New description (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.update_label(
            input_data["repo"], input_data["name"],
            new_name=input_data.get("new_name") or None,
            color=input_data.get("color") or None,
            description=input_data.get("description") if "description" in input_data else None,
        ),
    )


@action(
    name="delete_github_label",
    description="Delete a label from the repository.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "name": {"type": "string", "description": "Label name to delete.", "example": "wontfix"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_label(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_label(input_data["repo"], input_data["name"]),
    )


# ------------------------------------------------------------------
# Milestones
# ------------------------------------------------------------------

@action(
    name="list_github_milestones",
    description="List milestones in a repository.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "state": {"type": "string", "description": "open, closed, all.", "example": "open"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_milestones(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_milestones(input_data["repo"], state=input_data.get("state", "open"), per_page=input_data.get("per_page", 30)),
    )


@action(
    name="create_github_milestone",
    description="Create a milestone.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "title": {"type": "string", "description": "Milestone title.", "example": "v1.0.0"},
        "state": {"type": "string", "description": "open or closed.", "example": "open"},
        "description": {"type": "string", "description": "Description (optional).", "example": ""},
        "due_on": {"type": "string", "description": "ISO 8601 datetime (optional).", "example": "2026-12-31T00:00:00Z"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_milestone(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_milestone(
            input_data["repo"], input_data["title"],
            state=input_data.get("state", "open"),
            description=input_data.get("description", ""),
            due_on=input_data.get("due_on") or None,
        ),
    )


@action(
    name="update_github_milestone",
    description="Edit a milestone (title, state, description, due date).",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Milestone number.", "example": 1},
        "title": {"type": "string", "description": "New title (optional).", "example": ""},
        "state": {"type": "string", "description": "open or closed (optional).", "example": ""},
        "description": {"type": "string", "description": "New description (optional).", "example": ""},
        "due_on": {"type": "string", "description": "ISO 8601 datetime (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_milestone(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.update_milestone(
            input_data["repo"], input_data["number"],
            title=input_data.get("title") or None,
            state=input_data.get("state") or None,
            description=input_data["description"] if "description" in input_data else None,
            due_on=input_data.get("due_on") or None,
        ),
    )


@action(
    name="delete_github_milestone",
    description="Delete a milestone.",
    action_sets=["github_issues"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Milestone number.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_milestone(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_milestone(input_data["repo"], input_data["number"]),
    )


# ------------------------------------------------------------------
# Pull Requests
# ------------------------------------------------------------------

@action(
    name="list_github_prs",
    description="List pull requests for a GitHub repository.",
    action_sets=["github_pulls", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "state": {"type": "string", "description": "Filter: open, closed, all.", "example": "open"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_prs(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_pull_requests(
            input_data["repo"],
            state=input_data.get("state", "open"),
            per_page=input_data.get("per_page", 30),
        ),
    )


@action(
    name="get_github_pr",
    description="Get full details of a specific pull request.",
    action_sets=["github_pulls", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Pull request number.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_pr(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_pull_request(input_data["repo"], input_data["number"]),
    )


@action(
    name="create_github_pr",
    description="Open a pull request. For cross-fork PRs, head must be 'fork-owner:branch'.",
    action_sets=["github_pulls", "github"],
    input_schema={
        "repo": {"type": "string", "description": "TARGET repo in owner/repo format (the repo you're PRing into).", "example": "octocat/hello-world"},
        "title": {"type": "string", "description": "PR title.", "example": "Add CraftBot to list"},
        "head": {"type": "string", "description": "Source branch. For fork PRs: 'fork-owner:branch'.", "example": "myfork:feature-x"},
        "base": {"type": "string", "description": "Target branch in the repo.", "example": "main"},
        "body": {"type": "string", "description": "PR description (markdown).", "example": ""},
        "draft": {"type": "boolean", "description": "Open as draft.", "example": False},
        "maintainer_can_modify": {"type": "boolean", "description": "Allow upstream maintainers to push to the head branch.", "example": True},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_pr(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_pull_request(
            input_data["repo"], input_data["title"], input_data["head"], input_data["base"],
            body=input_data.get("body", ""),
            draft=bool(input_data.get("draft", False)),
            maintainer_can_modify=bool(input_data.get("maintainer_can_modify", True)),
        ),
    )


@action(
    name="update_github_pr",
    description="Update a pull request (title, body, state, base branch).",
    action_sets=["github_pulls", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "title": {"type": "string", "description": "New title (optional).", "example": ""},
        "body": {"type": "string", "description": "New body (optional).", "example": ""},
        "state": {"type": "string", "description": "open or closed (optional).", "example": ""},
        "base": {"type": "string", "description": "New base branch (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_pr(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.update_pull_request(
            input_data["repo"], input_data["number"],
            title=input_data.get("title") or None,
            body=input_data["body"] if "body" in input_data else None,
            state=input_data.get("state") or None,
            base=input_data.get("base") or None,
        ),
    )


@action(
    name="merge_github_pr",
    description="Merge a pull request. merge_method: merge, squash, or rebase.",
    action_sets=["github_pulls", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "commit_title": {"type": "string", "description": "Custom merge commit title (optional).", "example": ""},
        "commit_message": {"type": "string", "description": "Custom merge commit body (optional).", "example": ""},
        "sha": {"type": "string", "description": "Expected SHA of the PR head — merge fails if it doesn't match (optional safety check).", "example": ""},
        "merge_method": {"type": "string", "description": "merge, squash, or rebase.", "example": "merge"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def merge_github_pr(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.merge_pull_request(
            input_data["repo"], input_data["number"],
            commit_title=input_data.get("commit_title") or None,
            commit_message=input_data.get("commit_message") or None,
            sha=input_data.get("sha") or None,
            merge_method=input_data.get("merge_method", "merge"),
        ),
    )


@action(
    name="list_github_pr_files",
    description="List files changed in a pull request (filename, status, additions/deletions, patch preview).",
    action_sets=["github_pulls", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_pr_files(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_pr_files(input_data["repo"], input_data["number"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="list_github_pr_commits",
    description="List commits on a pull request.",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_pr_commits(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_pr_commits(input_data["repo"], input_data["number"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="request_github_pr_reviewers",
    description="Request reviews from users and/or teams on a pull request.",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "reviewers": {"type": "string", "description": "Comma-separated usernames.", "example": "octocat,hubot"},
        "team_reviewers": {"type": "string", "description": "Comma-separated team slugs (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def request_github_pr_reviewers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    reviewers = csv_list(input_data.get("reviewers", ""), default=None)
    team_reviewers = csv_list(input_data.get("team_reviewers", ""), default=None)
    return await with_client(
        "github",
        lambda c: c.request_pr_reviewers(input_data["repo"], input_data["number"], reviewers=reviewers, team_reviewers=team_reviewers),
    )


@action(
    name="remove_github_pr_reviewers",
    description="Cancel a pending review request from users and/or teams.",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "reviewers": {"type": "string", "description": "Comma-separated usernames.", "example": "octocat"},
        "team_reviewers": {"type": "string", "description": "Comma-separated team slugs (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_github_pr_reviewers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    reviewers = csv_list(input_data.get("reviewers", ""), default=None)
    team_reviewers = csv_list(input_data.get("team_reviewers", ""), default=None)
    return await with_client(
        "github",
        lambda c: c.remove_pr_reviewers(input_data["repo"], input_data["number"], reviewers=reviewers, team_reviewers=team_reviewers),
    )


@action(
    name="create_github_pr_review",
    description="Create a pending or submitted review on a PR. event: APPROVE, REQUEST_CHANGES, COMMENT (omit for pending draft).",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "body": {"type": "string", "description": "Top-level review comment.", "example": "LGTM!"},
        "event": {"type": "string", "description": "APPROVE, REQUEST_CHANGES, or COMMENT. Omit to create a pending draft.", "example": "APPROVE"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_pr_review(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_pr_review(
            input_data["repo"], input_data["number"],
            body=input_data.get("body", ""),
            event=input_data.get("event") or None,
        ),
    )


@action(
    name="list_github_pr_reviews",
    description="List reviews on a pull request.",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_pr_reviews(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_pr_reviews(input_data["repo"], input_data["number"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="submit_github_pr_review",
    description="Submit a pending PR review with an event (APPROVE, REQUEST_CHANGES, COMMENT).",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "review_id": {"type": "integer", "description": "Pending review ID (from create_github_pr_review).", "example": 1},
        "event": {"type": "string", "description": "APPROVE, REQUEST_CHANGES, or COMMENT.", "example": "APPROVE"},
        "body": {"type": "string", "description": "Optional override of review body.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def submit_github_pr_review(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.submit_pr_review(
            input_data["repo"], input_data["number"], input_data["review_id"],
            event=input_data["event"], body=input_data.get("body", ""),
        ),
    )


@action(
    name="list_github_pr_review_comments",
    description="List inline (file-line) review comments on a PR.",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_pr_review_comments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_pr_review_comments(input_data["repo"], input_data["number"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="create_github_pr_review_comment",
    description="Create an inline review comment on a specific file line in a PR.",
    action_sets=["github_pulls"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "PR number.", "example": 1},
        "body": {"type": "string", "description": "Comment body (markdown).", "example": "Consider extracting this into a helper."},
        "commit_id": {"type": "string", "description": "Commit SHA the comment applies to (head of the PR).", "example": ""},
        "path": {"type": "string", "description": "Relative path to the file.", "example": "src/foo.py"},
        "line": {"type": "integer", "description": "Line number in the file.", "example": 42},
        "side": {"type": "string", "description": "LEFT (old) or RIGHT (new). Default RIGHT.", "example": "RIGHT"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_pr_review_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_pr_review_comment(
            input_data["repo"], input_data["number"],
            body=input_data["body"], commit_id=input_data["commit_id"],
            path=input_data["path"], line=input_data["line"],
            side=input_data.get("side", "RIGHT"),
        ),
    )


# ------------------------------------------------------------------
# Repos
# ------------------------------------------------------------------

@action(
    name="list_github_repos",
    description="List repositories for the authenticated GitHub user.",
    action_sets=["github_repos", "github"],
    input_schema={
        "per_page": {"type": "integer", "description": "Max repos to return.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_repos(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client
    return await run_client("github", "list_repos", per_page=input_data.get("per_page", 30))


@action(
    name="get_github_repo",
    description="Get repository metadata (default_branch, description, stars, fork status, etc.).",
    action_sets=["github_repos", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_repo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.get_repo(input_data["repo"]))


@action(
    name="create_github_repo",
    description="Create a new repository under the authenticated user.",
    action_sets=["github_repos"],
    input_schema={
        "name": {"type": "string", "description": "Repository name (no owner).", "example": "my-new-repo"},
        "description": {"type": "string", "description": "Repository description.", "example": ""},
        "private": {"type": "boolean", "description": "Create as private.", "example": False},
        "auto_init": {"type": "boolean", "description": "Create an initial commit with empty README.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_repo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_repo(
            input_data["name"],
            description=input_data.get("description", ""),
            private=bool(input_data.get("private", False)),
            auto_init=bool(input_data.get("auto_init", False)),
        ),
    )


@action(
    name="update_github_repo",
    description="Update repository settings (name, description, visibility, default branch, archive status).",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "name": {"type": "string", "description": "New name (optional).", "example": ""},
        "description": {"type": "string", "description": "New description (optional).", "example": ""},
        "private": {"type": "boolean", "description": "Set private/public (optional).", "example": False},
        "default_branch": {"type": "string", "description": "New default branch (optional).", "example": ""},
        "archived": {"type": "boolean", "description": "Archive/unarchive (optional).", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_repo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.update_repo(
            input_data["repo"],
            name=input_data.get("name") or None,
            description=input_data["description"] if "description" in input_data else None,
            private=input_data["private"] if "private" in input_data else None,
            default_branch=input_data.get("default_branch") or None,
            archived=input_data["archived"] if "archived" in input_data else None,
        ),
    )


@action(
    name="delete_github_repo",
    description="DELETE a repository. Irreversible. Requires admin scope on the token.",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_repo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.delete_repo(input_data["repo"]))


@action(
    name="fork_github_repo",
    description="Fork a repository under the authenticated user (or an organization). The fork is created asynchronously — wait a few seconds before pushing/PRing.",
    action_sets=["github_repos", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Source repo in owner/repo format.", "example": "octocat/hello-world"},
        "organization": {"type": "string", "description": "Fork into this org instead of personal account (optional).", "example": ""},
        "name": {"type": "string", "description": "Custom name for the fork (optional).", "example": ""},
        "default_branch_only": {"type": "boolean", "description": "Only fork the default branch.", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def fork_github_repo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.fork_repo(
            input_data["repo"],
            organization=input_data.get("organization") or None,
            name=input_data.get("name") or None,
            default_branch_only=bool(input_data.get("default_branch_only", False)),
        ),
    )


@action(
    name="list_github_forks",
    description="List forks of a repository.",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_forks(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_forks(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="list_github_collaborators",
    description="List collaborators on a repository (login + permissions).",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_collaborators(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_collaborators(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="add_github_collaborator",
    description="Invite a user as a collaborator. Permission: pull, triage, push, maintain, admin.",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "username": {"type": "string", "description": "GitHub username to invite.", "example": "octocat"},
        "permission": {"type": "string", "description": "pull, triage, push, maintain, or admin.", "example": "push"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_github_collaborator(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.add_collaborator(
            input_data["repo"], input_data["username"],
            permission=input_data.get("permission", "push"),
        ),
    )


@action(
    name="remove_github_collaborator",
    description="Remove a collaborator from a repository.",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "username": {"type": "string", "description": "GitHub username to remove.", "example": "octocat"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_github_collaborator(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.remove_collaborator(input_data["repo"], input_data["username"]),
    )


@action(
    name="get_github_readme",
    description="Get the README of a repository (base64-encoded content + download_url).",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "ref": {"type": "string", "description": "Branch, tag, or commit SHA (optional, defaults to default branch).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_readme(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_readme(input_data["repo"], ref=input_data.get("ref") or None),
    )


@action(
    name="list_github_topics",
    description="Get the topic tags on a repository.",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_topics(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.list_topics(input_data["repo"]))


@action(
    name="set_github_topics",
    description="REPLACE the topic tags on a repository.",
    action_sets=["github_repos"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "topics": {"type": "string", "description": "Comma-separated topic slugs (lowercase, hyphenated).", "example": "ai-agent,mcp,llm"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def set_github_topics(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    from app.utils.text import csv_list
    topics = csv_list(input_data.get("topics", ""))
    return await with_client("github", lambda c: c.set_topics(input_data["repo"], topics))


# ------------------------------------------------------------------
# Contents (read/write files directly via API — no clone needed)
# ------------------------------------------------------------------

@action(
    name="get_github_file",
    description="Read a file from a repo by path. Returns base64-encoded content + sha (needed to update later).",
    action_sets=["github_code", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "path": {"type": "string", "description": "Path to the file in the repo.", "example": "README.md"},
        "ref": {"type": "string", "description": "Branch, tag, or commit SHA (optional, defaults to default branch).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_file(input_data["repo"], input_data["path"], ref=input_data.get("ref") or None),
    )


@action(
    name="create_or_update_github_file",
    description="Create or update a single file in a repo via API (no clone/push needed). Content must be base64-encoded. To update an existing file you MUST pass its current sha (from get_github_file).",
    action_sets=["github_code", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "path": {"type": "string", "description": "Path to the file in the repo.", "example": "README.md"},
        "message": {"type": "string", "description": "Commit message.", "example": "Add CraftBot to list"},
        "content_b64": {"type": "string", "description": "Base64-encoded file content.", "example": ""},
        "sha": {"type": "string", "description": "Current SHA of the file (REQUIRED when updating an existing file).", "example": ""},
        "branch": {"type": "string", "description": "Branch to commit on (optional, defaults to default branch).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_or_update_github_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_or_update_file(
            input_data["repo"], input_data["path"],
            message=input_data["message"], content_b64=input_data["content_b64"],
            sha=input_data.get("sha") or None,
            branch=input_data.get("branch") or None,
        ),
    )


@action(
    name="delete_github_file",
    description="Delete a file in a repo via API. Requires the current sha (from get_github_file).",
    action_sets=["github_code"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "path": {"type": "string", "description": "Path to the file in the repo.", "example": "old-file.md"},
        "message": {"type": "string", "description": "Commit message.", "example": "Remove old file"},
        "sha": {"type": "string", "description": "Current SHA of the file.", "example": ""},
        "branch": {"type": "string", "description": "Branch to commit on (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_file(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_file(
            input_data["repo"], input_data["path"],
            message=input_data["message"], sha=input_data["sha"],
            branch=input_data.get("branch") or None,
        ),
    )


# ------------------------------------------------------------------
# Branches / refs
# ------------------------------------------------------------------

@action(
    name="list_github_branches",
    description="List branches in a repository.",
    action_sets=["github_code", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_branches(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_branches(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="get_github_branch",
    description="Get details of a specific branch (name, sha, protection state).",
    action_sets=["github_code"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "branch": {"type": "string", "description": "Branch name.", "example": "main"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_branch(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_branch(input_data["repo"], input_data["branch"]),
    )


@action(
    name="create_github_branch",
    description="Create a new branch pointing at an existing commit SHA. Get from_sha via get_github_branch on the source branch.",
    action_sets=["github_code", "github"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "branch": {"type": "string", "description": "New branch name (no refs/heads/ prefix).", "example": "feature-x"},
        "from_sha": {"type": "string", "description": "Commit SHA the new branch should point at.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_branch(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_branch(input_data["repo"], input_data["branch"], input_data["from_sha"]),
    )


@action(
    name="delete_github_branch",
    description="Delete a branch.",
    action_sets=["github_code"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "branch": {"type": "string", "description": "Branch name.", "example": "feature-x"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_branch(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_branch(input_data["repo"], input_data["branch"]),
    )


# ------------------------------------------------------------------
# Commits
# ------------------------------------------------------------------

@action(
    name="list_github_commits",
    description="List commits on a branch (or filtered by path/author).",
    action_sets=["github_code"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "sha": {"type": "string", "description": "Branch name or SHA to list commits from (optional, defaults to default branch).", "example": ""},
        "path": {"type": "string", "description": "Only commits touching this path (optional).", "example": ""},
        "author": {"type": "string", "description": "GitHub username to filter by (optional).", "example": ""},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_commits(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_commits(
            input_data["repo"],
            sha=input_data.get("sha") or None,
            path=input_data.get("path") or None,
            author=input_data.get("author") or None,
            per_page=input_data.get("per_page", 30),
        ),
    )


@action(
    name="get_github_commit",
    description="Get details of a specific commit (files changed, stats, author).",
    action_sets=["github_code"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "sha": {"type": "string", "description": "Commit SHA.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_commit(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_commit(input_data["repo"], input_data["sha"]),
    )


@action(
    name="compare_github_commits",
    description="Compare two commits/branches/tags. Returns ahead_by/behind_by + changed files.",
    action_sets=["github_code"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "base": {"type": "string", "description": "Base ref (branch, tag, or SHA).", "example": "main"},
        "head": {"type": "string", "description": "Head ref (branch, tag, or SHA).", "example": "feature-x"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def compare_github_commits(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.compare_commits(input_data["repo"], input_data["base"], input_data["head"]),
    )


# ------------------------------------------------------------------
# Releases & tags
# ------------------------------------------------------------------

@action(
    name="list_github_releases",
    description="List releases of a repository.",
    action_sets=["github_releases"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_releases(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_releases(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="get_github_release",
    description="Get a release by ID, by tag, or the latest. Provide one of: release_id, tag, or latest=true.",
    action_sets=["github_releases"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "release_id": {"type": "integer", "description": "Release ID (optional).", "example": 0},
        "tag": {"type": "string", "description": "Tag name (optional).", "example": ""},
        "latest": {"type": "boolean", "description": "Get the latest release (optional).", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_release(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    rid = input_data.get("release_id")
    return await with_client(
        "github",
        lambda c: c.get_release(
            input_data["repo"],
            release_id=rid if rid else None,
            tag=input_data.get("tag") or None,
            latest=bool(input_data.get("latest", False)),
        ),
    )


@action(
    name="create_github_release",
    description="Create a release (optionally a draft or prerelease). Auto-creates the tag if it doesn't exist (using target_commitish).",
    action_sets=["github_releases"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "tag_name": {"type": "string", "description": "Tag name.", "example": "v1.0.0"},
        "name": {"type": "string", "description": "Release title (optional).", "example": ""},
        "body": {"type": "string", "description": "Release notes (markdown).", "example": ""},
        "draft": {"type": "boolean", "description": "Create as draft.", "example": False},
        "prerelease": {"type": "boolean", "description": "Mark as prerelease.", "example": False},
        "target_commitish": {"type": "string", "description": "Branch/SHA to create the tag from if it doesn't exist (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_release(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.create_release(
            input_data["repo"], input_data["tag_name"],
            name=input_data.get("name") or None,
            body=input_data.get("body", ""),
            draft=bool(input_data.get("draft", False)),
            prerelease=bool(input_data.get("prerelease", False)),
            target_commitish=input_data.get("target_commitish") or None,
        ),
    )


@action(
    name="update_github_release",
    description="Edit an existing release.",
    action_sets=["github_releases"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "release_id": {"type": "integer", "description": "Release ID.", "example": 1},
        "tag_name": {"type": "string", "description": "New tag (optional).", "example": ""},
        "name": {"type": "string", "description": "New title (optional).", "example": ""},
        "body": {"type": "string", "description": "New notes (optional).", "example": ""},
        "draft": {"type": "boolean", "description": "Set draft status (optional).", "example": False},
        "prerelease": {"type": "boolean", "description": "Set prerelease (optional).", "example": False},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_release(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.update_release(
            input_data["repo"], input_data["release_id"],
            tag_name=input_data.get("tag_name") or None,
            name=input_data.get("name") or None,
            body=input_data["body"] if "body" in input_data else None,
            draft=input_data["draft"] if "draft" in input_data else None,
            prerelease=input_data["prerelease"] if "prerelease" in input_data else None,
        ),
    )


@action(
    name="delete_github_release",
    description="Delete a release. Does NOT delete the underlying tag.",
    action_sets=["github_releases"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "release_id": {"type": "integer", "description": "Release ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_release(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_release(input_data["repo"], input_data["release_id"]),
    )


@action(
    name="list_github_tags",
    description="List tags in a repository.",
    action_sets=["github_releases"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_tags(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_tags(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


# ------------------------------------------------------------------
# Reactions (👍 👎 😄 🎉 😕 ❤️ 🚀 👀)
# Valid content: +1, -1, laugh, confused, heart, hooray, rocket, eyes
# ------------------------------------------------------------------

@action(
    name="add_github_issue_reaction",
    description="React to an issue (or issue's first body, not a comment). Content: +1, -1, laugh, confused, heart, hooray, rocket, eyes.",
    action_sets=["github_reactions"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "content": {"type": "string", "description": "One of: +1, -1, laugh, confused, heart, hooray, rocket, eyes.", "example": "+1"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_github_issue_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.add_issue_reaction(input_data["repo"], input_data["number"], input_data["content"]),
    )


@action(
    name="add_github_comment_reaction",
    description="React to an issue/PR comment by comment_id. Content: +1, -1, laugh, confused, heart, hooray, rocket, eyes.",
    action_sets=["github_reactions"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "comment_id": {"type": "integer", "description": "Comment ID.", "example": 1},
        "content": {"type": "string", "description": "Reaction emoji slug.", "example": "heart"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_github_comment_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.add_issue_comment_reaction(input_data["repo"], input_data["comment_id"], input_data["content"]),
    )


@action(
    name="add_github_pr_review_comment_reaction",
    description="React to an inline PR review comment by comment_id.",
    action_sets=["github_reactions"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "comment_id": {"type": "integer", "description": "PR review comment ID.", "example": 1},
        "content": {"type": "string", "description": "Reaction emoji slug.", "example": "+1"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_github_pr_review_comment_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.add_pr_review_comment_reaction(input_data["repo"], input_data["comment_id"], input_data["content"]),
    )


@action(
    name="delete_github_issue_reaction",
    description="Remove a reaction from an issue.",
    action_sets=["github_reactions"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "number": {"type": "integer", "description": "Issue or PR number.", "example": 1},
        "reaction_id": {"type": "integer", "description": "Reaction ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_issue_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_issue_reaction(input_data["repo"], input_data["number"], input_data["reaction_id"]),
    )


@action(
    name="delete_github_comment_reaction",
    description="Remove a reaction from an issue/PR comment.",
    action_sets=["github_reactions"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "comment_id": {"type": "integer", "description": "Comment ID.", "example": 1},
        "reaction_id": {"type": "integer", "description": "Reaction ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_comment_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_issue_comment_reaction(input_data["repo"], input_data["comment_id"], input_data["reaction_id"]),
    )


@action(
    name="delete_github_pr_review_comment_reaction",
    description="Remove a reaction from an inline PR review comment.",
    action_sets=["github_reactions"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "comment_id": {"type": "integer", "description": "PR review comment ID.", "example": 1},
        "reaction_id": {"type": "integer", "description": "Reaction ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_pr_review_comment_reaction(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.delete_pr_review_comment_reaction(input_data["repo"], input_data["comment_id"], input_data["reaction_id"]),
    )


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------

@action(
    name="search_github_issues",
    description="Search GitHub issues and PRs using GitHub search syntax.",
    action_sets=["github_search", "github"],
    input_schema={
        "query": {"type": "string", "description": "GitHub search query (e.g. 'repo:owner/repo is:open label:bug').", "example": "repo:octocat/hello-world is:open"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_github_issues(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.search_issues(input_data["query"], per_page=input_data.get("per_page", 20)),
    )


@action(
    name="search_github_repos",
    description="Search repositories using GitHub search syntax (e.g. 'language:python stars:>1000').",
    action_sets=["github_search", "github"],
    input_schema={
        "query": {"type": "string", "description": "GitHub search query.", "example": "awesome ai agents language:python"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_github_repos(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.search_repos(input_data["query"], per_page=input_data.get("per_page", 20)),
    )


@action(
    name="search_github_code",
    description="Search code across repositories. Query syntax: 'function in:file language:python repo:owner/repo'.",
    action_sets=["github_search"],
    input_schema={
        "query": {"type": "string", "description": "GitHub code search query.", "example": "addClass in:file language:js repo:jquery/jquery"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_github_code(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.search_code(input_data["query"], per_page=input_data.get("per_page", 20)),
    )


@action(
    name="search_github_users",
    description="Search GitHub users.",
    action_sets=["github_search"],
    input_schema={
        "query": {"type": "string", "description": "GitHub search query.", "example": "tom location:tokyo"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_github_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.search_users(input_data["query"], per_page=input_data.get("per_page", 20)),
    )


@action(
    name="search_github_commits",
    description="Search commit messages.",
    action_sets=["github_search"],
    input_schema={
        "query": {"type": "string", "description": "GitHub commit search query.", "example": "fix repo:owner/repo"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 20},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_github_commits(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.search_commits(input_data["query"], per_page=input_data.get("per_page", 20)),
    )


# ------------------------------------------------------------------
# Users
# ------------------------------------------------------------------

@action(
    name="get_github_authenticated_user",
    description="Get the profile of the authenticated GitHub user (the token owner).",
    action_sets=["github_users"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_authenticated_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.get_authenticated_user())


@action(
    name="get_github_user",
    description="Get the public profile of any GitHub user.",
    action_sets=["github_users"],
    input_schema={
        "username": {"type": "string", "description": "GitHub username.", "example": "octocat"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.get_user(input_data["username"]))


@action(
    name="list_github_user_repos",
    description="List public repositories of a specific GitHub user.",
    action_sets=["github_users"],
    input_schema={
        "username": {"type": "string", "description": "GitHub username.", "example": "octocat"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
        "sort": {"type": "string", "description": "Sort by: created, updated, pushed, full_name.", "example": "updated"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_user_repos(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_user_repos(input_data["username"], per_page=input_data.get("per_page", 30), sort=input_data.get("sort", "updated")),
    )


@action(
    name="follow_github_user",
    description="Follow a GitHub user as the authenticated user.",
    action_sets=["github_users"],
    input_schema={
        "username": {"type": "string", "description": "GitHub username to follow.", "example": "octocat"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def follow_github_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.follow_user(input_data["username"]))


@action(
    name="unfollow_github_user",
    description="Unfollow a GitHub user.",
    action_sets=["github_users"],
    input_schema={
        "username": {"type": "string", "description": "GitHub username to unfollow.", "example": "octocat"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unfollow_github_user(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.unfollow_user(input_data["username"]))


@action(
    name="list_github_followers",
    description="List followers of the authenticated user.",
    action_sets=["github_users"],
    input_schema={
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_followers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.list_followers(per_page=input_data.get("per_page", 30)))


@action(
    name="list_github_following",
    description="List users the authenticated user follows.",
    action_sets=["github_users"],
    input_schema={
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_following(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.list_following(per_page=input_data.get("per_page", 30)))


# ------------------------------------------------------------------
# Stars
# ------------------------------------------------------------------

@action(
    name="star_github_repo",
    description="Star a repository as the authenticated user.",
    action_sets=["github_users"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def star_github_repo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.star_repo(input_data["repo"]))


@action(
    name="unstar_github_repo",
    description="Unstar a repository.",
    action_sets=["github_users"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def unstar_github_repo(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.unstar_repo(input_data["repo"]))


@action(
    name="list_github_starred",
    description="List repositories starred by the authenticated user.",
    action_sets=["github_users"],
    input_schema={
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_starred(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.list_starred(per_page=input_data.get("per_page", 30)))


@action(
    name="list_github_stargazers",
    description="List users who have starred a repository.",
    action_sets=["github_users"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_stargazers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_stargazers(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


# ------------------------------------------------------------------
# Gists
# ------------------------------------------------------------------

@action(
    name="list_github_gists",
    description="List gists owned by the authenticated user.",
    action_sets=["github_gists"],
    input_schema={
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_gists(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.list_gists(per_page=input_data.get("per_page", 30)))


@action(
    name="get_github_gist",
    description="Get a gist (full file contents) by ID.",
    action_sets=["github_gists"],
    input_schema={
        "gist_id": {"type": "string", "description": "Gist ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_gist(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.get_gist(input_data["gist_id"]))


@action(
    name="create_github_gist",
    description="Create a gist. files_json is a JSON-encoded mapping of {filename: {content: 'text'}}. Example: '{\"hello.py\":{\"content\":\"print(1)\"}}'.",
    action_sets=["github_gists"],
    input_schema={
        "files_json": {"type": "string", "description": "JSON-encoded {filename: {content: 'text'}} map.", "example": "{\"hello.py\":{\"content\":\"print(1)\"}}"},
        "description": {"type": "string", "description": "Gist description.", "example": ""},
        "public": {"type": "boolean", "description": "Public gist (else secret).", "example": True},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_github_gist(input_data: dict) -> dict:
    import json
    from app.data.action.integrations._helpers import with_client
    try:
        files = json.loads(input_data["files_json"])
    except (json.JSONDecodeError, KeyError) as e:
        return {"status": "error", "message": f"Invalid files_json: {e}"}
    return await with_client(
        "github",
        lambda c: c.create_gist(
            files,
            description=input_data.get("description", ""),
            public=bool(input_data.get("public", True)),
        ),
    )


@action(
    name="update_github_gist",
    description="Update a gist's description and/or files. files_json is JSON-encoded; set a file's 'content' to update, or {filename: null} to delete it.",
    action_sets=["github_gists"],
    input_schema={
        "gist_id": {"type": "string", "description": "Gist ID.", "example": ""},
        "description": {"type": "string", "description": "New description (optional).", "example": ""},
        "files_json": {"type": "string", "description": "JSON-encoded files map (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_github_gist(input_data: dict) -> dict:
    import json
    from app.data.action.integrations._helpers import with_client
    files = None
    if input_data.get("files_json"):
        try:
            files = json.loads(input_data["files_json"])
        except json.JSONDecodeError as e:
            return {"status": "error", "message": f"Invalid files_json: {e}"}
    return await with_client(
        "github",
        lambda c: c.update_gist(
            input_data["gist_id"],
            description=input_data["description"] if "description" in input_data else None,
            files=files,
        ),
    )


@action(
    name="delete_github_gist",
    description="Delete a gist.",
    action_sets=["github_gists"],
    input_schema={
        "gist_id": {"type": "string", "description": "Gist ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_github_gist(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.delete_gist(input_data["gist_id"]))


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------

@action(
    name="list_github_notifications",
    description="List the authenticated user's notifications (unread by default).",
    action_sets=["github_notifications"],
    input_schema={
        "include_read": {"type": "boolean", "description": "Include already-read notifications.", "example": False},
        "participating": {"type": "boolean", "description": "Only notifications you're directly participating in (mentioned/assigned/authored).", "example": False},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_notifications(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_notifications(
            include_read=bool(input_data.get("include_read", False)),
            participating=bool(input_data.get("participating", False)),
            per_page=input_data.get("per_page", 30),
        ),
    )


@action(
    name="mark_github_notifications_read",
    description="Mark ALL the authenticated user's notifications as read.",
    action_sets=["github_notifications"],
    input_schema={
        "last_read_at": {"type": "string", "description": "ISO 8601 datetime — only mark items updated before this (optional, defaults to now).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def mark_github_notifications_read(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.mark_all_notifications_read(last_read_at=input_data.get("last_read_at") or None),
    )


@action(
    name="mark_github_notification_read",
    description="Mark a single notification thread as read.",
    action_sets=["github_notifications"],
    input_schema={
        "thread_id": {"type": "string", "description": "Notification thread ID.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def mark_github_notification_read(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client("github", lambda c: c.mark_notification_read(input_data["thread_id"]))


# ------------------------------------------------------------------
# Workflows / Actions (CI)
# ------------------------------------------------------------------

@action(
    name="list_github_workflows",
    description="List CI workflows defined in a repository.",
    action_sets=["github_workflows"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_workflows(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_workflows(input_data["repo"], per_page=input_data.get("per_page", 30)),
    )


@action(
    name="list_github_workflow_runs",
    description="List workflow runs (optionally filtered by workflow, branch, or status).",
    action_sets=["github_workflows"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "workflow_id": {"type": "string", "description": "Workflow ID or filename (optional — omit for all runs).", "example": ""},
        "branch": {"type": "string", "description": "Filter by branch (optional).", "example": ""},
        "status": {"type": "string", "description": "Filter: queued, in_progress, completed, success, failure, cancelled (optional).", "example": ""},
        "per_page": {"type": "integer", "description": "Max results.", "example": 30},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_github_workflow_runs(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.list_workflow_runs(
            input_data["repo"],
            workflow_id=input_data.get("workflow_id") or None,
            branch=input_data.get("branch") or None,
            status=input_data.get("status") or None,
            per_page=input_data.get("per_page", 30),
        ),
    )


@action(
    name="get_github_workflow_run",
    description="Get details of a single workflow run by ID.",
    action_sets=["github_workflows"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "run_id": {"type": "integer", "description": "Workflow run ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_workflow_run(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_workflow_run(input_data["repo"], input_data["run_id"]),
    )


@action(
    name="trigger_github_workflow",
    description="Trigger a workflow_dispatch event. The workflow YAML must have an 'on: workflow_dispatch:' trigger.",
    action_sets=["github_workflows"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "workflow_id": {"type": "string", "description": "Workflow ID or filename (e.g. 'ci.yml').", "example": "ci.yml"},
        "ref": {"type": "string", "description": "Branch or tag to run on.", "example": "main"},
        "inputs_json": {"type": "string", "description": "JSON-encoded inputs map (optional).", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def trigger_github_workflow(input_data: dict) -> dict:
    import json
    from app.data.action.integrations._helpers import with_client
    inputs = None
    if input_data.get("inputs_json"):
        try:
            inputs = json.loads(input_data["inputs_json"])
        except json.JSONDecodeError as e:
            return {"status": "error", "message": f"Invalid inputs_json: {e}"}
    return await with_client(
        "github",
        lambda c: c.trigger_workflow(input_data["repo"], input_data["workflow_id"], input_data["ref"], inputs=inputs),
    )


@action(
    name="cancel_github_workflow_run",
    description="Cancel an in-progress workflow run.",
    action_sets=["github_workflows"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "run_id": {"type": "integer", "description": "Workflow run ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def cancel_github_workflow_run(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.cancel_workflow_run(input_data["repo"], input_data["run_id"]),
    )


@action(
    name="rerun_github_workflow_run",
    description="Re-run a completed workflow run.",
    action_sets=["github_workflows"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "run_id": {"type": "integer", "description": "Workflow run ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def rerun_github_workflow_run(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.rerun_workflow_run(input_data["repo"], input_data["run_id"]),
    )


@action(
    name="get_github_workflow_run_logs_url",
    description="Get the signed download URL for a workflow run's logs zip. Returns the URL only — does NOT download the zip (which can be large).",
    action_sets=["github_workflows"],
    input_schema={
        "repo": {"type": "string", "description": "Repository in owner/repo format.", "example": "octocat/hello-world"},
        "run_id": {"type": "integer", "description": "Workflow run ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_github_workflow_run_logs_url(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client
    return await with_client(
        "github",
        lambda c: c.get_workflow_run_logs_url(input_data["repo"], input_data["run_id"]),
    )


# ------------------------------------------------------------------
# Watch settings (internal: control which GitHub notifications wake the agent)
# ------------------------------------------------------------------

@action(
    name="set_github_watch_tag",
    description="Set a mention tag for the GitHub listener. Only comments containing this tag (e.g. '@craftbot') will trigger events.",
    action_sets=["github_notifications"],
    input_schema={
        "tag": {"type": "string", "description": "Tag to watch for. Empty = disabled.", "example": "@craftbot"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_github_watch_tag(input_data: dict) -> dict:
    try:
        from craftos_integrations import get_client
        client = get_client("github")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No GitHub credential. Use /github login first."}
        tag = input_data.get("tag", "").strip()
        client.set_watch_tag(tag)
        if tag:
            return {"status": "success", "message": f"Now only triggering on comments containing '{tag}'."}
        return {"status": "success", "message": "Watch tag disabled. Triggering on all notifications."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="set_github_watch_repos",
    description="Set which repositories the GitHub listener watches. Only events from these repos will trigger.",
    action_sets=["github_notifications"],
    input_schema={
        "repos": {"type": "string", "description": "Comma-separated repos in owner/repo format. Empty = all repos.", "example": "octocat/hello-world,myorg/myrepo"},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_github_watch_repos(input_data: dict) -> dict:
    try:
        from craftos_integrations import get_client
        from app.utils.text import csv_list
        client = get_client("github")
        if not client or not client.has_credentials():
            return {"status": "error", "message": "No GitHub credential. Use /github login first."}
        repos = csv_list(input_data.get("repos", ""))
        client.set_watch_repos(repos)
        if repos:
            return {"status": "success", "message": f"Watching repos: {', '.join(repos)}"}
        return {"status": "success", "message": "Watching all repos."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==================================================================
# Intentionally NOT exposed as actions (and why)
# ==================================================================
# These GitHub REST categories are admin / niche / non-user-facing and are
# excluded from this action surface. Add them later if a real use case appears.
#
# - GitHub Apps / Installations / OIDC / Marketplace
#     Admin-only management of GitHub Apps; agents don't author Apps.
# - Billing / Enterprise admin
#     Org/enterprise admin surface.
# - Codespaces admin
#     Mostly billing/policy endpoints; the dev-loop endpoints aren't generic
#     enough for an assistant to use without per-user setup.
# - Code scanning / Secret scanning / Dependabot alerts
#     Security findings admin. Read-mostly and security-sensitive; opt-in only.
# - Migrations / Source imports
#     One-shot migration tooling, not day-to-day.
# - Organizations / Teams management
#     Org admin (members, team roles, role grants).
# - Packages (npm/Maven/Docker/RubyGems/NuGet on GHCR)
#     Each ecosystem has its own primary tooling; thin GHCR wrappers add little.
# - Pages
#     Niche site-deploy config.
# - Projects (v2) / Project boards
#     v1 boards are deprecated; v2 is a GraphQL-only API, doesn't fit the REST
#     action pattern. Add as a separate `github_projects` action set if needed.
# - Discussions
#     REST coverage is incomplete; the canonical API is GraphQL.
# - Checks / Deployments / Environments / Statuses
#     Owned by CI providers writing back into GitHub. Trigger from outside.
# - Webhooks management (org/repo webhook CRUD)
#     Infrastructure setup, not interactive use.
# - Interactions limits (block users / restrict interactions)
#     Moderation admin.
# - Git data primitives (blobs, trees, raw refs)
#     `create_or_update_github_file` and the branch endpoints cover the realistic
#     write workflow without exposing the full git-object plumbing.
