"""Host bootstrap for the integrations system.

The single place CraftBot constructs its IntegrationSystem. Everything
host-specific about the system — which storage backend, which providers, where
credentials live — is decided here; the package itself stays
host-blind.

Lazy singleton: construction needs nothing from app config because the
FileCredentialStore resolves ``ConfigStore.project_root`` per call, so
``get_system()`` is safe to call before ``configure_integrations`` has run
(clients are only built at action-execution time, long after startup).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from craftos_integrations.config import MessageCallback

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.logger import get_logger

logger = get_logger(__name__)

_system: Optional[IntegrationSystem] = None
_listeners: Optional[Any] = None  # ListenerManager, built lazily in start_listeners()
_listener_task: Optional[asyncio.Task] = None  # holds ListenerManager.start()'s run-loop


# ── attachment descriptors ───────────────────────────────────────────────
#
# Listeners normalize non-text payloads into PlatformMessage.attachments
# ({kind, id, name, mime, size, url, extra}); the host renders them as one
# descriptor line each, with a retrieval hint naming the platform's
# download ACTION so the agent knows how to fetch the bytes — see
# docs/plans/attachment-reception-plan.md.

# integration_type → hint builder. Returns "" when there is nothing to
# fetch (metadata-only or inline `extra` kinds).
_ATTACHMENT_HINTS: Dict[str, Any] = {
    "telegram_bot": lambda att: (
        f"retrieve with download_telegram_file(file_id={att['id']!r})"
        if att.get("id")
        else ""
    ),
    "telegram_user": lambda att: (
        f"retrieve with download_telegram_user_media("
        f"chat_id={att.get('extra', {}).get('chat_id', '')!r}, "
        f"message_id={att['id']!r})"
        if att.get("id")
        else ""
    ),
    "whatsapp_web": lambda att: (
        f"retrieve with download_whatsapp_message_media(message_id={att['id']!r})"
        if att.get("id")
        else ""
    ),
    "lark": lambda att: (
        f"retrieve with download_lark_message_resource("
        f"message_id={att.get('extra', {}).get('message_id', '')!r}, "
        f"file_key={att['id']!r})"
        if att.get("id")
        else ""
    ),
    "discord": lambda att: (f"fetch directly from url {att['url']}" if att.get("url") else ""),
    "slack": lambda att: (
        f"retrieve with download_slack_file(file_id={att['id']!r})"
        if att.get("id")
        else ""
    ),
    "gmail": lambda att: (
        f"retrieve with download_gmail_attachment("
        f"message_id={att.get('extra', {}).get('message_id', '')!r}, "
        f"attachment_id={att['id']!r})"
        if att.get("id")
        else ""
    ),
    "outlook": lambda att: (
        f"retrieve with download_outlook_attachment("
        f"message_id={att.get('extra', {}).get('message_id', '')!r}, "
        f"attachment_id={att['id']!r})"
        if att.get("id")
        else ""
    ),
    "jira": lambda att: (
        f"retrieve with download_jira_attachment(attachment_id={att['id']!r})"
        if att.get("id")
        else ""
    ),
}


def _human_size(size: Any) -> str:
    try:
        n = float(size)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return ""


def format_attachment_descriptors(
    integration_type: str, attachments: Any
) -> list[str]:
    """Render normalized attachment dicts into `[Attachment: …]` lines.

    Tolerant of junk entries — a malformed attachment yields no line
    rather than an exception (listener input is platform data)."""
    lines: list[str] = []
    hint_fn = _ATTACHMENT_HINTS.get((integration_type or "").lower())
    for att in attachments or []:
        if not isinstance(att, dict) or not att.get("kind"):
            continue
        parts = [str(att["kind"])]
        if att.get("name"):
            parts.append(f'"{att["name"]}"')
        meta = ", ".join(
            p for p in (att.get("mime") or "", _human_size(att.get("size"))) if p
        )
        if meta:
            parts.append(f"({meta})")
        extra = att.get("extra")
        if isinstance(extra, dict):
            inline = ", ".join(
                f"{k}={v}" for k, v in extra.items() if k not in ("chat_id", "message_id")
            )
            if inline:
                parts.append(f"[{inline}]")
        hint = ""
        if hint_fn is not None:
            try:
                hint = hint_fn(att) or ""
            except Exception:
                hint = ""
        if not hint and att.get("url"):
            hint = f"url: {att['url']}"
        line = f"[Attachment: {' '.join(parts)}"
        if hint:
            line += f" — {hint}"
        lines.append(line + "]")
    return lines


def set_event_callback(on_message: "MessageCallback") -> None:
    """Install the host callback that inbound listener events are forwarded to.

    ``CraftBotEventSink.on_event`` reads ``ConfigStore.on_message`` and DROPS
    every event when it is None, so this must be called before
    ``start_listeners()``. Setting it explicitly here, rather than as a side
    effect of some other bootstrap step, means it cannot be lost by accident.
    """
    from craftos_integrations.config import ConfigStore

    ConfigStore.on_message = on_message


def get_system() -> IntegrationSystem:
    global _system
    if _system is None:
        from craftos_integrations.providers import default_providers

        _system = IntegrationSystem(
            store=FileCredentialStore(),
            providers=default_providers(),
        )
    return _system


def reset_system() -> None:
    """Testing hook: drop the singletons so the next get_system() rebuilds."""
    global _system, _listeners
    _system = None
    _listeners = None


# ── listener fan-out (PR 5) ──────────────────────────────────────────────


class CraftBotEventSink:
    """EventSink implementation: listener events → the agent's trigger
    system.

    Every listener emits the same payload-dict shape, so events are
    forwarded to one host callback (``ConfigStore.on_message``,
    installed by ``set_event_callback`` during agent boot) — the agent cannot
    tell which engine delivered a message. Before forwarding, the payload is
    enriched with the account that received it so multi-account routing
    survives the trip: ``payload["account"]`` carries the identity, and the
    human-readable ``source`` gains an ``(alias-or-identity)`` suffix.
    """

    async def on_event(
        self, provider_id: str, identity: str, event: Dict[str, Any]
    ) -> None:
        from craftos_integrations.config import ConfigStore

        on_message = ConfigStore.on_message
        if on_message is None:
            logger.warning(
                f"[LISTENERS] Dropping {provider_id}/{identity} event: "
                "no on_message callback configured"
            )
            return

        payload = dict(event)
        payload["account"] = identity

        alias: Optional[str] = None
        try:
            for info in get_system().accounts.list_accounts(provider_id):
                if info.identity == identity:
                    alias = info.alias
                    break
        except Exception:
            pass  # best-effort: fall back to the bare identity
        payload["account_alias"] = alias
        payload["source"] = f"{payload.get('source', provider_id)} ({alias or identity})"

        await on_message(payload)


def _log_listener_task_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"[LISTENERS] manager run-loop died: {exc!r}")


async def start_listeners() -> None:
    """Build (once) and start the ListenerManager.

    Wires FileCursorStore + CraftBotEventSink and attaches the manager as
    ``system.listeners`` so account mutations can reconcile running
    listeners.

    ``ListenerManager.start()`` is a service run-loop — it reconciles and
    then HOLDS until ``stop()`` — so it must run as a background task;
    awaiting it inline deadlocks the caller (observed live 2026-08-12:
    agent boot froze at step 6/7). Idempotent: the manager is built once
    and a still-running task is left alone.
    """
    global _listeners, _listener_task
    if _listeners is None:
        from craftos_integrations.core.listeners import (
            FileCursorStore,
            ListenerManager,
        )

        system = get_system()
        _listeners = ListenerManager(system, CraftBotEventSink(), FileCursorStore())
        system.listeners = _listeners
    if _listener_task is None or _listener_task.done():
        _listener_task = asyncio.create_task(
            _listeners.start(), name="integrations-listener-manager"
        )
        _listener_task.add_done_callback(_log_listener_task_exit)
        # Yield once so the manager's initial reconcile gets underway
        # before boot continues.
        await asyncio.sleep(0)


async def stop_listeners() -> None:
    """Stop the ListenerManager if it was ever started."""
    global _listener_task
    if _listeners is not None:
        await _listeners.stop()
    if _listener_task is not None:
        if not _listener_task.done():
            try:
                await _listener_task
            except asyncio.CancelledError:
                pass
        _listener_task = None
