"""Bounded browser chat/activity buffers and the ordered chat-storage worker (RS-1.4, RS-1.8).

Components are built with ``__new__`` and fake storage so the real chat
database is never touched.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from app.ui_layer.adapters.browser_adapter import (
    BrowserActionPanelComponent,
    BrowserChatComponent,
)
from app.ui_layer.adapters.session_buffer import (
    SESSION_BUFFER_LIMIT,
    SESSION_BUFFER_SLACK,
)
from app.ui_layer.components.types import ActionItem, ChatMessage


class _FakeAdapter:
    async def _broadcast(self, message):
        pass


class _RecordingStorage:
    def __init__(self):
        self.calls = []
        self.threads = set()

    def insert_message(self, stored):
        self.threads.add(threading.get_ident())
        self.calls.append(("insert", stored.message_id))

    def clear_messages(self, session_id=None):
        self.calls.append(("clear", session_id))


def _chat_component(storage=None):
    chat = BrowserChatComponent.__new__(BrowserChatComponent)
    chat._adapter = _FakeAdapter()
    chat._messages = []
    chat._trim_at = SESSION_BUFFER_LIMIT
    chat._db = ThreadPoolExecutor(max_workers=1)
    chat._storage = storage
    return chat


def _message(i, session="a", **kwargs):
    return ChatMessage(
        sender="agent",
        content=f"m{i}",
        style="agent",
        timestamp=float(i),
        message_id=f"{session}-{i}",
        session_id=session,
        **kwargs,
    )


def test_chat_buffer_is_bounded_per_session_and_keeps_pending_questions():
    chat = _chat_component()
    question = _message(0, is_question=True)

    async def run():
        await chat.append_message(question)
        for i in range(1, 600):
            await chat.append_message(_message(i))
        await chat.append_message(_message(0, session="b"))

    asyncio.run(run())

    assert len(chat.get_messages()) <= SESSION_BUFFER_LIMIT + SESSION_BUFFER_SLACK + 2
    recent = chat.get_recent_messages()
    session_a = [m for m in recent if m.session_id == "a"]
    assert len(session_a) == SESSION_BUFFER_LIMIT + 1  # the cap + the pinned question
    assert session_a[0] is question
    assert session_a[-1].message_id == "a-599"
    assert [m.message_id for m in recent if m.session_id == "b"] == ["b-0"]


def test_chat_storage_calls_run_off_loop_in_issue_order():
    storage = _RecordingStorage()
    chat = _chat_component(storage)

    async def run():
        await asyncio.gather(
            chat.append_message(_message(1)),
            chat.append_message(_message(2)),
            chat.clear("a"),
            chat.append_message(_message(3)),
        )
        return threading.get_ident()

    loop_thread = asyncio.run(run())

    assert storage.calls == [
        ("insert", "a-1"),
        ("insert", "a-2"),
        ("clear", "a"),
        ("insert", "a-3"),
    ]
    assert loop_thread not in storage.threads


def test_activity_buffer_is_bounded_and_keeps_running_items():
    panel = BrowserActionPanelComponent.__new__(BrowserActionPanelComponent)
    panel._adapter = _FakeAdapter()
    panel._items = []
    panel._trim_at = SESSION_BUFFER_LIMIT
    panel._storage = None
    running = ActionItem(id="run-0", name="long", status="running", item_type="action")

    async def run():
        await panel.add_item(running)
        for i in range(1, 600):
            await panel.add_item(
                ActionItem(
                    id=f"done-{i}", name="x", status="completed", item_type="action"
                )
            )

    asyncio.run(run())

    assert len(panel.get_items()) <= SESSION_BUFFER_LIMIT + SESSION_BUFFER_SLACK + 1
    recent = panel.get_recent_items()
    assert len(recent) == SESSION_BUFFER_LIMIT + 1
    assert recent[0] is running
    assert recent[-1].id == "done-599"
