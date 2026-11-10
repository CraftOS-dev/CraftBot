# -*- coding: utf-8 -*-
"""CraftBot storage and registration of version-coupled native actions."""

import importlib
import sys

from agent_core.core.database_interface import DatabaseInterface as BaseDatabaseInterface
from agent_core.utils.logger import logger


class DatabaseInterface(BaseDatabaseInterface):
    def __init__(self, *, data_dir="app/data", chroma_path="./chroma_db"):
        super().__init__(data_dir=data_dir, chroma_path=chroma_path)

        # Custom actions still load from STATE. These four native bindings are
        # part of the host protocol and must come from the same CODE version as
        # framework_host, even when an older copy exists in CRAFTBOT_HOME.
        # Register last without replacing any of the user's files. Reload also
        # handles a rebuilt registry in the same process (e.g. agent startup).
        name = "app.data.action.agent_app_framework_actions"
        if name in sys.modules:
            module = importlib.reload(sys.modules[name])
        else:
            module = importlib.import_module(name)
        logger.info(f"Native Agent-App actions loaded from {module.__file__}")


__all__ = ["DatabaseInterface"]
