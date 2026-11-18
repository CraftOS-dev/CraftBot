# -*- coding: utf-8 -*-
"""A decision reply, read while the model writes it.

The decision reply is one JSON object::

    {"reasoning": "...", "status": "...", "actions": [{"action_name": "...", "parameters": {...}}, ...]}

``ReplyParser`` reads it piece by piece as the provider streams it. It
knows where the reasoning text is, the status line (what the step does, for
the user), where each action object starts, and the moment an action object
closes (its text then parses on its own, so the action is complete).

``ReplyStream`` follows one turn's decision. Its router asks it for a sink
per request (``begin_attempt``); the LLM call hands the reply's text to that
sink in its worker thread. The stream then, on the event loop:

- shows the reply as it is written: the reasoning text, the status line
  once complete, each action being prepared, and the text of a reply
  message (``publish``, coalesced to a few updates a second), and
- starts each action the moment its object closes, when the turn allows it
  (``start_action``) and the action may run alongside others
  (``classify``), instead of waiting for the whole reply.

Nothing here changes what is sent to the model or kept in its session
history: the reply text the provider returns is the one the router parses
and the history records, exactly as without streaming. Actions started
early run through ActionManager.execute_action like every other action and
log the same events, which come after the request's events in the stream,
as they do today.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import jiter

from agent_core.core.action_framework.registry import action_row_display
from agent_core.core.impl.llm.streaming import StreamRestarted, StreamSink
from agent_core.utils.logger import logger

#: Seconds between two updates of the reply as it is written.
PUBLISH_INTERVAL = 0.06

#: The most actions one reply runs (ActionRouter._validate_parallel_actions).
MAX_ACTIONS = 20

#: Actions the chat shows as a message (their ``message`` parameter is the
#: text being written), not as an action row.
MESSAGE_ACTIONS = frozenset({"send_message"})

#: Actions the activity view never shows (EventTransformer hides them).
HIDDEN_ACTIONS = frozenset({"end_turn"})

_UNSET = object()


def status_line(value: Any) -> Optional[str]:
    """A reply's "status" as the chat shows it: its first line, trimmed;
    None when the reply gave none."""
    if not isinstance(value, str):
        return None
    line = value.strip().split("\n", 1)[0].strip()
    return line or None


def _partial(text: str, mode: str) -> Any:
    """``text`` (a JSON value cut anywhere) parsed as far as it goes, or
    None when it does not parse yet."""
    try:
        return jiter.from_json(text.encode("utf-8"), partial_mode=mode)
    except ValueError:
        return None


class _Frame:
    __slots__ = ("kind", "role", "expect_key", "last_key", "record")

    def __init__(self, kind: str, role: Optional[str], record=None):
        self.kind = kind
        self.role = role  # None | "actions" (the actions array) | "action"
        self.expect_key = kind == "{"
        self.last_key: Optional[str] = None
        self.record = record


class ActionRecord:
    """One action object of the reply: where it starts, and (once closed)
    the parsed object. ``run_id`` is the id its run will carry."""

    __slots__ = ("index", "run_id", "start", "obj", "closed")

    def __init__(self, index: int, start: int):
        self.index = index
        self.run_id = str(uuid.uuid4())
        self.start = start
        self.obj: Optional[Dict[str, Any]] = None
        self.closed = False


class ReplyParser:
    """Reads a decision reply's JSON incrementally (see module docstring).

    ``feed`` scans only the new text, tracking strings, nesting, the
    top-level keys, and the action objects of the top-level "actions" array.
    It returns the indices of the actions that closed in that piece.

    Text before the object (a code fence, a <think> block) is skipped, and
    reading stops when the top-level object closes: a chained second object
    is never read, as the reply's own parse takes only the first.
    """

    def __init__(self) -> None:
        self.text = ""
        self._pos = 0
        self._began = False
        self.closed = False
        self._stack: List[_Frame] = []
        self._in_str = False
        self._esc = False
        self._str_start = 0
        self._str_role: Optional[str] = None
        self.reasoning_start: Optional[int] = None
        self.reasoning_end: Optional[int] = None
        self._reasoning: Optional[str] = None
        self._status_start: Optional[int] = None
        #: The status line, once its string closed (None until then).
        self.status: Optional[str] = None
        self.actions: List[ActionRecord] = []

    # ── scanning ──────────────────────────────────────────────────────

    def feed(self, delta: str) -> List[int]:
        self.text += delta
        if self.closed:
            return []
        if not self._began and not self._find_start():
            return []
        completed: List[int] = []
        text = self.text
        i = self._pos
        n = len(text)
        while i < n:
            ch = text[i]
            if self._in_str:
                if self._esc:
                    self._esc = False
                elif ch == "\\":
                    self._esc = True
                elif ch == '"':
                    self._in_str = False
                    self._close_string(i)
                i += 1
                continue
            if ch == '"':
                self._open_string(i)
            elif ch == "{" or ch == "[":
                self._open(ch, i)
            elif ch == "}" or ch == "]":
                index = self._close(i)
                if index is not None:
                    completed.append(index)
                if not self._stack:
                    self.closed = True
                    i = n
                    break
            elif ch == ",":
                if self._stack[-1].kind == "{":
                    self._stack[-1].expect_key = True
            elif ch == ":":
                if self._stack[-1].kind == "{":
                    self._stack[-1].expect_key = False
            i += 1
        self._pos = i
        return completed

    def _find_start(self) -> bool:
        """Move to the reply's top-level ``{``; False while it has not come."""
        text = self.text
        i = self._pos
        while True:
            brace = text.find("{", i)
            think = text.find("<think", i)
            if think != -1 and (brace == -1 or think < brace):
                end = text.find("</think>", think)
                if end == -1:
                    self._pos = think
                    return False
                i = end + len("</think>")
                continue
            if brace == -1:
                # Keep a tail that may be the start of "<think".
                self._pos = max(i, len(text) - len("<think"))
                return False
            self._began = True
            self._pos = brace
            return True

    def _open(self, ch: str, i: int) -> None:
        role = None
        record = None
        stack = self._stack
        if len(stack) == 1 and stack[0].kind == "{" and not stack[0].expect_key:
            if ch == "[" and stack[0].last_key == "actions":
                role = "actions"
        elif stack and stack[-1].role == "actions" and ch == "{":
            role = "action"
            record = ActionRecord(len(self.actions), i)
            self.actions.append(record)
        stack.append(_Frame(ch, role, record))

    def _close(self, i: int) -> Optional[int]:
        frame = self._stack.pop()
        if frame.role != "action":
            return None
        record = frame.record
        record.closed = True
        try:
            obj = json.loads(self.text[record.start : i + 1])
        except ValueError:
            obj = None
        record.obj = obj if isinstance(obj, dict) else None
        return record.index

    def _open_string(self, i: int) -> None:
        self._in_str = True
        self._esc = False
        self._str_start = i
        role = None
        stack = self._stack
        if len(stack) == 1 and stack[0].kind == "{":
            if stack[0].expect_key:
                role = "key"
            elif stack[0].last_key == "reasoning" and self.reasoning_start is None:
                role = "reasoning"
                self.reasoning_start = i
            elif stack[0].last_key == "status" and self._status_start is None:
                role = "status"
                self._status_start = i
        self._str_role = role

    def _close_string(self, i: int) -> None:
        if self._str_role == "key":
            try:
                self._stack[0].last_key = json.loads(self.text[self._str_start : i + 1])
            except ValueError:
                self._stack[0].last_key = None
        elif self._str_role == "reasoning":
            self.reasoning_end = i
        elif self._str_role == "status":
            try:
                self.status = status_line(json.loads(self.text[self._str_start : i + 1]))
            except ValueError:
                self.status = None
        self._str_role = None

    # ── what has been written so far ─────────────────────────────────

    @property
    def reasoning_done(self) -> bool:
        return self.reasoning_end is not None

    def reasoning(self) -> Optional[str]:
        """The reasoning text so far (all of it once ``reasoning_done``)."""
        if self.reasoning_start is None:
            return None
        if self._reasoning is not None:
            return self._reasoning
        if self.reasoning_end is not None:
            try:
                value = json.loads(self.text[self.reasoning_start : self.reasoning_end + 1])
            except ValueError:
                value = None
            self._reasoning = value if isinstance(value, str) else ""
            return self._reasoning
        value = _partial(self.text[self.reasoning_start :], "trailing-strings")
        return value if isinstance(value, str) else None

    def action_view(self, record: ActionRecord) -> Dict[str, Any]:
        """An action as written so far: its name once complete, and its
        parameters (strings cut where the reply is)."""
        if record.closed:
            obj = record.obj or {}
            name = obj.get("action_name")
            params = obj.get("parameters")
        else:
            segment = self.text[record.start :]
            whole = _partial(segment, "on")
            cut = _partial(segment, "trailing-strings")
            name = whole.get("action_name") if isinstance(whole, dict) else None
            params = cut.get("parameters") if isinstance(cut, dict) else None
        return {
            "name": name if isinstance(name, str) else None,
            "params": params if isinstance(params, dict) else {},
            "done": record.closed,
        }


