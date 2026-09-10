# -*- coding: utf-8 -*-
"""Engine acceptance: the Arc record.

Runs standalone:  python3 -m app.factory.test_phase0
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.factory.engine import (
    ARC_BUILD,
    ARC_MODIFY,
    ARC_NONE,
    MISSIONS_CAP,
    STALLS_CAP,
    VERIFYING,
    Arc,
    backoff_for,
)

# ── absence is explicit ─────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    arc = Arc(Path(td) / "arc.json")
    assert arc.kind == ARC_NONE and not arc.is_open
    assert arc.rounds() == [] and arc.paused is None
    # An unreadable file is ALSO the none-arc, never a crash or a phantom arc.
    (Path(td) / "bad.json").write_text("{not json", encoding="utf-8")
    assert not Arc(Path(td) / "bad.json").is_open
    # Garbage content with a wrong arc value is ignored too.
    (Path(td) / "junk.json").write_text('{"arc": "building"}', encoding="utf-8")
    assert not Arc(Path(td) / "junk.json").is_open
print("none-arc is explicit and unspoofable: OK")

# ── open / persist / close ──────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "arc.json"
    arc = Arc(path)
    arc.open(ARC_MODIFY)
    assert arc.is_open and arc.kind == ARC_MODIFY and arc.last_activity_at > 0
    # Round-trips through disk.
    again = Arc(path)
    assert again.is_open and again.kind == ARC_MODIFY
    # close() is "done": back to none, ledger dies with the arc.
    arc.record_ruled_out(["not the port"])
    arc.close()
    assert not arc.is_open and arc.ruled_out() == []
    assert not Arc(path).is_open
print("open/persist/close: OK")

# ── re-entry never resets the wallet, and IS the resume ─────────────────────
with tempfile.TemporaryDirectory() as td:
    arc = Arc(Path(td) / "arc.json")
    arc.open(ARC_BUILD)
    arc.mission_dispatched("fix-1")
    arc.pause("user")
    assert arc.paused and arc.paused["by"] == "user"
    arc.open(ARC_BUILD)  # the user asked again — resume, same arc
    assert arc.paused is None and arc.missions_spent == 1, (
        "re-entry clears the pause and keeps the budget"
    )
    try:
        arc.open("banana")
        raise AssertionError("open() must reject unknown kinds")
    except ValueError:
        pass
print("re-entry = resume, budget survives: OK")

# ── evidence of work resets the stall counter ───────────────────────────────
with tempfile.TemporaryDirectory() as td:
    arc = Arc(Path(td) / "arc.json")
    arc.open(ARC_MODIFY)
    arc.bump_stall()
    arc.bump_stall()
    assert arc.stalls == 2
    arc.record_round(fingerprint="abc", cards=[{"key": "verify.x", "sig": "502"}])
    assert arc.stalls == 0, "a verdict is work — the empty-loop counter resets"
    arc.set_unparseable_retried(True)
    arc.record_round(fingerprint="def")
    assert not arc.unparseable_retried, "a parsed verdict clears the retry flag"
print("evidence resets stalls: OK")

# ── ledger: dedup, caps, and the features scope ─────────────────────────────
with tempfile.TemporaryDirectory() as td:
    arc = Arc(Path(td) / "arc.json")
    arc.open(ARC_BUILD)
    assert arc.record_ruled_out(["not the grant", "not the grant", ""]) == 1
    assert arc.record_ruled_out(["NOT THE GRANT"]) == 0, "dedup is case-blind"
    assert arc.record_disputed(["Refresh works — I reproduced it"]) == 1
    for i in range(30):
        arc.record_round(fingerprint=f"fp{i}", features=[f"feat{i}"])
    assert len(arc.rounds()) == arc._MAX_ROUNDS
    assert arc.last_defect_features() == ["feat29"]
    arc.record_round(fingerprint="s", stall=True)
    assert arc.last_defect_features() == ["feat29"], (
        "a stall round carries no features — the last REAL round scopes"
    )
print("ledger dedup/caps/features: OK")

# ── budget + backoff constants ──────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    arc = Arc(Path(td) / "arc.json")
    arc.open(ARC_BUILD)
    for i in range(MISSIONS_CAP):
        arc.mission_dispatched(f"m-{i}")
    assert arc.budget_exhausted()
    assert backoff_for(0) < backoff_for(1) < backoff_for(99)
    arc2 = Arc(Path(td) / "arc2.json")
    arc2.open(ARC_BUILD)
    for _ in range(STALLS_CAP):
        arc2.bump_stall()
    assert arc2.budget_exhausted()
print("budget + backoff: OK")

# ── phases + honest reports ─────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    arc = Arc(Path(td) / "arc.json")
    arc.open(ARC_MODIFY)
    arc.set_phase(VERIFYING)
    assert arc.phase == VERIFYING
    arc.record_round(fingerprint="same")
    arc.record_round(fingerprint="same")
    arc.mission_dispatched("fix-1")
    arc.record_ruled_out(["not the schema"])
    report = arc.stuck_report()
    # User-facing report: friendly, no mission counts / fingerprints / history.
    assert "try again" in report
    assert f"1/{MISSIONS_CAP}" not in report
    assert "same" not in report and "not the schema" not in report
    blocked = arc.blocked_report("Which calendar?")
    # The question and a plain lead only; no internal ruled-out notes.
    assert "Which calendar?" in blocked and "decision from you" in blocked
    assert "not the schema" not in blocked
print("phases + reports: OK")

print("\nEngine acceptance: ALL GREEN")
