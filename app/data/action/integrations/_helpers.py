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
envelopes (Outlook, Jira, etc.). ``_shape_result`` collapses that
transport envelope automatically — the agent never sees a nested
``{"ok": true, "result": ...}`` wrapper inside the action result, and
envelope failures surface as ``{"status": "error"}`` instead of being
buried under a success wrapper. ``unwrap_envelope=True`` is still
accepted for backward compatibility (it additionally treats ANY dict
containing an ``error`` key as a failure). Pair with
``success_message="..."`` when the action should report a fixed success
string instead of the inner result.

Actions that do real pre/post-processing (parsing labels, recording to
conversation history, building complex payloads) keep their explicit
form — the helper is only for the boilerplate-heavy 80% case.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional


# Common aliases the agent/user might use → canonical registered integration id.
# Google Workspace apps in particular are frequently referred to by short names
# or lumped under "google", which is not itself an integration.
#
# These live here (not in an action module) because action handlers are executed
# via exec() on their own extracted source — module-level names in the action
# file are NOT in scope at runtime. Handlers must import these inside the function
# body, the same way they import run_client/with_client.
INTEGRATION_ALIASES = {
    "mail": "gmail",
    "googlemail": "gmail",
    "google mail": "gmail",
    "drive": "google_drive",
    "gdrive": "google_drive",
    "googledrive": "google_drive",
    "google drive": "google_drive",
    "docs": "google_docs",
    "gdocs": "google_docs",
    "googledocs": "google_docs",
    "google docs": "google_docs",
    "google_doc": "google_docs",
    "calendar": "google_calendar",
    "gcal": "google_calendar",
    "gcalendar": "google_calendar",
    "google calendar": "google_calendar",
    "youtube": "google_youtube",
}

# Umbrella terms that aren't a single integration — Google Workspace apps are
# tracked individually, so callers must check the specific app.
GOOGLE_UMBRELLA = {
    "google",
    "google workspace",
    "google_workspace",
    "workspace",
    "gsuite",
    "g suite",
    "google suite",
}
GOOGLE_FAMILY = (
    "gmail",
    "google_drive",
    "google_docs",
    "google_calendar",
    "google_youtube",
)


def normalize_integration_id(integration_id: str) -> str:
    """Map a user/agent-supplied integration name through known aliases."""
    return INTEGRATION_ALIASES.get(integration_id, integration_id)


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
            sm.record_agent_message(label, platform=platform_name)
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
    """Translate a client return value into the action response envelope.

    The ``{"ok": ...}`` transport envelope some clients emit is ALWAYS
    collapsed — previously (without ``unwrap_envelope=True``) the agent got
    a double-nested ``{"status": "success", "result": {"ok": true,
    "result": ...}}`` on every call, and envelope failures were wrapped as
    successes. ``unwrap_envelope`` remains as an opt-in for the looser
    "any dict containing an 'error' key is a failure" interpretation.
    """
    if isinstance(raw, dict):
        # Success envelope: {"ok": True, "result": ...} — or Slack-style
        # bodies where "ok" sits alongside the payload fields.
        if raw.get("ok") is True:
            if success_message:
                return {"status": "success", "message": success_message}
            if set(raw.keys()) == {"ok", "result"}:
                return {"status": "success", "result": raw["result"]}
            return {
                "status": "success",
                "result": {k: v for k, v in raw.items() if k != "ok"},
            }
        # Explicit failure envelope: {"ok": False, "error": ...}
        if raw.get("ok") is False:
            return {"status": "error", "message": raw.get("error", fail_message)}
        # Implicit failure envelope from craftos_integrations.helpers.request:
        # 4xx/5xx HTTP responses (and caught exceptions) return
        # {"error": "API error: 403", "details": "..."} with NO "ok" key.
        # Restricted to exactly that shape by default so a legitimate payload
        # that merely *contains* an "error" field isn't misread as failure;
        # unwrap_envelope=True keeps the looser historical behavior.
        if "error" in raw and (
            unwrap_envelope or set(raw.keys()) <= {"error", "details"}
        ):
            return {
                "status": "error",
                "message": raw.get("error", fail_message),
                "details": raw.get("details"),
            }
        # Clients that pre-wrap their own {"status": "error", ...} (e.g. the
        # WhatsApp bridge) — surface the failure instead of re-wrapping it
        # under a success envelope.
        if raw.get("status") == "error":
            return {
                "status": "error",
                "message": raw.get("message") or raw.get("error", fail_message),
            }
    if success_message:
        return {"status": "success", "message": success_message}
    return {"status": "success", "result": raw}


def pick_result(res: Dict[str, Any], keys) -> Dict[str, Any]:
    """Reduce a successful ``run_client`` result to the named top-level keys.

    Used by write/create/send actions whose provider returns the entire
    mutated object: the agent only needs the id (+ a couple of key fields),
    and can always fetch the full object with the matching ``get_*`` action.
    Non-dict results, error results, and missing keys pass through untouched
    so this is always safe to apply::

        res = await run_client("stripe", "create_customer", ...)
        return pick_result(res, ["id", "status"])
    """
    if res.get("status") == "success" and isinstance(res.get("result"), dict):
        r = res["result"]
        picked = {k: r.get(k) for k in keys if r.get(k) is not None}
        if picked:
            res = {**res, "result": picked}
    return res


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
