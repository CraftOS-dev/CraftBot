"""Settings > Security: what the page and the approval card call.

Security settings change only through these handlers, which only the
CraftBot window and terminal reach. The agent has no action that calls
them, and from the Enhanced level up its file tools refuse
``security.json``, so it cannot lower its own security.
"""

from __future__ import annotations

from typing import Any, Dict

from app.security import audit
from app.security.approvals import Decision, broker
from app.security.policy import (
    SecurityConfigError,
    SecurityLevel,
    SecurityPolicy,
    get_store,
)


def get_security_state() -> Dict[str, Any]:
    return {"success": True, **get_store().describe()}


def _changed(before: SecurityPolicy, after: SecurityPolicy) -> None:
    changed = sorted(
        k for k, v in after.to_dict().items() if before.to_dict().get(k) != v
    )
    if changed:
        audit.record("security_settings_changed", changed=changed)


def set_security_level(level: str) -> Dict[str, Any]:
    try:
        target = SecurityLevel(level)
    except ValueError:
        return {"success": False, "error": f"Unknown security level: {level}"}
    store = get_store()
    before = store.policy
    after = store.set_level(target)
    _changed(before, after)
    return get_security_state()


def update_security_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(changes, dict) or not changes:
        return {"success": False, "error": "No settings to change"}
    store = get_store()
    before = store.policy
    try:
        after = store.update(changes)
    except SecurityConfigError as exc:
        return {"success": False, "error": str(exc)}
    _changed(before, after)
    return get_security_state()


def reset_security_settings() -> Dict[str, Any]:
    store = get_store()
    before = store.policy
    after = store.reset()
    _changed(before, after)
    return get_security_state()


def answer_approval(request_id: str, decision: str) -> Dict[str, Any]:
    try:
        choice = Decision(decision)
    except ValueError:
        return {"success": False, "error": f"Unknown decision: {decision}"}
    if choice not in (Decision.ALLOW_ONCE, Decision.ALLOW_SESSION, Decision.DENY):
        return {"success": False, "error": f"Not a user decision: {decision}"}
    if not broker.resolve(str(request_id), choice):
        return {"success": False, "error": "This approval request has already ended"}
    return {"success": True}


def pending_approvals() -> Dict[str, Any]:
    return {"success": True, "requests": broker.pending()}


def audit_entries(limit: int = 200) -> Dict[str, Any]:
    log = audit.get_log()
    intact, count, broken = log.verify()
    return {
        "success": True,
        "entries": list(reversed(log.entries(limit))),
        "intact": intact,
        "count": count,
        "broken_at": broken,
        "path": str(log.path),
    }


def run_security_check() -> Dict[str, Any]:
    from app.security.checks import run_checks

    return {"success": True, "checks": run_checks()}


def fix_security_check(fix_id: str) -> Dict[str, Any]:
    from app.security.checks import apply_fix, run_checks

    if not apply_fix(fix_id):
        return {"success": False, "error": f"No automatic fix for: {fix_id}", "checks": run_checks()}
    audit.record("security_check_fixed", fix=fix_id)
    return {"success": True, "checks": run_checks()}
