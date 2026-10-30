# -*- coding: utf-8 -*-
"""A delta does not repeat what the model's own reply holds (prompt audit T6).

On the session path the history keeps each decision reply (reasoning plus
every action's parameters) as an assistant message, and the next delta used
to send the same reasoning and the same inputs again as events. These tests
pin:

* the delta leaves out the reply's reasoning event, and shows an
  action_start by reference when its action and input are exactly as the
  reply has them;
* anything the run changed, anything the reply did not emit, and every
  other event is sent in full;
* full renders (a history's first request, a fold, EVENT.md) keep
  everything, and a history that did not record the reply gets no
  references.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agent_core.core.event_stream.event import SESSION_ID_INPUT_KEY, EventType
from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.impl.llm import LLMCallType

ACTION = LLMCallType.ACTION_SELECTION
CONTENT = "line of the report " * 40
PARAMS = {"file_path": "C:/work/report.md", "content": CONTENT}
WRITE = {
    "reasoning": "Write the report.",
    "actions": [{"action_name": "write_file", "parameters": PARAMS}],
}
END_TURN = {
    "reasoning": "Done.",
    "actions": [{"action_name": "end_turn", "parameters": {}}],
}
REFERENCE = "Running action write_file (input as in your reply above)."


def _run(stream, decision, params=None):
    """Log what the agent logs when it runs ``decision``."""
    stream.log(
        "agent reasoning",
        decision["reasoning"],
        event_type=EventType.REASONING,
    )
    for action in decision["actions"]:
        executed = action["parameters"] if params is None else params
        stream.log(
            "action_start",
            f"Running action {action['action_name']} with input: "
            f"{json.dumps(executed, indent=2)}.",
            event_type=EventType.ACTION_START,
            action_name=action["action_name"],
            action_input=executed,
        )
        stream.log(
            "action_end",
            f"Action {action['action_name']} completed with output: ok.",
            event_type=EventType.ACTION_END,
            action_name=action["action_name"],
        )


def _synced_stream():
    stream = EventStream(llm=None, temp_dir=None)
    stream.log("user message", "write the report")
    stream.mark_session_synced(ACTION)
    return stream


def test_the_delta_refers_to_the_reply_instead_of_repeating_it():
    stream = _synced_stream()
    stream.set_reply_in_history(ACTION, WRITE)
    _run(stream, WRITE)

    delta, _ = stream.get_delta_events(ACTION)
    assert REFERENCE in delta
    assert "line of the report" not in delta
    assert "Write the report." not in delta
    assert "completed with output: ok" in delta  # results are always sent

    full = stream.to_prompt_snapshot()
    assert "line of the report" in full and "Write the report." in full


def test_the_session_id_the_runtime_adds_is_not_a_change():
    # ActionManager.execute_action adds the session id to every input.
    stream = _synced_stream()
    stream.set_reply_in_history(ACTION, WRITE)
    _run(stream, WRITE, params={**PARAMS, SESSION_ID_INPUT_KEY: "s1"})
    delta, _ = stream.get_delta_events(ACTION)
    assert REFERENCE in delta and "line of the report" not in delta


def test_a_session_id_the_model_wrote_is_compared_like_any_input():
    written = {**PARAMS, SESSION_ID_INPUT_KEY: "made up"}
    stream = _synced_stream()
    stream.set_reply_in_history(
        ACTION,
        {
            "reasoning": "r",
            "actions": [{"action_name": "write_file", "parameters": written}],
        },
    )
    _run(stream, WRITE, params={**PARAMS, SESSION_ID_INPUT_KEY: "s1"})
    delta, _ = stream.get_delta_events(ACTION)
    assert REFERENCE not in delta


def test_an_input_the_run_changed_is_sent_in_full():
    stream = _synced_stream()
    stream.set_reply_in_history(ACTION, WRITE)
    _run(stream, WRITE, params={**PARAMS, "account": "work"})

    delta, _ = stream.get_delta_events(ACTION)
    assert REFERENCE not in delta
    assert '"account": "work"' in delta


def test_without_a_reply_in_history_everything_is_sent():
    stream = _synced_stream()
    _run(stream, WRITE)
    delta, _ = stream.get_delta_events(ACTION)
    assert "line of the report" in delta and "Write the report." in delta


def test_each_emitted_action_is_referred_to_once():
    stream = _synced_stream()
    stream.set_reply_in_history(ACTION, WRITE)
    _run(stream, WRITE)
    _run(stream, WRITE)  # the same action ran again without a reply of its own

    delta, _ = stream.get_delta_events(ACTION)
    assert delta.count(REFERENCE) == 1
    assert delta.count("line of the report") == 40  # the second run, in full
    assert delta.count("Write the report.") == 1


def test_the_single_action_reply_form_is_understood():
    stream = _synced_stream()
    stream.set_reply_in_history(
        ACTION, {"action_name": "write_file", "parameters": PARAMS}
    )
    _run(stream, {"reasoning": "r", "actions": WRITE["actions"]})
    delta, _ = stream.get_delta_events(ACTION)
    assert REFERENCE in delta


def test_the_reply_is_copied_when_recorded():
    stream = _synced_stream()
    decision = json.loads(json.dumps(WRITE))
    stream.set_reply_in_history(ACTION, decision)
    decision["actions"][0]["parameters"]["account"] = "work"  # mutated afterwards
    _run(stream, decision)  # runs with the mutated input
    delta, _ = stream.get_delta_events(ACTION)
    assert REFERENCE not in delta


def test_a_new_history_forgets_the_reply():
    for end_history in (
        lambda s: s.reset_session_sync(ACTION, reason="skill"),
        lambda s: s.clear(),
    ):
        stream = _synced_stream()
        stream.set_reply_in_history(ACTION, WRITE)
        end_history(stream)
        stream.log("user message", "again")
        stream.mark_session_synced(ACTION)
        _run(stream, WRITE)
        delta, _ = stream.get_delta_events(ACTION)
        assert REFERENCE not in delta


# ── through the router ───────────────────────────────────────────────────────


class _StreamContext:
    def __init__(self, stream):
        self.stream = stream

    def make_prompt(self, **kwargs):
        return "BASE", ""

    def get_event_stream_delta(self, call_type, session_id=None, up_to=None):
        delta, has_delta = self.stream.get_delta_events(call_type, up_to=up_to)
        return (delta, True) if has_delta else ("", False)

    def mark_event_stream_synced(self, call_type, session_id=None, up_to=None):
        self.stream.mark_session_synced(call_type, up_to=up_to)

    def reset_event_stream_sync(self, call_type, session_id=None, reason="reset"):
        self.stream.reset_session_sync(call_type, reason=reason)


class _LLM:
    def __init__(self, replies, recorded):
        self.replies = [json.dumps(r) for r in replies]
        self.recorded = list(recorded)
        self.sent = []
        self._last = False

    def has_session_cache(self, task_id, call_type):
        return True

    def fits_context(self, *args):
        return True

    def reset_session_history(self, task_id, call_type):
        pass

    def checkpoint_session(self, *args):
        pass

    def session_turn_recorded(self, task_id, call_type):
        return self._last

    async def generate_response_with_session_async(
        self,
        task_id,
        call_type,
        user_prompt,
        system_prompt_for_new_session,
        prompt_name=None,
        call_metadata=None,
    ):
        self.sent.append(user_prompt)
        self._last = self.recorded.pop(0)
        return self.replies.pop(0)


def _decide(monkeypatch, llm, stream):
    manager = SimpleNamespace(get_stream_by_id=lambda session_id: stream)
    monkeypatch.setattr(router_module, "get_event_stream_manager", lambda: manager)
    router = router_module.ActionRouter(None, llm, _StreamContext(stream))
    return asyncio.run(
        router._prompt_for_decision(
            "FULL",
            is_task=True,
            session_id="s1",
            render_prompt=lambda up_to=None: stream.to_prompt_snapshot(up_to=up_to),
            instructions="INSTR",
        )
    )


def test_the_router_sends_the_next_delta_by_reference(monkeypatch):
    stream = EventStream(llm=None, temp_dir=None)
    stream.log("user message", "write the report")
    llm = _LLM([WRITE, END_TURN], recorded=[True, True])

    _run(stream, _decide(monkeypatch, llm, stream))
    _decide(monkeypatch, llm, stream)

    assert REFERENCE in llm.sent[1]
    assert "line of the report" not in llm.sent[1]


def test_a_reply_the_history_did_not_record_is_not_referred_to(monkeypatch):
    stream = EventStream(llm=None, temp_dir=None)
    stream.log("user message", "write the report")
    llm = _LLM([END_TURN, WRITE, END_TURN], recorded=[True, False, True])

    _decide(monkeypatch, llm, stream)  # recorded: the history ends with END_TURN
    stream.log("user message", "now write it")
    _run(stream, _decide(monkeypatch, llm, stream))  # a fallback provider's reply
    _decide(monkeypatch, llm, stream)

    assert REFERENCE not in llm.sent[2]
    assert "line of the report" in llm.sent[2]
