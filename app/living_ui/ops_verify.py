"""Live verification of an external app's A2App operation mappings.

Spec: docs/design/external-app-a2app-adapter.md §7. The protocol's own
rule for any-technology mappings: a mapping that does not actually work is
rejected rather than shipped. The adoption mission calls this (via the
living_ui_ops_verify action) after authoring operations.json; it drives
the RUNNING app through the real proxy surface — the same calls any agent
would make — so a pass here means the surface actually works.

Deterministic and mechanical by design (no sub-agent): identity probe,
manifest validation, then one real invocation per non-destructive op with
synthesized parameters. Destructive ops are shape-checked only — never
invoked on data we do not own.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.living_ui.ops_manifest import (
    load_external_manifest,
    synthesize_params,
)


async def verify_external_ops(
    project: Any, op_names: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Verify a running external project's A2App surface end to end.
    Returns {status, identity_ok, checked, passed, failed, results, message};
    status is 'success' only when the manifest validates, identity answers,
    and every checked op either passes or is destructive (skipped)."""
    import aiohttp

    project_dir = Path(project.path)
    base = f"http://127.0.0.1:{project.port}"

    manifest, problems = load_external_manifest(project_dir)
    if problems:
        return {
            "status": "error",
            "identity_ok": False,
            "checked": 0,
            "passed": 0,
            "failed": 0,
            "results": [],
            "message": (
                "operations.json failed structural validation — fix these "
                "before verifying live:\n- " + "\n- ".join(problems[:20])
            ),
        }

    token = ""
    try:
        token = (project_dir / ".agent-token").read_text(encoding="utf-8").strip()
    except Exception:
        pass
    headers = {"X-LUI-Agent": "ops-verify"}
    if token:
        headers["X-LUI-Token"] = token

    results: List[Dict[str, Any]] = []
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=90)
    ) as session:
        # Identity first: the only reliable probe that the thing on this
        # port is the A2App surface of THIS app (a status code never is).
        identity_ok = False
        try:
            async with session.get(f"{base}/api/_a2app") as resp:
                ident = await resp.json(content_type=None)
                identity_ok = (
                    resp.status == 200 and ident.get("a2app") is True
                )
        except Exception:
            identity_ok = False
        if not identity_ok:
            return {
                "status": "error",
                "identity_ok": False,
                "checked": 0,
                "passed": 0,
                "failed": 0,
                "results": [],
                "message": (
                    f"GET {base}/api/_a2app did not answer as an A2App "
                    "surface — is the project running? Launch via "
                    "living_ui_notify_ready first."
                ),
            }

        ops = manifest.get("operations", [])
        if op_names:
            wanted = set(op_names)
            ops = [o for o in ops if o.get("name") in wanted]
        for op in ops:
            name = op.get("name", "?")
            if op.get("destructive") is True:
                # Structure already validated above; never invoke on real data.
                results.append(
                    {
                        "op": name,
                        "outcome": "skipped_destructive",
                        "detail": (
                            "shape-checked only — destructive ops are never "
                            "auto-invoked"
                        ),
                    }
                )
                continue
            executor = op["executor"]
            params = synthesize_params(op)
            url = base + executor["path"]
            kwargs: Dict[str, Any] = {"headers": headers}
            if executor["method"] in ("GET", "DELETE"):
                if params:
                    kwargs["params"] = {k: str(v) for k, v in params.items()}
            else:
                kwargs["json"] = params
            try:
                async with session.request(
                    executor["method"], url, **kwargs
                ) as resp:
                    body = (await resp.read())[:2000].decode(
                        "utf-8", errors="replace"
                    )
                    results.append(_classify(name, params, resp.status, body))
            except Exception as e:
                results.append(
                    {
                        "op": name,
                        "outcome": "unreachable",
                        "detail": str(e)[:300],
                        "params_sent": params,
                    }
                )

    failed = [r for r in results if r["outcome"] not in ("pass", "skipped_destructive")]
    passed = [r for r in results if r["outcome"] == "pass"]
    ok = not failed
    return {
        "status": "success" if ok else "error",
        "identity_ok": True,
        "checked": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "results": results,
        "message": (
            f"A2App surface verified: {len(passed)} op(s) invoked live, "
            f"{len(results) - len(passed) - len(failed)} destructive op(s) "
            "shape-checked."
            if ok
            else (
                f"{len(failed)} op(s) failed live verification. Per the "
                "protocol, a mapping that does not work must be fixed or "
                "removed from operations.json before the import is done. "
                "For each failure, check executor.upstream against the "
                "app's real API (path, method, body field names)."
            )
        ),
    }


def _classify(
    name: str, params: Dict[str, Any], status: int, body: str
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "op": name,
        "status": status,
        "params_sent": params,
        "body_excerpt": body,
    }
    if 200 <= status < 300:
        entry["outcome"] = "pass"
        entry.pop("body_excerpt", None)
        return entry
    is_envelope = False
    try:
        is_envelope = json.loads(body).get("a2app") is True
    except Exception:
        pass
    if status == 404 and is_envelope:
        entry["outcome"] = "unknown_operation"
        entry["detail"] = "the proxy has no such op — executor.path/method drift"
    elif status == 404:
        entry["outcome"] = "upstream_not_found"
        entry["detail"] = (
            "the app has no such endpoint — executor.upstream.path is "
            "probably wrong (or the synthesized id does not exist; judge "
            "from the body excerpt)"
        )
    elif status == 400:
        entry["outcome"] = "rejected_params"
        entry["detail"] = (
            "the call was rejected — check param names/types against what "
            "the app expects (upstream.body template may need remapping)"
        )
    elif status >= 500:
        entry["outcome"] = "upstream_error"
        entry["detail"] = "the app errored on the mapped call"
    else:
        entry["outcome"] = "failed"
        entry["detail"] = f"unexpected HTTP {status}"
    return entry
