# -*- coding: utf-8 -*-
"""app.agentic — the shared agentic loop layer.

One engine, everything else is configuration:

- ``parsing``   — the ONE decision-JSON parser (normalization, json/literal
                  fallback, batch extraction). Previously implemented twice
                  (router `_parse_action_decision` + runner `_parse_decision`).
- ``engine``    — the ONE decide phase (session-delta orchestration → LLM →
                  parse → retry-with-feedback → fatal policy). Previously
                  implemented twice (router `_prompt_for_decision` session
                  branch + runner `_ask_llm_for_decision`/`_build_user_prompt`).
- ``steps``     — step programs: code-chosen turns consulted BEFORE the LLM
                  ({"kind": "actions"|"llm"|"wait"|"end"}), fail-open to the
                  normal decide on any exception/malformed step.
- ``loop``      — the ONE turn skeleton (AgentLoop, Template Method):
                  consult step program → code step | directive → LLM turn.
                  Drivers subclass it and override only policy hooks.
- ``task_driver`` — TaskTurn: the task driver's AgentLoop (one instance per
                  select_action_in_task call; returns decisions for
                  agent_base to execute).

Drivers (scheduling policy) stay thin and separate by design:
- the TASK driver — TaskTurn + agent_base's trigger-reentrant react turns,
  persistence, token limits, UI visibility;
- the SUB-AGENT driver — SubAgentRunner(AgentLoop): inline-blocking loop,
  iteration/wall caps, exit gates, isolation (app/subagent/runner.py).

Layer mnemonic: app/agentic = HOW agents run · app/workflows = WHAT each
domain's agents do · app/living_ui = the PRODUCT they build on.

Import the submodules directly (``from app.agentic.engine import decide``);
this package deliberately re-exports nothing — ``task_driver`` imports
agent_core prompts at module level, and the package must stay importable
from inside agent_core.
"""
