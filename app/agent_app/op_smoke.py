"""Changed-op smoke — deterministic server-side check of a shadow boot.

After a shadow boots cleanly, invoke the operations the current change
actually touched and hand any failure (status + response body) back with
the launch result. This catches the server-side defect class one turn
earlier than the walk verifier and with better evidence (the 503-with-body
that cost the Brainstorm arc a whole fix mission was exactly this).

Everything here is structural — no free-text matching:

- "Changed" ops come from the same diff the scoped verifier uses:
  a changed `operations.json` entry (JSON compare against the baseline
  snapshot), or a changed route symbol in a non-system hook file
  (verify_scope's hook_symbols names routes as "METHOD /path"; equality
  against the op's declared executor method+path).
- Safety is a manifest fact, not a guess: if the manifest declares ANY
  bridge actions (`capabilities.actions` non-empty), the app's handlers can
  reach real-world side effects (send a mail, post a message) and NOTHING
  is invoked — the probe mandate still covers those apps. Ops marked
  `destructive` are never invoked either. The shadow's database is
  disposable by construction, so data writes are safe.
- First build (no baseline): every eligible op is a changed op, capped.

Failures never fail the launch — they are EVIDENCE, same philosophy as the
boot-log excerpts.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

_MAX_OPS = 8
_REQUEST_TIMEOUT_S = 30

# Synthesized values by declared param type — mirrors ops_verify's approach.
_SYNTH: Dict[str, Any] = {
    "string": "smoke",
    "number": 1,
    "integer": 1,
    "boolean": False,
    "array": [],
    "object": {},
}


@dataclass
class OpSmokeResult:
    name: str
    ok: bool
    status: int
    detail: str  # response-body excerpt on failure, "" on success


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _declared_ops(operations: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(operations, dict):
        return []
    ops = operations.get("operations")
    return [op for op in ops if isinstance(op, dict)] if isinstance(ops, list) else []


def _executor_route(op: Dict[str, Any]) -> Optional[str]:
    """'METHOD /path' for an op's declared HTTP executor, or None."""
    executor = op.get("executor")
    if not isinstance(executor, dict):
        return None
    method = str(executor.get("method") or "").upper()
    path = str(executor.get("path") or "")
    if not method or not path:
        return None
    return f"{method} {path}"


def select_changed_ops(project_path: Path, store_dir: Path) -> List[Dict[str, Any]]:
    """The non-destructive ops this change touched (capped at _MAX_OPS).

    Empty when the manifest declares bridge actions (side-effect safety),
    when nothing op-related changed, or when the project declares no ops.
    """
    project_path = Path(project_path)
    manifest = _load_json(project_path / "manifest.json") or {}
    capabilities = manifest.get("capabilities")
    declared_actions = (
        capabilities.get("actions") if isinstance(capabilities, dict) else None
    )
    if isinstance(declared_actions, list) and len(declared_actions) > 0:
        # The app can call real-world bridge actions from its handlers;
        # auto-invocation could send something on the user's behalf.
        return []

    operations = _load_json(project_path / "operations.json")
    eligible = [
        op
        for op in _declared_ops(operations)
        if not op.get("destructive")
        and not op.get("system")
        and _executor_route(op) is not None
    ]
    if not eligible:
        return []

    from app.agent_app import verify_scope as vs

    baseline = vs.read_baseline(Path(store_dir))
    if baseline is None:
        return eligible[:_MAX_OPS]

    changes = vs.diff_against_baseline(project_path, Path(store_dir), baseline)
    changed_routes: set = set()
    ops_json_changed = False
    for fc in changes:
        rel = Path(fc.rel).as_posix()
        if rel == "operations.json":
            ops_json_changed = True
            continue
        parent = Path(rel).parent.as_posix()
        name = Path(rel).name
        if parent == "pb/pb_hooks" and not name.startswith("_"):
            changed, _unchanged = vs.attribute_symbols(
                fc.old_text, fc.new_text, vs.hook_symbols
            )
            for label in changed:
                # Labels are symbol paths ('outer > inner (suffix)'); the
                # route symbol itself is the leaf's 'METHOD /path' core.
                leaf = label.split(" > ")[-1]
                for suffix in (" (body)", " (new)", " (removed)"):
                    if leaf.endswith(suffix):
                        leaf = leaf[: -len(suffix)]
                changed_routes.add(leaf)

    if ops_json_changed:
        # Op declarations moved — compare each entry against the baseline
        # snapshot's declarations and take the ones that differ.
        old_ops_by_name = {
            str(op.get("name")): op
            for op in _declared_ops(
                _load_json(Path(store_dir) / "snapshot" / "operations.json")
            )
        }
        for op in eligible:
            if old_ops_by_name.get(str(op.get("name"))) != op:
                changed_routes.add(_executor_route(op) or "")

    selected = [
        op for op in eligible if _executor_route(op) in changed_routes
    ]
    return selected[:_MAX_OPS]


def _superuser_token(project_path: Path, base_url: str) -> Optional[str]:
    creds = _load_json(Path(project_path) / ".superuser")
    if not isinstance(creds, dict):
        return None
    body = json.dumps(
        {"identity": creds.get("email"), "password": creds.get("password")}
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/api/collections/_superusers/auth-with-password",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode(errors="replace"))
        token = payload.get("token")
        return str(token) if token else None
    except Exception:
        return None


def _invoke(
    base_url: str, op: Dict[str, Any], token: Optional[str]
) -> OpSmokeResult:
    name = str(op.get("name") or "?")
    executor = op.get("executor") or {}
    method = str(executor.get("method") or "GET").upper()
    path = str(executor.get("path") or "")
    params = op.get("params") if isinstance(op.get("params"), dict) else {}
    synthesized = {
        key: _SYNTH.get(str(spec.get("type") or "string"), "smoke")
        for key, spec in params.items()
        if isinstance(spec, dict) and spec.get("required")
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    url = f"{base_url}{path}"
    data: Optional[bytes] = None
    if method in ("POST", "PUT", "PATCH"):
        data = json.dumps(synthesized).encode()
    elif synthesized:
        from urllib.parse import urlencode

        url += "?" + urlencode(synthesized)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            return OpSmokeResult(name=name, ok=True, status=response.status, detail="")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(errors="replace")
        except Exception:
            body = ""
        excerpt = " ".join(body.split())[:300]
        return OpSmokeResult(name=name, ok=False, status=e.code, detail=excerpt)
    except Exception as e:
        return OpSmokeResult(name=name, ok=False, status=0, detail=str(e)[:300])


def run_op_smoke(
    project_path: Path, store_dir: Path, base_url: str
) -> List[OpSmokeResult]:
    """Invoke every changed non-destructive op against the shadow. Pure
    evidence gathering: exceptions never escape, an empty list means
    nothing needed smoking."""
    try:
        ops = select_changed_ops(Path(project_path), Path(store_dir))
        if not ops:
            return []
        token = _superuser_token(Path(project_path), base_url)
        results = [_invoke(base_url, op, token) for op in ops]
        failed = [r for r in results if not r.ok]
        logger.info(
            f"[OP_SMOKE] {len(results)} changed op(s) invoked, "
            f"{len(failed)} failed"
        )
        return results
    except Exception as e:
        logger.warning(f"[OP_SMOKE] skipped: {e}")
        return []
