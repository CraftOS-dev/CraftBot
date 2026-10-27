"""Bounded source readers for visible session transcripts and app descriptions."""

from __future__ import annotations

import asyncio
import json

from app.agent_app import agent_view

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
    def __init__(self, apps):
        self.apps = apps

    async def capture(
        self, target_id: str, limit: int, cursor: str | None = None
    ) -> dict:
        if cursor:
            raise ReferenceError("App references do not have transcript pages.")
        project = self.apps.get_project(target_id) if self.apps else None
        if project is None:
            raise ReferenceError("The referenced app is no longer available.")
        # Explicit allowlist: no credentials, app records, filesystem or runtime URLs.
        data = {
            "name": str(project.name)[:256],
            "description": str(project.description)[:8192],
            "features": [str(f)[:256] for f in (project.features or [])[:32]],
            "type": project.project_type,
            "status": project.status,
        }
        # The manager's registered address, as the agent's own app note uses
        # (agent_base): external apps need not listen on 127.0.0.1:<port>.
        base_url = project.backend_url or project.url
        if project.status == "running" and base_url:
            described = await asyncio.to_thread(self._describe, base_url)
            data["schema"] = (
                described if described is not None else "Schema unavailable"
            )
        else:
            data["schema"] = "Schema unavailable (app is not running)"
        excerpt, clipped = bounded(json.dumps(data, ensure_ascii=False), limit)
        return {
            "label": data["name"],
            "excerpt": excerpt,
            "truncated": clipped,
            "nextCursor": None,
        }

    @staticmethod
    def _describe(base_url: str) -> dict | None:
        """Schema and operation declarations from the app's describe document.

        The document comes from agent_view.describe, the same cached, bounded,
        no-redirect reader the agent's own app note uses; this never fetches
        records."""
        result = agent_view.describe(base_url)
        if result is None:
            return None
        try:
            # Keep schema/operation declarations only. Never forward arbitrary
            # extra keys returned by an app's describe endpoint.
            entities = result.get("entities") or {}
            operations = result.get("operations") or []
            return {
                "entities": {
                    str(name)[:128]: {
                        "fields": {
                            str(field)[:128]: {
                                key: spec[key]
                                for key in (
                                    "type",
                                    "required",
                                    "readOnly",
                                    "values",
                                    "entity",
                                )
                                if key in spec
                            }
                            for field, spec in (entity.get("fields") or {}).items()
                            if isinstance(spec, dict)
                        }
                    }
                    for name, entity in entities.items()
                    if isinstance(entity, dict)
                },
                "operations": [
                    {
                        key: op[key]
                        for key in ("name", "description", "params", "destructive")
                        if key in op
                    }
                    for op in operations[:100]
                    if isinstance(op, dict) and not op.get("system")
                ],
            }
        except (TypeError, AttributeError):
            return None
