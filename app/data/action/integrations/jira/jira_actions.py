from agent_core import action
from app.utils import csv_list


_NO_CRED_MSG = "No Jira credential. Use /jira login first."


# ------------------------------------------------------------------
# Issues — search, get, create, update, delete, transition, assign
# Sub-set: jira_issues
# ------------------------------------------------------------------


@action(
    name="search_jira_issues",
    description="Search for Jira issues using JQL (Jira Query Language). Returns lean issues (summary, description, status, assignee, priority, issuetype, labels, dates) by default; set include_metadata=true for all fields incl. custom fields.",
    action_sets=["jira_issues", "jira"],
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
            "description": "Comma-separated fields to return. Leave empty for lean defaults.",
            "example": "summary,status,assignee,priority",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return every field (incl. customfield_*) with full nested objects.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "total + issues. Lean: default field set, status/assignee/priority/issuetype collapsed to names. Full payload when include_metadata=true.",
        },
    },
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
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="get_jira_issue",
    description="Get details of a specific Jira issue by its key (e.g. PROJ-123). Returns lean fields (summary, description, status, assignee, priority, issuetype, labels, dates) by default; set include_metadata=true for all fields incl. custom fields.",
    action_sets=["jira_issues", "jira"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "fields": {
            "type": "string",
            "description": "Comma-separated fields to return. Leave empty for lean defaults.",
            "example": "summary,status,assignee,description",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return every field (incl. customfield_*) with full nested objects.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: default field set, status/assignee/priority/issuetype collapsed to names. Full payload when include_metadata=true.",
        },
    },
)
async def get_jira_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import with_client

    fields_list = csv_list(input_data.get("fields", ""), default=None)
    return await with_client(
        "jira",
        lambda c: c.get_issue(
            input_data["issue_key"],
            fields_list=fields_list,
            include_metadata=bool(input_data.get("include_metadata", False)),
        ),
    )


