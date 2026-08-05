# -*- coding: utf-8 -*-
"""
Presentation-tier split for react-loop errors (app/agent_base.py):

- "Minor" tier: a recognized, user-actionable failure (bad key, no credits,
  misconfigured provider) — shown as a short, calm message. Signaled by
  either an `LLMConsecutiveFailureError.last_error_info` or a
  `ClassifiedError` (agent_core/core/errors.py) anywhere in the exception
  chain.
- "Critical" tier: anything unclassified — a genuine bug/crash — shown with
  full raw detail.

Also covers the action router's message cleanup: it used to leak an
"Unable to generate action decision on attempt N:" wrapper (with a
duplicated trailing period) into the user-facing text; it now raises a
`ClassifiedError` with a clean message instead.
"""

import asyncio

import pytest

from agent_core.core.errors import (
    ClassifiedError,
    ErrorAction,
    ErrorCategory,
    ErrorInfo,
    Severity,
)
from agent_core.core.impl.action.router import ActionRouter
from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError, LLMErrorInfo
from app.agent_base import AgentBase
from app.errors import CatalogError, make_error
from app.triggers import TriggerSource
from app.ui_layer.components.error_message import build_error_chat_message
from app.ui_layer.components.types import ChatMessage, ChatMessageOption


# ─── ClassifiedError / CatalogError ────────────────────────────────────────


def test_classified_error_carries_info_and_message():
    info = ErrorInfo(category=ErrorCategory.CONFIG, code="X", title="t", message="m")
    err = ClassifiedError(info)
    assert err.info is info
    assert str(err) == "m"


def test_catalog_error_is_a_classified_error():
    info = make_error("CONFIG_NO_API_KEY", provider="OpenRouter")
    err = CatalogError(info)
    assert isinstance(err, ClassifiedError)
    assert err.info is info


# ─── AgentBase._classify_react_error ───────────────────────────────────────


def test_classify_react_error_fatal_with_classified_info():
    info = LLMErrorInfo(category=ErrorCategory.AUTH, title="t", message="m", provider="p")
    exc = LLMConsecutiveFailureError(1, last_error_info=info, is_immediate=True)

    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(exc)

    assert is_fatal is True
    assert fatal_exc is exc
    assert classified_info is info


def test_classify_react_error_fatal_without_classified_info():
    """A fatal error with no classified info (e.g. classification itself
    raised) must still be recognized as fatal, but with no info — the
    caller falls back to the critical/unclassified presentation."""
    exc = LLMConsecutiveFailureError(1)

    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(exc)

    assert is_fatal is True
    assert fatal_exc is exc
    assert classified_info is None


def test_classify_react_error_non_fatal_classified_error_in_chain():
    """A ClassifiedError raised (e.g. by the action router after its own
    retry budget is exhausted) must be recognized as minor-tier, not fatal —
    even when chained under an outer exception."""
    info = ErrorInfo(category=ErrorCategory.UNKNOWN, code="X", title="t", message="clean message")
    try:
        try:
            raise ClassifiedError(info)
        except ClassifiedError as inner:
            raise RuntimeError("outer wrapper") from inner
    except RuntimeError as outer:
        is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(outer)

    assert is_fatal is False
    assert fatal_exc is None
    assert classified_info is info


def test_classify_react_error_unclassified_exception():
    """A bare, unrecognized exception (a genuine bug) must fall through to
    critical/unclassified — no fatal flag, no classified info."""
    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(
        KeyError("something broke")
    )

    assert is_fatal is False
    assert fatal_exc is None
    assert classified_info is None


def test_critical_fallback_info_is_critical_severity():
    info = AgentBase._critical_fallback_info("KeyError: 'boom'")
    assert info.severity is Severity.CRITICAL
    assert info.category is ErrorCategory.INTERNAL
    assert "boom" in info.message


# ─── Consecutive-failure fallback: fold "gave up" into the real cause ─────
#
# BytePlus can return an empty response (blocked/filtered content) with no
# raised exception, so `last_error_info` is never populated — before this
# fix, a fatal LLMConsecutiveFailureError with no last_error_info fell
# straight to the critical/unclassified tier, showing a bare, disconnected
# "Aborted after consecutive failures." bubble with zero information about
# what actually failed. `_register_failure` now always passes `raw_error`
# too, so `_consecutive_failure_fallback_info` can fold the real detail and
# the "gave up" fact into one minor-tier message.


