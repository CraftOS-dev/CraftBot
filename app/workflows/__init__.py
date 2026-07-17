# -*- coding: utf-8 -*-
"""THE WORKFLOW LAYER — what each domain's agents do.

One folder per domain; each domain package owns its complete agentic
story: the workflow definition (prompts + registration), its step program
(when deterministic), and its specialist sub-agents. Importing this
package registers everything.

    app/workflows/<domain>/
        workflow.py      # prompts + register_workflow(...)
        steps.py         # step program / decision table (optional)
        subagents/*.py   # the domain's specialists (register_subagent)

Layer mnemonic: app/agentic = HOW agents run · app/workflows = WHAT each
domain's agents do · app/living_ui = the PRODUCT they build on.

To add a domain: create the folder, then import it below.
"""

from app.workflows import base  # noqa: F401
from app.workflows import common  # noqa: F401
from app.workflows import living_ui  # noqa: F401
from app.workflows import outcome_tap  # noqa: F401  (generic spawn tap)
