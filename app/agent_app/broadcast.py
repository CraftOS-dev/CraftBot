"""Browser handoff for the chat-driven app setup wizard."""

_wizard_open = None


def register_wizard_callback(callback):
    global _wizard_open
    _wizard_open = callback


async def broadcast_agent_app_wizard_open(payload):
    if _wizard_open is None:
        return False
    return await _wizard_open(payload)


def make_todo_broadcast_hook(callback):
    """Forward framework build todos without a legacy project registry."""
    import asyncio

    loop = asyncio.get_running_loop()

    def hook(session, todos):
        if (session.agent_app_framework_pending or session.agent_app_framework_key) and loop.is_running():
            asyncio.run_coroutine_threadsafe(callback({
                "type": "agent_app_todos",
                "data": {"projectId": f"framework-build:{session.id}", "todos": todos},
            }), loop)

    return hook
