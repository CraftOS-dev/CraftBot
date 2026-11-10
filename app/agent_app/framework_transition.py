"""Temporary routing for existing action names; never reinterpret legacy IDs."""

from app.agent_app.framework_host import get_host


def is_framework_request(input_data):
    host = get_host()
    if host is None:
        return True
    session = host.agent.session_manager.get(input_data.get("_session_id"))
    return not (session and getattr(session, "agent_app_project_id", None))


async def start_activity(activity, request, input_data):
    host = get_host()
    if host is None:
        return {
            "status": "error",
            "message": "The CraftBot app host is unavailable. Restart CraftBot to create or convert apps. Existing framework commands remain available through agent_app_framework_command.",
        }
    result = await host.workflow(activity, request)
    return {
        "status": "success",
        **result,
        "message": "The framework workflow started in its conversation. This is not a ready or verified result.",
    }


async def install_package(request):
    import uuid

    host = get_host()
    if host is None:
        return {
            "status": "error",
            "message": "The CraftBot app host is unavailable. Restart CraftBot to track installation, or use agent_app_framework_command with the upstream install command.",
        }
    job = await host.start_install(request, uuid.uuid4().hex)
    return {
        "status": "success",
        "job": job,
        "message": "Installation started. Successfully registered apps appear under Agent App. No agent run was started.",
    }
