# -*- coding: utf-8 -*-
"""Living UI domain workflow.

This package owns everything the domain's agents ARE and DO: the conductor
workflow (workflow.py), its deterministic step brain (steps.py), its
specialists (subagents/), and the build machinery they verify with
(workspace.py, verifiers.py). The PLATFORM the steps operate on (project
lifecycle, launch pipeline, CLI, data plane) lives in app/living_ui.
"""

from app.workflows.living_ui import subagents  # noqa: F401
from app.workflows.living_ui import workflow  # noqa: F401
