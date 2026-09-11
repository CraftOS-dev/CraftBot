"""Walk-verify hard gate (Agent App).

Runs the ``walk_verify`` sub-agent against a RUNNING project and parses its
verdicts. Called by ``agent_app_walk_verify`` AFTER a successful launch —
success is only reported to the building agent when every feature verdict
is pass/unverified. Structural by design: the building agent cannot skip it
or grade itself.

SCOPED VERIFY (docs/design/scoped-walk-verify.md rev 2): the verifier is
handed the evidence to decide what to re-test — the symbol-level diff since
the last promote, each feature's verify history, recorded coverage — and
returns a SCOPE block alongside its verdicts. This module builds that
evidence into the query and records what the verifier decided; it never
decides scope itself.
"""

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _runtime():
    from app.internal_action_interface import InternalActionInterface as I

    parts = (
        I.subagent_manager,
        I.action_manager,
        I.action_library,
        I.llm_interface,
        I.event_stream_manager,
    )
    return None if any(p is None for p in parts) else parts


# ---------------------------------------------------------------------------
# Query composition — the evidence the verifier decides from
# ---------------------------------------------------------------------------

_TOUCHES_HINT = re.compile(r"\(touches:\s*([^)]+)\)", re.I)


def _builder_hints(project_path: Path) -> List[str]:
    """`(touches: …)` notes the builder left on ## Changes entries — claims
    by an interested party, surfaced as such."""
    spec = Path(project_path) / "reference" / "requirements.md"
    if not spec.is_file():
        return []
    try:
        text = spec.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    changes = text.split("## Changes", 1)[-1] if "## Changes" in text else ""
    hints = []
    for line in changes.splitlines():
        if line.strip().startswith("~~"):
            continue
        m = _TOUCHES_HINT.search(line)
        if m:
            hints.append(m.group(1).strip())
    return hints[-3:]


def _exact_symbols_factory(manager, store_dir: Path):
    """symbols_for(rel, text) backed by `lui symbols` (the project's own
    TypeScript when reachable). Returns None on any failure so attribution
    falls back to the heuristic parser. Synchronous and short: one node
    process per changed code file, 20 s cap each."""
    runner = getattr(manager, "runner", None)
    cli = getattr(runner, "_cli", None)
    if runner is None or cli is None:
        return None
    try:
        from app import node_runtime
    except Exception:
        node_runtime = None
    tmp_dir = Path(store_dir) / "tmp"

    def symbols_for(rel: str, text: str):
        try:
            from app.agent_app.verify_scope import Symbol

            tmp_dir.mkdir(parents=True, exist_ok=True)
            suffix = Path(rel).suffix or ".ts"
            tmp = tmp_dir / f"sym_{abs(hash((rel, text))) % 10**8}{suffix}"
            tmp.write_text(text, encoding="utf-8")
            try:
                env = node_runtime.child_env() if node_runtime else None
                kwargs: Dict[str, Any] = {}
                try:
                    import sys as _sys

                    if _sys.platform == "win32":
                        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                except Exception:
                    pass
                proc = subprocess.run(
                    cli("symbols", str(tmp)),
                    capture_output=True,
                    text=True,
                    timeout=20,
                    env=env,
                    **kwargs,
                )
            finally:
                try:
                    tmp.unlink()
                except Exception:
                    pass
            if proc.returncode != 0:
                return None
            line = next(
                (ln for ln in proc.stdout.splitlines() if ln.strip().startswith("[")),
                "",
            )
            data = json.loads(line) if line else []
            if not data:
                return None
            return [
                Symbol(
                    name=str(d["name"]),
                    start=int(d["start"]),
                    end=int(d["end"]),
                    depth=int(d.get("depth", 0)),
                    kind=str(d.get("kind", "fn")),
                )
                for d in data
                if d.get("name")
            ]
        except Exception as e:
            logger.debug(f"[WALK_VERIFY] exact symbols unavailable for {rel}: {e}")
            return None

    return symbols_for


