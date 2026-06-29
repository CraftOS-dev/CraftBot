# -*- coding: utf-8 -*-
"""
Sub-agent type definitions.

Each module in this package defines exactly one sub-agent type and calls
:func:`app.subagent.registry.register_subagent` at import time. Importing
this package registers all of them.

To add a new sub-agent type:

1. Create ``app/subagent/definitions/your_agent.py`` modeled on the
   existing files (system prompt, actions list, caps, single
   :func:`register_subagent` call at module level).
2. Add ``from app.subagent.definitions import your_agent`` to the
   imports below so it loads on package import.
3. Update the ``enum`` and description in
   ``app/data/action/spawn_subagent.py`` so the spawning agent knows the
   new type exists.

Do NOT include ``sub_task_end`` in the actions list — the registry
auto-injects it as the universal terminator.
"""

from app.subagent.definitions import research_agent  # noqa: F401
from app.subagent.definitions import validation_agent  # noqa: F401