def test_classify_react_error_fatal_with_last_error_but_no_info():
    exc = LLMConsecutiveFailureError(
        5, last_error=RuntimeError("LLM returned empty response. Provider: byteplus.")
    )

    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(exc)

    assert is_fatal is True
    assert classified_info is not None
    assert classified_info.message == (
        "LLM returned empty response. Provider: byteplus. "
        "Gave up after repeated failures."
    )


def test_classify_react_error_fatal_immediate_with_last_error_uses_immediate_wording():
    exc = LLMConsecutiveFailureError(
        1, last_error=RuntimeError("boom"), is_immediate=True
    )

    _, _, classified_info = AgentBase._classify_react_error(exc)

    assert classified_info.message == "boom. This can't be fixed by retrying."


def test_classify_react_error_fatal_with_neither_info_nor_last_error_stays_critical():
    exc = LLMConsecutiveFailureError(5)

    is_fatal, fatal_exc, classified_info = AgentBase._classify_react_error(exc)

    assert is_fatal is True
    assert classified_info is None


def test_last_error_info_takes_priority_over_last_error():
    info = ErrorInfo(category=ErrorCategory.AUTH, code="X", title="t", message="the real cause")
    exc = LLMConsecutiveFailureError(
        5, last_error=RuntimeError("raw text"), last_error_info=info
    )

    _, _, classified_info = AgentBase._classify_react_error(exc)

    assert classified_info is info


# ─── ChatMessage.requires_choice: don't mislabel convenience action links ──


def test_error_action_links_do_not_require_choice():
    info = ErrorInfo(
        category=ErrorCategory.CREDIT,
        code="X",
        title="t",
        message="m",
        actions=[ErrorAction(label="Open settings", action="open_settings_model")],
    )
    message = build_error_chat_message(info, sender="System", session_id="main")

    assert message.options  # the action produced a button
    assert message.requires_choice is False
    assert message.to_dict()["requiresChoice"] is False


def test_limit_choice_message_requires_choice_by_default():
    message = ChatMessage(
        sender="Agent",
        content="Action limit reached. Continue or stop?",
        style="agent",
        options=[ChatMessageOption(label="Continue", value="continue_limit")],
    )

    assert message.requires_choice is True
    assert message.to_dict()["requiresChoice"] is True


def test_requires_choice_omitted_from_wire_format_without_options():
    message = ChatMessage(sender="System", content="No buttons here", style="system")
    assert "requiresChoice" not in message.to_dict()


# ─── Action router: clean message, no attempt-number leakage ──────────────


class _FakeContextEngine:
    def make_prompt(self, **kwargs):
        return "system prompt", None


class _FakeLLMInterface:
    """Always fails with the same RuntimeError, like an uninitialized client."""

    provider = "anthropic"
    model = "test-model"

    async def generate_response_async(self, system_prompt, user_prompt, prompt_name=None):
        raise RuntimeError("Anthropic client was not initialised.")


def test_router_wraps_persistent_llm_failure_as_classified_error():
    router = ActionRouter(
        action_library=object(),
        llm_interface=_FakeLLMInterface(),
        context_engine=_FakeContextEngine(),
    )

    with pytest.raises(ClassifiedError) as exc_info:
        asyncio.run(router._prompt_for_decision("do something"))

    info = exc_info.value.info
    # No "Unable to generate action decision on attempt N:" wrapper, and no
    # duplicated period from concatenating the original "...initialised."
    # with the appended hint.
    assert "attempt" not in info.message.lower()
    assert ".." not in info.message
    assert info.message == (
        "Anthropic client was not initialised. Check LLM configuration, "
        "API credentials, and service availability."
    )


