# -*- coding: utf-8 -*-
"""CraftBot storage and registration of version-coupled native actions."""

import importlib
import sys

from agent_core.core.database_interface import DatabaseInterface as BaseDatabaseInterface
from agent_core.utils.logger import logger


# Reserved built-ins from the removed CraftBot app runtime. Saved state may
# still contain their files after an upgrade; they must not enter the catalog.
RETIRED_APP_ACTIONS = frozenset({
    "agent_app_framework_command", "agent_app_list_projects",
    "agent_app_notify_ready", "agent_app_walk_verify", "agent_app_ops_verify",
    "agent_app_restart", "agent_app_report_progress", "agent_app_report_finding",
    "agent_app_http", "agent_app_usage", "agent_app_marketplace_list",
    "agent_app_approve_triggers", "agent_app_marketplace_install",
    "agent_app_import_zip", "agent_app_import", "agent_app_convert",
    "walk_mark_feature",
})


class DatabaseInterface(BaseDatabaseInterface):
    def __init__(self, *, data_dir="app/data", chroma_path="./chroma_db"):
        super().__init__(data_dir=data_dir, chroma_path=chroma_path)

        # Custom actions still load from STATE. These native bindings are
        # part of the host protocol and must come from the same CODE version as
        # framework_host, even when an older copy exists in CRAFTBOT_HOME.
        # Register last without replacing any of the user's files. Reload also
        # handles a rebuilt registry in the same process (e.g. agent startup).
        # Retire legacy bindings even if STATE still contains older copies.
        # Remove its registration only; never rewrite the user's action files.
        from agent_core.core.action_framework.registry import registry_instance

        for name in RETIRED_APP_ACTIONS:
            registry_instance._registry.pop(name, None)
        for name in ("app.data.action.agent_app_actions", "app.data.action.agent_app_framework_actions"):
            if name in sys.modules:
                module = importlib.reload(sys.modules[name])
            else:
                module = importlib.import_module(name)
            logger.info(f"Native Agent-App actions loaded from {module.__file__}")


__all__ = ["DatabaseInterface"]