@action(
    name="create_jira_issue",
    description="Create a new Jira issue in a project.",
    action_sets=["jira_issues", "jira"],
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
    action_sets=["jira_issues", "jira"],
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


@action(
    name="delete_jira_issue",
    description="Delete a Jira issue. Can optionally cascade-delete subtasks.",
    action_sets=["jira_issues"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "delete_subtasks": {
            "type": "boolean",
            "description": "Also delete subtasks.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_issue(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "delete_issue",
        issue_key=input_data["issue_key"],
        delete_subtasks=input_data.get("delete_subtasks", False),
    )


@action(
    name="get_jira_transitions",
    description="Get available status transitions for a Jira issue (to know which statuses you can move it to).",
    action_sets=["jira_issues", "jira"],
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
    action_sets=["jira_issues", "jira"],
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


@action(
    name="assign_jira_issue",
    description="Assign a Jira issue to a user. Use search_jira_users to find the account ID.",
    action_sets=["jira_issues", "jira"],
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


@action(
    name="add_jira_labels",
    description="Add labels to a Jira issue without removing existing ones.",
    action_sets=["jira_issues"],
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
    action_sets=["jira_issues"],
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


@action(
    name="get_jira_issue_watchers",
    description="Get the list of watchers on a Jira issue.",
    action_sets=["jira_issues"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_issue_watchers(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "get_watchers", issue_key=input_data["issue_key"])


@action(
    name="add_jira_issue_watcher",
    description="Add a user as a watcher on a Jira issue.",
    action_sets=["jira_issues"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "account_id": {
            "type": "string",
            "description": "Atlassian account ID of user to add.",
            "example": "557058:...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_jira_issue_watcher(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "add_watcher",
        issue_key=input_data["issue_key"],
        account_id=input_data["account_id"],
    )


@action(
    name="remove_jira_issue_watcher",
    description="Remove a watcher from a Jira issue.",
    action_sets=["jira_issues"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "account_id": {
            "type": "string",
            "description": "Atlassian account ID of user to remove.",
            "example": "557058:...",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def remove_jira_issue_watcher(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "remove_watcher",
        issue_key=input_data["issue_key"],
        account_id=input_data["account_id"],
    )


# ------------------------------------------------------------------
# Comments — add, get, edit, delete
# Sub-set: jira_comments
# ------------------------------------------------------------------


@action(
    name="add_jira_comment",
    description="Add a comment to a Jira issue.",
    action_sets=["jira_comments", "jira"],
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
    action_sets=["jira_comments", "jira"],
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


@action(
    name="update_jira_comment",
    description="Edit the body of an existing comment.",
    action_sets=["jira_comments"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "comment_id": {
            "type": "string",
            "description": "Comment ID.",
            "example": "10001",
        },
        "body": {
            "type": "string",
            "description": "New comment text.",
            "example": "Edited comment.",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_jira_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "update_comment",
        issue_key=input_data["issue_key"],
        comment_id=input_data["comment_id"],
        body=input_data["body"],
    )


@action(
    name="delete_jira_comment",
    description="Delete a comment from a Jira issue.",
    action_sets=["jira_comments"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "comment_id": {
            "type": "string",
            "description": "Comment ID.",
            "example": "10001",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_comment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "delete_comment",
        issue_key=input_data["issue_key"],
        comment_id=input_data["comment_id"],
    )


# ------------------------------------------------------------------
# Attachments — upload, get, download, delete
# Sub-set: jira_attachments
# ------------------------------------------------------------------


@action(
    name="add_jira_attachment",
    description="Upload a local file as an attachment on a Jira issue.",
    action_sets=["jira_attachments"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "file_path": {
            "type": "string",
            "description": "Local file path to upload.",
            "example": "/tmp/screenshot.png",
        },
        "filename": {
            "type": "string",
            "description": "Optional override filename.",
            "example": "screenshot.png",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_jira_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "add_attachment",
        issue_key=input_data["issue_key"],
        file_path=input_data["file_path"],
        filename=input_data.get("filename") or None,
    )


@action(
    name="get_jira_attachment",
    description="Get metadata for a specific attachment by ID.",
    action_sets=["jira_attachments"],
    input_schema={
        "attachment_id": {
            "type": "string",
            "description": "Attachment ID.",
            "example": "10001",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "get_attachment", attachment_id=input_data["attachment_id"]
    )


@action(
    name="delete_jira_attachment",
    description="Delete an attachment by ID.",
    action_sets=["jira_attachments"],
    input_schema={
        "attachment_id": {
            "type": "string",
            "description": "Attachment ID.",
            "example": "10001",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "delete_attachment", attachment_id=input_data["attachment_id"]
    )


@action(
    name="download_jira_attachment",
    description="Download an attachment's bytes to a local file path.",
    action_sets=["jira_attachments"],
    input_schema={
        "attachment_id": {
            "type": "string",
            "description": "Attachment ID.",
            "example": "10001",
        },
        "dest_path": {
            "type": "string",
            "description": "Local destination path.",
            "example": "/tmp/saved.png",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def download_jira_attachment(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "download_attachment",
        attachment_id=input_data["attachment_id"],
        dest_path=input_data["dest_path"],
    )


# ------------------------------------------------------------------
# Worklogs — add, list, update, delete
# Sub-set: jira_worklogs
# ------------------------------------------------------------------


@action(
    name="add_jira_worklog",
    description="Log time spent on a Jira issue.",
    action_sets=["jira_worklogs"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "time_spent": {
            "type": "string",
            "description": "Jira-style duration (e.g. '2h 30m', '1d').",
            "example": "2h 30m",
        },
        "time_spent_seconds": {
            "type": "integer",
            "description": "Alternative to time_spent: total seconds.",
            "example": 9000,
        },
        "comment": {
            "type": "string",
            "description": "Optional worklog comment.",
            "example": "Implemented feature",
        },
        "started": {
            "type": "string",
            "description": "Optional ISO start time, e.g. '2026-05-21T09:00:00.000+0000'.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def add_jira_worklog(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "add_worklog",
        issue_key=input_data["issue_key"],
        time_spent=input_data.get("time_spent") or None,
        time_spent_seconds=input_data.get("time_spent_seconds"),
        comment=input_data.get("comment") or None,
        started=input_data.get("started") or None,
    )


@action(
    name="get_jira_worklogs",
    description="Get worklog entries for an issue.",
    action_sets=["jira_worklogs"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_worklogs(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "get_worklogs", issue_key=input_data["issue_key"])


@action(
    name="update_jira_worklog",
    description="Edit an existing worklog entry.",
    action_sets=["jira_worklogs"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "worklog_id": {
            "type": "string",
            "description": "Worklog ID.",
            "example": "10010",
        },
        "time_spent": {
            "type": "string",
            "description": "Jira-style duration.",
            "example": "3h",
        },
        "time_spent_seconds": {
            "type": "integer",
            "description": "Total seconds.",
            "example": 10800,
        },
        "comment": {"type": "string", "description": "New comment.", "example": ""},
        "started": {"type": "string", "description": "ISO start time.", "example": ""},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def update_jira_worklog(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "update_worklog",
        issue_key=input_data["issue_key"],
        worklog_id=input_data["worklog_id"],
        time_spent=input_data.get("time_spent") or None,
        time_spent_seconds=input_data.get("time_spent_seconds"),
        comment=input_data.get("comment") or None,
        started=input_data.get("started") or None,
    )


@action(
    name="delete_jira_worklog",
    description="Delete a worklog entry.",
    action_sets=["jira_worklogs"],
    input_schema={
        "issue_key": {
            "type": "string",
            "description": "Issue key.",
            "example": "PROJ-123",
        },
        "worklog_id": {
            "type": "string",
            "description": "Worklog ID.",
            "example": "10010",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_worklog(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "delete_worklog",
        issue_key=input_data["issue_key"],
        worklog_id=input_data["worklog_id"],
    )


# ------------------------------------------------------------------
# Issue links — create, get, delete, list types
# Sub-set: jira_links
# ------------------------------------------------------------------


@action(
    name="create_jira_issue_link",
    description="Link two issues together (e.g. 'blocks', 'relates to'). Use list_jira_issue_link_types to discover names.",
    action_sets=["jira_links"],
    input_schema={
        "link_type": {
            "type": "string",
            "description": "Link type name (e.g. 'Blocks', 'Relates').",
            "example": "Blocks",
        },
        "inward_issue_key": {
            "type": "string",
            "description": "Issue on the inward side.",
            "example": "PROJ-1",
        },
        "outward_issue_key": {
            "type": "string",
            "description": "Issue on the outward side.",
            "example": "PROJ-2",
        },
        "comment": {
            "type": "string",
            "description": "Optional comment on the source.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_jira_issue_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "create_issue_link",
        link_type=input_data["link_type"],
        inward_issue_key=input_data["inward_issue_key"],
        outward_issue_key=input_data["outward_issue_key"],
        comment=input_data.get("comment") or None,
    )


@action(
    name="get_jira_issue_link",
    description="Get a specific issue link by ID. Returns lean fields (id, type name, linked issue keys/summaries/statuses) by default; set include_metadata=true for the raw payload.",
    action_sets=["jira_links"],
    input_schema={
        "link_id": {
            "type": "string",
            "description": "Issue link ID.",
            "example": "10000",
        },
        "include_metadata": {
            "type": "boolean",
            "description": "Return the full raw API payload instead of lean fields.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Lean: id, type, inwardIssue/outwardIssue {key, summary, status}. Raw payload when include_metadata=true.",
        },
    },
)
async def get_jira_issue_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "get_issue_link",
        link_id=input_data["link_id"],
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="delete_jira_issue_link",
    description="Delete a specific issue link.",
    action_sets=["jira_links"],
    input_schema={
        "link_id": {
            "type": "string",
            "description": "Issue link ID.",
            "example": "10000",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_issue_link(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "delete_issue_link", link_id=input_data["link_id"])


@action(
    name="list_jira_issue_link_types",
    description="List the available issue link types (Blocks, Relates, Duplicate, etc.).",
    action_sets=["jira_links"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_issue_link_types(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "list_issue_link_types")


# ------------------------------------------------------------------
# Projects / Versions / Components / Users / Metadata
# Sub-set: jira_projects
# ------------------------------------------------------------------


@action(
    name="list_jira_projects",
    description="List accessible Jira projects.",
    action_sets=["jira_projects", "jira"],
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
    name="get_jira_project",
    description="Get information about a single Jira project.",
    action_sets=["jira_projects"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Project key.",
            "example": "PROJ",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_project(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "get_project", project_key=input_data["project_key"]
    )


@action(
    name="search_jira_users",
    description="Search for Jira users by name or email.",
    action_sets=["jira_projects", "jira"],
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


@action(
    name="list_jira_priorities",
    description="List available issue priorities (e.g. High, Medium, Low).",
    action_sets=["jira_projects"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_priorities(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "list_priorities")


@action(
    name="list_jira_issue_types",
    description="List available issue types (Task, Bug, Story, etc.).",
    action_sets=["jira_projects"],
    input_schema={},
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_issue_types(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "list_issue_types")


@action(
    name="list_jira_versions",
    description="List versions for a project (releases/fix versions).",
    action_sets=["jira_projects"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Project key.",
            "example": "PROJ",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_versions(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "list_versions", project_key=input_data["project_key"]
    )


@action(
    name="create_jira_version",
    description="Create a new version for a project.",
    action_sets=["jira_projects"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Project key.",
            "example": "PROJ",
        },
        "name": {"type": "string", "description": "Version name.", "example": "v1.0"},
        "description": {
            "type": "string",
            "description": "Optional description.",
            "example": "",
        },
        "release_date": {
            "type": "string",
            "description": "Optional release date (YYYY-MM-DD).",
            "example": "2026-06-30",
        },
        "start_date": {
            "type": "string",
            "description": "Optional start date (YYYY-MM-DD).",
            "example": "",
        },
        "released": {
            "type": "boolean",
            "description": "Mark as released.",
            "example": False,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_jira_version(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "create_version",
        project_key=input_data["project_key"],
        name=input_data["name"],
        description=input_data.get("description") or None,
        release_date=input_data.get("release_date") or None,
        start_date=input_data.get("start_date") or None,
        released=input_data.get("released", False),
    )


@action(
    name="update_jira_version",
    description="Update a Jira version (e.g. mark as released, archived). Returns id, name, released.",
    action_sets=["jira_projects"],
    input_schema={
        "version_id": {
            "type": "string",
            "description": "Version ID.",
            "example": "10001",
        },
        "name": {"type": "string", "description": "New name.", "example": ""},
        "description": {
            "type": "string",
            "description": "New description.",
            "example": "",
        },
        "release_date": {
            "type": "string",
            "description": "New release date.",
            "example": "",
        },
        "released": {
            "type": "boolean",
            "description": "Set released flag.",
            "example": True,
        },
        "archived": {
            "type": "boolean",
            "description": "Set archived flag.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Updated version: id, name, released.",
        },
    },
    parallelizable=False,
)
async def update_jira_version(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "jira",
        "update_version",
        version_id=input_data["version_id"],
        name=input_data.get("name") or None,
        description=input_data.get("description") or None,
        release_date=input_data.get("release_date") or None,
        released=input_data.get("released"),
        archived=input_data.get("archived"),
    )
    return pick_result(res, ["id", "name", "released"])


@action(
    name="delete_jira_version",
    description="Delete a Jira version.",
    action_sets=["jira_projects"],
    input_schema={
        "version_id": {
            "type": "string",
            "description": "Version ID.",
            "example": "10001",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_version(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "delete_version", version_id=input_data["version_id"]
    )


@action(
    name="list_jira_components",
    description="List components for a project.",
    action_sets=["jira_projects"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Project key.",
            "example": "PROJ",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_components(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "list_components", project_key=input_data["project_key"]
    )


@action(
    name="create_jira_component",
    description="Create a new component within a project.",
    action_sets=["jira_projects"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Project key.",
            "example": "PROJ",
        },
        "name": {
            "type": "string",
            "description": "Component name.",
            "example": "Backend",
        },
        "description": {
            "type": "string",
            "description": "Optional description.",
            "example": "",
        },
        "lead_account_id": {
            "type": "string",
            "description": "Optional component lead account ID.",
            "example": "",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_jira_component(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "create_component",
        project_key=input_data["project_key"],
        name=input_data["name"],
        description=input_data.get("description") or None,
        lead_account_id=input_data.get("lead_account_id") or None,
    )


@action(
    name="delete_jira_component",
    description="Delete a project component.",
    action_sets=["jira_projects"],
    input_schema={
        "component_id": {
            "type": "string",
            "description": "Component ID.",
            "example": "10100",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_component(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "delete_component", component_id=input_data["component_id"]
    )


@action(
    name="list_jira_project_statuses",
    description="List the status workflow for a project (issue statuses grouped by issue type).",
    action_sets=["jira_projects"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Project key.",
            "example": "PROJ",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_project_statuses(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira", "get_statuses", project_key=input_data["project_key"]
    )


# ------------------------------------------------------------------
# Agile — Boards, Sprints, Epics, Backlog
# Sub-set: jira_sprints
# ------------------------------------------------------------------


@action(
    name="list_jira_boards",
    description="List Agile boards (Scrum/Kanban). Optionally filter by project or type.",
    action_sets=["jira_sprints", "jira"],
    input_schema={
        "project_key": {
            "type": "string",
            "description": "Optional project key filter.",
            "example": "PROJ",
        },
        "board_type": {
            "type": "string",
            "description": "Optional 'scrum' or 'kanban'.",
            "example": "scrum",
        },
        "max_results": {
            "type": "integer",
            "description": "Max boards to return.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def list_jira_boards(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "list_boards",
        project_key=input_data.get("project_key") or None,
        board_type=input_data.get("board_type") or None,
        max_results=input_data.get("max_results", 50),
    )


@action(
    name="get_jira_board",
    description="Get details of a specific Agile board.",
    action_sets=["jira_sprints"],
    input_schema={
        "board_id": {"type": "integer", "description": "Board ID.", "example": 1},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_board(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "get_board", board_id=input_data["board_id"])


@action(
    name="get_jira_board_issues",
    description="List issues currently on a board. Returns lean issues (summary, description, status, assignee, priority, issuetype, labels, dates) by default; set include_metadata=true for all fields incl. custom fields.",
    action_sets=["jira_sprints"],
    input_schema={
        "board_id": {"type": "integer", "description": "Board ID.", "example": 1},
        "jql": {"type": "string", "description": "Optional JQL filter.", "example": ""},
        "max_results": {"type": "integer", "description": "Max issues.", "example": 50},
        "include_metadata": {
            "type": "boolean",
            "description": "Return every field (incl. customfield_*) with full nested objects.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "total + issues. Lean: default field set, status/assignee/priority/issuetype collapsed to names. Full payload when include_metadata=true.",
        },
    },
)
async def get_jira_board_issues(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "get_board_issues",
        board_id=input_data["board_id"],
        jql=input_data.get("jql") or None,
        max_results=input_data.get("max_results", 50),
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="get_jira_board_sprints",
    description="List sprints on a board (optionally filter by state).",
    action_sets=["jira_sprints", "jira"],
    input_schema={
        "board_id": {"type": "integer", "description": "Board ID.", "example": 1},
        "state": {
            "type": "string",
            "description": "Comma-separated states: 'active,closed,future'.",
            "example": "active",
        },
        "max_results": {
            "type": "integer",
            "description": "Max sprints.",
            "example": 50,
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_board_sprints(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "get_board_sprints",
        board_id=input_data["board_id"],
        state=input_data.get("state") or None,
        max_results=input_data.get("max_results", 50),
    )


@action(
    name="get_jira_board_backlog",
    description="Get the backlog issues for a board (issues not yet in any sprint). Returns lean issues by default; set include_metadata=true for all fields incl. custom fields.",
    action_sets=["jira_sprints"],
    input_schema={
        "board_id": {"type": "integer", "description": "Board ID.", "example": 1},
        "max_results": {"type": "integer", "description": "Max issues.", "example": 50},
        "include_metadata": {
            "type": "boolean",
            "description": "Return every field (incl. customfield_*) with full nested objects.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "total + issues. Lean: default field set, status/assignee/priority/issuetype collapsed to names. Full payload when include_metadata=true.",
        },
    },
)
async def get_jira_board_backlog(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "get_board_backlog",
        board_id=input_data["board_id"],
        max_results=input_data.get("max_results", 50),
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="get_jira_sprint",
    description="Get details of a specific sprint.",
    action_sets=["jira_sprints"],
    input_schema={
        "sprint_id": {"type": "integer", "description": "Sprint ID.", "example": 42},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_sprint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "get_sprint", sprint_id=input_data["sprint_id"])


@action(
    name="get_jira_sprint_issues",
    description="List issues in a sprint. Returns lean issues by default; set include_metadata=true for all fields incl. custom fields.",
    action_sets=["jira_sprints", "jira"],
    input_schema={
        "sprint_id": {"type": "integer", "description": "Sprint ID.", "example": 42},
        "jql": {"type": "string", "description": "Optional JQL filter.", "example": ""},
        "max_results": {"type": "integer", "description": "Max issues.", "example": 50},
        "include_metadata": {
            "type": "boolean",
            "description": "Return every field (incl. customfield_*) with full nested objects.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "total + issues. Lean: default field set, status/assignee/priority/issuetype collapsed to names. Full payload when include_metadata=true.",
        },
    },
)
async def get_jira_sprint_issues(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "get_sprint_issues",
        sprint_id=input_data["sprint_id"],
        jql=input_data.get("jql") or None,
        max_results=input_data.get("max_results", 50),
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="create_jira_sprint",
    description="Create a new sprint on a board.",
    action_sets=["jira_sprints"],
    input_schema={
        "board_id": {
            "type": "integer",
            "description": "Origin board ID.",
            "example": 1,
        },
        "name": {
            "type": "string",
            "description": "Sprint name.",
            "example": "Sprint 23",
        },
        "goal": {
            "type": "string",
            "description": "Optional sprint goal.",
            "example": "",
        },
        "start_date": {
            "type": "string",
            "description": "ISO start date.",
            "example": "2026-05-21T00:00:00.000Z",
        },
        "end_date": {
            "type": "string",
            "description": "ISO end date.",
            "example": "2026-06-04T00:00:00.000Z",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def create_jira_sprint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "create_sprint",
        name=input_data["name"],
        board_id=input_data["board_id"],
        goal=input_data.get("goal") or None,
        start_date=input_data.get("start_date") or None,
        end_date=input_data.get("end_date") or None,
    )


@action(
    name="update_jira_sprint",
    description="Update a sprint's name, state (active/closed/future), goal, or dates. Returns id, name, state.",
    action_sets=["jira_sprints"],
    input_schema={
        "sprint_id": {"type": "integer", "description": "Sprint ID.", "example": 42},
        "name": {"type": "string", "description": "New name.", "example": ""},
        "state": {
            "type": "string",
            "description": "'active' (start) or 'closed' (complete).",
            "example": "",
        },
        "goal": {"type": "string", "description": "New goal.", "example": ""},
        "start_date": {
            "type": "string",
            "description": "ISO start date.",
            "example": "",
        },
        "end_date": {"type": "string", "description": "ISO end date.", "example": ""},
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "Updated sprint: id, name, state.",
        },
    },
    parallelizable=False,
)
async def update_jira_sprint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import pick_result, run_client

    res = await run_client(
        "jira",
        "update_sprint",
        sprint_id=input_data["sprint_id"],
        name=input_data.get("name") or None,
        state=input_data.get("state") or None,
        goal=input_data.get("goal") or None,
        start_date=input_data.get("start_date") or None,
        end_date=input_data.get("end_date") or None,
    )
    return pick_result(res, ["id", "name", "state"])


@action(
    name="delete_jira_sprint",
    description="Delete a sprint.",
    action_sets=["jira_sprints"],
    input_schema={
        "sprint_id": {"type": "integer", "description": "Sprint ID.", "example": 42},
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def delete_jira_sprint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "delete_sprint", sprint_id=input_data["sprint_id"])


@action(
    name="move_issues_to_jira_sprint",
    description="Move one or more issues into a sprint.",
    action_sets=["jira_sprints", "jira"],
    input_schema={
        "sprint_id": {
            "type": "integer",
            "description": "Target sprint ID.",
            "example": 42,
        },
        "issue_keys": {
            "type": "string",
            "description": "Comma-separated issue keys.",
            "example": "PROJ-1,PROJ-2",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def move_issues_to_jira_sprint(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    keys = csv_list(input_data["issue_keys"])
    if not keys:
        return {"status": "error", "message": "No issue keys provided."}
    return await run_client(
        "jira",
        "move_issues_to_sprint",
        sprint_id=input_data["sprint_id"],
        issue_keys=keys,
    )


@action(
    name="move_issues_to_jira_backlog",
    description="Move issues back to the backlog (remove from current sprint).",
    action_sets=["jira_sprints"],
    input_schema={
        "issue_keys": {
            "type": "string",
            "description": "Comma-separated issue keys.",
            "example": "PROJ-1,PROJ-2",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def move_issues_to_jira_backlog(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    keys = csv_list(input_data["issue_keys"])
    if not keys:
        return {"status": "error", "message": "No issue keys provided."}
    return await run_client("jira", "move_issues_to_backlog", issue_keys=keys)


@action(
    name="get_jira_epic",
    description="Get details of an epic.",
    action_sets=["jira_sprints"],
    input_schema={
        "epic_key": {
            "type": "string",
            "description": "Epic key or ID.",
            "example": "PROJ-100",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
)
async def get_jira_epic(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client("jira", "get_epic", epic_id_or_key=input_data["epic_key"])


@action(
    name="get_jira_epic_issues",
    description="List child issues of an epic. Returns lean issues by default; set include_metadata=true for all fields incl. custom fields.",
    action_sets=["jira_sprints"],
    input_schema={
        "epic_key": {
            "type": "string",
            "description": "Epic key or ID.",
            "example": "PROJ-100",
        },
        "max_results": {"type": "integer", "description": "Max issues.", "example": 50},
        "include_metadata": {
            "type": "boolean",
            "description": "Return every field (incl. customfield_*) with full nested objects.",
            "example": False,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success"},
        "result": {
            "type": "object",
            "description": "total + issues. Lean: default field set, status/assignee/priority/issuetype collapsed to names. Full payload when include_metadata=true.",
        },
    },
)
async def get_jira_epic_issues(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    return await run_client(
        "jira",
        "get_epic_issues",
        epic_id_or_key=input_data["epic_key"],
        max_results=input_data.get("max_results", 50),
        include_metadata=bool(input_data.get("include_metadata", False)),
    )


@action(
    name="move_issues_to_jira_epic",
    description="Move issues to an epic (use 'none' as epic key to unlink from epic).",
    action_sets=["jira_sprints"],
    input_schema={
        "epic_key": {
            "type": "string",
            "description": "Epic key, or 'none' to unlink.",
            "example": "PROJ-100",
        },
        "issue_keys": {
            "type": "string",
            "description": "Comma-separated issue keys.",
            "example": "PROJ-1,PROJ-2",
        },
    },
    output_schema={"status": {"type": "string", "example": "success"}},
    parallelizable=False,
)
async def move_issues_to_jira_epic(input_data: dict) -> dict:
    from app.data.action.integrations._helpers import run_client

    keys = csv_list(input_data["issue_keys"])
    if not keys:
        return {"status": "error", "message": "No issue keys provided."}
    return await run_client(
        "jira",
        "move_issues_to_epic",
        epic_id_or_key=input_data["epic_key"],
        issue_keys=keys,
    )


# ------------------------------------------------------------------
# Listener configuration (bespoke success messages, sync)
# Sub-set: jira_listener
# ------------------------------------------------------------------


@action(
    name="set_jira_watch_tag",
    description="Set a mention tag to watch for in Jira comments. Only comments containing this tag (e.g. '@craftbot') will trigger events. Pass empty string to disable and receive all updates.",
    action_sets=["jira_listener"],
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
    action_sets=["jira_listener"],
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
    action_sets=["jira_listener"],
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
    action_sets=["jira_listener"],
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
