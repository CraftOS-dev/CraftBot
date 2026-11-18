"""Bounded source readers for visible session transcripts and app descriptions."""

from __future__ import annotations

import asyncio
import json


from .service import ReferenceError, bounded


class SessionReferenceProvider:
    def __init__(self, sessions, storage):
        self.sessions, self.storage = sessions, storage

    async def capture(
        self, target_id: str, limit: int, cursor: str | None = None
    ) -> dict:
        session = self.sessions.get(target_id)
        if session is None:
            raise ReferenceError("The referenced session is no longer available.")
        page = await asyncio.to_thread(
            self.storage.reference_page, target_id, cursor, limit
        )
        excerpt, clipped = bounded(page["text"], limit)
        return {
            "label": str(session.title or "Main chat")[:256],
            "excerpt": excerpt,
            "truncated": page["truncated"] or clipped,
            "nextCursor": page["nextCursor"],
        }


class AgentAppReferenceProvider:
    async def capture(self, target_id: str, limit: int, cursor: str | None = None) -> dict:
        from app.agent_app.framework_references import reference_app, describe_reference

        if cursor:
            raise ReferenceError("App references do not have transcript pages.")
        try:
            row = await reference_app(target_id)
            if row is None:
                raise ReferenceError("The referenced app is no longer available.")
            data = await describe_reference(row)
            excerpt, clipped = bounded(json.dumps(data, ensure_ascii=False), limit)
            return {"label": str(row["name"])[:256], "excerpt": excerpt,
                    "truncated": clipped, "nextCursor": None}
        except (ValueError, OSError) as error:
            raise ReferenceError(str(error)) from error
