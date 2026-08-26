"""Shared plumbing for authoring operations and listeners.

``client_op`` turns "call this client method with these schema'd inputs"
into an Operation, keeping per-provider operations.py files declarative.
The result-envelope shaping mirrors the host's historical behavior
(``_shape_result`` in the old action helpers) so ported operations return
identical dicts to what agents already expect.

``platform_message_payload`` is the listener-side twin: it converts a
``PlatformMessage`` into the event-dict shape the host's trigger system
consumes, so every listener emits an identical payload regardless of which
client produced it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from ..contracts import Operation

STATUS_OUTPUT = {"status": {"type": "string", "example": "success"}}

# Type of the account-bound event callable the core hands make_listener.
EmitFn = Callable[[Dict[str, Any]], Awaitable[None]]


def platform_message_payload(msg: Any) -> Dict[str, Any]:
    """``PlatformMessage`` → host event payload.

    Builds the host event payload every listener emits
    exactly — same keys, same fallbacks — so listeners ported from the
    clients emit identical events.
    """
    raw = msg.raw if isinstance(msg.raw, dict) else {}
    return {
        "source": msg.platform.replace("_", " ").title(),
        "integrationType": msg.platform,
        "contactId": msg.sender_id,
        "contactName": msg.sender_name or msg.sender_id,
        "messageBody": msg.text,
        "channelId": msg.channel_id,
        "channelName": msg.channel_name,
        "messageId": msg.message_id,
        "is_self_message": raw.get("is_self_message", False),
        "raw": raw,
        "attachments": list(getattr(msg, "attachments", None) or []),
    }


def emit_callback(emit: EmitFn) -> Callable[[Any], Awaitable[None]]:
    """Adapt an account-bound ``emit`` into the API client callback.

    Poll loops call ``self._message_callback(PlatformMessage)``;
    this shim converts each message to the host payload shape and awaits
    ``emit`` — the only plumbing the ported listeners have to replace.
    """

    async def _callback(msg: Any) -> None:
        await emit(platform_message_payload(msg))

    return _callback


class ClientListenerAdapter:
    """Generic ``Listener`` over a client's own listen loop.

    The account-bound client is a ``BasePlatformClient`` subclass with its own
    ``start_listening``/``stop_listening`` poll loop; this adapts that loop to
    the ``Listener`` protocol, converting each message through
    ``emit_callback``. ``cursor()`` is None because these loops keep their
    watermark in memory and run their own catch-up on start — providers that
    need restart-safe cursors get a hand-written listener instead (see
    slack/listener.py for the pattern).
    """

    def __init__(self, client: Any, emit: EmitFn) -> None:
        self._client = client
        self._emit = emit

    async def start(self) -> None:
        # The supervisor re-invokes start() after every clean cycle, and the
        # client loops do not all guard against double-starts — spawn only when
        # one is not already running.
        if getattr(self._client, "is_listening", False):
            return
        await self._client.start_listening(emit_callback(self._emit))

    async def stop(self) -> None:
        await self._client.stop_listening()

    def cursor(self) -> Optional[Dict[str, Any]]:
        return None


def read_guidance(package_file: str) -> str:
    """Load GUIDANCE.md sitting next to a provider module."""
    from pathlib import Path

    path = Path(package_file).parent / "GUIDANCE.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def shape_result(
    raw: Any,
    *,
    unwrap_envelope: bool = False,
    success_message: Optional[str] = None,
    fail_message: str = "Operation failed",
) -> Dict[str, Any]:
    """Normalize a client return value into {"status": ..., ...}."""
    if isinstance(raw, dict):
        if raw.get("ok") is True:
            if success_message:
                return {"status": "success", "message": success_message}
            if set(raw.keys()) == {"ok", "result"}:
                return {"status": "success", "result": raw["result"]}
            return {
                "status": "success",
                "result": {k: v for k, v in raw.items() if k != "ok"},
            }
        if raw.get("ok") is False:
            return {"status": "error", "message": raw.get("error", fail_message)}
        if "error" in raw and (
            unwrap_envelope or set(raw.keys()) <= {"error", "details"}
        ):
            return {
                "status": "error",
                "message": raw.get("error", fail_message),
                "details": raw.get("details"),
            }
        if raw.get("status") == "error":
            return {
                "status": "error",
                "message": raw.get("message") or raw.get("error", fail_message),
            }
    if success_message:
        return {"status": "success", "message": success_message}
    return {"status": "success", "result": raw}


def client_op(
    name: str,
    method: str,
    *,
    description: str,
    input_schema: Dict[str, Any],
    output_schema: Optional[Dict[str, Any]] = None,
    destructive: bool = False,
    parallelizable: bool = True,
    tags: Tuple[str, ...] = (),
    unwrap_envelope: bool = False,
    success_message: Optional[str] = None,
    fail_message: str = "Operation failed",
    arg_map: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Operation:
    """Operation that calls ``client.<method>(**kwargs)``.

    Default kwargs are the input keys present in the request (missing
    optionals are NOT passed as None, so client-side defaults apply).
    ``arg_map`` overrides that for input→kwarg renames or computed args.
    Sync client methods run on a worker thread; async ones are awaited.
    """

    async def fn(client: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if arg_map is not None:
            kwargs = arg_map(input_data)
        else:
            kwargs = {k: input_data[k] for k in input_schema if k in input_data}
        try:
            target = getattr(client, method, None)
            if target is None:
                return {
                    "status": "error",
                    "message": f"Method {method!r} not found on client",
                }
            if asyncio.iscoroutinefunction(target):
                raw = await target(**kwargs)
            else:
                raw = await asyncio.to_thread(target, **kwargs)
                if asyncio.iscoroutine(raw):
                    raw = await raw
            return shape_result(
                raw,
                unwrap_envelope=unwrap_envelope,
                success_message=success_message,
                fail_message=fail_message,
            )
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return Operation(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema or STATUS_OUTPUT,
        fn=fn,
        destructive=destructive,
        parallelizable=parallelizable,
        tags=tags,
    )
