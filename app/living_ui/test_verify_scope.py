"""Scoped walk-verify acceptance (docs/design/scoped-walk-verify.md rev 2).

The invariant under test: the SYSTEM produces evidence and records the
verifier's decision; it never decides scope itself — and the guard enforces
only the SHAPE of that decision (a SCOPE block, reasons for exclusions,
evidence for inclusions, FULL when the evidence demanded it).

Run:  python -m app.living_ui.test_verify_scope

Style follows app/living_ui/test_data_safety.py: a module-level assert
script with hand-rolled stubs, no pytest.
"""

import json
import sys
import tempfile
import types
from pathlib import Path

# Windows consoles default to cp1252; the checks print arrows and dashes.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.living_ui import verify_scope as vs
from app.living_ui import walk_verify as wv
import app.subagent.definitions.walk_verify as defn_mod
from app.subagent.registry import get_subagent_definition
from app.subagent.runner import SubAgentRunner

PASSED = 0


def ok(name: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  ok  {name}")


# ── 1. baseline + diff + symbol attribution ─────────────────────────────────
BOARD_OLD = """import { useState } from 'react'

interface BoardViewProps {
  board: Board
}

export function BoardView({ board }: BoardViewProps) {
  const [adding, setAdding] = useState(false)

  const handleAddList = async () => {
    await controller.createList(board.id, 'x')
  }

  const handleDragEnd = async () => {
    await controller.moveCard(1, 2, 3)
  }

  return (
    <div>
      {board.lists.map(list => (
        <ListColumn key={list.id} list={list} onDragEnd={handleDragEnd} />
      ))}
    </div>
  )
}
"""
BOARD_NEW = BOARD_OLD.replace(
    "  const handleDragEnd = async () => {",
    "  const handleColumnDrop = async (targetIndex: number) => {\n"
    "    await Promise.all(board.lists.map((l, i) => controller.moveList(l.id, i)))\n"
    "  }\n\n"
    "  const handleDragEnd = async () => {",
).replace("{board.lists.map(list => (", "{board.lists.map((list, index) => (")

HOOK_OLD = """routerAdd('POST', '/api/ops/cards/clear-archived', (e) => {
  const n = 1;
  return e.json(200, { cleared: n });
});

routerAdd('GET', '/api/ops/stats', (e) => {
  return e.json(200, { total: 3 });
});

function formatCard(c) {
  return c.title;
}
"""
HOOK_NEW = HOOK_OLD.replace("{ cleared: n }", "{ cleared: n, ok: true }")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    proj = root / "kanban_board_1"
    (proj / "frontend" / "src" / "app" / "components").mkdir(parents=True)
    (proj / "pb" / "pb_hooks").mkdir(parents=True)
    (proj / "pb" / "pb_migrations").mkdir(parents=True)
    (proj / "reference").mkdir(parents=True)
    (proj / "frontend" / "src" / "app" / "components" / "BoardView.tsx").write_text(
        BOARD_OLD, encoding="utf-8"
    )
    (proj / "frontend" / "src" / "app" / "components" / "MainView.tsx").write_text(
        "import { BoardView } from './BoardView'\nexport function MainView() { return <BoardView /> }\n",
        encoding="utf-8",
    )
    (proj / "pb" / "pb_hooks" / "ops.pb.js").write_text(HOOK_OLD, encoding="utf-8")
    (proj / "pb" / "pb_migrations" / "1700000000_init.js").write_text(
        "migrate((app) => {})", encoding="utf-8"
    )
    (proj / "operations.json").write_text(
        json.dumps([{"name": "clear_archived"}, {"name": "stats"}]), encoding="utf-8"
    )
    (proj / "reference" / "requirements.md").write_text(
        "# Req\n\n## Changes\n\n- 2026-08-25: column drag (touches: card DnD, list rename)\n",
        encoding="utf-8",
    )

    project = types.SimpleNamespace(
        id="1", path=str(proj), name="Kanban", port=3103, session_id=None
    )
    store = vs.verify_store_dir(project)
    assert store == root / "_verify" / "1", store
    ok("store dir is a sibling of the project, never inside it")

    baseline = vs.write_baseline(proj, store)
    assert (store / "promoted.json").is_file() and (
        store / "snapshot" / "pb" / "pb_hooks" / "ops.pb.js"
    ).is_file()
    assert "frontend/src/app/components/BoardView.tsx" in baseline["files"]
    ok("baseline writes hashes + a source snapshot")

    assert vs.diff_against_baseline(proj, store, baseline) == []
    ok("no changes → empty diff")

    assert vs.ensure_baseline(proj, store) is False, (
        "identical tree must not rewrite the baseline"
    )
    (proj / "operations.json").write_text(
        json.dumps([{"name": "clear_archived"}, {"name": "stats"}, {"name": "x"}]),
        encoding="utf-8",
    )
    assert vs.ensure_baseline(proj, store) is True
    baseline = vs.read_baseline(store)
    (proj / "operations.json").write_text(
        json.dumps([{"name": "clear_archived"}, {"name": "stats"}]), encoding="utf-8"
    )
    assert (
        vs.ensure_baseline(proj, store) is True
        and vs.diff_against_baseline(proj, store, vs.read_baseline(store)) == []
    )
    baseline = vs.read_baseline(store)
    ok(
        "ensure_baseline: no-op on an identical tree, rewrites on change (live launch / install / promote all use it)"
    )

    # An app that arrived finished (marketplace/import) is a verified state.
    store2 = root / "_verify" / "mk"
    vs.record_delivered(proj, store2, source="marketplace")
    assert vs.read_baseline(store2) is not None
    hb2 = vs.render_history_block(store2)
    assert "arrived finished (marketplace)" in hb2 and "verified upstream" in hb2, hb2
    ok(
        "record_delivered: baseline + 'verified upstream' history for marketplace/import apps"
    )

    # Modify: component + hook + new migration + spec entry + ops key
    (proj / "frontend" / "src" / "app" / "components" / "BoardView.tsx").write_text(
        BOARD_NEW, encoding="utf-8"
    )
    (proj / "pb" / "pb_hooks" / "ops.pb.js").write_text(HOOK_NEW, encoding="utf-8")
    (proj / "pb" / "pb_migrations" / "1700000002_positions.js").write_text(
        "migrate((app) => {\n  const c = app.findCollectionByNameOrId('lists')\n  c.fields.add(new NumberField({ name: 'position' }))\n  app.save(c)\n})",
        encoding="utf-8",
    )
    (proj / "operations.json").write_text(
        json.dumps([{"name": "clear_archived", "x": 1}, {"name": "stats"}]),
        encoding="utf-8",
    )
    changes = vs.diff_against_baseline(proj, store, baseline)
    kinds = {c.rel: c.kind for c in changes}
    assert kinds["frontend/src/app/components/BoardView.tsx"] == "modified"
    assert kinds["pb/pb_migrations/1700000002_positions.js"] == "added"
    assert "frontend/src/app/components/MainView.tsx" not in kinds
    ok("diff lists exactly the changed files")

    vs.attribute_changes(proj, changes, symbols_for=None)
    by_rel = {c.rel: c for c in changes}
    bv = by_rel["frontend/src/app/components/BoardView.tsx"]
    assert "BoardView > handleColumnDrop (new)" in bv.changed_symbols, (
        bv.changed_symbols
    )
    assert "BoardView (body)" in bv.changed_symbols, bv.changed_symbols
    assert "handleAddList" not in " ".join(bv.changed_symbols)
    assert "BoardViewProps" in bv.unchanged_symbols
    assert any(
        "also referenced by frontend/src/app/components/MainView.tsx" in n
        for n in bv.notes
    ), bv.notes
    ok(
        "TS attribution: nested handler as 'Component > handler', JSX hunk as '(body)', untouched handler not listed, cross-file references named"
    )

    hk = by_rel["pb/pb_hooks/ops.pb.js"]
    assert hk.changed_symbols == ["POST /api/ops/cards/clear-archived"], (
        hk.changed_symbols
    )
    assert (
        "GET /api/ops/stats" in hk.unchanged_symbols
        and "formatCard" in hk.unchanged_symbols
    )
    ok("hook attribution: one route changed, the other route + helper listed unchanged")

    mig = by_rel["pb/pb_migrations/1700000002_positions.js"]
    assert (
        mig.attribution == "file"
        and any("lists" in n for n in mig.notes)
        and any("position" in n for n in mig.notes)
    ), mig.notes
    ok("migration: collections + fields named, file-level attribution stated")

    ops = by_rel["operations.json"]
    assert ops.changed_symbols == ["clear_archived"] and ops.unchanged_symbols == [
        "stats"
    ], (ops.changed_symbols, ops.unchanged_symbols)
    ok("JSON: attributed to the op name, not the file")

    block = vs.render_diff_block(changes, baseline, len(baseline["files"]))
    assert (
        "CHANGED SINCE LAST PROMOTE" in block
        and "changed:   BoardView > handleColumnDrop (new)" in block
    )
    assert (
        "unchanged: GET /api/ops/stats" in block
        and "DIFF (per file" in block
        and "UNCHANGED:" in block
    )
    ok("diff block renders symbol-level changed/unchanged lines + unified diffs")

    assert "NO BASELINE" in vs.render_diff_block([], None, 0)
    ok("no baseline → NO BASELINE block")

    # Whole evidence builder (no manager → heuristic symbols) + builder hint
    evidence = wv.build_verify_evidence(
        project, proj, manager=None, scope="auto", defect_features=["Card DnD"]
    )
    txt = evidence["text"]
    assert (
        "VERIFY MODE: AUTO" in txt
        and "DEFECTS TO RE-CHECK" in txt
        and "Card DnD" in txt
    )
    assert "BUILDER'S HINT" in txt and "card DnD, list rename" in txt
    assert 'walk_mark_feature(project_id="1"' in txt
    assert "LAST VERIFY RESULTS: none recorded" in txt
    ok(
        "evidence text: mode, diff, defects, builder hint, coverage-recording instruction, empty history"
    )
    assert (
        "VERIFY MODE: FULL"
        in wv.build_verify_evidence(project, proj, manager=None, scope="full")["text"]
    )
    ok("scope='full' → VERIFY MODE: FULL in the query")

    # ── 2. history + coverage fold/render ──
    report_text = """SCOPE: DELTA
INCLUDED: Column drag, Card DnD
EXCLUDED:
- Labels — Sidebar untouched; no data-shape change
- Search — search route unchanged
VERDICT: PASS
FEATURES:
- Column drag — PASS — dragged In Progress before To Do; order persisted after reload
- Card DnD — PASS — moved a card between lists
"""
    report = wv.parse_check_report(report_text)
    assert report["kind"] == "pass" and report["passed"] == [
        "Column drag",
        "Card DnD",
    ], report
    assert (
        report["scope"]["mode"] == "DELTA"
        and report["scope"]["excluded"][0][0] == "Labels"
    )
    assert report["features"] == {"Column drag": "PASS", "Card DnD": "PASS"}
    ok(
        "parse_check_report carries scope + per-feature verdicts; EXCLUDED bullets never count as passed"
    )
    assert wv.describe_scope(report).startswith("scoped to your change — 2 unaffected")
    assert wv.describe_scope({"scope": {"mode": "FULL"}}) == ""
    ok("describe_scope: clause for DELTA, empty for FULL")

    # coverage timeline from the dev app
    dev = root / "_staging" / "1"
    (dev / "logs").mkdir(parents=True)
    (dev / "logs" / "coverage.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": 1,
                        "counters": {
                            "/x/frontend/src/app/components/BoardView.tsx": [
                                {"name": "BoardView", "line": 7, "hits": 1}
                            ]
                        },
                    }
                ),
                json.dumps({"ts": 2, "mark": "Column drag"}),
                json.dumps(
                    {
                        "ts": 3,
                        "counters": {
                            "/x/frontend/src/app/components/BoardView.tsx": [
                                {"name": "handleColumnDrop", "line": 15, "hits": 2}
                            ]
                        },
                    }
                ),
                json.dumps({"ts": 4, "mark": "Card DnD"}),
                json.dumps(
                    {
                        "ts": 5,
                        "counters": {
                            "/x/frontend/src/app/components/BoardView.tsx": [
                                {"name": "handleDragEnd", "line": 20, "hits": 1}
                            ]
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    wv.record_walk(project, report, evidence, dev)
    hist = vs.read_history(store)
    assert (
        hist[-1]["scope"]["mode"] == "DELTA"
        and hist[-1]["features"]["Column drag"] == "PASS"
    )
    cov = vs.read_coverage(store)
    assert set(cov["features"]) == {"Column drag", "Card DnD"}, cov
    assert (
        cov["features"]["Column drag"]["files"][
            "frontend/src/app/components/BoardView.tsx"
        ][0]["fn"]
        == "handleColumnDrop"
    )
    ok(
        "record_walk: history appended, coverage folded per feature (pre-mark counters unattributed)"
    )

    hb = vs.render_history_block(store)
    assert (
        "Column drag — PASS" in hb
        and "(delta walk)" in hb
        and "skipped 2 feature(s)" in hb
    )
    ok("history block: per-feature last verdict, mode, skipped count")

    # a later diff to handleDragEnd is attributed to Card DnD by coverage
    (proj / "frontend" / "src" / "app" / "components" / "BoardView.tsx").write_text(
        BOARD_NEW.replace(
            "await controller.moveCard(1, 2, 3)", "await controller.moveCard(1, 2, 4)"
        ),
        encoding="utf-8",
    )
    baseline2 = vs.write_baseline(proj, store)  # promote the DnD version
    (proj / "frontend" / "src" / "app" / "components" / "BoardView.tsx").write_text(
        BOARD_NEW.replace(
            "await controller.moveCard(1, 2, 3)", "await controller.moveCard(1, 2, 5)"
        ),
        encoding="utf-8",
    )
    ch2 = vs.diff_against_baseline(proj, store, baseline2)
    vs.attribute_changes(proj, ch2)
    covblock = vs.render_coverage_block(store, ch2)
    assert "handleDragEnd → Card DnD" in covblock, covblock
    ok(
        "coverage block: a diff in handleDragEnd names Card DnD as the feature that executed it"
    )

# ── 3. scope parsing edge cases ──
assert vs.parse_scope("VERDICT: PASS\nFEATURES:\n- a — PASS — b") is None
s = vs.parse_scope("SCOPE: FULL\nINCLUDED: a, b\nEXCLUDED: none\nVERDICT: PASS")
assert (
    s["mode"] == "FULL"
    and s["included"] == ["a", "b"]
    and s["excluded"] == []
    and s["excluded_without_reason"] == []
)
s = vs.parse_scope(
    "SCOPE: DELTA\nINCLUDED: a\nEXCLUDED:\n- b\n- c: reason\nVERDICT: PASS\nFEATURES:\n- a — PASS — x"
)
assert s["excluded"] == [("c", "reason")] and s["excluded_without_reason"] == ["b"], s
for txt in (
    "EXCLUDED: none (single-feature delta walk; only Header.tsx changed)",
    "EXCLUDED: nothing excluded",
    "EXCLUDED: N/A",
):
    s = vs.parse_scope(
        "SCOPE: DELTA"
        + chr(10)
        + "INCLUDED: a"
        + chr(10)
        + txt
        + chr(10)
        + "VERDICT: PASS"
    )
    assert s["excluded"] == [] and s["excluded_without_reason"] == [], (txt, s)
ok(
    "parse_scope: none (…) / nothing / N/A are no exclusions (guard false-rejected this live)"
)

ex = SubAgentRunner._extract_json_object
assert ex(
    "I will click next."
    + chr(10)
    + chr(10)
    + '{"action_name": "x", "parameters": {"a": "{b}"}}'
) == {"action_name": "x", "parameters": {"a": "{b}"}}
assert ex("no json here") is None
dec, err = SubAgentRunner._parse_decision(
    "Reading requirements first."
    + chr(10)
    + chr(10)
    + '{"action_name": "read_file", "parameters": {"file_path": "C:\\\\x"}}'
)
assert err is None and dec["action_name"] == "read_file", (dec, err)
ok("runner: prose before the JSON decision is salvaged instead of costing a retry call")

# a report whose feature lines use '--' as the separator (observed live) still yields verdicts
fv = vs.feature_verdicts(
    "VERDICT: FAIL"
    + chr(10)
    + "FEATURES:"
    + chr(10)
    + "- Priority filter pills in header -- FAIL -- toggle-off broken"
)
assert fv == {"Priority filter pills in header": "FAIL"}, fv
ok("feature_verdicts: double-dash separators parse to a clean feature name")
ok("parse_scope: none/absent/bare-exclusion cases")

# ── 4. the guard enforces SHAPE, never content ──
guard = defn_mod._early_end_guard


def sub(query="CHANGED SINCE LAST PROMOTE (x): …", iterations=6):
    return types.SimpleNamespace(query=query, iterations=iterations)


def end(result):
    return {"status": "completed", "result": result}


DELTA_OK = """SCOPE: DELTA
INCLUDED: Column drag
EXCLUDED:
- Labels — Sidebar untouched
VERDICT: PASS
FEATURES:
- Column drag — PASS — dragged the column; new order read back after reload
"""
assert guard(sub(), end(DELTA_OK)) is None
ok("guard: a complete DELTA walk may end at turn 6 (no turn floor)")

r = guard(
    sub(),
    end(
        DELTA_OK.replace(
            "SCOPE: DELTA\nINCLUDED: Column drag\nEXCLUDED:\n- Labels — Sidebar untouched\n",
            "",
        )
    ),
)
assert r and "no SCOPE block" in r
ok("guard: missing SCOPE block is rejected")

r = guard(
    sub(query="CHANGED SINCE LAST PROMOTE: NO BASELINE — first verify"), end(DELTA_OK)
)
assert r and "not available" in r
ok("guard: DELTA rejected when the query says NO BASELINE")
r = guard(sub(query="VERIFY MODE: FULL — a full sweep"), end(DELTA_OK))
assert r and "not available" in r
ok("guard: DELTA rejected when a FULL sweep was requested")

r = guard(sub(), end(DELTA_OK.replace("- Labels — Sidebar untouched", "- Labels")))
assert r and "without a reason" in r
ok("guard: exclusion without a reason is rejected")

r = guard(
    sub(),
    end(DELTA_OK.replace("INCLUDED: Column drag", "INCLUDED: Column drag, Search")),
)
assert r and "no FEATURES line" in r and "Search" in r
ok("guard: an INCLUDED feature with no verdict line is rejected")

r = guard(
    sub(),
    end(
        DELTA_OK.replace(
            "— PASS — dragged the column; new order read back after reload",
            "— NOT REACHED",
        )
    ),
)
assert r and "NOT REACHED" in r
ok("guard: bare NOT REACHED on an included feature is rejected while turns remain")
assert (
    guard(
        sub(iterations=48),
        end(
            DELTA_OK.replace(
                "— PASS — dragged the column; new order read back after reload",
                "— NOT REACHED",
            )
        ),
    )
    is None
)
ok("guard: …but allowed when the cap is near")

FULL_EARLY = "SCOPE: FULL\nINCLUDED: a, b\nEXCLUDED: none\nVERDICT: FAIL\nFEATURES:\n- a — PASS — did it, read it back\n- b — NOT REACHED\n"
r = guard(sub(iterations=10), end(FULL_EARLY))
assert r and "Early conclusion REJECTED" in r
assert guard(sub(iterations=40), end(FULL_EARLY)) is None
ok("guard: FULL walks keep the 70% premature-conclusion floor")

r = guard(
    sub(),
    end(
        DELTA_OK.replace(
            "dragged the column; new order read back after reload", "button visible"
        )
    ),
)
assert r and "cosmetic" in r
ok("guard: quality gates still apply")

assert guard(sub(), {"status": "failed", "result": "missing base_url"}) is None
assert (
    guard(sub(), end("VERDICT: BLOCKED\nBLOCKED BY:\n- browser MCP connection lost"))
    is None
)
ok("guard: failed status and genuine tooling blockage pass through")

# ── 5. definition wiring ──
d = get_subagent_definition("walk_verify")
assert "walk_mark_feature" in d.actions and "sub_task_end" in d.actions
assert d.compact_actions and d.session_reset_every == 10 and d.compact_keep == 3
assert (
    "SCOPE: DELTA | FULL" in d.system_prompt
    and "EVERY feature in the requirements MUST appear" not in d.system_prompt
)
ok("definition: walk_mark_feature allowed, compaction configured, prompt rewritten")

# ── 6. runner compaction (Phase 3) on a stub stream ──


class _Ev:
    def __init__(self, name, msg, out):
        self.action_name, self.message, self.action_output = name, msg, out


class _Rec:
    def __init__(self, ev):
        self.event, self._cached_tokens = ev, 123


class _Stream:
    def __init__(self, recs):
        self.tail_events = recs


recs = [
    _Rec(_Ev("mcp_playwright-mcp_browser_snapshot", "tree %d" % i, {"i": i}))
    for i in range(5)
]
recs.insert(2, _Rec(_Ev("read_file", "spec", {"x": 1})))
runner = SubAgentRunner.__new__(SubAgentRunner)
runner.event_stream_manager = types.SimpleNamespace(
    get_stream_by_id=lambda _id: _Stream(recs)
)
runner._compact_stream(types.SimpleNamespace(id="s"), d)
snaps = [r for r in recs if r.event.action_name.endswith("snapshot")]
assert [r.event.message.startswith("[superseded") for r in snaps] == [
    True,
    True,
    False,
    False,
    False,
]
assert snaps[0].event.action_output is None and snaps[0]._cached_tokens is None
assert recs[2].event.message == "spec"
ok("runner: older snapshots stubbed, newest 3 kept, other actions untouched")

# ── 7. factory helper ──
try:
    from app.factory.host_craftbot import FactoryHost  # type: ignore

    names = FactoryHost._defect_feature_names(
        [
            "- Column drag-and-drop reordering (2026-08-25 change) — FAIL — order unchanged",
            "- Card DnD: FAIL — nothing moved",
        ]
    )
    assert names == [
        "Column drag-and-drop reordering (2026-08-25 change)",
        "Card DnD",
    ], names
    ok("factory: defect lines → feature names for the next verify's must-include list")
except ImportError as e:
    print(f"  skip factory helper ({e})")

print(f"\n{PASSED} checks passed")
