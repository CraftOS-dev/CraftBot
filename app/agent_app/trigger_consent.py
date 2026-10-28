"""User decisions about the exact requests an Agent App may send to CraftBot.

Decisions come from the authenticated CraftBot UI, before the first fire.
Legacy per-app booleans do not authorize new or changed trigger instructions.
"""

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

_LOCK = threading.RLock()


class TriggerConsentError(ValueError):
    pass


def _fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _declarations(project) -> dict:
    path = Path(project.path) / "triggers.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise TriggerConsentError(
            "This app's agent requests could not be read."
        ) from exc
    declared = raw.get("triggers") if isinstance(raw, dict) else None
    if not isinstance(declared, dict) or any(
        not isinstance(definition, dict)
        or not isinstance(definition.get("instruction"), str)
        or not definition["instruction"].strip()
        for definition in declared.values()
    ):
        raise TriggerConsentError("This app's agent request definitions are invalid.")
    return declared


def _path(project) -> Path:
    return Path(project.path) / ".factory" / "trigger-consent.json"


def _decision(project) -> dict:
    try:
        value = json.loads(_path(project).read_text(encoding="utf-8"))
        return (
            value
            if isinstance(value, dict) and value.get("project_id") == project.id
            else {}
        )
    except (OSError, ValueError):
        return {}


def _status(declared: dict, decision: dict) -> dict:
    approved = decision.get("approved")
    if not isinstance(approved, dict):
        approved = {}
    revision = _fingerprint(declared)
    triggers = [
        {
            "name": name,
            "description": str(definition.get("description") or ""),
            "instruction": definition["instruction"],
            "change": (
                "approved"
                if approved.get(name) == _fingerprint(definition)
                else "changed"
                if name in approved
                else "new"
            ),
        }
        for name, definition in sorted(declared.items())
    ]
    required = any(trigger["change"] != "approved" for trigger in triggers)
    return {
        "revision": revision,
        "required": required,
        "needsReview": required and decision.get("reviewed_revision") != revision,
        "triggers": triggers,
    }


def status(project) -> dict:
    """UI snapshot. Errors keep requests off and are visible on the app page."""
    with _LOCK:
        try:
            return _status(_declarations(project), _decision(project))
        except TriggerConsentError as exc:
            return {
                "revision": "",
                "required": True,
                "needsReview": False,
                "triggers": [],
                "error": str(exc),
            }


def approved_trigger(project, name: str):
    """Return the reviewed definition, or None. Never execute a later reread."""
    with _LOCK:
        definition = _declarations(project).get(name)
        approved = _decision(project).get("approved")
        if (
            definition is not None
            and isinstance(approved, dict)
            and approved.get(name) == _fingerprint(definition)
        ):
            return definition
    return None


def decide(project, revision: str, allow: bool) -> dict:
    """Persist a UI decision only if the displayed definitions are still current."""
    with _LOCK:
        declared = _declarations(project)
        if not revision or revision != _fingerprint(declared):
            raise TriggerConsentError(
                "The app's requests changed. Review the updated list before choosing."
            )
        decision = {
            "project_id": project.id,
            "reviewed_revision": revision,
            "approved": (
                {
                    name: _fingerprint(definition)
                    for name, definition in declared.items()
                }
                if allow
                else {}
            ),
        }
        path = _path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep a failed save from corrupting the previous decision.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(decision, stream)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return _status(declared, decision)


def reset(project) -> None:
    """A newly acquired app cannot bring a publisher's approval with it."""
    with _LOCK:
        _path(project).unlink(missing_ok=True)