# ─── AgentBase._handle_react_error: allow_continuation gates auto-retry ────
#
# A failure in the action-decision LLM call (react()'s _select_action) used
# to unconditionally auto-retrigger a full new turn via RUN_CONTINUATION,
# even though reaching the LLM is exactly what just failed — silently
# repeating a doomed call and, because LLMInterface._consecutive_failures is
# a shared cross-turn counter, often crossing the fatal threshold moments
# later and showing a SECOND, differently-worded message for the same
# underlying failure. react() now catches _select_action's failures
# separately and passes allow_continuation=False so _handle_react_error
# halts instead of re-triggering; every other pipeline stage keeps the
# default (allow_continuation=True, today's existing behavior).


class _FakeEventStreamManager:
    def __init__(self):
        self.logged = []

    def log(self, *args, **kwargs):
        self.logged.append((args, kwargs))


class _FakeStateManager:
    def bump_event_stream(self):
        pass


class _FakeTriggerService:
    def __init__(self):
        self.emitted = []

    async def emit(self, spec):
        self.emitted.append(spec)


class _FakeChatComponent:
    def __init__(self):
        self.messages = []

    async def append_message(self, message):
        self.messages.append(message)


class _FakeActiveAdapter:
    def __init__(self):
        self.chat_component = _FakeChatComponent()


class _FakeUIController:
    def __init__(self):
        self.active_adapter = _FakeActiveAdapter()


class _FakeAgent(AgentBase):
    """Skips AgentBase.__init__ (which wires up dozens of real subsystems —
    session/action/trigger managers, DB, etc.) and provides just the
    attributes `_handle_react_error` touches. Every OTHER method used by
    `_handle_react_error` (`_classify_react_error`, `_critical_fallback_info`,
    `_display_react_error`) is the real, inherited `AgentBase` implementation
    — only the I/O boundary (event stream, triggers, chat, run-state) is
    faked."""

    def __init__(self):
        self.event_stream_manager = _FakeEventStreamManager()
        self.state_manager = _FakeStateManager()
        self.trigger_service = _FakeTriggerService()
        self.ui_controller = _FakeUIController()
        self.run_states = []

    def _emit_run_state(self, session_id, busy):
        self.run_states.append((session_id, busy))


def test_handle_react_error_halts_without_continuation_when_disallowed():
    """The action-decision-failure path: a non-fatal ClassifiedError with
    allow_continuation=False must show exactly one message and NOT emit a
    RUN_CONTINUATION trigger — the fix for the duplicate-message bug."""
    agent = _FakeAgent()
    info = ErrorInfo(
        category=ErrorCategory.UNKNOWN, code="ACTION_DECISION_FAILED", title="t", message="m"
    )
    err = ClassifiedError(info)

    asyncio.run(
        AgentBase._handle_react_error(agent, err, "sess1", {}, allow_continuation=False)
    )

    assert agent.trigger_service.emitted == []
    assert agent.run_states == [("sess1", False)]
    assert len(agent.ui_controller.active_adapter.chat_component.messages) == 1


def test_handle_react_error_continues_by_default():
    """Regression guard: non-fatal errors from every OTHER pipeline stage
    (allow_continuation defaults to True) keep today's exact behavior —
    display the message and auto-continue via RUN_CONTINUATION."""
    agent = _FakeAgent()
    info = ErrorInfo(category=ErrorCategory.UNKNOWN, code="X", title="t", message="m")
    err = ClassifiedError(info)

    asyncio.run(AgentBase._handle_react_error(agent, err, "sess1", {}))

    assert len(agent.trigger_service.emitted) == 1
    assert agent.trigger_service.emitted[0].source == TriggerSource.RUN_CONTINUATION
    assert agent.run_states == []
    assert len(agent.ui_controller.active_adapter.chat_component.messages) == 1


def test_handle_react_error_fatal_halts_regardless_of_allow_continuation():
    """A fatal LLMConsecutiveFailureError must halt (no trigger) whether or
    not allow_continuation is set — is_fatal already implies halting."""
    agent = _FakeAgent()
    exc = LLMConsecutiveFailureError(5, last_error=RuntimeError("boom"))

    asyncio.run(
        AgentBase._handle_react_error(agent, exc, "sess1", {}, allow_continuation=True)
    )

    assert agent.trigger_service.emitted == []
    assert agent.run_states == [("sess1", False)]
    assert len(agent.ui_controller.active_adapter.chat_component.messages) == 1
