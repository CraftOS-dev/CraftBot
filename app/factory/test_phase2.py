# -*- coding: utf-8 -*-
"""Phase 2 acceptance: distiller replays of two REAL incidents.
    python3 -m app.factory.test_phase2
"""

from __future__ import annotations

from app.factory.appfactory.distill import distill
from app.factory.engine.cards import validate_card

# ── Replay 1: run 14 (the "Vite" hallucination incident) ────────────────────
# What the verifier + new requestfailed capture would produce for that tail:
WALK_14 = """VERDICT: FAIL
FEATURES:
- View current top stories list refreshed hourly — FAIL — Clicked Refresh HN; received "Refresh failed: HTTP 502" and console error; no stories loaded | expected: stories list populates after refresh
- Bookmark any story — NOT REACHED
"""
CONSOLE_14 = [
    "REQUEST FAILED: POST http://127.0.0.1:3100/api/ops/refresh-stories — net::ERR_CONNECTION_REFUSED",
]
cards = distill(WALK_14, server_log="", console_lines=CONSOLE_14,
                project_path="/w/proj", cli="node cli.ts")
assert len(cards) == 1
c = cards[0].__dict__
assert validate_card({k: v for k, v in c.items()}) == []
assert "/api/ops/refresh-stories" in cards[0].where or any(
    "refresh-stories" in e for e in cards[0].evidence
)
assert any("ERR_CONNECTION_REFUSED" in e for e in cards[0].evidence), "URL+cause must be quoted"
assert "node cli.ts run /w/proj refresh-stories" == cards[0].repro
blob = cards[0].render()
assert "Vite" not in blob and "vite" not in blob  # the hallucination is not utterable from evidence
print("run-14 replay: refused URL named, repro ready, no Vite utterable: OK")

# ── Replay 2: run 15 (comment_count — evidence present, cause matched) ──────
WALK_15 = """VERDICT: FAIL
FEATURES:
- View current top stories list refreshed hourly (title, url, score) — FAIL — Clicked Refresh HN; 502 Bad Gateway on /api/ops/refresh-stories; no stories loaded | expected: rows appear
"""
LOG_15 = """INFO POST /api/ops/refresh-stories
2026/08/03 07:34:26 hn-refresh failed: GoError: comment_count: cannot be blank.
[0.00ms] SELECT `stories`.* FROM `stories`"""
cards = distill(WALK_15, server_log=LOG_15, project_path="/w/proj", cli="node cli.ts")
assert len(cards) == 1
assert "cannot be blank" in cards[0].candidate_cause, "server evidence must drive the cause"
assert "cannot be blank" in " ".join(cards[0].evidence)
assert cards[0].repro.endswith("run /w/proj refresh-stories")
print("run-15 replay: cause quoted from server log: OK")

# ── No-evidence failure: cause must be 'unknown', direction = gather ────────
cards = distill("- Something — FAIL — it broke | expected: works",
                server_log="", console_lines=[])
assert cards[0].candidate_cause.startswith("unknown")
assert "Do NOT theorize" in cards[0].suggested_direction
print("evidence-bound: no evidence → unknown + gather, never a theory: OK")

# ── Unstructured report still yields a card (fingerprint/caps never starve) ─
cards = distill("the verifier returned prose with no FAIL lines at all")
assert len(cards) == 1 and cards[0].key == "verify.unstructured-failure"
print("unstructured fallback card: OK")

# ── Cookbook selection ──────────────────────────────────────────────────────
from app.factory.host_craftbot import FactoryHost

books = FactoryHost._select_cookbooks("GoError: comment_count: cannot be blank")
assert books and "required: true" in books[0] or "REJECTS 0" in books[0]
books = FactoryHost._select_cookbooks("send_gmail failed: not granted")
assert any("confirmIrreversible" in b for b in books)
books = FactoryHost._select_cookbooks("REQUEST FAILED: net::ERR_CONNECTION_REFUSED")
assert any("RELATIVELY" in b or "relative" in b.lower() for b in books)
print("cookbook selection by evidence keywords: OK")

print("\nPhase 2 acceptance: ALL GREEN")
