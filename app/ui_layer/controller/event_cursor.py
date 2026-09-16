# -*- coding: utf-8 -*-
"""
Incremental reading of agent event streams for the UI event pump.

The pump used to walk every event of every stream on each 50 ms tick, so its
cost grew with the length of every conversation. ``EventStreamCursors``
remembers, per stream, the last event record the pump has already seen, so a
tick reads only records added since.

Streams are only read, never modified. Folding or clearing a stream replaces
its record list; when the remembered record is no longer there, the whole
stream is returned once and the pump's de-duplication keys keep that safe.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


class EventStreamCursors:
    """Per-stream read positions for the UI event pump."""

    def __init__(self) -> None:
        # stream id → (last record seen, its index in the record list)
        self._positions: Dict[str, Tuple[Any, int]] = {}

    def new_events(self, stream_id: str, stream: Any) -> List[Any]:
        """Events added to ``stream`` since the previous call for ``stream_id``."""
        records = getattr(stream, "tail_events", None)
        if records is None:  # unexpected stream shape: fall back to a full read
            return list(stream.as_list())

        # Read the length once: the agent may append concurrently, and the
        # slice below must end at the same record the cursor remembers.
        count = len(records)
        start = self._start_index(stream_id, records, count)
        if count:
            self._positions[stream_id] = (records[count - 1], count - 1)
        else:
            self._positions.pop(stream_id, None)
        return [record.event for record in records[start:count]]

    def retain(self, stream_ids: Iterable[str]) -> None:
        """Forget streams that no longer exist."""
        live = set(stream_ids)
        for stream_id in list(self._positions):
            if stream_id not in live:
                del self._positions[stream_id]

    def _start_index(self, stream_id: str, records: List[Any], count: int) -> int:
        position = self._positions.get(stream_id)
        if position is None:
            return 0
        last_record, last_index = position
        if last_index < count and records[last_index] is last_record:
            return last_index + 1
        # The list was replaced (fold/clear): find the record from the end.
        for index in range(count - 1, -1, -1):
            if records[index] is last_record:
                return index + 1
        return 0
