"""Notices to the ORIGIN session: the chat that ran ``agent_app_scaffold``.

After the scaffold hands the setup questions to the user, that chat's agent
has ended its turn and only hears back through these triggers. This module is
the single place that writes their text, so the agent's view of a pending
setup (pending_setups.py) has exactly two endings: created or cancelled.

Both are best-effort. A failed notice is logged and never breaks the
finalize or cancel it reports.
"""

from __future__ import annotations

from typing import Any, Optional

from .pending_setups import PendingSetup

try:
    from loguru import logger
except ImportError:  # pragma: no cover - loguru is always present in-app
    import logging

    logger = logging.getLogger(__name__)


async def notify_setup_created(
    trigger_service: Optional[Any], session_id: str, project_id: str, project_name: str
) -> None:
    """The setup questions were answered and the project now exists."""
    from app.triggers import TriggerSource

    await _emit(
        trigger_service,
        TriggerSource.AGENT_APP_CREATED,
        session_id,
        (
            f"FYI: the setup questions were answered — Agent App "
            f"'{project_name}' (project_id {project_id}) has been created and "
            "its build is running in its own session. No action and no "
            "message needed: acknowledge silently with end_turn unless the "
            "user has asked for something. Remember the project_id for "
            "future requests about this app."
        ),
        {"project_id": project_id},
    )


async def notify_setup_cancelled(
    trigger_service: Optional[Any], setup: PendingSetup
) -> None:
    """The user cancelled the setup, so no project will be created."""
    from app.triggers import TriggerSource

    await _emit(
        trigger_service,
        TriggerSource.AGENT_APP_SETUP_CANCELLED,
        setup.origin_session_id,
        (
            f"FYI: the user cancelled the setup for Agent App '{setup.name}'. "
            "No project was created. Do not ask the setup questions again or "
            "call agent_app_scaffold for it unless the user asks. No message "
            "needed: acknowledge silently with end_turn unless the user has "
            "asked for something."
        ),
        {"wizard_id": setup.wizard_id},
    )


async def _emit(
    trigger_service: Optional[Any],
    source: Any,
    session_id: str,
    description: str,
    payload: dict,
) -> None:
    if not trigger_service or not session_id:
        return
    try:
        from app.triggers import TriggerSpec

        await trigger_service.emit(
            TriggerSpec(
                source=source,
                description=description,
                priority=10,
                session_id=session_id,
                payload=payload,
            )
        )
    except Exception as e:
        logger.debug(f"[AGENT_APP:SETUP] origin-session notice failed: {e}")


__all__ = ["notify_setup_created", "notify_setup_cancelled"]
