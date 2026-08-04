# -*- coding: utf-8 -*-
"""aiohttp helper for returning a classified error as a JSON response."""

from __future__ import annotations

from aiohttp import web

from agent_core.core.errors import ErrorInfoLike
from app.errors.envelope import error_fields


def error_json_response(info: ErrorInfoLike, status: int) -> web.Response:
    """Build a `web.json_response` from a classified error.

    Keeps the existing `"error"` string key (so current frontend `fetch`
    consumers that only read `.error` keep working unchanged) and adds
    `error_category`/`error_code`/`error_severity` additively via the shared
    `error_fields()` tag block (app/errors/envelope.py) — the `error_severity`
    key is new here; `error`/`error_category`/`error_code` are byte-identical
    to the contract this shipped with in Phase 1.
    """
    return web.json_response(
        {"error": info.message, **error_fields(info)},
        status=status,
    )
