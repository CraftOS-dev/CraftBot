from agent_core import action
from app.utils import csv_list


_NO_CRED_MSG = "No Jira credential. Use /jira login first."


# ------------------------------------------------------------------
# Issues
# ------------------------------------------------------------------


@action(
    name="search_jira_issues",
    description="Search for Jira issues using JQL (Jira Query Language).",
    action_sets=["jira"],
    input_schema={
        "jql": {
            "type": "string",
            "description": "JQL query string.",
            "example": 'project = PROJ AND status = "In Progress"',
        },
        "max_results": {
            "type": "integer",
            "description": "Max issues to return (max 100).",
            "example": 20,
        },
        "fields": {
            "type": "string",
            "description": "Comma-separated fields to return. Leave empty for defaults.",
            "example": "summary,status,assignee,priority",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_jira_issues(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    fields_list = csv_list(input_data.get("fields", ""), default=None)
    return await run_client(
        "jira",
        "search_issues",
        jql=input_data["jql"],
        max_results=input_data.get("max_results", 20),
        fields_list=fields_list,
    )


@action(
    name="get_jira_issue",
    description="Get details of a specific Jira issue by its key (e.g. PROJ-123).",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "fields": {
            "type": "string",
            "description": "Comma-separated fields to return. Leave empty for all.",
            "example": "summary,status,assignee,description",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    fields_list = csv_list(input_data.get("fields", ""), default=None)
    return await with_client(
        "jira",
        lambda c: c.get_issue(input_data["issue_key"], fields_list=fields_list),
    )


@action(
    name="create_jira_issue",
    description="Create a new Jira issue in a project.",
    action_sets=["jira"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Project key.",
            "example": "PROJ",
        },
        "summary": {
            "type": "string",
            "description": "Issue title/summary.",
            "example": "Fix login bug",
        },
        "issue_type": {
            "type": "string",
            "description": "Issue type name.",
            "example": "Task",
        },
        "description": {
            "type": "string",
            "description": "Issue description (plain text).",
            "example": "",
        },
        "assignee_id": {
            "type": "string",
            "description": "Atlassian account ID of the assignee. Leave empty for unassigned.",
            "example": "",
        },
        "labels": {
            "type": "string",
            "description": "Comma-separated labels.",
            "example": "bug,urgent",
        },
        "priority": {
            "type": "string",
            "description": "Priority name (e.g. High, Medium, Low).",
            "example": "Medium",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_jira_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    labels = csv_list(input_data.get("labels", ""), default=None)
    return await run_client(
        "jira",
        "create_issue",
        project_key=input_data["project_key"],
        summary=input_data["summary"],
        issue_type=input_data.get("issue_type", "Task"),
        description=input_data.get("description") or None,
        assignee_id=input_data.get("assignee_id") or None,
        labels=labels,
        priority=input_data.get("priority") or None,
    )


@action(
    name="update_jira_issue",
    description="Update fields on an existing Jira issue.",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "summary": {
            "type": "string",
            "description": "New summary. Leave empty to keep current.",
            "example": "",
        },
        "priority": {
            "type": "string",
            "description": "New priority name. Leave empty to keep current.",
            "example": "",
        },
        "labels": {
            "type": "string",
            "description": "Comma-separated labels to SET (replaces all). Leave empty to keep current.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_jira_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    fields_update = {}
    if input_data.get("summary"):
        fields_update["summary"] = input_data["summary"]
    if input_data.get("priority"):
        fields_update["priority"] = {"name": input_data["priority"]}
    if input_data.get("labels"):
        fields_update["labels"] = csv_list(input_data["labels"])
    if not fields_update:
        return {"status": "error", "message": "No fields to update."}
    return await with_client(
        "jira",
        lambda c: c.update_issue(input_data["issue_key"], fields_update),
    )


# ------------------------------------------------------------------
# Comments
# ------------------------------------------------------------------


@action(
    name="add_jira_comment",
    description="Add a comment to a Jira issue.",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "body": {
            "type": "string",
            "description": "Comment text.",
            "example": "Fixed in latest commit.",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_jira_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    return await with_client(
        "jira",
        lambda c: c.add_comment(input_data["issue_key"], input_data["body"]),
    )


@action(
    name="get_jira_comments",
    description="Get comments on a Jira issue.",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "max_results": {
            "type": "integer",
            "description": "Max comments to return.",
            "example": 20,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_comments(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    return await with_client(
        "jira",
        lambda c: c.get_issue_comments(
            input_data["issue_key"],
            max_results=input_data.get("max_results", 20),
        ),
    )


# ------------------------------------------------------------------
# Transitions
# ------------------------------------------------------------------


@action(
    name="get_jira_transitions",
    description="Get available status transitions for a Jira issue (to know which statuses you can move it to).",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_transitions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "get_transitions", issue_key=input_data["issue_key"]
    )


@action(
    name="transition_jira_issue",
    description="Move a Jira issue to a new status. Use get_jira_transitions first to find the transition ID.",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "transition_id": {
            "type": "string",
            "description": "Transition ID from get_jira_transitions.",
            "example": "31",
        },
        "comment": {
            "type": "string",
            "description": "Optional comment to add with the transition.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def transition_jira_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    return await with_client(
        "jira",
        lambda c: c.transition_issue(
            input_data["issue_key"],
            input_data["transition_id"],
            comment=input_data.get("comment") or None,
        ),
    )


# ------------------------------------------------------------------
# Assignment
# ------------------------------------------------------------------


@action(
    name="assign_jira_issue",
    description="Assign a Jira issue to a user. Use search_jira_users to find the account ID.",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "account_id": {
            "type": "string",
            "description": "Atlassian account ID. Leave empty to unassign.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def assign_jira_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    return await with_client(
        "jira",
        lambda c: c.assign_issue(
            input_data["issue_key"],
            account_id=input_data.get("account_id") or None,
        ),
    )


# ------------------------------------------------------------------
# Labels
# ------------------------------------------------------------------


@action(
    name="add_jira_labels",
    description="Add labels to a Jira issue without removing existing ones.",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "labels": {
            "type": "string",
            "description": "Comma-separated labels to add.",
            "example": "urgent,backend",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_jira_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    labels = csv_list(input_data["labels"])
    if not labels:
        return {"status": "error", "message": "No labels provided."}
    return await with_client(
        "jira",
        lambda c: c.add_labels(input_data["issue_key"], labels),
    )


@action(
    name="remove_jira_labels",
    description="Remove labels from a Jira issue.",
    action_sets=["jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "labels": {
            "type": "string",
            "description": "Comma-separated labels to remove.",
            "example": "urgent",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_jira_labels(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    labels = csv_list(input_data["labels"])
    if not labels:
        return {"status": "error", "message": "No labels provided."}
    return await with_client(
        "jira",
        lambda c: c.remove_labels(input_data["issue_key"], labels),
    )


# ------------------------------------------------------------------
# Projects & Users
# ------------------------------------------------------------------


@action(
    name="list_jira_projects",
    description="List accessible Jira projects.",
    action_sets=["jira"],
    input_schema={
        "max_results": {
            "type": "integer",
            "description": "Max projects to return.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_projects(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "get_projects",
        max_results=input_data.get("max_results", 50),
    )


@action(
    name="search_jira_users",
    description="Search for Jira users by name or email.",
    action_sets=["jira"],
    input_schema={
        "query": {
            "type": "string",
            "description": "Search string (name or email).",
            "example": "john",
        },
        "max_results": {
            "type": "integer",
            "description": "Max results.",
            "example": 10,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def search_jira_users(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    return await with_client(
        "jira",
        lambda c: c.search_users(
            input_data["query"], max_results=input_data.get("max_results", 10)
        ),
    )


# ------------------------------------------------------------------
# Watch Tag (custom: bespoke success messages, sync)
# ------------------------------------------------------------------


@action(
    name="set_jira_watch_tag",
    description="Set a mention tag to watch for in Jira comments. Only comments containing this tag (e.g. '@craftbot') will trigger events. Pass empty string to disable and receive all updates.",
    action_sets=["jira"],
    input_schema={
        "tag": {
            "type": "string",
            "description": "The mention tag to watch for in comments. e.g. '@craftbot'. Empty = disabled.",
            "example": "@craftbot",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_jira_watch_tag(input_data: dict) -> dict:
    try:
        from craftos_integrations import get_client

        client = get_client("jira")
        if not client or not client.has_credentials():
            return {"status": "error", "message": _NO_CRED_MSG}
        tag = input_data.get("tag", "").strip()
        client.set_watch_tag(tag)
        if tag:
            return {
                "status": "success",
                "message": f"Now only triggering on comments containing '{tag}'.",
            }
        return {
            "status": "success",
            "message": "Watch tag disabled. Triggering on all issue updates.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_jira_watch_tag",
    description="Get the current mention tag the Jira listener watches for in comments.",
    action_sets=["jira"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_jira_watch_tag(input_data: dict) -> dict:
    try:
        from craftos_integrations import get_client

        client = get_client("jira")
        if not client or not client.has_credentials():
            return {"status": "error", "message": _NO_CRED_MSG}
        tag = client.get_watch_tag()
        if tag:
            return {
                "status": "success",
                "tag": tag,
                "message": f"Watching for: '{tag}' in comments.",
            }
        return {
            "status": "success",
            "tag": "",
            "message": "No watch tag set. Triggering on all issue updates.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="set_jira_watch_labels",
    description="Set which labels the Jira listener watches for. Only issues with these labels will trigger events. Pass empty to watch all issues.",
    action_sets=["jira"],
    input_schema={
        "labels": {
            "type": "string",
            "description": "Comma-separated labels to watch. Empty string = watch all issues.",
            "example": "craftos,agent-task",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
def set_jira_watch_labels(input_data: dict) -> dict:
    try:
        from craftos_integrations import get_client

        client = get_client("jira")
        if not client or not client.has_credentials():
            return {"status": "error", "message": _NO_CRED_MSG}
        labels = csv_list(input_data.get("labels", ""))
        client.set_watch_labels(labels)
        if labels:
            return {
                "status": "success",
                "message": f"Now watching issues with labels: {', '.join(labels)}",
            }
        return {
            "status": "success",
            "message": "Now watching all issues (no label filter).",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@action(
    name="get_jira_watch_labels",
    description="Get the current label filter for the Jira listener.",
    action_sets=["jira"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
def get_jira_watch_labels(input_data: dict) -> dict:
    try:
        from craftos_integrations import get_client

        client = get_client("jira")
        if not client or not client.has_credentials():
            return {"status": "error", "message": _NO_CRED_MSG}
        labels = client.get_watch_labels()
        if labels:
            return {
                "status": "success",
                "labels": labels,
                "message": f"Watching: {', '.join(labels)}",
            }
        return {
            "status": "success",
            "labels": [],
            "message": "Watching all issues (no label filter).",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
