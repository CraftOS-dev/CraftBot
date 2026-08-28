# -*- coding: utf-8 -*-
"""Distill raw verifier output + server evidence into DefectCards
(FACTORY-PLAN §3.5 / Phase 2).

Pure code, deterministic — no ModelPort yet (Phase 3 adds an optional LLM
polish for candidate_cause/suggested_direction once the runner exists; the
mechanical distillation already carries the high-value components: location,
observed value with quotes, repro command, and evidence lines).

Input is what the pipeline already produces:
- the walk-verify report ("- <feature> — FAIL — <observed>" lines)
- the errors-first pocketbase.log excerpt
- verify.ts console lines (HTTP-with-body, REQUEST FAILED with URL+cause)
"""

from __future__ import annotations

import re
from typing import List, Optional

from app.factory.engine.cards import DefectCard

# Separator = em/en dash, colon, or a run of hyphens: verifiers write
# "-- FAIL --" as often as "— FAIL —" (observed live 2026-08-25 — a report
# with '--' produced a useless 'unstructured-failure' card).
_FAIL_LINE = re.compile(
    r"^-\s+(.{1,140}?)\s*(?:[—–:]|-+)\s*FAIL\s*(?:[—–:]|-+)\s*(.+)$"
)
_ROUTE = re.compile(r"(/api/[\w/.-]+)")
_OP_ROUTE = re.compile(r"/api/ops/([\w/-]+)")
# Server-side lines that name causes (the console.error convention + PB's own)
_CAUSE_HINT = re.compile(
    r"(cannot be blank|is not defined|GoError|panic|ReferenceError|TypeError|"
    r"invalid |failed:|REQUEST FAILED|ERR_CONNECTION|no rows|not permitted|"
    r"is not granted|Dry-run found)",
    re.IGNORECASE,
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "feature"


def _evidence_lines(server_log: str, console: List[str]) -> List[str]:
    lines: List[str] = []
    for line in (server_log or "").splitlines():
        if _CAUSE_HINT.search(line):
            lines.append(line.strip()[:220])
    for line in console or []:
        if _CAUSE_HINT.search(line) or line.startswith(("HTTP ", "REQUEST FAILED")):
            lines.append(line.strip()[:220])
    # Dedup, keep order, cap.
    seen, out = set(), []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out[:10]


def _match_evidence(observed: str, evidence: List[str]) -> Optional[str]:
    """The evidence line most plausibly behind THIS feature's failure:
    shares a route, an op name, or a distinctive token with the observation."""
    route = _ROUTE.search(observed)
    for line in evidence:
        if route and route.group(1) in line:
            return line
    tokens = [t for t in re.findall(r"[A-Za-z_]{6,}", observed)][:5]
    for line in evidence:
        if any(t.lower() in line.lower() for t in tokens):
            return line
    return evidence[0] if evidence else None


def distill(
    walk_report: str,
    server_log: str = "",
    console_lines: Optional[List[str]] = None,
    project_path: str = "<project>",
    cli: str = "node living-ui/tools/src/cli.ts",
) -> List[DefectCard]:
    """Raw report → cards. Every card gets a repro and quoted evidence;
    candidate_cause is 'unknown' when no evidence line matches — a card must
    never contain an unquoted theory (the Vite lesson)."""
    console_lines = console_lines or []
    evidence = _evidence_lines(server_log, console_lines)
    cards: List[DefectCard] = []

    for raw_line in (walk_report or "").splitlines():
        m = _FAIL_LINE.match(raw_line.strip())
        if not m:
            continue
        feature, observed = m.group(1).strip(), m.group(2).strip()
        best = _match_evidence(observed, evidence)

        route_m = _ROUTE.search(observed) or (_ROUTE.search(best) if best else None)
        where = route_m.group(1) if route_m else "see evidence"
        op_m = _OP_ROUTE.search(where)
        if op_m:
            repro = f"{cli} run {project_path} {op_m.group(1).replace('/', '-')}"
        else:
            repro = f"open the app and exercise: {feature}"

        if best:
            cause = f"evidence points at: {best}"
            direction = (
                "Reproduce with the repro command, confirm the quoted evidence "
                "line recurs, then fix the code path it names. Re-check the "
                "server log after your fix — the line must stop appearing."
            )
        else:
            cause = "unknown — no matching server/console evidence captured"
            direction = (
                "Do NOT theorize. Reproduce with the repro command, then read "
                f"{project_path}/logs/pocketbase.log and the op's response body "
                "for the failing call; quote what you find before changing code."
            )

        cards.append(
            DefectCard(
                key=f"verify.{_slug(feature)}",
                where=where,
                observed=observed[:300],
                expected=f"'{feature}' works as a user would expect (see report line)",
                candidate_cause=cause[:300],
                suggested_direction=direction,
                repro=repro,
                evidence=([best] if best else [])
                + [e for e in evidence if e != best][:4],
            )
        )

    if not cards and (walk_report or "").strip():
        # A failure with no parseable FAIL lines still needs a card — the
        # machine's fingerprint/caps must never depend on report formatting.
        cards.append(
            DefectCard(
                key="verify.unstructured-failure",
                where="see evidence",
                observed=(walk_report.strip()[:300]),
                expected="the verifier reports per-feature verdicts",
                candidate_cause="unknown — report had no parseable FAIL lines",
                suggested_direction=(
                    "Reproduce the app's main flows manually via the CLI and "
                    "browser probe; read logs/pocketbase.log; quote evidence."
                ),
                repro=f"{cli} verify {project_path} --url <app-url>",
                evidence=evidence[:5],
            )
        )
    return cards
