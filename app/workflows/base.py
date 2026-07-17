# -*- coding: utf-8 -*-
"""Workflow-authoring surface — one import for domain packages.

The model: ``Task → deterministic workflow → actions``. A domain is
ONE class — subclass :class:`~app.workflows.workflow.Workflow`,
set the task surface (``name``, ``system_prompt``, optionally
``select_action_prompt``) and the engine attributes (``worker_agent``,
``checker_agent``, budgets), override the domain hooks
(``resolve_subject`` / ``state_dir`` / ``is_bootstrapped`` /
``work_query`` / ``check_query``), and register an instance:

    class MyDomainWorkflow(Workflow):
        name = "my_domain"
        system_prompt = "..."
        worker_agent = "my_worker"
        checker_agent = "my_checker"
        ...

    register_workflow(MyDomainWorkflow())

Tasks created with ``workflow_id="my_domain"`` then resolve the instance
each turn (the registry is the string→object map — tasks persist across
restarts, so they carry a name, never a live object). Its ``step()`` is
consulted BEFORE any LLM decision and returns
``{"kind": "actions"|"llm"|"wait"|"end", ...}`` (contract:
:mod:`app.agentic.steps`) or None = the LLM decides that turn; "llm" steps
are bounded single decisions (answer the user, last-resort ask,
presentation). Sub-agent types get the same step hook by subclassing
``SubAgentDefinition`` and overriding ``step``.

Specialist sub-agents register through :func:`app.subagent.registry.
register_subagent` — a domain keeps its specialists in
``app/workflows/<domain>/subagents/``.
"""

from agent_core.core.registry.task_workflows import (  # noqa: F401
    get_workflow,
    list_workflow_names,
    register_workflow,
)
from app.subagent.registry import register_subagent  # noqa: F401
from app.workflows.workflow import (  # noqa: F401
    LLM_TURN,
    StepContext,
    Workflow,
    WorkState,
)
