# -*- coding: utf-8 -*-
"""
Reference resolution + shape summarisation for action I/O.

The LLM emits compact ``{"$ref": "key", "path": "..."}`` markers in action
parameters; the manager replaces them with the actual values from
``ActionOutputStore`` before the action handler runs. This keeps large prior
outputs out of the LLM's response (and therefore out of every subsequent
prompt's event stream).

The shape summariser is the companion: it renders an action's output as a
purely structural skeleton (types, key names, list lengths) for the event
stream — no content values that the LLM would re-ship on every later prompt.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from agent_core.core.impl.action.output_store import ActionOutputStore
from agent_core.utils.logger import logger


# ──────────────────────────────────────────────────────────────────────────
# Reference resolution
# ──────────────────────────────────────────────────────────────────────────

_PATH_SEGMENT = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _split_path(path: str) -> List[Any]:
    """Tokenise a dotted/indexed path. ``a.b[2].c`` → ``['a', 'b', 2, 'c']``."""
    tokens: List[Any] = []
    for match in _PATH_SEGMENT.finditer(path):
        name, index = match.group(1), match.group(2)
        if name is not None:
            tokens.append(name)
        elif index is not None:
            tokens.append(int(index))
    return tokens


def navigate(value: Any, path: Optional[str]) -> Any:
    """Walk a dotted/indexed path through nested dicts and lists."""
    if not path:
        return value
    current = value
    for token in _split_path(path):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise KeyError(f"index {token} out of range")
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                raise KeyError(f"key {token!r} not found")
            current = current[token]
    return current


def _is_ref(value: Any) -> bool:
    return (
        isinstance(value, dict) and "$ref" in value and isinstance(value["$ref"], str)
    )


def _resolve_one(
    ref: Dict[str, Any],
    store: ActionOutputStore,
    session_id: str,
) -> Any:
    """Resolve a single ``$ref`` marker. Returns the resolved value, or a
    structured error placeholder the action handler can surface cleanly."""
    key = ref.get("$ref")
    path = ref.get("path")

    record = store.load(session_id, key) if key else None
    if record is None:
        logger.warning(
            f"[ref_resolver] Unable to resolve $ref={key!r} (session={session_id})"
        )
        return {"$ref_error": "key not found", "$ref": key, "path": path}

    try:
        return navigate(record.outputs, path)
    except KeyError as exc:
        logger.warning(f"[ref_resolver] Path {path!r} failed for $ref={key!r}: {exc}")
        return {"$ref_error": str(exc), "$ref": key, "path": path}


def resolve_refs(
    value: Any,
    store: ActionOutputStore,
    session_id: str,
) -> Any:
    """Recursively replace every ``$ref`` marker in ``value``.

    Returns a new structure with refs substituted; the original is untouched.
    Non-dict/non-list values pass through. Refs nested inside resolved
    payloads are *not* re-resolved — one level of substitution only.
    """
    if not session_id or store is None:
        return value
    if _is_ref(value):
        return _resolve_one(value, store, session_id)
    if isinstance(value, dict):
        return {k: resolve_refs(v, store, session_id) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(item, store, session_id) for item in value]
    return value


# ──────────────────────────────────────────────────────────────────────────
# Shape summary
# ──────────────────────────────────────────────────────────────────────────

# Caps to keep summaries bounded even for pathological inputs.
_MAX_LINES = 24
_MAX_KEYS_PER_DICT = 12
_SCALAR_INLINE_CHARS = 60  # show actual value for short scalars


def summarize_shape(value: Any) -> str:
    """Render a purely structural summary of ``value``.

    No content from arbitrary string leaves above ``_SCALAR_INLINE_CHARS``,
    no list items — only types, key names, and list lengths. Designed so the
    same big payload can be summarised the same way every time it appears in
    the event stream.
    """
    lines: List[str] = []

    def emit(path: str, summary: str) -> bool:
        if len(lines) >= _MAX_LINES:
            return False
        lines.append(f"{path}: {summary}" if path else summary)
        return True

    def walk(path: str, node: Any) -> None:
        if len(lines) >= _MAX_LINES:
            return

        if isinstance(node, dict):
            keys = list(node.keys())
            shown = keys[:_MAX_KEYS_PER_DICT]
            extra = len(keys) - len(shown)
            header = f"dict ({len(keys)} keys: {', '.join(map(str, shown))}{'…' if extra > 0 else ''})"
            emit(path, header)
            for k in shown:
                walk(_child_path(path, str(k)), node[k])
            return

        if isinstance(node, list):
            emit(path, f"list[{len(node)}]")
            return

        if isinstance(node, str):
            if len(node) <= _SCALAR_INLINE_CHARS:
                emit(path, f"str = {node!r}")
            else:
                emit(path, f"str (len={len(node)})")
            return

        if isinstance(node, (int, float, bool)) or node is None:
            emit(path, f"{type(node).__name__} = {node!r}")
            return

        emit(path, type(node).__name__)

    walk("", value)
    if len(lines) >= _MAX_LINES:
        lines.append("… (summary truncated)")
    return "\n".join(lines)


def _child_path(parent: str, name: str) -> str:
    return f"{parent}.{name}" if parent else name


# ──────────────────────────────────────────────────────────────────────────
# Inline-vs-shape decision
# ──────────────────────────────────────────────────────────────────────────

# Below this byte budget we keep the full output inline in the event stream;
# above it we emit shape + file path. Small enough that any Discord-size dump
# externalises, large enough that small acks (todo updates, send-message
# receipts) keep their full content where it's actually useful.
EVENT_STREAM_INLINE_BUDGET = 2000


def render_output_for_event_stream(
    outputs: Any,
    *,
    file_path: Optional[str],
    record_key: Optional[str],
) -> str:
    """Return the string the event stream should show for an action's output.

    Small outputs are inlined verbatim as pretty JSON. Large outputs collapse
    to a deterministic shape summary plus the file path where the full
    payload lives (so the agent can ``$ref`` into it).
    """
    try:
        pretty = json.dumps(outputs, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        pretty = str(outputs)

    if len(pretty) <= EVENT_STREAM_INLINE_BUDGET:
        return pretty

    shape = summarize_shape(outputs)
    footer_parts = []
    if record_key:
        footer_parts.append(
            f'Reference: {{"$ref": "{record_key}", "path": "<dotted.path>"}}'
        )
    if file_path:
        footer_parts.append(f"Full output: {file_path}")
    footer = "\n".join(footer_parts)
    return f"[shape only]\n{shape}\n{footer}".rstrip()
