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

    def cause_signature(self) -> str:
        """The failure's IDENTITY, not the feature's name.

        Hashing `key` alone (a slug of the verifier's feature title) meant a
        defect kept one fingerprint no matter what happened to it. A Gmail
        status check failed three rounds running on three DIFFERENT causes —
        create_gmail_draft ungranted, send_gmail ungranted, send_gmail
        irreversible — each fix clearing one gate and exposing the next. The
        cap read three identical fingerprints and declared the build stuck one
        gate from done.

        The signature is deliberately NOT the observed text: that is prose
        written by the verifier model and is reworded every round. It keeps
        only the parts a machine wrote — the route, the status code, and
        snake_case/dotted identifiers — and drops the narration around them.

        Quoted strings were harvested too, at first, on the theory that a
        report quotes what matters. Measured, they were the whole problem:
        one failure phrased three ways produced three signatures (one round
        quoted the JSON key "error", one quoted the button label "Check
        Gmail"), while the three genuinely different Gmail causes above were
        already told apart by create_gmail_draft / send_gmail /
        confirm_irreversible — machine-written identifiers, every one. The
        quotes added instability and no discrimination, so they are gone.
        """
        import re

        text = f"{self.where} {self.observed}"
        tokens = set()
        # Routes. rstrip because a route ending a sentence keeps the full
        # stop ("…failed on /api/ops/x/status.") and would otherwise be a
        # different token from the same route mid-sentence — punctuation is
        # exactly the kind of rewording this signature must not see.
        tokens.update(m.rstrip("./-") for m in re.findall(r"/api/[\w/.-]+", text))
        # Tagged, not bare: the volatile filter below drops anything all
        # digits (ports, pids), which silently ate status codes too and let a
        # 404 and a 500 on the same route hash identically — a fixed defect
        # failing a NEW way would have scored as "no progress" and burned a
        # retry, which is the bug this whole signature exists to prevent.
        tokens.update(f"status{s}" for s in re.findall(r"\b[45]\d\d\b", text))
        # Identifiers: snake_case or dotted — action names, config keys,
        # module paths. Written by code, so stable across rewordings.
        tokens.update(re.findall(r"\b[a-z][a-z0-9]*(?:[._][a-z0-9]+)+\b", text))
        # Volatile: ids, ports, paths and timestamps recur differently every
        # round and would defeat the cap on their own.
        tokens = {
            t
            for t in tokens
            if not re.fullmatch(r"[0-9a-f]{8,}|\d+|.*\d{4}-\d\d-\d\d.*", t)
            and not t.startswith(("c:", "/users", "/home", "http://", "https://"))
        }
        return "|".join(sorted(tokens)[:8]) or self.key

    def fingerprint(self) -> str:
        import hashlib

        seed = f"{self.key}|{self.cause_signature()}"
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]

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


def fingerprint_all(cards: List["DefectCard"]) -> str:
    """One identity for the whole outstanding defect SET.

    Taking cards[0]'s fingerprint made the retry cap depend on card ordering,
    and blinded it to real progress: fixing one of two defects left the first
    card's fingerprint untouched and scored as another wasted round. Order is
    normalised away, so "the set of things still broken changed" — a defect
    cleared, or a cause that moved — reads as progress and earns a fresh
    budget, while a genuinely stalled loop still repeats and still trips.
    """
    import hashlib

    if not cards:
        return ""
    seed = "|".join(sorted(f"{c.key}::{c.cause_signature()}" for c in cards))
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


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
