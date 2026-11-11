"""Native actions backed by the unchanged Agent-App framework."""

from agent_core import action


@action(
    name="agent_app_framework_verification",
    description="Read independent verification status for an app. Use agent_app_framework_workflow(activity='verify') to await a verifier subagent; CraftBot records its verdict. Report is reserved for already-assigned legacy verifier runs. A pass must cover the current upstream validation stamp.",
    default=False,
    mode="CLI",
    action_sets=["agent_app"],
    parallelizable=False,
    input_schema={
        "operation": {"type": "string", "enum": ["status", "report"], "required": True},
        "path": {"type": "string", "required": False},
        "verdict": {
            "type": "string",
            "enum": ["pass", "defects", "incomplete", "blocked"],
            "required": False,
        },
        "evidence": {"type": "string", "required": False},
    },
    output_schema={
        "status": {"type": "string"},
        "data": {"type": "object"},
        "message": {"type": "string"},
    },
    test_payload={"simulated_mode": True},
)
async def agent_app_framework_verification(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "data": None}
    from app.agent_app.framework_host import get_host
    from agent_core.core.state.session import StateSession

    host = get_host()
    if host is None:
        return {"status": "error", "message": "The native app host is unavailable."}
    try:
        if input_data["operation"] == "status":
            result = host.verification(input_data["path"])
        elif input_data["operation"] == "report":
            state = StateSession.bound()
            result = host.report_verification(
                input_data.get("_session_id") or (state.session_id if state else ""),
                input_data.get("verdict"),
                input_data.get("evidence"),
            )
            await host.verification_reported(result)
        else:
            raise ValueError("Choose status or report.")
        return {"status": "success", "data": result}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@action(
    name="agent_app_framework_workflow",
    description="Start the unchanged Agent-App creator, modify or importer workflow. Use the a2app action set to connect to or operate existing apps. For activity='verify', run the installed walk-verify skill in an independent CraftBot subagent and WAIT for its verdict in this action's verification field. It creates no separate chat. Run validate first. Repair defects, validate again and re-run verify before promotion; never treat queued/running/blocked/incomplete as pass.",
    default=False,
    mode="CLI",
    action_sets=["agent_app"],
    parallelizable=False,
    input_schema={
        "activity": {
            "type": "string",
            "enum": ["create", "modify", "import", "convert", "verify"],
            "required": True,
        },
        "request": {"type": "string", "required": True},
        "path": {"type": "string", "required": False},
        "app_id": {"type": "string", "required": False},
    },
    output_schema={
        "status": {"type": "string"},
        "sessionId": {"type": "string"},
        "childTaskId": {"type": "string"},
        "verification": {"type": "object"},
        "message": {"type": "string"},
    },
    test_payload={"simulated_mode": True},
)
async def agent_app_framework_workflow(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "sessionId": "simulated"}
    from app.agent_app.framework_host import get_host
    from agent_core.core.state.session import StateSession

    host = get_host()
    if host is None:
        return {
            "status": "error",
            "message": "The native CraftBot app host is unavailable.",
        }
    try:
        state = StateSession.bound()
        parent_session_id = input_data.get("_session_id") or (
            state.session_id if state else None
        )
        if input_data["activity"] == "verify" and not parent_session_id:
            raise ValueError("Independent verification needs the calling conversation.")
        result = await host.workflow(
            input_data["activity"],
            input_data["request"],
            input_data.get("path"),
            input_data.get("app_id"),
            parent_session_id=parent_session_id,
        )
        return {"status": "success", **result}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@action(
    name="agent_app_command",
    description=(
        "Build, evolve and manage apps through the bundled unchanged agent-app CLI: "
        "scaffold/dev/validate/promote/serve/stop/backup/restore/export/bridge/"
        "owner/invite/remove. Use a2app_command to connect, inspect and operate app data. "
        "args is a literal argument array, starting with an absolute app directory "
        "or remote URL for app commands. Registry commands such as blueprints, "
        "skills, catalogue, inspect and install need no app prefix. Use --help "
        "for upstream syntax. Follow framework-* skills. "
        "For app requests to "
        "CraftBot, use the app settings' Allow requests to CraftBot control; "
        "an unqualified bridge start uses an external default harness. No shell expansion."
    ),
    default=False,
    mode="CLI",
    action_sets=["agent_app"],
    parallelizable=False,
    input_schema={
        "args": {"type": "array", "items": {"type": "string"}, "required": True},
        "cwd": {
            "type": "string",
            "required": False,
            "description": "Optional absolute working directory.",
        },
    },
    output_schema={
        "status": {"type": "string"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "data": {"type": "object"},
        "exit_code": {"type": "integer"},
        "message": {"type": "string"},
    },
    test_payload={"simulated_mode": True},
)
async def agent_app_command(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "stdout": "", "exit_code": 0}
    try:
        from app.agent_app.framework_commands import command

        return await command(
            "agent-app", input_data["args"], cwd=input_data.get("cwd")
        )
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@action(
    name="a2app_command",
    description=(
        "Connect to, inspect and control apps through the bundled unchanged a2app CLI. "
        "Discover modules and operations, read current context, invoke operations, "
        "and report task progress/completion. args is a literal argument array, "
        "starting with the absolute app directory or remote URL. Start at the root "
        "and follow its discovery screens; use --help for upstream syntax. Follow "
        "framework-operator or framework-connect. No shell expansion. "
        "For builds and lifecycle changes, load agent_app and use agent_app_command."
    ),
    default=False,
    mode="CLI",
    action_sets=["a2app"],
    parallelizable=False,
    input_schema={
        "args": {"type": "array", "items": {"type": "string"}, "required": True},
        "cwd": {
            "type": "string",
            "required": False,
            "description": "Optional absolute working directory.",
        },
    },
    output_schema={
        "status": {"type": "string"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "data": {"type": "object"},
        "exit_code": {"type": "integer"},
        "message": {"type": "string"},
    },
    test_payload={"simulated_mode": True},
)
async def a2app_command(input_data: dict) -> dict:
    if input_data.get("simulated_mode"):
        return {"status": "success", "stdout": "", "exit_code": 0}
    try:
        from app.agent_app.framework_commands import command

        return await command("a2app", input_data["args"], cwd=input_data.get("cwd"))
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@action(
    name="agent_app_framework_list",
    description=(
        "List apps in the Agent-App framework registry, including canonical app "
        "IDs, paths, derived status and connected apps. Uses CraftBot's "
        "bundled framework CLI."
    ),
    default=False,
    mode="CLI",
    action_sets=["a2app"],
    parallelizable=True,
    input_schema={},
    output_schema={
        "status": {"type": "string", "description": "'success' or 'error'."},
        "data": {
            "type": "object",
            "description": (
                "Unmodified framework JSON on success: ok, registry, apps, "
                "connected. IDs belong to the framework registry."
            ),
        },
        "exit_code": {"type": "integer", "description": "CLI exit code, if run."},
        "stderr": {"type": "string", "description": "CLI diagnostics, if run."},
        "stdout": {"type": "string", "description": "Raw CLI output on failure."},
        "message": {"type": "string", "description": "Failure explanation."},
    },
    test_payload={"simulated_mode": True},
)
async def agent_app_framework_list(input_data: dict) -> dict:
    if input_data.get("simulated_mode", False):
        return {
            "status": "success",
            "data": {"ok": True, "apps": [], "connected": []},
            "exit_code": 0,
            "stderr": "",
        }
    try:
        # CraftBot extracts only this function's source for execution, so its
        # imports must live here rather than depend on module-level helpers.
        from app.agent_app.framework import list_apps

        return await list_apps()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
