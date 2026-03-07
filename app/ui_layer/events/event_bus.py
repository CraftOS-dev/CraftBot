"""Publish/subscribe event bus for UI events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Coroutine, Any

from app.ui_layer.events.event_types import UIEvent, UIEventType

# Type aliases for event handlers
EventHandler = Callable[[UIEvent], None]
AsyncEventHandler = Callable[[UIEvent], Coroutine[Any, Any, None]]


class EventBus:
    """
    Publish/subscribe event bus for UI events.

    Supports both sync and async handlers. Events can be subscribed to by type
    or globally (all events). Event history is maintained for debugging.

    Example:
        bus = EventBus()

        # Subscribe to specific event type
        def on_user_message(event: UIEvent):
            print(f"User said: {event.data['message']}")

        unsubscribe = bus.subscribe(UIEventType.USER_MESSAGE, on_user_message)

        # Emit event
        bus.emit(UIEvent(type=UIEventType.USER_MESSAGE, data={"message": "Hello"}))

        # Clean up
        unsubscribe()
    """

    def __init__(self, max_history: int = 1000) -> None:
        """
        Initialize the event bus.

        Args:
            max_history: Maximum number of events to keep in history
        """
        self._handlers: Dict[UIEventType, List[EventHandler]] = defaultdict(list)
        self._async_handlers: Dict[UIEventType, List[AsyncEventHandler]] = defaultdict(
            list
        )
        self._global_handlers: List[EventHandler] = []
        self._global_async_handlers: List[AsyncEventHandler] = []
        self._event_history: List[UIEvent] = []
        self._max_history = max_history

    def subscribe(
        self,
        event_type: UIEventType,
        handler: EventHandler,
    ) -> Callable[[], None]:
        """
        Subscribe to a specific event type with a sync handler.

        Args:
            event_type: The event type to subscribe to
            handler: Callback function to invoke when event is emitted

        Returns:
            Unsubscribe function that removes the handler
        """
        self._handlers[event_type].append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)

        return unsubscribe

    def subscribe_async(
        self,
        event_type: UIEventType,
        handler: AsyncEventHandler,
    ) -> Callable[[], None]:
        """
        Subscribe to a specific event type with an async handler.

        Args:
            event_type: The event type to subscribe to
            handler: Async callback function to invoke when event is emitted

        Returns:
            Unsubscribe function that removes the handler
        """
        self._async_handlers[event_type].append(handler)

        def unsubscribe() -> None:
            if handler in self._async_handlers[event_type]:
                self._async_handlers[event_type].remove(handler)

        return unsubscribe

    def subscribe_all(self, handler: EventHandler) -> Callable[[], None]:
        """
        Subscribe to all events with a sync handler.

        Args:
            handler: Callback function to invoke for every event

        Returns:
            Unsubscribe function that removes the handler
        """
        self._global_handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._global_handlers:
                self._global_handlers.remove(handler)

        return unsubscribe

    def subscribe_all_async(self, handler: AsyncEventHandler) -> Callable[[], None]:
        """
        Subscribe to all events with an async handler.

        Args:
            handler: Async callback function to invoke for every event

        Returns:
            Unsubscribe function that removes the handler
        """
        self._global_async_handlers.append(handler)

        def unsubscribe() -> None:
            if handler in self._global_async_handlers:
                self._global_async_handlers.remove(handler)

        return unsubscribe

    def emit(self, event: UIEvent) -> None:
        """
        Emit an event to all subscribers.

        Sync handlers are called immediately. Async handlers are scheduled
        as tasks in the current event loop.

        Args:
            event: The event to emit
        """
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history :]

        # Call type-specific sync handlers
        for handler in self._handlers.get(event.type, []):
            try:
                handler(event)
            except Exception:
                # Log but don't crash - handlers shouldn't break the bus
                pass

        # Call global sync handlers
        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception:
                pass

        # Schedule type-specific async handlers
        for handler in self._async_handlers.get(event.type, []):
            try:
                asyncio.create_task(handler(event))
            except RuntimeError:
                # No event loop running - skip async handlers
                pass

        # Schedule global async handlers
        for handler in self._global_async_handlers:
            try:
                asyncio.create_task(handler(event))
            except RuntimeError:
                pass

    async def emit_async(self, event: UIEvent) -> None:
        """
        Emit an event and await all async handlers.

        Use this when you need to ensure all handlers have completed
        before continuing.

        Args:
            event: The event to emit
        """
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history :]

        # Call sync handlers
        for handler in self._handlers.get(event.type, []):
            try:
                handler(event)
            except Exception:
                pass

        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception:
                pass

        # Await async handlers
        tasks = []
        for handler in self._async_handlers.get(event.type, []):
            tasks.append(asyncio.create_task(handler(event)))

        for handler in self._global_async_handlers:
            tasks.append(asyncio.create_task(handler(event)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_history(
        self,
        event_type: Optional[UIEventType] = None,
        limit: int = 100,
    ) -> List[UIEvent]:
        """
        Get recent event history.

        Args:
            event_type: Filter by event type (None for all)
            limit: Maximum number of events to return

        Returns:
            List of recent events, most recent last
        """
        events = self._event_history
        if event_type is not None:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear the event history."""
        self._event_history.clear()

    def clear_handlers(self) -> None:
        """Remove all event handlers."""
        self._handlers.clear()
        self._async_handlers.clear()
        self._global_handlers.clear()
        self._global_async_handlers.clear()
