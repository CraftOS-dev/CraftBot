# -*- coding: utf-8 -*-
"""
app.usage.task_attribution

Shared helper for attributing LLM/VLM usage to the currently-active task.

Called from the `_report_usage` hooks in both `app.llm.interface` and
`app.vlm_interface`. It bumps cumulative token counters on the active Task
object and emits a `TASK_TOKEN_UPDATE` UI event so the browser can tick its
display while the task runs.
"""

from __future__ import annotations

from agent_core.core.hooks.types import UsageEventData


def attribute_usage_to_current_task(event: UsageEventData) -> None:
    """Bump per-task token counters and emit a UI tick.

    Best-effort: any failure here is swallowed so that token tracking can
    never break an in-flight LLM/VLM call. If no task is active (e.g.
    conversation mode), this is a no-op.
    """
    try:
        from app.state.agent_state import STATE
        from app.logger import logger

        task = STATE.current_task
        if task is None:
            logger.debug(
                f"[TOKEN_ATTR] skipped — no current task "
                f"(event: in={event.input_tokens} out={event.output_tokens} cached={event.cached_tokens})"
            )
            return

        task.input_tokens = (task.input_tokens or 0) + int(event.input_tokens or 0)
        task.output_tokens = (task.output_tokens or 0) + int(event.output_tokens or 0)
        task.cache_tokens = (task.cache_tokens or 0) + int(event.cached_tokens or 0)

        logger.info(
            f"[TOKEN_ATTR] task={task.id} +in={event.input_tokens} "
            f"+out={event.output_tokens} +cached={event.cached_tokens} "
            f"-> totals: in={task.input_tokens} out={task.output_tokens} cache={task.cache_tokens}"
        )

        bus = STATE.event_bus
        if bus is None:
            logger.warning(
                f"[TOKEN_ATTR] task={task.id} counters bumped but no event_bus on STATE "
                f"(UI will not update until next broadcast)"
            )
            return

        from app.ui_layer.events import UIEvent, UIEventType

        bus.emit(
            UIEvent(
                type=UIEventType.TASK_TOKEN_UPDATE,
                data={
                    "task_id": task.id,
                    "input_tokens": task.input_tokens,
                    "output_tokens": task.output_tokens,
                    "cache_tokens": task.cache_tokens,
                },
                task_id=task.id,
            )
        )
    except Exception as e:
        try:
            from app.logger import logger

            logger.warning(f"[TOKEN_ATTR] attribution failed: {e}", exc_info=True)
        except Exception:
            pass
