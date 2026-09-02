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

        machine = get_factory_host().machine_for(project.id)
        if machine is None:
            return []
        return [
            str(e.get("what", "")).strip()
            for e in machine.disputed()[-5:]
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
    report = parse_check_report(raw)
    record_walk(project, report, evidence, Path(target_path) if project_path else None)
    return report


# ---------------------------------------------------------------------------
# Check-report parsing (ported from PR #388 — pure, testable, no I/O).
# ---------------------------------------------------------------------------

_BLOCKED_MARKERS = (
    "mcp server connection lost",
    "browser mcp",
    "browser is unavailable",
    "browser tool",
    "no features could be tested",
    "could not launch a browser",
)


def _reads_as_blocked(result_text: str) -> bool:
    body = (result_text or "").lower()
    return any(marker in body for marker in _BLOCKED_MARKERS)


def _scope_fields(text: str) -> Dict[str, Any]:
    """The verifier's SCOPE decision + per-feature verdicts, always present
    in a parsed report (empty when the report carries none)."""
    try:
        from app.agent_app.verify_scope import feature_verdicts, parse_scope

        return {"scope": parse_scope(text), "features": feature_verdicts(text)}
    except Exception:
        return {"scope": None, "features": {}}


def parse_check_report(text: str) -> Dict[str, Any]:
    """Classify a walk_verify result. kinds:
    pass | defects | incomplete (NOT REACHED, defect-free) | blocked |
    unparseable (the report itself is non-compliant — re-run the verifier) |
    throttled (the verifier's own LLM died — not the app, not the report).
    Every result also carries `scope` (the verifier's SCOPE block, or None)
    and `features` ({feature: PASS|FAIL|NOT REACHED})."""
    text = text or ""
    extra = _scope_fields(text)

    # A sub the runner aborted on consecutive LLM failures returns
    # "(sub-agent aborted — LLM unavailable: …)". That is neither an app
    # verdict nor an unparseable report: retrying LATER can succeed, and
    # counting it toward stuck punishes the app for the provider (observed
    # live 2026-08-06: two walkers died on rate limits 4 seconds apart and a
    # healthy modify went STUCK).
    if "sub-agent aborted" in text and "LLM unavailable" in text:
        return {"kind": "throttled", "passed": [], "defects": [], "raw": text, **extra}
    # The contract allows PASS|FAIL|BLOCKED, but sub-agents invent softeners —
    # "VERDICT: INCOMPLETE" and "VERDICT: PARTIAL VERIFICATION" both observed
    # live. An unknown word must NOT fall through to "blocked" (which
    # announces the app with a misleading tooling-issue warning): treat the
    # softeners as FAIL and let the defect / NOT-REACHED logic classify the
    # report into the honest "incomplete" kind.
    m = re.search(
        r"VERDICT:\s*(PASS|FAIL|BLOCKED|INCOMPLETE|PARTIAL(?:\s+\w+)?)",
        text,
        re.IGNORECASE,
    )
    verdict = m.group(1).upper() if m else None
    if verdict is not None and verdict.startswith(("INCOMPLETE", "PARTIAL")):
        verdict = "FAIL"

    # A verdict our OWN REPORT GUARDS rejected ("Verdict REJECTED — ...")
    # is a compliance failure in the verifier's paperwork, not a finding
    # about the app. It must never reach the defect path.
    #
    # Observed live 2026-09-01 (newsletter_tool 3f6013ce): _guard_evidence
    # rejected a report for marking an AI feature PASS without a quoted hook
    # line; the sub echoed that as "VERDICT: BLOCKED / BLOCKED BY: Verdict
    # rejected: ...". _reads_as_blocked only knows BROWSER/TOOLING markers,
    # so this fell through the mirror-image branch into FAIL -> defects ->
    # DefectCard("verify.unstructured-failure") -> a fix mission reading
    # "Your ONLY goal: make these features work". The builder then spent
    # five minutes grepping the APP for the verifier's report template,
    # which of course lives in CraftBot. "unparseable" is the right kind:
    # it re-runs the verifier instead of dispatching app work.
    # Guarded: only when the report carries NO real per-feature FAIL lines.
    # A genuine defect report that merely quotes an earlier rejection still
    # contains findings, and those must survive.
    if re.search(r"verdict\s+rejected", text, re.IGNORECASE) and not re.search(
        r"^-\s+.*\s—\s*FAIL\b", text, re.MULTILINE | re.IGNORECASE
    ):
        return {
            "kind": "unparseable",
            "passed": [],
            "defects": [],
            "raw": text,
            **extra,
        }
    # A FAIL whose body describes a blockage is a blockage wearing a FAIL
    # costume — never dispatch fixes for defects nobody observed.
    if verdict == "FAIL" and _reads_as_blocked(text):
        verdict = "BLOCKED"

    # The mirror image: a BLOCKED verdict with NO tooling evidence but real
    # per-feature lines is a partial walk wearing a BLOCKED costume (observed
    # live 2026-08-05: "BLOCKED BY: limited turns" with 1 PASS + 6 NOT
    # REACHED — it was classified unparseable and a working app went stuck
    # with 0 missions). Route it through the FAIL branch so the FEATURES
    # evidence decides: FAIL lines → defects, NOT-REACHED-only → incomplete
    # (delivered with the coverage caveat). Evidence-free BLOCKED stays
    # blocked — the caller's no-markers second-guess makes it unparseable.
    if verdict == "BLOCKED" and not _reads_as_blocked(text):
        if re.search(
            r"^-\s+.*\b(?:FAIL|NOT REACHED)\b", text, re.MULTILINE | re.IGNORECASE
        ):
            verdict = "FAIL"

    if verdict == "PASS":
        return {
            "kind": "pass",
            "passed": _passed(text),
            "defects": [],
            "raw": text,
            **extra,
        }

    if verdict == "FAIL":
        # Feature lines come from the FEATURES section ONLY — prose in
        # FAILURES/BLOCKED BY must never become a work order.
        feature_section = re.split(
            r"^\s*(?:FAILURES|BLOCKED BY)\b",
            text,
            maxsplit=1,
            flags=re.MULTILINE | re.IGNORECASE,
        )[0]
        passed = _passed(feature_section)
        defects = [
            d.strip()
            for d in re.findall(
                r"^-\s+(?!.*\bNOT REACHED\b).*(?:—|–|:|-+)\s*FAIL\b.*$",
                feature_section,
                re.MULTILINE,
            )
        ]
        if not defects and re.search(r"NOT REACHED", feature_section, re.IGNORECASE):
            return {
                "kind": "incomplete",
                "passed": passed,
                "defects": [],
                "raw": text,
                **extra,
            }
        return {
            "kind": "defects",
            "passed": passed,
            "defects": defects,
            "raw": text,
            **extra,
        }

    return {"kind": "blocked", "passed": [], "defects": [], "raw": text, **extra}


def _passed(section: str) -> list:
    # The FEATURES section only — a SCOPE/EXCLUDED bullet must never count as
    # a verified feature.
    section = section.split("FEATURES:", 1)[-1] if "FEATURES:" in section else section
    return [
        f.strip()
        for f in re.findall(
            r"^-\s+(.{1,120}?)\s*(?:—|–|:|-+)\s*PASS\b", section, re.MULTILINE
        )
        if f.strip()
    ]


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
