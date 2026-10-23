"""Read receipts survive browser/backend crashes and never move backwards."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.usage.chat_storage import ChatStorage, StoredChatMessage


def _message(mid, sid="a", ts=1.0):
    return StoredChatMessage(mid, "agent", "reply", "agent", ts, session_id=sid)


def test_receipt_survives_reopen_without_marking_new_reply_read(tmp_path):
    path = str(tmp_path / "chat.db")
    storage = ChatStorage(path)
    storage.insert_message(_message("a1"))
    assert storage.mark_session_seen("a", "a1") == "a1"
    storage.insert_message(_message("a2", ts=2.0))

    restored = ChatStorage(path)
    assert restored.get_last_seen_message_ids() == {"a": "a1"}
    assert restored.get_recent_messages(session_id="a")[-1].message_id == "a2"


def test_delayed_or_duplicate_receipts_cannot_regress(tmp_path):
    storage = ChatStorage(str(tmp_path / "chat.db"))
    for mid, ts in (("a1", 1), ("a2", 2), ("a3", 2)):
        storage.insert_message(_message(mid, ts=ts))
    assert storage.mark_session_seen("a", "a3") == "a3"
    assert storage.mark_session_seen("a", "a1") == "a3"
    assert storage.mark_session_seen("a", "a2") == "a3"
    assert storage.mark_session_seen("a", "a3") == "a3"


def test_unknown_and_cross_session_ids_cannot_clear_an_unread_dot(tmp_path):
    storage = ChatStorage(str(tmp_path / "chat.db"))
    storage.insert_message(_message("b1", sid="b"))
    assert storage.mark_session_seen("a", "missing") is None
    assert storage.mark_session_seen("a", "b1") is None
    assert storage.get_last_seen_message_ids() == {}


def test_clear_removes_receipts_for_only_the_cleared_session(tmp_path):
    storage = ChatStorage(str(tmp_path / "chat.db"))
    for sid in ("a", "b"):
        storage.insert_message(_message(sid + "1", sid=sid))
        storage.mark_session_seen(sid, sid + "1")
    storage.clear_messages("a")
    assert storage.get_last_seen_message_ids() == {"b": "b1"}
    storage.clear_messages()
    assert storage.get_last_seen_message_ids() == {}


def test_socket_ack_is_broadcast_after_commit_and_contains_durable_marker(tmp_path):
    from app.ui_layer.adapters.browser_adapter import (
        BrowserAdapter,
        BrowserChatComponent,
    )

    path = str(tmp_path / "chat.db")
    storage = ChatStorage(path)
    storage.insert_message(_message("a1"))
    storage.insert_message(_message("a2", ts=2))
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    worker = ThreadPoolExecutor(max_workers=1)
    chat = BrowserChatComponent.__new__(BrowserChatComponent)
    chat._db = worker
    chat._storage = storage
    adapter._chat = chat
    recorded = []

    async def broadcast(payload):
        # Read through a separate SQLite connection at acknowledgement time.
        assert ChatStorage(path).get_last_seen_message_ids() == {"a": "a2"}
        recorded.append(payload)

    adapter._broadcast = broadcast

    async def run():
        await adapter._handle_ws_message(
            {"type": "session_seen", "sessionId": "a", "messageId": "a2"}
        )
        await adapter._handle_session_seen({"sessionId": "a", "messageId": "a1"})
        await adapter._handle_session_seen({"sessionId": [], "messageId": "a2"})

    try:
        asyncio.run(run())
    finally:
        worker.shutdown(wait=True)
    assert (
        recorded
        == [{"type": "session_seen", "data": {"sessionId": "a", "messageId": "a2"}}] * 2
    )
