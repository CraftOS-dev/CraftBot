"""Generated agent actions for every integration provider.

This file replaces the ten hand-maintained action files (gmail, calendar,
docs, drive, youtube, outlook, linkedin, notion, hubspot, slack). At
import time (action discovery) it walks ``default_providers()`` and
registers one ``@action`` per Operation:

  - schema = the operation's input_schema + the injected ``account``
    property. Injection happens HERE, once, for every action — a provider
    cannot ship an action that silently ignores account selection (the
    defect that sank the previous multi-account attempt).
  - execution routes through ``IntegrationSystem.execute()``, which
    resolves ``account`` (email / alias / unique fragment, empty = primary
    account) to one connected account and runs the operation against that
    account's client.
  - resolution failures come back as the standard
    ``{"status": "error", "message": ...}`` dict, worded so the model can
    self-correct (they enumerate the connected accounts).
  - the operation's ``destructive`` flag maps to ``irreversible`` so the
    activity ledger never silently re-executes sends/deletes after a
    crash.
"""

from __future__ import annotations

from typing import Any, Dict

from agent_core import action

from craftos_integrations.contracts import Operation, Provider


def _account_schema(provider: Provider) -> Dict[str, Any]:
    name = getattr(provider, "display_name", "") or provider.id
    return {
        "type": "string",
        "description": (
            f"Optional {name} account to act as: an email/identity, the "
            f"user's nickname for the account (e.g. 'work'), or any unique "
            f"fragment of either. OMIT to use the primary account. Always "
            f"set this when the user names an account in any form."
        ),
        "example": "",
    }


def _make_handler(provider_id: str, op_name: str):
    """Build the action handler AND its exec-able source.

    The action system never calls the registered function directly: the
    registry extracts its SOURCE (``inspect.getsource``, or the
    ``_mcp_source_code`` attribute when present) and the executor
    ``exec()``s that string in a fresh namespace. A closure would lose its
    cell variables in that round-trip — every call failed with "name
    'provider_id' is not defined" (observed live 2026-08-12) — so, like
    the MCP adapter, the source is generated with the ids baked in as
    literals and stored on the function for the registry to pick up.
    """
    source = f'''async def handler(input_data: dict) -> dict:
    """integration operation {provider_id}/{op_name}."""
    from app.integrations import get_system

    _provider_id = "{provider_id}"
    _op_name = "{op_name}"

    # Strip the routing hint and internal parameters (e.g. _session_id);
    # everything else is the operation's payload.
    payload = {{
        k: v
        for k, v in input_data.items()
        if k != "account" and not k.startswith("_")
    }}
    try:
        result = await get_system().execute(
            _provider_id, _op_name, payload, account=input_data.get("account")
        )
    except Exception as e:
        # AccountResolutionError / LookupError / anything else -- the
        # action contract is an error dict, never a raised exception.
        return {{"status": "error", "message": str(e)}}
    if result.get("status") != "error":
        try:
            from app.ui_layer.metrics.collector import MetricsCollector

            collector = MetricsCollector.get_instance()
            if collector:
                collector.record_integration_call(_provider_id)
        except Exception:
            pass
    return result
'''
    namespace: Dict[str, Any] = {}
    exec(source, namespace)
    handler = namespace["handler"]
    handler._mcp_source_code = source
    return handler


def _register(provider: Provider, op: Operation) -> None:
    input_schema = dict(op.input_schema)
    input_schema["account"] = _account_schema(provider)
    action(
        name=op.name,
        description=op.description,
        action_sets=list(op.tags),
        input_schema=input_schema,
        output_schema=op.output_schema,
        parallelizable=op.parallelizable,
        irreversible=op.destructive,
    )(_make_handler(provider.id, op.name))


def _register_all() -> None:
    from craftos_integrations.providers import default_providers

    for provider in default_providers():
        for op in provider.operations():
            _register(provider, op)


_register_all()