class _AttemptSink(StreamSink):
    """The sink one request's LLM call streams to (worker thread side)."""

    def __init__(self, attempt: "ReplyAttempt") -> None:
        self._attempt = attempt
        self.cancelled = False

    def on_begin(self) -> None:
        self._attempt._begin()

    def on_text(self, delta: str) -> None:
        self._attempt._feed(delta)


class ReplyAttempt:
    """One request of a decision: its reply as it streams, and the actions
    it started. The router makes a new one per request (a retry is a new
    request)."""

    def __init__(self, stream: "ReplyStream", number: int) -> None:
        self.stream = stream
        self.number = number
        self.reasoning_id = f"{stream.session_id}:reasoning:{uuid.uuid4()}"
        self.parser = ReplyParser()
        self.sink = _AttemptSink(self)
        self._lock = threading.Lock()
        self._requests = 0
        self._publish_posted = False
        #: Actions started while the reply streamed: index -> (run id, task).
        self.started: Dict[int, tuple] = {}
        # Written on the loop once the first action starts; read in the
        # worker thread by _begin (a bool, so no lock is needed to read it).
        self._work_started = False

    # ── worker thread ─────────────────────────────────────────────────

    def _begin(self) -> None:
        with self._lock:
            if self._work_started:
                raise StreamRestarted(
                    "A second request began for a reply whose actions already started."
                )
            self._requests += 1
            if self._requests > 1:
                # A retry inside the call: its text replaces what came so far.
                self.parser = ReplyParser()
        self._post_publish()

    def _feed(self, delta: str) -> None:
        with self._lock:
            completed = self.parser.feed(delta)
        for index in completed:
            self.stream._post(self.stream._on_action_complete, self, index)
        self._post_publish()

    def _post_publish(self) -> None:
        if not self._publish_posted:
            self._publish_posted = True
            self.stream._post(self.stream._schedule_publish, self)

    # ── event loop ────────────────────────────────────────────────────

    @property
    def has_started(self) -> bool:
        """Whether this reply's actions began running before it ended."""
        return bool(self.started)

    def run_id_for(self, index: Optional[int]) -> Optional[str]:
        """The run id the reply's ``index``-th action object carries."""
        with self._lock:
            actions = self.parser.actions
            if index is None or not 0 <= index < len(actions):
                return None
            return actions[index].run_id

    def salvage(self) -> Dict[str, Any]:
        """The decision as far as the reply went: its reasoning, its status
        line and every action object that closed, each marked with its
        index. For a reply whose actions already started but which did not
        end well-formed (cut off, broken off by an error): the turn keeps
        what started instead of asking again, which would run those actions
        a second time."""
        with self._lock:
            reasoning = self.parser.reasoning() or ""
            status = self.parser.status
            actions = []
            ordinal = 0
            for record in self.parser.actions:
                if record.obj is not None:
                    actions.append({**record.obj, "_stream_index": ordinal})
                ordinal += 1
        return {"reasoning": reasoning, "status": status, "actions": actions}

    def view(self) -> Dict[str, Any]:
        """The reply as written so far, for the chat."""
        with self._lock:
            parser = self.parser
            reasoning = parser.reasoning()
            reasoning_done = parser.reasoning_done
            status = parser.status
            records = [(r, parser.action_view(r)) for r in parser.actions]
        actions = []
        messages = []
        for record, seen in records:
            name = seen["name"]
            if not name or name in HIDDEN_ACTIONS:
                continue
            params = seen["params"]
            if name in MESSAGE_ACTIONS:
                text = params.get("message")
                if isinstance(text, str) and text:
                    messages.append(
                        {
                            "id": record.run_id,
                            "text": text,
                            "continueWork": params.get("continue_work") is True,
                            "done": seen["done"],
                        }
                    )
                continue
            try:
                rendered = json.dumps(params, ensure_ascii=False)
            except (TypeError, ValueError):
                rendered = "{}"
            actions.append(
                {
                    "id": record.run_id,
                    "name": name,
                    "input": rendered,
                    "done": seen["done"],
                    # Shown as its real row will be (icon, display param).
                    **action_row_display(name),
                }
            )
        view = {
            "reasoning": (
                {"id": self.reasoning_id, "text": reasoning, "done": reasoning_done}
                if reasoning
                else None
            ),
            "actions": actions,
            "messages": messages,
        }
        if status:
            # Complete only: the line replaces the previous step's status
            # whole, never word by word.
            view["status"] = status
        return view


