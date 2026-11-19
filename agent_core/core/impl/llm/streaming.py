# -*- coding: utf-8 -*-
"""A reply's text, handed out while the provider generates it.

A caller that wants to watch a reply as it is written sets a sink for its
call (``streaming_to``). The context variable rides into the worker thread
the call runs in (asyncio.to_thread copies the context), where a transport
that can stream asks for it (``current_sink``) and passes each piece of
text to it (``emit``). A call without a sink is sent exactly as before.

Streaming changes how the reply is delivered, never what is sent or kept:
the transport joins the pieces into the same text a non-streamed reply
carries, reads the same usage, and the session history records that text
once, as it always did. A reply the caller stops (``StreamSink.cancelled``)
raises ``LLMStreamAborted`` in the transport, so nothing of it joins a
session history and it is not counted as a provider failure.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional


class LLMStreamAborted(Exception):
    """The caller stopped the reply while it streamed. Not a provider
    failure: nothing is retried, counted, or recorded in a history."""


class StreamSink:
    """Receives a reply's text as it streams (called in the worker thread)."""

    #: Set by the caller to stop the reply; the transport checks it between
    #: pieces and raises LLMStreamAborted.
    cancelled: bool = False

    def on_begin(self) -> None:
        """A request for this reply starts. A second one within the same
        call (a retry inside the transport, a fallback provider) replaces
        the text received so far; a sink whose reply was already acted on
        raises instead (see begin)."""

    def on_text(self, delta: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class StreamRestarted(RuntimeError):
    """A second request began for a reply the caller already acted on: its
    text would be received twice. Raised to fail the call instead."""


_current_sink: ContextVar[Optional[StreamSink]] = ContextVar(
    "llm_stream_sink", default=None
)


def current_sink() -> Optional[StreamSink]:
    """The sink of the call in flight, or None (the call does not stream)."""
    return _current_sink.get()


@contextmanager
def streaming_to(sink: Optional[StreamSink]) -> Iterator[None]:
    """Stream the LLM calls made inside the block to ``sink`` (None: none)."""
    token = _current_sink.set(sink)
    try:
        yield
    finally:
        _current_sink.reset(token)


def begin(sink: StreamSink) -> None:
    """Tell ``sink`` a streamed request for its reply starts (before it is
    sent); raise LLMStreamAborted once the caller stopped the reply."""
    if sink.cancelled:
        raise LLMStreamAborted()
    sink.on_begin()


def emit(sink: StreamSink, delta: str) -> None:
    """Hand one piece of text to ``sink``; raise LLMStreamAborted once the
    caller stopped the reply."""
    if sink.cancelled:
        raise LLMStreamAborted()
    if delta:
        sink.on_text(delta)


def check_cancelled(sink: Optional[StreamSink]) -> None:
    """Raise LLMStreamAborted if ``sink``'s caller stopped the reply."""
    if sink is not None and sink.cancelled:
        raise LLMStreamAborted()


__all__ = [
    "LLMStreamAborted",
    "StreamRestarted",
    "StreamSink",
    "begin",
    "check_cancelled",
    "current_sink",
    "emit",
    "streaming_to",
]
