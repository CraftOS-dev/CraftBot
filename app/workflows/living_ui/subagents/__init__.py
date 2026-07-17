# -*- coding: utf-8 -*-
"""Living UI's specialists — registered at import time.

``coding_agent`` builds; ``walk_verify`` independently confirms the built
app actually works. The domain owns its specialists; registration is
triggered by ``app.subagent``'s import of the workflow packages.
"""

from app.workflows.living_ui.subagents import coding_agent  # noqa: F401
from app.workflows.living_ui.subagents import walk_verify  # noqa: F401
