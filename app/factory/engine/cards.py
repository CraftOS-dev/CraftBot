# -*- coding: utf-8 -*-
"""Defect cards (FACTORY-PLAN §3.5) — the ONLY thing a fix mission receives
about a failure.

Format follows the strongest weak-model repair evidence (location + observed
value + suggested fix direction ⇒ +40–44pp terminal repair success on 8–14B
models; raw diagnostics ≈ baseline). Cards are machine-distilled from raw
reports/logs; missions never see the undistilled dumps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Required string fields, in brief-rendering order.
_REQUIRED = (
    "key",
    "where",
    "observed",
    "expected",
    "candidate_cause",
    "suggested_direction",
    "repro",
)


@dataclass
class DefectCard:
    key: str  # stable fingerprint source, e.g. "verify.feature.refresh-502"
    where: str  # route/file:line — the location component
    observed: str  # what actually happened, with the quoted value
    expected: str  # what passing looks like
    candidate_cause: str  # best supported theory ("unknown" is valid)
    suggested_direction: str  # the +40pp component: how to approach the fix
    repro: str  # ready-made command (I2: agents execute pasted calls)
    evidence: List[str] = field(
        default_factory=list
    )  # quoted log/console/request lines

    def fingerprint(self) -> str:
        import hashlib

        return hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:12]

    def render(self) -> str:
        """Brief-ready text block. Terse and evidence-rich (ACI principle)."""
        lines = [
            f"DEFECT {self.key}",
            f"  where:     {self.where}",
            f"  observed:  {self.observed}",
            f"  expected:  {self.expected}",
            f"  cause?:    {self.candidate_cause}",
            f"  direction: {self.suggested_direction}",
            f"  repro:     {self.repro}",
        ]
        for e in self.evidence[:8]:
            lines.append(f"  evidence:  {e}")
        return "\n".join(lines)


def validate_card(data: Dict[str, Any]) -> List[str]:
    """Problems list (empty = valid). Pure; used by the distiller to reject
    malformed model output and retry."""
    problems: List[str] = []
    for key in _REQUIRED:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"missing/empty required field '{key}'")
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence):
        problems.append("'evidence' must be a list of strings")
    unknown = set(data) - set(_REQUIRED) - {"evidence"}
    if unknown:
        problems.append(f"unknown fields: {sorted(unknown)}")
    return problems


def card_from_dict(data: Dict[str, Any]) -> DefectCard:
    problems = validate_card(data)
    if problems:
        raise ValueError("; ".join(problems))
    return DefectCard(
        **{k: data[k] for k in _REQUIRED}, evidence=list(data.get("evidence", []))
    )
