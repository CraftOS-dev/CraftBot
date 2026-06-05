"""Action-side helpers — collapse the repeated try/has_credentials/wrap pattern.

Each action used to be ~14 lines of skeleton wrapped around a single
client method call. With ``run_client`` an action becomes ~5 lines:

    from app.data.action.integrations._helpers import run_client

    @action(name="send_discord_message", ...)
    async def send_discord_message(input_data: dict) -> dict:
        return await run_client(
            "discord", "bot_send_message",
            channel_id=input_data["channel_id"],
            content=input_data["content"],
        )

For sync actions, use ``run_client_sync`` (same API, no await).

Some clients return ``{"ok": True, "result": ...}`` / ``{"error": ...}``
envelopes (Outlook, Jira, etc.). Pass ``unwrap_envelope=True`` to
extract the inner ``result`` on success or surface the inner ``error``
message on failure. Pair with ``success_message="..."`` when the action
should report a fixed success string instead of the inner result.

Actions that do real pre/post-processing (parsing labels, recording to
conversation history, building complex payloads) keep their explicit
form — the helper is only for the boilerplate-heavy 80% case.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional


def record_outgoing_message(platform_name: str, recipient: str, text: str) -> None:
    """Best-effort: record an outgoing platform message into the agent's conversation history.

    Used by integration actions that send messages on behalf of the agent
    (Telegram, WhatsApp, etc.) so the conversation transcript reflects what
    the agent emitted, not just what came back. Silently no-ops if the
    state manager is not reachable — never raises.
    """
    try:
        import app.internal_action_interface as iai

        sm = iai.InternalActionInterface.state_manager
        if sm:
            label = f"[Sent via {platform_name} to {recipient}]: {text}"
            sm.event_stream_manager.record_conversation_message(
                f"agent message to platform: {platform_name}",
                label,
            )
            sm._append_to_conversation_history("agent", label)
    except Exception:
        pass


def _resolve_handler(integration: str):
    """Resolve a handler by handler-name first, then by client platform_id (e.g. 'google_workspace' -> google handler)."""
    try:
        from craftos_integrations import get_handler, get_registered_handler_names

        handler = get_handler(integration)
        if handler is not None:
            return handler, integration
        for name in get_registered_handler_names():
            h = get_handler(name)
            spec = getattr(h, "spec", None)
            if spec and getattr(spec, "platform_id", None) == integration:
                return h, name
    except Exception:
        pass
    return None, integration


def _no_cred_message(integration: str) -> str:
    handler, slash_name = _resolve_handler(integration)
    display = handler.display_name if handler and handler.display_name else integration
    return f"No {display} credential. Use /{slash_name} login first."


def _shape_result(
    raw: Any,
    *,
    unwrap_envelope: bool,
    success_message: Optional[str],
    fail_message: str,
) -> Dict[str, Any]:
    """Translate a client return value into the action response envelope."""
    if unwrap_envelope and isinstance(raw, dict):
        # Success envelope: {"ok": True, "result": ...}
        if raw.get("ok") is True:
            if success_message:
                return {"status": "success", "message": success_message}
            return {"status": "success", "result": raw.get("result", raw)}
        # Explicit failure envelope: {"ok": False, "error": ...}
        if raw.get("ok") is False:
            return {"status": "error", "message": raw.get("error", fail_message)}
        # Implicit failure envelope from craftos_integrations.helpers.request:
        # 4xx/5xx HTTP responses (and caught exceptions) return
        # {"error": "API error: 403", "details": "..."} with NO "ok" key.
        # Without this branch, the next clauses fall through and wrap the
        # error as {"status": "success"}, hiding the failure from the agent.
        if "error" in raw:
            return {
                "status": "error",
                "message": raw.get("error", fail_message),
                "details": raw.get("details"),
            }
    if success_message and isinstance(raw, dict) and raw.get("status") == "error":
        return {
            "status": "error",
            "message": raw.get("message") or raw.get("error", fail_message),
        }
    if success_message:
        return {"status": "success", "message": success_message}
    return {"status": "success", "result": raw}


async def run_client(
    integration: str,
    method_name: str,
    *,
    unwrap_envelope: bool = False,
    success_message: Optional[str] = None,
    fail_message: str = "Operation failed",
    **kwargs,
) -> Dict[str, Any]:
    """Resolve client by integration, check creds, call method, wrap result.

    The named method may be sync or async; coroutines are awaited.
    """
    from craftos_integrations import get_client

    client = get_client(integration)
    if client is None:
        return {"status": "error", "message": f"Unknown integration: {integration}"}
    if not client.has_credentials():
        return {"status": "error", "message": _no_cred_message(integration)}
    try:
        method = getattr(client, method_name, None)
        if method is None:
            return {
                "status": "error",
                "message": f"Method {method_name!r} not found on {integration} client",
            }
        raw = method(**kwargs)
        if asyncio.iscoroutine(raw):
            raw = await raw
        result = _shape_result(
            raw,
            unwrap_envelope=unwrap_envelope,
            success_message=success_message,
            fail_message=fail_message,
        )
        if result.get("status") != "error":
            try:
                from app.ui_layer.metrics.collector import MetricsCollector

                collector = MetricsCollector.get_instance()
                if collector:
                    collector.record_integration_call(integration)
            except Exception:
                pass
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def run_client_sync(
    integration: str,
    method_name: str,
    *,
    unwrap_envelope: bool = False,
    success_message: Optional[str] = None,
    fail_message: str = "Operation failed",
    **kwargs,
) -> Dict[str, Any]:
    """Sync flavor of ``run_client`` for sync actions calling sync methods."""
    from craftos_integrations import get_client

    client = get_client(integration)
    if client is None:
        return {"status": "error", "message": f"Unknown integration: {integration}"}
    if not client.has_credentials():
        return {"status": "error", "message": _no_cred_message(integration)}
    try:
        method = getattr(client, method_name, None)
        if method is None:
            return {
                "status": "error",
                "message": f"Method {method_name!r} not found on {integration} client",
            }
        raw = method(**kwargs)
        if asyncio.iscoroutine(raw):
            return {
                "status": "error",
                "message": f"{method_name!r} is async — use run_client (await) instead",
            }
        result = _shape_result(
            raw,
            unwrap_envelope=unwrap_envelope,
            success_message=success_message,
            fail_message=fail_message,
        )
        if result.get("status") != "error":
            try:
                from app.ui_layer.metrics.collector import MetricsCollector

                collector = MetricsCollector.get_instance()
                if collector:
                    collector.record_integration_call(integration)
            except Exception:
                pass
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_client_or_error(integration: str):
    """Resolve a client + run the credential check.

    Returns a tuple ``(client, error_dict)``:
      - on success: ``(client, None)``
      - on failure: ``(None, {"status": "error", "message": ...})``

    Use this in actions that return bespoke result shapes / do multi-step
    logic and can't use ``run_client`` or ``with_client``::

        def my_action(input_data):
            client, err = get_client_or_error("google_workspace")
            if err:
                return err
            ...
    """
    from craftos_integrations import get_client

    client = get_client(integration)
    if client is None:
        return None, {
            "status": "error",
            "message": f"Unknown integration: {integration}",
        }
    if not client.has_credentials():
        return None, {"status": "error", "message": _no_cred_message(integration)}
    return client, None


async def with_client(
    integration: str, fn: Callable, *args, **kwargs
) -> Dict[str, Any]:
    """Call ``fn(client, *args, **kwargs)`` after credential check.

    Use when an action needs to do more than a single method call:
    multiple calls in sequence, payload building, etc. ``fn`` may be
    sync or async. Wraps the return as ``{"status": "success", "result": ...}``;
    for bespoke result shapes use ``get_client_or_error`` instead.
    """
    client, err = get_client_or_error(integration)
    if err:
        return err
    try:
        result = fn(client, *args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        try:
            from app.ui_layer.metrics.collector import MetricsCollector

            collector = MetricsCollector.get_instance()
            if collector:
                collector.record_integration_call(integration)
        except Exception:
            pass
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
