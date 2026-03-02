# -*- coding: utf-8 -*-
"""
app.usage.reporter

Local usage reporter for LLM/VLM operations.
Adapts the WhiteCollarAgent UsageReporter pattern for local SQLite storage.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from agent_core.core.hooks.types import UsageEventData

from app.usage.storage import UsageEvent, UsageStorage, get_usage_storage

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class UsageReporter:
    """
    Reports usage events to local SQLite storage.

    Events are buffered and saved in batches for efficiency.
    Implements the same pattern as WhiteCollarAgent's UsageReporter,
    but stores locally instead of sending to a chatserver.

    Usage:
        reporter = get_usage_reporter()
        reporter.start_background_flush()
        await reporter.report(UsageEventData(
            service_type="llm_openai",
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            cached_tokens=200,
        ))
    """

    BATCH_SIZE = 10
    FLUSH_INTERVAL_SEC = 30

    def __init__(self, storage: Optional[UsageStorage] = None) -> None:
        """
        Initialize the usage reporter.

        Args:
            storage: UsageStorage instance to use. If None, uses global storage.
        """
        self._storage = storage or get_usage_storage()
        self._buffer: List[UsageEvent] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._started = False

        # Statistics
        self._total_reported = 0
        self._total_failed = 0

        logger.info("[UsageReporter] Initialized with local storage")

    def start_background_flush(self) -> None:
        """Start the background flush task."""
        if self._started:
            return
        self._started = True

        try:
            loop = asyncio.get_event_loop()
            self._flush_task = loop.create_task(self._background_flush_loop())
            logger.info("[UsageReporter] Background flush task started")
        except RuntimeError:
            # No event loop running - will flush on demand
            logger.info("[UsageReporter] No event loop - will flush on demand")

    async def _background_flush_loop(self) -> None:
        """Periodically flush the buffer."""
        while True:
            await asyncio.sleep(self.FLUSH_INTERVAL_SEC)
            try:
                await self.flush()
            except Exception as e:
                logger.error(f"[UsageReporter] Background flush failed: {e}")

    async def report(self, event: UsageEventData) -> None:
        """
        Buffer a usage event for reporting.

        This implements the ReportUsageHook signature.

        Args:
            event: UsageEventData from the hook call.
        """
        # Convert UsageEventData to UsageEvent
        usage_event = UsageEvent(
            service_type=event.service_type,
            provider=event.provider,
            model=event.model,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            cached_tokens=event.cached_tokens,
        )

        async with self._buffer_lock:
            self._buffer.append(usage_event)

            # Log immediately for debugging
            total_tokens = event.input_tokens + event.output_tokens
            logger.debug(
                f"[UsageReporter] Buffered: {event.service_type}/{event.model} "
                f"(in={event.input_tokens}, out={event.output_tokens}, "
                f"cached={event.cached_tokens}, total={total_tokens})"
            )

            # Flush if buffer is large enough
            if len(self._buffer) >= self.BATCH_SIZE:
                asyncio.create_task(self.flush())

    async def report_full(
        self,
        service_type: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        duration_ms: int = 0,
        call_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Report usage with full metadata.

        Convenience method for reporting with additional fields not in UsageEventData.
        """
        usage_event = UsageEvent(
            service_type=service_type,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            duration_ms=duration_ms,
            call_type=call_type,
            session_id=session_id,
        )

        async with self._buffer_lock:
            self._buffer.append(usage_event)

            if len(self._buffer) >= self.BATCH_SIZE:
                asyncio.create_task(self.flush())

    async def flush(self) -> None:
        """Save buffered events to storage."""
        async with self._buffer_lock:
            if not self._buffer:
                return

            events = self._buffer.copy()
            self._buffer.clear()

        if not events:
            return

        try:
            count = self._storage.insert_events_batch(events)
            self._total_reported += count
            logger.info(
                f"[UsageReporter] Saved {count} usage events "
                f"(total reported: {self._total_reported})"
            )
        except Exception as e:
            logger.error(f"[UsageReporter] Failed to save events: {e}")
            self._total_failed += len(events)
            # Re-add failed events to buffer
            async with self._buffer_lock:
                self._buffer.extend(events)

    def get_stats(self) -> dict:
        """Get reporter statistics."""
        return {
            "buffered": len(self._buffer),
            "total_reported": self._total_reported,
            "total_failed": self._total_failed,
        }

    async def shutdown(self) -> None:
        """Flush remaining events and stop background task."""
        logger.info("[UsageReporter] Shutting down...")

        # Cancel background task
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush remaining events
        try:
            await self.flush()
        except Exception as e:
            logger.warning(f"[UsageReporter] Failed to flush on shutdown: {e}")


# Global usage reporter instance
_usage_reporter: Optional[UsageReporter] = None


def get_usage_reporter() -> UsageReporter:
    """Get the global usage reporter instance."""
    global _usage_reporter
    if _usage_reporter is None:
        _usage_reporter = UsageReporter()
    return _usage_reporter


# Convenience function for quick reporting
async def report_usage(
    service_type: str,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    duration_ms: int = 0,
    call_type: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Convenience function to report usage without creating UsageEventData manually.

    Usage:
        await report_usage(
            service_type="llm_openai",
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            cached_tokens=200,
            call_type="reasoning",
        )
    """
    await get_usage_reporter().report_full(
        service_type=service_type,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        duration_ms=duration_ms,
        call_type=call_type,
        session_id=session_id,
    )
