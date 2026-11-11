# -*- coding: utf-8 -*-
"""
Background run ledger.

Scheduler fires (proactive heartbeat, planners, schedule_task jobs) run in
the background session, off the user's main chat. Each background run ends
by posting ONE result into the main session: the run's final message. This
ledger holds what the in-flight run is for (its causes and proactive tasks)
and the final message it sent, from run start until run end.

The background session is a single serial lane, so at most one run is in
flight. A cause that starts while a run is still open (a fire merged into
the running batch) joins that run instead of replacing it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BackgroundRun:
    """What one background run is for, and how it ended."""

    causes: List[str] = field(default_factory=list)
    proactive_task_ids: List[str] = field(default_factory=list)
    final_message: Optional[str] = None
    suggested_responses: List[str] = field(default_factory=list)
    allow_free_text: bool = True


class BackgroundRunLedger:
    """The in-flight background run (at most one)."""

    def __init__(self) -> None:
        self._run: Optional[BackgroundRun] = None
        self._lock = threading.Lock()

    def start(self, causes: List[str], proactive_task_ids: List[str]) -> None:
        """A background run starts (or more causes join the open one)."""
        with self._lock:
            if self._run is None:
                self._run = BackgroundRun()
            self._join(causes, proactive_task_ids)

    def join(self, causes: List[str], proactive_task_ids: List[str]) -> None:
        """Causes merged into the open run's next turn."""
        with self._lock:
            if self._run is not None:
                self._join(causes, proactive_task_ids)

    def _join(self, causes: List[str], proactive_task_ids: List[str]) -> None:
        for cause in causes:
            if cause and cause not in self._run.causes:
                self._run.causes.append(cause)
        for task_id in proactive_task_ids:
            if task_id and task_id not in self._run.proactive_task_ids:
                self._run.proactive_task_ids.append(task_id)

    def note_final_message(
        self,
        message: str,
        suggested_responses: Optional[List[str]] = None,
        allow_free_text: bool = True,
    ) -> None:
        """The run's final (run-ending) message; the last one wins."""
        with self._lock:
            if self._run is None:
                self._run = BackgroundRun()
            self._run.final_message = message
            self._run.suggested_responses = list(suggested_responses or [])
            self._run.allow_free_text = allow_free_text

    def finish(self) -> Optional[BackgroundRun]:
        """Close the open run and return it (None when nothing was open)."""
        with self._lock:
            run, self._run = self._run, None
            return run


background_runs = BackgroundRunLedger()
