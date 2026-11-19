"""Browser handoff for framework build progress."""


def make_todo_broadcast_hook(callback):
    """Forward framework build todos without a legacy project registry."""
    import asyncio

    loop = asyncio.get_running_loop()

    def hook(session, todos):
        if (
            session.agent_app_framework_pending or session.agent_app_framework_key
        ) and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                callback(
                    {
                        "type": "agent_app_todos",
                        "data": {
                            "projectId": f"framework-build:{session.id}",
                            "todos": todos,
                        },
                    }
                ),
                loop,
            )

    return hook
