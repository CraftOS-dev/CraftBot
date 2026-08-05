# -*- coding: utf-8 -*-
"""aiohttp helper for returning a classified error as a JSON response."""

from __future__ import annotations

from aiohttp import web

from agent_core.core.errors import ErrorInfoLike


def error_json_response(info: ErrorInfoLike, status: int) -> web.Response:
    """Build a `web.json_response` from a classified error.

    Keeps the existing `"error"` string key (so current frontend `fetch`
    consumers that only read `.error` keep working unchanged) and adds
    `error_category`/`error_code` additively.
    """
    code = getattr(info, "code", None)
    return web.json_response(
        {
            "error": info.message,
            "error_category": info.category.value,
            **({"error_code": code} if code else {}),
        },
        status=status,
    )
