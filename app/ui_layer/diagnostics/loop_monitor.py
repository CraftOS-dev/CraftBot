# -*- coding: utf-8 -*-
"""
Event-loop stall detector.

The browser UI server, the agent and background jobs share one asyncio loop
(docs/plans/ui-data-freshness-plan.md, Part B). When anything blocks that loop,
every browser tab stops receiving updates. This monitor makes those stalls
visible: a daemon thread pings the loop, and when a ping isn't serviced in
time it samples the loop thread's Python stack, so the log names the exact
line that blocked and whether UI-layer code was on the stack.

It only observes. It never changes how the loop or the code on it runs.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Deque, Dict, List, Optional

from agent_core.utils.logger import logger

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_THIS_FILE = Path(__file__).resolve()
_UI_LAYER_PREFIX = "app/ui_layer/"

_MAX_STACK_FRAMES = 12
_MAX_SAMPLES_PER_STALL = 5
_MAX_RECENT_STALLS = 20
_RESAMPLE_SECONDS = 1.0

ORIGIN_UI_LAYER = "ui_layer"
ORIGIN_OUTSIDE_UI_LAYER = "outside_ui_layer"
ORIGIN_UNKNOWN = "unknown"


@dataclass(frozen=True)
class StackFrame:
    """One project frame on the loop thread's stack."""

    path: str  # project-relative, forward slashes
    line: int
    function: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} in {self.function}"


@dataclass
class LoopStall:
    """A period during which the loop didn't service a ping in time."""

    started_at: float  # epoch seconds
    duration: float = 0.0  # seconds
    origin: str = ORIGIN_UNKNOWN
    # Distinct stack samples, innermost frame first; long stalls may move.
    samples: List[List[StackFrame]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "startedAt": self.started_at,
            "durationMs": round(self.duration * 1000),
            "origin": self.origin,
            "samples": [[str(frame) for frame in sample] for sample in self.samples],
        }


class LoopStallMonitor:
    """
    Detects and records event-loop stalls.

    ``start()`` must be called on the loop's own thread (it captures the
    running loop and the thread to sample). ``snapshot()`` is safe from any
    thread.
    """

    def __init__(self, threshold: float = 0.25, interval: float = 0.1) -> None:
        self._threshold = threshold
        self._interval = interval
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread_id: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()

        self._lock = threading.Lock()
        self._stall_count = 0
        self._total_seconds = 0.0
        self._max_seconds = 0.0
        self._by_origin: Dict[str, int] = {}
        self._buckets: Dict[str, int] = {"<1s": 0, "1-5s": 0, ">=5s": 0}
        self._recent: Deque[LoopStall] = deque(maxlen=_MAX_RECENT_STALLS)

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start watching the running loop. Call from the loop's thread."""
        if self._thread is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._watch, name="loop-stall-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ─────────────────────────────────────────────────────────────────────
    # Reporting
    # ─────────────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, object]:
        """Aggregate statistics plus the most recent stalls, newest first."""
        with self._lock:
            return {
                "running": self._thread is not None,
                "thresholdMs": round(self._threshold * 1000),
                "stalls": self._stall_count,
                "totalStallSeconds": round(self._total_seconds, 3),
                "maxStallSeconds": round(self._max_seconds, 3),
                "byOrigin": dict(self._by_origin),
                "buckets": dict(self._buckets),
                "recent": [stall.to_dict() for stall in reversed(self._recent)],
            }

    # ─────────────────────────────────────────────────────────────────────
    # Watcher thread
    # ─────────────────────────────────────────────────────────────────────

    def _watch(self) -> None:
        while not self._stopped.wait(self._interval):
            serviced = threading.Event()
            try:
                self._loop.call_soon_threadsafe(serviced.set)
            except RuntimeError:
                return  # loop closed
            started = time.monotonic()
            if not serviced.wait(self._threshold):
                self._observe_stall(serviced, started)

    def _observe_stall(self, serviced: threading.Event, started: float) -> None:
        stall = LoopStall(started_at=time.time() - (time.monotonic() - started))
        self._add_sample(stall)
        stall.origin = _origin_of(stall.samples[0] if stall.samples else [])
        logger.warning(
            f"[LOOP STALL] Event loop blocked >{round(self._threshold * 1000)}ms "
            f"({stall.origin}) at {_describe(stall)}"
        )

        while not serviced.wait(_RESAMPLE_SECONDS):
            if self._stopped.is_set():
                return
            self._add_sample(stall)

        stall.duration = time.monotonic() - started
        self._record(stall)
        stack = "\n    ".join(
            str(frame) for frame in (stall.samples[0] if stall.samples else [])
        )
        logger.warning(
            f"[LOOP STALL] Resolved after {stall.duration:.2f}s ({stall.origin}). "
            f"Stack (innermost first):\n    {stack or '(no project frames)'}"
        )

    def _add_sample(self, stall: LoopStall) -> None:
        if len(stall.samples) >= _MAX_SAMPLES_PER_STALL:
            return
        sample = self._sample_stack()
        if sample and (not stall.samples or stall.samples[-1] != sample):
            stall.samples.append(sample)

    def _sample_stack(self) -> List[StackFrame]:
        frame = sys._current_frames().get(self._loop_thread_id)
        frames: List[StackFrame] = []
        while frame is not None and len(frames) < _MAX_STACK_FRAMES:
            relative = _project_relative(frame.f_code.co_filename)
            if relative is not None:
                frames.append(
                    StackFrame(relative, frame.f_lineno, frame.f_code.co_name)
                )
            frame = frame.f_back
        return frames

    def _record(self, stall: LoopStall) -> None:
        with self._lock:
            self._stall_count += 1
            self._total_seconds += stall.duration
            self._max_seconds = max(self._max_seconds, stall.duration)
            self._by_origin[stall.origin] = self._by_origin.get(stall.origin, 0) + 1
            if stall.duration < 1:
                self._buckets["<1s"] += 1
            elif stall.duration < 5:
                self._buckets["1-5s"] += 1
            else:
                self._buckets[">=5s"] += 1
            self._recent.append(stall)


@lru_cache(maxsize=4096)
def _project_relative(filename: str) -> Optional[str]:
    """Project-relative path for project source files; None for anything else."""
    try:
        path = Path(filename).resolve()
    except (OSError, ValueError):
        return None
    if path == _THIS_FILE or "site-packages" in path.parts:
        return None
    try:
        return path.relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return None


def _origin_of(frames: List[StackFrame]) -> str:
    if not frames:
        return ORIGIN_UNKNOWN
    if any(frame.path.startswith(_UI_LAYER_PREFIX) for frame in frames):
        return ORIGIN_UI_LAYER
    return ORIGIN_OUTSIDE_UI_LAYER


def _describe(stall: LoopStall) -> str:
    """Innermost frame, plus the innermost UI-layer frame when different."""
    frames = stall.samples[0] if stall.samples else []
    if not frames:
        return "(no project frames on the loop thread)"
    innermost = frames[0]
    ui_frame = next((f for f in frames if f.path.startswith(_UI_LAYER_PREFIX)), None)
    if ui_frame is None or ui_frame == innermost:
        return str(innermost)
    return f"{innermost} (called from {ui_frame})"