class ReplyStream:
    """One turn's decision reply as it streams (see module docstring).

    Args:
        session_id: The session the turn runs in.
        publish: Takes each update of the reply as written (on the loop).
        start_action: Starts one complete action of the reply early and
            returns its task, or None when it did not start it. The action
            dict carries ``_run_id``, the id its run must use. None: actions
            only start after the reply ends, as without streaming.
        classify: How an action may start early: "run" (it may run
            alongside the others), "block" (it must run alone: nothing after
            it starts early), or "hold" (it waits for the reply's end).
        log_reasoning: Records the reply's reasoning (text, id) in the event
            stream; called before the first action starts, so the stream
            reads reasoning first, then the actions, as without streaming.
        sender: The name the chat shows on the agent's messages.
    """

    def __init__(
        self,
        *,
        session_id: str,
        publish: Optional[Callable[[Dict[str, Any]], None]] = None,
        start_action: Optional[
            Callable[[Dict[str, Any]], Optional[asyncio.Future]]
        ] = None,
        classify: Optional[Callable[[Dict[str, Any]], str]] = None,
        log_reasoning: Optional[Callable[[str, str], None]] = None,
        sender: str = "Agent",
    ) -> None:
        self.session_id = session_id
        self.loop = asyncio.get_running_loop()
        # The turn's context, before any call's sink is set in it: actions
        # started early run in a copy of it, as the turn's other actions do.
        self._context = contextvars.copy_context()
        self.stream_id = str(uuid.uuid4())
        self.started_at = time.time()
        self.sender = sender
        self._publish = publish
        self._start_action = start_action
        self._classify = classify
        self._log_reasoning = log_reasoning
        self.current: Optional[ReplyAttempt] = None
        self._attempts = 0
        self._blocked = False
        self._closed = False
        self._last_publish = 0.0
        #: Whether the reasoning was already recorded (by log_reasoning).
        self.reasoning_logged = False

    # ── router side ───────────────────────────────────────────────────

    def begin_attempt(self) -> ReplyAttempt:
        """A new request of the decision; its sink goes to the LLM call."""
        self._attempts += 1
        self.current = ReplyAttempt(self, self._attempts)
        self._blocked = False
        return self.current

    @property
    def reasoning_id(self) -> Optional[str]:
        """The activity id of the reply's reasoning (the current request's)."""
        return self.current.reasoning_id if self.current is not None else None

    # ── turn side ─────────────────────────────────────────────────────

    def started_tasks(self, decisions: List[Dict[str, Any]]) -> List[asyncio.Future]:
        """The tasks of the decisions the reply started early, in order."""
        attempt = self.current
        if attempt is None:
            return []
        tasks = {run_id: task for run_id, task in attempt.started.values()}
        return [
            tasks[d["_run_id"]]
            for d in decisions
            if d.get("_started") and d.get("_run_id") in tasks
        ]

    def finish(self, decisions: List[Dict[str, Any]]) -> None:
        """The reply ended and the turn runs ``decisions``: the chat keeps
        what runs (its rows and its message become the real ones) and drops
        the rest of what was shown. Its status line (None: the reply gave
        none) is what the chat shows while they run, also when the reply did
        not stream."""
        keep = [
            d["_run_id"]
            for d in decisions
            if d.get("_run_id") and not d.get("_error")
        ]
        self._end(keep, status=decisions[0].get("status") if decisions else None)

    async def abort(self, *, cancel_actions: bool) -> None:
        """The turn ends before its actions ran (stopped, or failed): stop
        the reply, and settle the actions it started (cancelled when the turn
        was stopped, otherwise awaited)."""
        attempt = self.current
        tasks = []
        keep = []
        if attempt is not None:
            attempt.sink.cancelled = True
            for run_id, task in attempt.started.values():
                tasks.append(task)
                keep.append(run_id)
        self._end(keep)
        if not tasks:
            return
        if cancel_actions:
            for task in tasks:
                task.cancel()
        await asyncio.wait(tasks)

    def _end(self, keep: List[str], status: Any = _UNSET) -> None:
        """``status``: the step's status line (None: none), given when the
        reply ended well (finish); a turn that aborts leaves the chat's as
        it is."""
        if self._closed:
            return
        self._closed = True
        body: Dict[str, Any] = {"phase": "end", "keep": keep}
        if status is not _UNSET:
            body["status"] = status_line(status)
        self._emit(body)

    # ── event loop: updates and early starts ─────────────────────────

    def _post(self, callback, *args) -> None:
        """Run ``callback`` on the loop (called from the worker thread)."""
        try:
            self.loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            pass  # the loop closed (shutdown)

    def _schedule_publish(self, attempt: ReplyAttempt) -> None:
        delay = max(0.0, self._last_publish + PUBLISH_INTERVAL - time.monotonic())
        self.loop.call_later(delay, self._publish_now, attempt)

    def _publish_now(self, attempt: ReplyAttempt) -> None:
        # Cleared before the view is read: a piece fed after this point
        # posts a new update instead of being missed.
        attempt._publish_posted = False
        if self._closed or attempt is not self.current:
            return
        self._last_publish = time.monotonic()
        self._emit({"phase": "update", **attempt.view()})

    def _emit(self, body: Dict[str, Any]) -> None:
        if self._publish is None:
            return
        attempt = self.current
        payload = {
            "sessionId": self.session_id,
            "streamId": self.stream_id,
            "attempt": attempt.number if attempt is not None else 0,
            "sender": self.sender,
            "startedAt": int(self.started_at * 1000),
            **body,
        }
        try:
            self._publish(payload)
        except Exception as e:
            logger.debug(f"[REPLY STREAM] publish failed: {e}")

    def _on_action_complete(self, attempt: ReplyAttempt, index: int) -> None:
        """An action object of the reply closed: start it if it may start
        now (see class docstring)."""
        if (
            self._closed
            or attempt is not self.current
            or attempt.sink.cancelled
            or self._start_action is None
            or self._blocked
            or len(attempt.started) >= MAX_ACTIONS
        ):
            return
        with attempt._lock:
            parser = attempt.parser
            if index >= len(parser.actions):
                return
            record = parser.actions[index]
            obj = record.obj
            reasoning = parser.reasoning() if parser.reasoning_done else None
        if (
            not isinstance(obj, dict)
            or not isinstance(obj.get("action_name"), str)
            or not isinstance(obj.get("parameters", {}), dict)
        ):
            return
        kind = self._classify(obj) if self._classify is not None else "hold"
        if kind == "block":
            if not attempt.started:
                # It runs alone, as the reply's end decides; nothing after
                # it starts early.
                self._blocked = True
            return
        if kind != "run":
            return
        if not self.reasoning_logged and reasoning and self._log_reasoning:
            self._log_reasoning(reasoning, attempt.reasoning_id)
            self.reasoning_logged = True
        decision = {
            **obj,
            "parameters": dict(obj.get("parameters") or {}),
            "reasoning": reasoning or "",
            "_run_id": record.run_id,
        }
        task = self._context.copy().run(self._start_action, decision)
        if task is None:
            return
        attempt._work_started = True
        attempt.started[index] = (record.run_id, task)
        logger.info(
            f"[REPLY STREAM] Started {obj['action_name']} while the reply streams "
            f"(action {index + 1})"
        )


__all__ = [
    "ActionRecord",
    "MAX_ACTIONS",
    "ReplyAttempt",
    "ReplyParser",
    "ReplyStream",
]
