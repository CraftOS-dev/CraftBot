# -*- coding: utf-8 -*-
"""A restart continues each session on the provider's cached prefix.

A session's LLM history used to live only in memory, so the first request
after a restart started a new session: the whole prompt as one new message,
of which a provider that caches at message boundaries reuses only the system
prompt (observed 2026-10-19: 8,305 of 21,053 cached). The history is now
saved with the session and restored at boot when it still matches the
restored event stream. These tests pin:

* the first request after a restart starts with exactly the messages of the
  last request before it (so the provider's cache applies);
* nothing is restored that would not match: another provider's history, a
  stream that was folded or cleared since, a turn not yet marked as sent;
* the saved state survives JSON and the session storage.
"""

from __future__ import annotations

import json

from agent_core.core.event_stream.event import EventRecord
from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.impl.llm import LLMCallType

from .golden.conftest import build_interface

ACTION = LLMCallType.ACTION_SELECTION


def _decide(iface, stream, task_id="s1"):
    """One decision the way the router makes it on the session path."""
    if stream.has_session_sync(ACTION):
        prompt, _ = stream.get_delta_events(ACTION)
    else:
        iface.reset_session_history(task_id, ACTION)
        prompt = stream.to_prompt_snapshot()
    iface.generate_response_with_session(
        task_id,
        ACTION,
        prompt,
        system_prompt_for_new_session="SYSTEM",
        log_response=False,
    )
    stream.mark_session_synced(ACTION)
    iface.checkpoint_session(task_id, ACTION, stream.sync_marker(ACTION))


def _session_before_restart(monkeypatch):
    iface, recorder = build_interface(monkeypatch, "openai", "gpt-6-luna")
    iface.create_session_cache("s1", ACTION, "SYSTEM")
    stream = EventStream(llm=None, temp_dir=None)
    stream.log("action_end", "event one")
    _decide(iface, stream)
    stream.log("action_end", "event two")
    _decide(iface, stream)
    return iface, recorder, stream


def _restart(monkeypatch, iface, stream, provider="openai", model="gpt-6-luna"):
    """Save, then rebuild everything from what was saved, as a boot does."""
    saved = json.loads(json.dumps(iface.export_session("s1")))
    records = [EventRecord.from_dict(r.to_dict()) for r in stream.tail_events]
    head = stream.head_summary

    new_iface, recorder = build_interface(monkeypatch, provider, model)
    new_iface.create_session_cache("s1", ACTION, "SYSTEM")
    new_stream = EventStream(llm=None, temp_dir=None)
    new_stream.head_summary = head
    new_stream.tail_events = records
    synced = new_iface.import_session("s1", saved, new_stream)
    return new_iface, recorder, new_stream, synced


def test_the_first_request_after_a_restart_continues_the_cached_prefix(monkeypatch):
    iface, recorder, stream = _session_before_restart(monkeypatch)
    before = recorder.calls[-1]["payload"]["messages"]

    new_iface, new_recorder, new_stream, synced = _restart(monkeypatch, iface, stream)
    assert synced == len(stream.tail_events)

    new_stream.log("action_end", "event three")
    _decide(new_iface, new_stream)
    after = new_recorder.calls[-1]["payload"]["messages"]

    assert after[: len(before)] == before
    assert "event three" in after[-1]["content"]
    assert "event two" not in after[-1]["content"]  # already sent before the restart


def test_the_readout_survives_a_restart(monkeypatch):
    iface, _, stream = _session_before_restart(monkeypatch)
    new_iface, _, _, _ = _restart(monkeypatch, iface, stream)
    assert new_iface.last_request("s1", ACTION) == iface.last_request("s1", ACTION)


def test_another_providers_history_is_not_restored(monkeypatch):
    iface, _, stream = _session_before_restart(monkeypatch)
    new_iface, _, new_stream, synced = _restart(
        monkeypatch, iface, stream, provider="anthropic", model="claude-sonnet-4-6"
    )
    assert synced is None
    assert not new_stream.has_session_sync(ACTION)
    assert new_iface._session_histories == {}


def test_a_stream_folded_since_is_not_continued(monkeypatch):
    iface, _, stream = _session_before_restart(monkeypatch)
    saved = json.loads(json.dumps(iface.export_session("s1")))
    stream.head_summary = "a fold happened after the save"
    new_iface, _ = build_interface(monkeypatch, "openai", "gpt-6-luna")
    assert new_iface.import_session("s1", saved, stream) is None


def test_a_cleared_stream_is_not_continued(monkeypatch):
    iface, _, stream = _session_before_restart(monkeypatch)
    saved = json.loads(json.dumps(iface.export_session("s1")))
    stream.clear()
    stream.log("action_end", "a new conversation")
    new_iface, _ = build_interface(monkeypatch, "openai", "gpt-6-luna")
    assert new_iface.import_session("s1", saved, stream) is None


def test_a_turn_not_yet_marked_sent_is_not_saved(monkeypatch):
    # The history grows in the worker thread before the router marks the
    # stream synced; a save in between must stop at the last checkpoint.
    iface, _, stream = _session_before_restart(monkeypatch)
    checkpointed = iface.export_session("s1")[ACTION]["history"]
    stream.log("action_end", "event three")
    prompt, _ = stream.get_delta_events(ACTION)
    iface.generate_response_with_session(
        "s1", ACTION, prompt, system_prompt_for_new_session="SYSTEM", log_response=False
    )
    assert iface.export_session("s1")[ACTION]["history"] == checkpointed


def test_a_fold_drops_the_checkpoint(monkeypatch):
    iface, _, _ = _session_before_restart(monkeypatch)
    iface.reset_session_history("s1", ACTION)
    assert "history" not in iface.export_session("s1")[ACTION]


def test_the_saved_state_round_trips_through_session_storage(tmp_path, monkeypatch):
    from app.usage.session_storage import SessionStorage

    storage = SessionStorage(db_path=str(tmp_path / "sessions.db"))
    iface, _, _ = _session_before_restart(monkeypatch)
    state = iface.export_session("s1")
    storage.persist_llm_session("s1", state)
    assert storage.get_llm_session("s1") == json.loads(json.dumps(state))

    storage.persist_llm_session("s1", {})  # a cleared session
    assert storage.get_llm_session("s1") == {}

    storage.persist_llm_session("s1", state)
    storage.remove_session("s1")
    assert storage.get_llm_session("s1") == {}


def test_events_after_the_restored_sync_point_stay_unsent(monkeypatch):
    # They reach the model with the first request after the restart; until
    # then a fold must not collapse them (see test_event_stream_delivery.py).
    iface, _, stream = _session_before_restart(monkeypatch)
    stream.log("action_end", "logged after the last request")
    _, _, new_stream, synced = _restart(monkeypatch, iface, stream)
    new_stream.mark_delivered(synced)  # what the boot restore does
    delivered = [record.delivered for record in new_stream.tail_events]
    assert delivered == [True] * synced + [False] * (len(delivered) - synced)
    assert not delivered[-1]
