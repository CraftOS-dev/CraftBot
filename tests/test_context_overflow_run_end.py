# -*- coding: utf-8 -*-
"""
A run that cannot hand the model its request ends cleanly (#441).

Two failures the next turn would only repeat, with nothing counting the
attempts (the budget check refuses before anything is sent, so neither the LLM
failure counter nor the action/token limits move):

- A user message saved to a file cannot be read back in full: the file is
  missing, unreadable, outside CraftBot's storage, empty, cut short, changed,
  or the read hangs. The model would get a file path instead of the request.
- The request cannot fit the model's context window even after the router
  folded the stream; with the read-back text in parts no fold collapses, a
  message too large for the window ends here instead of as a pointer.

The react loop used to show either as a red "critical" error and queue another
turn. Now the session goes idle with one calm message saying what happened and
what to do, no turn is queued, and what the model never received is set aside
so the next message gets through. The two stay distinguishable: a read-back
failure is never reported as a context overflow. A sub-agent stops on its
first overflow and reports why to its parent.

See AgentBase._handle_react_error in app/agent_base.py.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_core.core.errors import ErrorCategory
from agent_core.core.event_stream.event import EventRecord, EventType
from agent_core.core.impl.event_stream import event_stream as event_stream_module
from agent_core.core.impl.event_stream.event_stream import (
    USER_MESSAGE_PART_KIND,
    EventStream,
    UserMessageReadBackError,
)
from agent_core.core.impl.llm.interface import LLMContextOverflowError
from app import agent_base as agent_base_module
from app.agent_base import AgentBase
from app.subagent.runner import SubAgentRunner
from tests.test_long_user_messages import (
    LONG,
    MARKERS,
    SESSION,
    _claim,
    _parts,
    _router_over,
    _stream,
    _turn,
    _user_turn,
)

OVERFLOW = (
    "Request of ~40213 input tokens exceeds the 28000-token budget "
    "(32000 window - 4000 reserved for output) for ollama/llama3."
)


_DECISION = json.dumps(
    {"reasoning": "r", "actions": [{"action_name": "send_message", "parameters": {}}]}
)


class _RecordingLLM:
    """Records every user prompt the router sends; always answers one action.

    With ``window``, refuses a prompt longer than that many characters, as the
    budget check refuses one over the window in tokens."""

    def __init__(self, session_cache: bool = True, window: int | None = None):
        self.session_cache = session_cache
        self.window = window
        self.calls = 0
        self.prompts: list[str] = []

    def has_session_cache(self, task_id, call_type):
        return self.session_cache

    def fits_context(self, *args, **kwargs):
        return True

    def input_budget(self, *args, **kwargs):
        return self.window // 4 if self.window else 10**6

    def reset_session_history(self, *args):
        pass

    def checkpoint_session(self, *args):
        pass

    def session_turn_recorded(self, *args):
        return True

    def _answer(self, user_prompt: str) -> str:
        self.calls += 1
        if self.window and len(user_prompt) > self.window:
            raise LLMContextOverflowError("Request does not fit the test window.")
        self.prompts.append(user_prompt)
        return _DECISION

    async def generate_response_with_session_async(
        self, task_id, call_type, user_prompt, system_prompt_for_new_session=None, **kw
    ):
        return self._answer(user_prompt)

    async def generate_response_async(self, system_prompt, user_prompt, **kw):
        return self._answer(user_prompt)


class _Agent:
    """An AgentBase with only what _handle_react_error touches, recorded.

    ``unsent`` is what the session's stream reports setting aside, as
    (characters, tokens, platform); ``streams`` swaps in real EventStreams."""

    def __init__(
        self,
        streams: dict[str, EventStream] | None = None,
        unsent: list[tuple[int, int, str | None]] | None = None,
        budget: int | None = 28_000,
    ):
        self.agent = AgentBase.__new__(AgentBase)
        self.run_states: list[tuple[str, str]] = []
        self.triggers: list = []
        self.bubbles: list = []
        self.set_aside: list[str] = []
        streams = streams or {}

        async def emit(spec):
            self.triggers.append(spec)

        async def append_message(message):
            self.bubbles.append(message)

        def set_aside_for(sid):
            def set_aside_unsent_user_messages(why):
                self.set_aside.append(sid)
                return list(unsent or [])

            return set_aside_unsent_user_messages

        def get_stream_by_id(sid):
            if sid in streams:
                return streams[sid]
            return SimpleNamespace(set_aside_unsent_user_messages=set_aside_for(sid))

        def input_budget():
            if budget is None:
                raise RuntimeError("no model configured")
            return budget

        a = self.agent
        a.event_stream_manager = SimpleNamespace(
            log=lambda kind, message, **kw: None, get_stream_by_id=get_stream_by_id
        )
        a.state_manager = SimpleNamespace(bump_event_stream=lambda: None)
        a.trigger_service = SimpleNamespace(emit=emit)
        a.llm = SimpleNamespace(input_budget=input_budget)
        a.ui_controller = SimpleNamespace(
            active_adapter=SimpleNamespace(
                chat_component=SimpleNamespace(append_message=append_message)
            )
        )
        a._emit_run_state = lambda sid, state: self.run_states.append((sid, state))

    def handle(self, error: Exception, session_id: str = "chat_a") -> str:
        asyncio.run(self.agent._handle_react_error(error, session_id, {}))
        return self.bubbles[-1].content if self.bubbles else ""


def _texts_gone(es: EventStream) -> bool:
    """Every part read back for a message set aside holds no text now."""
    return all(
        p.event.message.endswith(": not processed]")
        and not any(m in p.event.message for m in MARKERS)
        for p in _parts(es)
    )


def _assert_run_ended_once(agent: _Agent, session_id: str = "chat_a") -> None:
    assert agent.run_states == [(session_id, "idle")]
    assert agent.triggers == []  # nothing sends the same request again
    assert len(agent.bubbles) == 1
    assert agent.bubbles[0].style == "system"  # user-actionable, not a red crash


# --- A saved user message that cannot be read back -----------------------------


def _damage(path: Path, how: str, monkeypatch) -> None:
    if how == "missing":
        os.remove(path)
    elif how == "empty":
        path.write_text("", encoding="utf-8")
    elif how == "incomplete":
        path.write_text(LONG[:9_000], encoding="utf-8")
    elif how == "changed":  # same length, different text
        path.write_text("Z" + LONG[1:], encoding="utf-8")
    elif how == "not-text":
        path.write_bytes(b"\xff\xfe\xfa" * 100)
    elif how == "unreadable":

        def denied(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(event_stream_module, "open", denied, raising=False)
    elif how == "slow":
        time.sleep(0.5)


@pytest.mark.parametrize(
    ("how", "code"),
    [
        ("missing", "missing"),
        ("unreadable", "unreadable"),
        ("empty", "empty"),
        ("incomplete", "incomplete"),
        ("changed", "corrupted"),
        ("not-text", "corrupted"),
        ("slow", "timeout"),
    ],
)
def test_a_message_that_cannot_be_read_back_ends_the_run_unprocessed(
    tmp_path, monkeypatch, how, code
):
    es = _stream(tmp_path)
    read = EventStream.read_saved_user_message

    def damaged_read(self, meta):
        _damage(Path(meta["path"]), how, monkeypatch)
        return read(self, meta)

    monkeypatch.setattr(EventStream, "read_saved_user_message", damaged_read)
    monkeypatch.setattr(agent_base_module, "USER_MESSAGE_READ_BACK_TIMEOUT", 0.1)

    with pytest.raises(UserMessageReadBackError) as raised:
        _claim(es, LONG)
    assert raised.value.code == code
    assert _parts(es) == []  # never a partial text

    agent = _Agent(streams={"chat_a": es})
    content = agent.handle(raised.value)

    _assert_run_ended_once(agent)
    assert "Your message (26,014 characters)" in content
    assert "could not read it back" in content and "It was not processed" in content
    assert "context window" not in content  # not reported as an overflow
    assert "Shorten" not in content
    assert not any(m in content for m in MARKERS)  # never the saved text
    # A larger model would not help, so no model-settings button.
    assert not (agent.bubbles[0].options or [])
    pointer = next(
        r.event for r in es.tail_events if r.event.event_type is EventType.USER_MESSAGE
    )
    assert pointer.message.startswith(
        "[Not processed: this message (26,014 characters) could not be read back"
    )
    if how not in ("missing",):
        assert Path(raised.value.path).exists()  # the saved copy stays


def test_a_file_outside_craftbots_storage_is_not_read(tmp_path):
    es = _stream(tmp_path)
    es.log("user message", LONG, event_type=EventType.USER_MESSAGE)
    meta = dict(es.tail_events[-1].event.externalized)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text(LONG, encoding="utf-8")

    with pytest.raises(UserMessageReadBackError) as raised:
        es.read_saved_user_message({**meta, "path": str(outside)})
    assert raised.value.code == "outside_storage"


def _saved(tmp_path):
    """A stream holding LONG saved behind a pointer, and that pointer's metadata."""
    es = _stream(tmp_path)
    es.log("user message", LONG, event_type=EventType.USER_MESSAGE)
    return es, dict(es.tail_events[-1].event.externalized)


