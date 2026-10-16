"""Validated SSE relay with bounded semantic source-echo holdback."""

import codecs
import json
import re
from .helpers import _response_variants, _sanitize_json_payloads
from .use_errors import CredentialUseError, UseCode


class StreamFilter:
    def __init__(self, fields, emit):
        self.fields, self.emit = fields, emit
        self.patterns = _response_variants(fields)
        self.tables = []
        for pattern in self.patterns.reveal():
            table, matched = [0] * len(pattern), 0
            for i in range(1, len(pattern)):
                while matched and pattern[i] != pattern[matched]:
                    matched = table[matched - 1]
                if pattern[i] == pattern[matched]:
                    matched += 1
                table[i] = matched
            self.tables.append(table)
        self.states, self.pending = {}, []
        self.pending_size = 0

    def _strings(self, value, path=()):
        if type(value) is dict:
            for key, child in value.items():
                yield from self._strings(child, (*path, key))
        elif type(value) is list:
            for index, child in enumerate(value):
                yield from self._strings(child, (*path, index))
        elif (
            isinstance(value, str)
            and path
            and path[-1]
            in (
                "content",
                "text",
                "arguments",
                "partial_json",
                "thinking",
                "refusal",
                "delta",
                "signature",
            )
        ):
            yield path, value

    def feed(self, record):
        event, data = "", []
        for line in record.splitlines():
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line.startswith("event:") and re.fullmatch(
                r"event: ?[A-Za-z0-9_.-]{1,64}", line
            ):
                event = line + "\n"
            elif line and not line.startswith(":"):
                raise CredentialUseError(UseCode.HELPER)
        if not data:
            return
        raw = "\n".join(data)
        if raw == "[DONE]":
            self.flush()
            self.emit("data: [DONE]\n\n")
            return
        cleaned = _sanitize_json_payloads([json.loads(raw)], self.fields)[0]
        for path, value in self._strings(json.loads(cleaned)):
            if len(self.states) > 2048:
                raise CredentialUseError(UseCode.LIMIT)
            states = self.states.setdefault(path, [0] * len(self.tables))
            for index, (pattern, table) in enumerate(
                zip(self.patterns.reveal(), self.tables)
            ):
                state = states[index]
                for char in value:
                    while state and char != pattern[state]:
                        state = table[state - 1]
                    if char == pattern[state]:
                        state += 1
                    if state == len(pattern):
                        # The entire echo is still in pending frames. Never
                        # release even the first source fragment to the SDK.
                        raise CredentialUseError(UseCode.HELPER)
                states[index] = state
        frame = event + "data: " + cleaned + "\n\n"
        self.pending.append(frame)
        self.pending_size += len(frame)
        if self.pending_size > 1_000_000:
            raise CredentialUseError(UseCode.LIMIT)
        if not any(any(states) for states in self.states.values()):
            self.flush()

    def flush(self):
        for frame in self.pending:
            self.emit(frame)
        self.pending, self.pending_size = [], 0


def relay(response, fields, execution, maximum):
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer, total = "", 0
    filtering = StreamFilter(fields, execution.emit)
    while True:
        if execution.cancelled.is_set():
            raise CredentialUseError(UseCode.INTERRUPTED)
        chunk = response.read1(8192)
        if not chunk:
            buffer += decoder.decode(b"", final=True)
            break
        total += len(chunk)
        if total > maximum:
            raise CredentialUseError(UseCode.LIMIT)
        buffer += decoder.decode(chunk)
        # SSE line endings are normalized after decoding; a CRLF split across
        # TLS reads is retained until the following chunk arrives.
        buffer = buffer.replace("\r\n", "\n")
        while "\n\n" in buffer:
            record, buffer = buffer.split("\n\n", 1)
            filtering.feed(record)
        if len(buffer) > 1_000_000:
            raise CredentialUseError(UseCode.LIMIT)
    if buffer.strip():
        filtering.feed(buffer)
    filtering.flush()