def _disputed_verdicts(project) -> List[str]:
    """What the builder reproduced and says the last verdict got wrong.

    A verifier drives a feature once; the builder can run it as many times as
    it likes, read the server log while it does, and inspect the record
    afterwards. So when the two disagree, the builder's evidence is worth
    something, and a verifier repeating a verdict should have to answer it
    rather than re-run blind. Never raises.
    """
    try:
        from app.factory.host_craftbot import get_factory_host

        return [
            str(e.get("what", "")).strip()
            for e in get_factory_host().disputed(project.id)[-5:]
            if str(e.get("what", "")).strip()
        ]
    except Exception as e:
        logger.debug(f"[WALK_VERIFY] disputed ledger unavailable: {e}")
        return []


def build_verify_evidence(
    project,
    verify_path: Path,
    manager=None,
    scope: str = "auto",
    defect_features: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Everything the verifier receives beyond URL/path — as one text block
    plus the structured pieces the caller records. Never raises: a broken
    evidence builder must degrade to the pre-scoping query, not block the
    verify."""
    from app.agent_app import verify_scope as vs

    out: Dict[str, Any] = {
        "text": "",
        "changes": [],
        "baseline": None,
        "store_dir": None,
    }
    try:
        store_dir = vs.verify_store_dir(project)
        out["store_dir"] = store_dir
        baseline = vs.read_baseline(store_dir)
        out["baseline"] = baseline
        changes: List[Any] = []
        total_watched = 0
        if baseline is not None:
            changes = vs.diff_against_baseline(verify_path, store_dir, baseline)
            total_watched = len(baseline.get("files") or {})
            vs.attribute_changes(
                verify_path,
                changes,
                symbols_for=_exact_symbols_factory(manager, store_dir),
            )
        out["changes"] = changes

        blocks: List[str] = []
        if scope == "full":
            blocks.append(
                "VERIFY MODE: FULL — a full sweep was requested (by the user or the "
                "builder). Your SCOPE must be FULL: exercise every feature."
            )
        else:
            blocks.append(
                "VERIFY MODE: AUTO — decide your own scope from the evidence below. "
                "Open with a SCOPE block (DELTA or FULL) that lists what you include "
                "and, for each feature you exclude, why the diff cannot reach it."
            )
        blocks.append(vs.render_diff_block(changes, baseline, total_watched))
        blocks.append(vs.render_history_block(store_dir))
        cov = (
            vs.render_coverage_block(store_dir, changes) if baseline is not None else ""
        )
        if cov:
            blocks.append(cov)
        if defect_features:
            blocks.append(
                "DEFECTS TO RE-CHECK (this is a fix mission — these features were "
                "observed broken last walk and MUST be in scope):\n  - "
                + "\n  - ".join(defect_features)
            )
        hints = _builder_hints(verify_path)
        if hints:
            blocks.append(
                "BUILDER'S HINT (a claim by an interested party — read it, do not "
                "trust it): touches " + "; ".join(hints)
            )
        disputes = _disputed_verdicts(project)
        if disputes:
            blocks.append(
                "DISPUTED BY THE BUILDER (it reproduced these and reports the "
                "last verdict was wrong — its evidence, not mine). Put every "
                "one IN SCOPE and exercise it yourself. Then either confirm "
                "the failure with what YOU observed this time, or change the "
                "verdict. Do not repeat a verdict without answering the "
                "evidence below:\n  - " + "\n  - ".join(disputes)
            )
        blocks.append(
            "COVERAGE RECORDING: before exercising EACH feature, call "
            f'walk_mark_feature(project_id="{project.id}", feature="<the exact '
            'feature name from your list>"). It costs nothing and records which '
            "code that feature runs through, so future verifies can scope with "
            "evidence instead of guesswork."
        )
        out["text"] = "\n\n".join(b for b in blocks if b)
    except Exception as e:
        logger.warning(
            f"[WALK_VERIFY] evidence builder failed (walking everything): {e}"
        )
        out["text"] = (
            "CHANGED SINCE LAST PROMOTE: unavailable (evidence builder error) — "
            "treat as NO BASELINE and walk everything."
        )
    return out


def record_walk(
    project,
    report: Dict[str, Any],
    evidence: Dict[str, Any],
    verify_path: Optional[Path],
) -> None:
    """Append the walk to history and fold the dev app's coverage timeline
    into the store. Best-effort."""
    try:
        from app.agent_app import verify_scope as vs

        store_dir = evidence.get("store_dir") or vs.verify_store_dir(project)
        scope = report.get("scope") or None
        entry = {
            "at": time.time(),
            "at_human": time.strftime("%Y-%m-%d %H:%M"),
            "kind": report.get("kind"),
            "scope": {
                "mode": (scope or {}).get("mode") or "FULL",
                "included": (scope or {}).get("included") or [],
                "excluded": [list(x) for x in ((scope or {}).get("excluded") or [])],
            },
            "features": report.get("features") or {},
        }
        vs.append_history(store_dir, entry)
        if verify_path:
            jsonl = Path(verify_path) / "logs" / "coverage.jsonl"
            folded = vs.fold_coverage(jsonl)
            baseline = evidence.get("baseline") or {}
            vs.merge_coverage(store_dir, folded, baseline.get("at"))
            if folded:
                logger.info(
                    f"[WALK_VERIFY] coverage recorded for {len([k for k in folded if k != '(unattributed)'])} feature(s)"
                )
    except Exception as e:
        logger.warning(f"[WALK_VERIFY] could not record walk: {e}")


def _reset_coverage_log(verify_path: Optional[Path]) -> None:
    if not verify_path:
        return
    try:
        logs = Path(verify_path) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "coverage.jsonl").write_text("", encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def run_walk_verify(
    project: Any,
    base_url: Optional[str] = None,
    project_path: Optional[str] = None,
    scope: str = "auto",
    defect_features: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Run the walk_verify sub-agent for a running project.

    base_url/project_path override where the verifier drives and reads —
    used to point it at the DEV environment, where the app under test is a
    disposable copy on a hidden port, never the user's live instance.
    Defaults preserve the original behavior (the registered project).

    scope: "auto" (the verifier decides from the evidence) or "full" (a
    full sweep was requested — the verifier must walk everything).
    defect_features: fix missions pass the features observed broken last
    walk; they are handed to the verifier as must-include.

    Returns the parsed verdict dict, or None when the sub-agent runtime is
    unavailable (headless/test contexts) — callers treat None as 'skipped',
    never as 'pass'.
    """
    runtime = _runtime()
    if runtime is None:
        return None
    mgr, action_manager, action_library, llm, event_stream_manager = runtime

    from app.subagent.runner import SubAgentRunner

    target_url = base_url or f"http://127.0.0.1:{project.port}"
    target_path = project_path or project.path

    manager = None
    try:
        from app.agent_app import get_agent_app_manager

        manager = get_agent_app_manager()
    except Exception:
        manager = None

    # Evidence building hashes the watched tree and may shell out to
    # `lui symbols` per changed code file — off the event loop.
    import asyncio as _asyncio

    evidence = await _asyncio.get_running_loop().run_in_executor(
        None,
        lambda: build_verify_evidence(
            project,
            Path(target_path),
            manager=manager,
            scope=scope,
            defect_features=defect_features,
        ),
    )
    _reset_coverage_log(Path(target_path) if project_path else None)

    query = (
        f"Verify the Agent App project '{project.name}'.\n"
        f"project_id: {project.id}\n"
        f"project_path: {target_path}\n"
        f"base_url: {target_url}\n"
        f"Requirements: read {target_path}/reference/requirements.md "
        f"(fallback: the feature checklist in {target_path}/AGENT_APP.md).\n\n"
        + evidence["text"]
    )

    sub = mgr.spawn(
        agent_type="walk_verify",
        query=query,
        parent_task_id=project.session_id,
        parent_temp_dir=None,
    )
    runner = SubAgentRunner(
        subagent_manager=mgr,
        action_manager=action_manager,
        action_library=action_library,
        event_stream_manager=event_stream_manager,
        llm_interface=llm,
    )

    # Same dedicated log file as agent-spawned sub-agents:
    # <run>/<session>/sub_walk_verify_<id>.log
    from app.logger import (
        add_subagent_log_sink,
        logger as app_logger,
        remove_subagent_log_sink,
    )

    short_id = sub.id[4:] if sub.id.startswith("sub_") else sub.id
    agent_tag = f"sub:{sub.agent_type}:{short_id}"
    log_session = project.session_id or "main"
    sink_id = add_subagent_log_sink(agent_tag, log_session)
    try:
        with app_logger.contextualize(agent=agent_tag, session=log_session):
            sub = await runner.run_to_completion(sub)
    finally:
        remove_subagent_log_sink(sink_id)

    raw = (getattr(sub, "result", None) or "").strip()
    if str(getattr(sub, "status", "") or "").lower() in ("failed", "timeout", "error"):
        # The verifier ENDED ITSELF (structural refusal, cap, or its own LLM
        # dying), not a verdict. Told apart by the RUNNER's own abort sentinel
        # (a control string we emit, not the model's prose): a provider outage
        # is `throttled` (retry later, do not advance the machine); anything
        # else is a setup `failed`. Parsing its apology as a report classified
        # these as "unparseable", burned the one re-verify on the identical
        # wall, and stuck-capped healthy arcs (observed live 2026-09-08).
        kind = "throttled" if _LLM_ABORT_SENTINEL in raw else "failed"
        return {
            "kind": kind,
            "passed": [],
            "defects": [],
            "raw": raw or "the verifier sub-agent ended without a verdict",
        }
    report = parse_check_report(raw)
    record_walk(project, report, evidence, Path(target_path) if project_path else None)
    return report


# ---------------------------------------------------------------------------
# Structured verdict (typed — NO free-text pattern matching)
#
# The walk_verify sub-agent ends by emitting a JSON verdict object (schema
# below) as its sub_task_end `result`. Classification is DERIVED from typed
# fields (verdict/status enums), never scraped from prose, so a verdict's
# wording can never change how it routes. This replaced a regex/substring
# parser whose six-string BLOCKED test decided promote-vs-stuck from phrasing.
# ---------------------------------------------------------------------------

# The RUNNER (not the model) emits this exact substring when the sub-agent's
# own LLM died. Matching OUR OWN control string is not pattern-matching the
# model's reply — it is how a provider outage is told apart from a structural
# verifier failure (both arrive with status="failed").
_LLM_ABORT_SENTINEL = "sub-agent aborted"

# One source of truth for the contract, reused by the sub-agent prompt and the
# guard's rejection message.
VERDICT_SCHEMA = (
    '{"scope": {"mode": "full" | "delta", "excluded": '
    '[{"feature": "<name>", "reason": "<why the diff cannot reach it>"}]}, '
    '"verdict": "pass" | "fail" | "blocked", '
    '"blocked_reason": "<what stopped you>"   // only when verdict is "blocked", '
    '"features": [{"name": "<feature>", "status": "pass" | "fail" | "not_reached", '
    '"evidence": "<the flow you ran and what you saw>", '
    '"unreached_reason": "code_present" | "tooling" | null}]}'
)

_STATUS_LABEL = {"pass": "PASS", "fail": "FAIL", "not_reached": "NOT REACHED"}


def load_verdict(text: str) -> Optional[Dict[str, Any]]:
    """json.loads the sub-agent's result, tolerating a code fence or a stray
    prose prefix. Returns None when nothing parses as a JSON object."""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        nl = raw.find("\n")
        raw = raw[nl + 1 :] if nl != -1 else raw
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        obj = json.loads(raw)
    except Exception:
        obj = _first_json_object(raw)
    return obj if isinstance(obj, dict) else None


def _first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """First balanced {...} in `text` that parses as a dict (string-aware)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                    except Exception:
                        break
                    return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None


def valid_verdict(obj: Dict[str, Any]) -> bool:
    """Structural shape check: a verdict enum plus a features list whose every
    entry carries a name and a status enum. Nothing about wording."""
    if not isinstance(obj, dict):
        return False
    if str(obj.get("verdict") or "").lower() not in ("pass", "fail", "blocked"):
        return False
    feats = obj.get("features")
    if not isinstance(feats, list):
        return False
    for f in feats:
        if not isinstance(f, dict) or not str(f.get("name") or "").strip():
            return False
        if str(f.get("status") or "").lower() not in ("pass", "fail", "not_reached"):
            return False
    return True


def _scope_and_features(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the recorded `scope` dict and `features` map from typed fields."""
    raw_scope = obj.get("scope") if isinstance(obj.get("scope"), dict) else {}
    mode = "DELTA" if str(raw_scope.get("mode") or "").lower() == "delta" else "FULL"
    excluded: List[Any] = []
    excluded_without_reason: List[str] = []
    for e in raw_scope.get("excluded") or []:
        if not isinstance(e, dict):
            continue
        name = str(e.get("feature") or "").strip()
        if not name:
            continue
        reason = str(e.get("reason") or "").strip()
        (excluded if reason else excluded_without_reason).append(
            (name, reason) if reason else name
        )
    feats = obj.get("features") or []
    named = [f for f in feats if str(f.get("name") or "").strip()]
    return {
        "scope": {
            "mode": mode,
            "included": [str(f["name"]).strip() for f in named],
            "excluded": excluded,
            "excluded_without_reason": excluded_without_reason,
        },
        "features": {
            str(f["name"]).strip(): _STATUS_LABEL[str(f["status"]).lower()]
            for f in named
        },
    }


def parse_check_report(text: str) -> Dict[str, Any]:
    """Classify the sub-agent's STRUCTURED verdict into a kind:
    pass | defects | incomplete (NOT REACHED, defect-free) | blocked |
    unparseable (the JSON is absent or shape-invalid — re-run the verifier).
    `throttled`/`failed` are decided in run_walk_verify from the runner's
    status, not here. Every result also carries `scope` and `features`.

    Purely typed derivation: the top-level `verdict` decides blocked; the
    per-feature `status` enums decide pass/defects/incomplete. No prose is
    inspected, so how a verdict is WORDED cannot change how it routes.
    """
    obj = load_verdict(text)
    if obj is None or not valid_verdict(obj):
        return {
            "kind": "unparseable",
            "passed": [],
            "defects": [],
            "raw": text or "",
            "scope": None,
            "features": {},
        }

    sf = _scope_and_features(obj)
    feats = [f for f in (obj.get("features") or []) if str(f.get("name") or "").strip()]
    verdict = str(obj.get("verdict")).lower()
    passed = [str(f["name"]).strip() for f in feats if str(f["status"]).lower() == "pass"]

    if verdict == "blocked":
        return {
            "kind": "blocked",
            "passed": [],
            "defects": [],
            "blocked_reason": str(obj.get("blocked_reason") or "").strip(),
            "raw": text,
            **sf,
        }

    fails = [f for f in feats if str(f["status"]).lower() == "fail"]
    if fails:
        defects = [
            f"- {str(f['name']).strip()} — FAIL — {str(f.get('evidence') or '').strip()}"
            for f in fails
        ]
        return {"kind": "defects", "passed": passed, "defects": defects, "raw": text, **sf}

    if any(str(f["status"]).lower() == "not_reached" for f in feats):
        return {"kind": "incomplete", "passed": passed, "defects": [], "raw": text, **sf}

    if not passed:
        # A "pass" that verified nothing did not judge the app: treat the
        # report as non-compliant (re-run) rather than promote on air.
        return {"kind": "unparseable", "passed": [], "defects": [], "raw": text, **sf}
    return {"kind": "pass", "passed": passed, "defects": [], "raw": text, **sf}


def describe_scope(report: Dict[str, Any]) -> str:
    """One clause for the ready announcement: '' for a full walk."""
    scope = (report or {}).get("scope") or {}
    if (scope.get("mode") or "FULL") != "DELTA":
        return ""
    excluded = scope.get("excluded") or []
    n_ex = len(excluded) + len(scope.get("excluded_without_reason") or [])
    if n_ex:
        return (
            f"scoped to your change — {n_ex} unaffected feature(s) skipped with "
            "reasons; say 'verify everything' for a full sweep"
        )
    return "scoped to your change"