@pytest.mark.parametrize("where", ["elsewhere", "traversal", "empty-path"])
def test_only_files_inside_the_sessions_storage_are_read(tmp_path, where):
    """Even a file holding exactly the saved text is refused outside storage."""
    es, meta = _saved(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text(LONG, encoding="utf-8")
    path = {
        "elsewhere": str(outside),
        "traversal": str(es.temp_dir / ".." / "elsewhere.txt"),
        "empty-path": "",
    }[where]

    with pytest.raises(UserMessageReadBackError) as raised:
        es.read_saved_user_message({**meta, "path": path})
    assert raised.value.code == "outside_storage"


def test_a_symlink_out_of_storage_is_not_followed(tmp_path):
    es, meta = _saved(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text(LONG, encoding="utf-8")
    link = es.temp_dir / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("creating symlinks needs a privilege this account lacks")

    with pytest.raises(UserMessageReadBackError) as raised:
        es.read_saved_user_message({**meta, "path": str(link)})
    assert raised.value.code == "outside_storage"


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
def test_a_junction_out_of_storage_is_not_followed(tmp_path):
    """Junctions need no privilege on Windows, unlike symlinks."""
    import _winapi

    es, meta = _saved(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "copy.txt").write_text(LONG, encoding="utf-8")
    _winapi.CreateJunction(str(outside), str(es.temp_dir / "junction"))

    with pytest.raises(UserMessageReadBackError) as raised:
        es.read_saved_user_message(
            {**meta, "path": str(es.temp_dir / "junction" / "copy.txt")}
        )
    assert raised.value.code == "outside_storage"


@pytest.mark.skipif(os.name != "nt", reason="Windows paths ignore case")
def test_a_windows_path_in_another_case_is_still_read(tmp_path):
    es, meta = _saved(tmp_path)

    text = es.read_saved_user_message({**meta, "path": meta["path"].upper()})
    assert text == LONG


def test_a_file_replaced_after_the_check_is_refused(tmp_path, monkeypatch):
    es, meta = _saved(tmp_path)
    monkeypatch.setattr(event_stream_module.os.path, "samestat", lambda a, b: False)

    with pytest.raises(UserMessageReadBackError) as raised:
        es.read_saved_user_message(meta)
    assert raised.value.code == "corrupted"


def test_events_saved_before_this_change_still_load_and_send(harness_router):
    """A stream persisted by an older CraftBot has no ``externalized`` field;
    its old-style pointers load, and do not trip the router's guard."""
    es, router, llm = harness_router
    old = {
        "event": {
            "message": "Action None completed. The output is too long therefore "
            "is saved in event_action_1.txt to save token.",
            "kind": "user message",
            "severity": "INFO",
            "event_type": "user_message",
            "ts": "2026-10-01T10:00:00+00:00",
        },
        "ts": "2026-10-01T10:00:00+00:00",
    }
    record = EventRecord.from_dict(old)
    assert record.event.externalized is None
    es.tail_events.append(record)

    _turn(router, "user chat")
    assert "Action None completed" in llm.prompts[-1]


def test_a_pointer_whose_text_was_not_read_back_is_never_sent(harness_router):
    """The router's guard: whatever logged the pointer, the model never gets
    a file path in place of the user's request."""
    es, router, llm = harness_router
    es.log("user message", LONG, event_type=EventType.USER_MESSAGE)

    with pytest.raises(UserMessageReadBackError) as raised:
        _turn(router, "user chat")
    assert raised.value.code == "not_read_back"
    assert llm.calls == 0

    agent = _Agent(streams={SESSION: es})
    content = agent.handle(raised.value, session_id=SESSION)
    _assert_run_ended_once(agent, SESSION)
    assert "could not read it back" in content


def test_a_batch_with_one_unreadable_message_processes_none_of_it(
    tmp_path, monkeypatch
):
    es = _stream(tmp_path)
    read = EventStream.read_saved_user_message
    calls = []

    def second_missing(self, meta):
        calls.append(meta["path"])
        if len(calls) == 2:
            os.remove(meta["path"])
        return read(self, meta)

    monkeypatch.setattr(EventStream, "read_saved_user_message", second_missing)
    with pytest.raises(UserMessageReadBackError):
        _claim(es, LONG, LONG.replace("BEGIN", "OTHER"))

    agent = _Agent(streams={"chat_a": es})
    agent.handle(
        UserMessageReadBackError("missing", "gone", path=calls[1], chars=26_014)
    )

    _assert_run_ended_once(agent)
    assert _texts_gone(es)
    notes = [
        r.event.message
        for r in es.tail_events
        if r.event.event_type is EventType.USER_MESSAGE
    ]
    assert len(notes) == 2 and all(n.startswith("[Not processed") for n in notes)


@pytest.fixture
def harness_router(tmp_path, monkeypatch):
    es = _stream(tmp_path)
    llm = _RecordingLLM()
    return es, _router_over(es, llm, monkeypatch), llm


def test_after_a_read_back_failure_the_next_message_gets_through(
    harness_router, monkeypatch
):
    es, router, llm = harness_router
    read = EventStream.read_saved_user_message
    broken = [True]

    def missing(self, meta):
        if broken.pop() if broken else False:
            os.remove(meta["path"])
        return read(self, meta)

    monkeypatch.setattr(EventStream, "read_saved_user_message", missing)
    with pytest.raises(UserMessageReadBackError) as raised:
        _claim(es, LONG)
    _Agent(streams={SESSION: es}).handle(raised.value, session_id=SESSION)

    _user_turn(router, es, "Here is a shorter version of my request.")

    prompt = llm.prompts[-1]
    assert "Here is a shorter version of my request." in prompt
    assert "[Not processed: this message (26,014 characters)" in prompt
    assert not any(m in prompt for m in MARKERS)


# --- The request cannot fit the context window ---------------------------------


def test_a_read_back_message_too_large_for_the_window_ends_the_run_once(
    tmp_path, monkeypatch
):
    """Through the real router and stream: the read-back parts are not
    collapsed into a pointer to make the request fit; the overflow is raised
    after one fold, the run ends once, and a shorter follow-up is answered.
    Setting aside keeps the UI pump's place (it finds the last record it saw
    by identity), so the chat is not replayed."""
    from app.ui_layer.controller.event_cursor import EventStreamCursors

    es = _stream(tmp_path)
    llm = _RecordingLLM(window=20_000)
    router = _router_over(es, llm, monkeypatch)
    cursors = EventStreamCursors()

    with pytest.raises(LLMContextOverflowError) as raised:
        _user_turn(router, es, LONG)
    assert llm.calls == 2  # the request, then once more after the fold
    assert cursors.new_events(SESSION, es)[-1].kind == USER_MESSAGE_PART_KIND

    agent = _Agent(streams={SESSION: es}, budget=llm.input_budget())
    content = agent.handle(raised.value, session_id=SESSION)
    _assert_run_ended_once(agent, SESSION)
    assert "Your message (26,014 characters) is too large" in content
    assert [o.value for o in agent.bubbles[0].options] == ["open_settings_model"]
    assert _texts_gone(es)
    assert cursors.new_events(SESSION, es) == []  # nothing replayed

    _user_turn(router, es, "Here is a shorter version of my request.")

    follow_up = llm.prompts[-1]
    assert "Here is a shorter version of my request." in follow_up
    assert not any(m in follow_up for m in MARKERS)
    assert "[Not processed: this message (26,014 characters) did not fit" in follow_up


@pytest.mark.parametrize(
    ("unsent", "says", "never_says"),
    [
        # A: the user typed a message too large for the model.
        (
            [(26_014, 20_000, None)],
            [
                "Your message (26,014 characters) is too large",
                "It was not processed",
                "Shorten it",
                # The budget check's own numbers, unchanged.
                "~40213 input tokens",
                "28000-token budget",
                "32000 window",
            ],
            ["This conversation"],
        ),
        # B: the oversized message arrived through an integration.
        (
            [(26_014, 20_000, "WhatsApp")],
            ["A message received from WhatsApp (26,014 characters)"],
            ["Shorten", "Your message"],
        ),
        # C: a continuation turn, nothing new from the user.
        (
            [],
            ["This conversation no longer fits", "Start a new chat"],
            ["Shorten", "not processed"],
        ),
        # D: history, not the short new message, is what does not fit.
        (
            [(42, 12, None)],
            [
                "This conversation no longer fits",
                "Your latest message was not processed; send it again.",
            ],
            ["Shorten"],
        ),
    ],
    ids=["typed-message", "integration-message", "continuation", "history"],
)
def test_the_overflow_advice_follows_what_did_not_fit(unsent, says, never_says):
    agent = _Agent(unsent=unsent)

    content = agent.handle(LLMContextOverflowError(OVERFLOW))

    _assert_run_ended_once(agent)
    assert agent.set_aside == ["chat_a"]
    for text in says:
        assert text in content
    for text in never_says:
        assert text not in content


def test_without_a_known_budget_the_message_size_decides():
    agent = _Agent(unsent=[(26_014, 20_000, None)], budget=None)

    assert "Your message (26,014 characters)" in agent.handle(
        LLMContextOverflowError(OVERFLOW)
    )


def test_an_overflow_under_another_exception_ends_the_run_too():
    agent = _Agent()
    try:
        try:
            raise LLMContextOverflowError(OVERFLOW)
        except LLMContextOverflowError as inner:
            raise RuntimeError("decision failed") from inner
    except RuntimeError as outer:
        agent.handle(outer)

    _assert_run_ended_once(agent)


def test_repeated_overflows_never_queue_a_turn():
    """Each overflow is final for its run: nothing schedules the same request."""
    agent = _Agent()

    for _ in range(3):
        agent.handle(LLMContextOverflowError(OVERFLOW))

    assert agent.triggers == []
    assert agent.run_states == [("chat_a", "idle")] * 3


def test_only_the_overflowing_session_is_stopped():
    agent = _Agent()

    agent.handle(LLMContextOverflowError(OVERFLOW), session_id="chat_b")

    _assert_run_ended_once(agent, "chat_b")
    assert {m.session_id for m in agent.bubbles} == {"chat_b"}
    assert agent.set_aside == ["chat_b"]


def test_other_turn_errors_still_continue_the_run():
    """Unchanged: a recoverable error is shown and the run goes on."""
    agent = _Agent()

    agent.handle(RuntimeError("Model failed"))

    assert agent.run_states == []
    assert len(agent.triggers) == 1
    assert agent.bubbles[0].style == "error"
    assert agent.set_aside == []


def test_only_unsent_user_messages_are_set_aside(tmp_path):
    es = _stream(tmp_path)
    _claim(es, "an earlier question")
    es.mark_delivered()
    short = "a short follow-up"
    _claim(es, short)
    es.log("action_end", "small tool result", event_type=EventType.ACTION_END)

    reported = es.set_aside_unsent_user_messages(
        "did not fit the model's context window"
    )

    assert [(chars, platform) for chars, _, platform in reported] == [
        (len(short), None)
    ]
    messages = [r.event.message for r in es.tail_events if r.event.kind != "datetime"]
    assert messages[0] == "an earlier question"
    assert messages[1].startswith("[Not processed: this message (17 characters)")
    assert messages[2] == "small tool result"
    saved = messages[1].split("saved in ", 1)[1].rstrip(".]")
    assert Path(saved).read_text(encoding="utf-8") == short


# --- Sub-agents: stop on the first overflow and tell their parent why ----------


def test_a_subagent_overflow_ends_that_subagent_after_one_attempt():
    ended: list[tuple[str, str, str]] = []
    sub = SimpleNamespace(id="sub_1", iterations=0, status="running")
    sub.is_terminal = lambda: sub.status != "running"

    def end(sid, status, result):
        ended.append((sid, status, result))
        sub.status = status

    runner = SubAgentRunner.__new__(SubAgentRunner)
    runner.sub = sub
    runner.definition = SimpleNamespace(max_iterations=10)
    runner.manager = SimpleNamespace(
        end=end, event_stream_manager=SimpleNamespace(log=lambda **kw: None)
    )
    attempts = 0

    async def decide(query, sid):
        nonlocal attempts
        attempts += 1
        raise LLMContextOverflowError(OVERFLOW)

    runner.step = SimpleNamespace(decide=decide)
    runner.sub.query = "summarize the repo"

    asyncio.run(runner._turns())

    assert attempts == 1
    assert [(sid, status) for sid, status, _ in ended] == [("sub_1", "failed")]
    assert "~40213 input tokens" in ended[0][2]  # the parent reads why


def test_a_read_back_failure_is_not_classified_as_a_context_overflow():
    info = AgentBase._read_back_failure_info(
        UserMessageReadBackError(
            "missing", "the saved file no longer exists", path="p", chars=26_014
        )
    )
    assert info.category is ErrorCategory.NOT_FOUND
    assert info.code == "USER_MESSAGE_READ_BACK_FAILED"
    overflow = AgentBase._context_overflow_info(LLMContextOverflowError(OVERFLOW))
    assert overflow.category is ErrorCategory.CONTEXT_OVERFLOW
