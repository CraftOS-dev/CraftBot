"""The Factory (FACTORY-PLAN.md): deterministic orchestration, free intelligence.

Layering (enforced by check_imports.py):
    engine/      generic durable-workflow core — imports stdlib ONLY
    appfactory/  the app-creation domain pack — imports engine only
    host         (CraftBot: app/agent_app, app/agent_base) — imports this API
"""
