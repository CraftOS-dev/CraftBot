"""verify_scope — evidence for a SCOPED walk-verify.

Design: docs/design/scoped-walk-verify.md (rev 2). The verifier decides what
to re-test; this module only produces the evidence it decides FROM and
records what it decided:

  baseline   per-file hashes + a source snapshot of the agent-owned paths,
             written at every successful promote
  diff       dev copy vs baseline, attributed to SYMBOLS (functions, routes,
             components, migrations' collections, JSON keys, CSS rules) with
             in-file and cross-file references — never "the file changed"
  history    per-feature verdicts of past walks, so the query can say when a
             feature was last actually exercised
  coverage   feature → executed functions, folded from the dev app's
             /api/_coverage timeline (Phase 2) — optional evidence
  scope      the verifier's SCOPE / INCLUDED / EXCLUDED block, parsed

Storage lives OUTSIDE the project dir, beside _staging and _backups:
<living_ui_dir>/_verify/<project_id>/. The builder agent never sees or
edits it (it could otherwise shrink its own scope); the verifier receives
rendered text in its query, not files.

Pure functions where possible; every disk write is best-effort and must never
fail a promote or a verify.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


# ── what the baseline watches ────────────────────────────────────────────────
# Agent-owned source plus the platform files whose change reaches every
# feature (kit, styles, deps). pb_data, node_modules, build output: never.
WATCHED_DIRS: Tuple[str, ...] = (
    "frontend/src/app",
    "frontend/src/kit",
    "pb/pb_hooks",
    "pb/pb_migrations",
    "reference",
)
WATCHED_FILES: Tuple[str, ...] = (
    "operations.json",
    "triggers.json",
    "frontend/package.json",
    "frontend/src/app.css",
    "frontend/src/main.tsx",
)
_SKIP_DIR_NAMES = {"node_modules", ".git", "dist", "__pycache__", "logs"}
_TEXT_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".css", ".md",
    ".html", ".txt", ".svg",
}
MAX_DIFF_LINES_PER_FILE = 200
MAX_FILES_IN_BLOCK = 40


# ── storage ──────────────────────────────────────────────────────────────────
def verify_store_dir(project) -> Path:
    """<living_ui_dir>/_verify/<project_id> — the project's own dir is
    <living_ui_dir>/<slug>_<id>, so its parent is the living_ui root."""
    return Path(project.path).parent / "_verify" / str(project.id)


def _posix(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def _iter_watched(project_path: Path) -> Iterable[Path]:
    for rel in WATCHED_FILES:
        f = project_path / rel
        if f.is_file():
            yield f
    for rel in WATCHED_DIRS:
        d = project_path / rel
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if any(part in _SKIP_DIR_NAMES for part in p.relative_to(d).parts):
                continue
            if p.is_file():
                yield p


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_files(project_path: Path) -> Dict[str, str]:
    project_path = Path(project_path)
    return {_posix(p, project_path): _sha256(p) for p in _iter_watched(project_path)}


def write_baseline(project_path: Path, store_dir: Path) -> Dict[str, Any]:
    """Record the just-promoted state: hashes + a source snapshot (needed for
    unified diffs and symbol attribution — hashes alone can't say WHAT
    changed inside a file). Replaces the previous snapshot wholesale."""
    project_path, store_dir = Path(project_path), Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    snap_dir = store_dir / "snapshot"
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    files: Dict[str, str] = {}
    for p in _iter_watched(project_path):
        rel = _posix(p, project_path)
        files[rel] = _sha256(p)
        dest = snap_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    spec = project_path / "reference" / "requirements.md"
    baseline = {
        "at": time.time(),
        "at_human": time.strftime("%Y-%m-%d %H:%M"),
        "files": files,
        "spec_hash": _sha256(spec) if spec.is_file() else None,
    }
    (store_dir / "promoted.json").write_text(
        json.dumps(baseline, indent=2), encoding="utf-8"
    )
    return baseline


def ensure_baseline(project_path: Path, store_dir: Path) -> bool:
    """Record the baseline if none exists or the watched tree differs from
    it. Called wherever the REAL project dir becomes the live app — promote,
    marketplace install, import, a live (re)launch with no modify in flight
    — so "changed since last promote" means "changed since what is live",
    and an app that never went through a promote (marketplace) still gets a
    diff on its first modify instead of a NO BASELINE full walk. Returns
    True when a new baseline was written."""
    project_path, store_dir = Path(project_path), Path(store_dir)
    current = read_baseline(store_dir)
    if current is not None and (current.get("files") or {}) == snapshot_files(project_path):
        return False
    write_baseline(project_path, store_dir)
    return True


def record_delivered(project_path: Path, store_dir: Path, source: str) -> None:
    """An app that ARRIVED finished (marketplace install, import) is a
    verified state: its features were walked upstream, not here. Record the
    baseline and a history entry saying so, so the first local modify sees
    "verified at install" instead of "none recorded" and can scope
    honestly. Best-effort."""
    try:
        ensure_baseline(project_path, store_dir)
        append_history(
            Path(store_dir),
            {
                "at": time.time(),
                "at_human": time.strftime("%Y-%m-%d %H:%M"),
                "kind": "delivered",
                "source": source,
                "scope": {"mode": "FULL", "included": [], "excluded": []},
                "features": {},
            },
        )
    except Exception as e:
        logger.warning(f"[VERIFY_SCOPE] could not record delivered state: {e}")


def read_baseline(store_dir: Path) -> Optional[Dict[str, Any]]:
    f = Path(store_dir) / "promoted.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── diff ─────────────────────────────────────────────────────────────────────
@dataclass
class FileChange:
    rel: str
    kind: str  # added | modified | deleted
    old_text: Optional[str]
    new_text: Optional[str]
    added_lines: int = 0
    removed_lines: int = 0
    # symbol attribution (filled by attribute_changes)
    changed_symbols: List[str] = field(default_factory=list)
    unchanged_symbols: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)  # references, migrations…
    attribution: str = "symbol"  # symbol | file


def _read_text(p: Path) -> Optional[str]:
    if p.suffix.lower() not in _TEXT_SUFFIXES:
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def diff_against_baseline(
    project_path: Path, store_dir: Path, baseline: Dict[str, Any]
) -> List[FileChange]:
    project_path, store_dir = Path(project_path), Path(store_dir)
    snap_dir = store_dir / "snapshot"
    current = snapshot_files(project_path)
    recorded: Dict[str, str] = baseline.get("files") or {}
    changes: List[FileChange] = []
    for rel in sorted(set(current) | set(recorded)):
        now, then = current.get(rel), recorded.get(rel)
        if now == then:
            continue
        kind = "added" if then is None else "deleted" if now is None else "modified"
        new_text = _read_text(project_path / rel) if now else None
        old_text = _read_text(snap_dir / rel) if then and (snap_dir / rel).is_file() else None
        fc = FileChange(rel=rel, kind=kind, old_text=old_text, new_text=new_text)
        if old_text is not None or new_text is not None:
            a = (old_text or "").splitlines()
            b = (new_text or "").splitlines()
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
                if tag in ("replace", "delete"):
                    fc.removed_lines += i2 - i1
                if tag in ("replace", "insert"):
                    fc.added_lines += j2 - j1
        changes.append(fc)
    return changes


def _changed_line_sets(old: str, new: str) -> Tuple[set, set]:
    """(old line numbers removed/replaced, new line numbers added/replaced),
    1-based."""
    a, b = old.splitlines(), new.splitlines()
    old_lines: set = set()
    new_lines: set = set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            old_lines.update(range(i1 + 1, i2 + 1))
        if tag in ("replace", "insert"):
            new_lines.update(range(j1 + 1, j2 + 1))
            if j1 == j2:  # pure delete — mark the neighbouring new line
                new_lines.add(max(1, j1))
        if tag == "delete":
            new_lines.add(max(1, j1))
    return old_lines, new_lines


# ── symbol attribution ───────────────────────────────────────────────────────
@dataclass
class Symbol:
    name: str
    start: int  # 1-based inclusive
    end: int  # 1-based inclusive
    depth: int = 0
    kind: str = "fn"

    @property
    def span(self) -> int:
        return self.end - self.start


# Declarations we attribute hunks to (any indentation — nested handlers inside
# a component matter: "BoardView > handleColumnDrop").
_TS_DECL = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?:export\s+)?(?:default\s+)?"
    r"(?:"
    r"(?:async\s+)?function\s*\*?\s*(?P<fn>[A-Za-z_$][\w$]*)"
    r"|class\s+(?P<cls>[A-Za-z_$][\w$]*)"
    r"|(?:interface|type|enum)\s+(?P<ty>[A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+(?P<var>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
    r"(?P<varval>.*)"
    r"|(?P<meth>[A-Za-z_$][\w$]*)\s*\([^()]*\)\s*(?::\s*[^{]+)?\{\s*$"
    r")"
)
_ROUTE = re.compile(
    r"""routerAdd\(\s*['"](?P<method>[A-Z]+)['"]\s*,\s*['"](?P<path>[^'"]+)['"]"""
)
_CRON = re.compile(r"""cronAdd\(\s*['"](?P<name>[^'"]+)['"]""")
_HOOK_EVT = re.compile(r"^(?:on[A-Z]\w+)\(\s*\(e\)\s*=>", re.M)
_STRING_OR_COMMENT = re.compile(
    r"""//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`""",
    re.S,
)
_JSX_TAG = re.compile(r"<[A-Za-z][^<>]*>")


def _blank_strings(text: str) -> str:
    """Replace string/comment contents with spaces (same length) so brace
    matching ignores braces inside them. Newlines are kept."""

    def repl(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return _STRING_OR_COMMENT.sub(repl, text)


def _block_end(lines: Sequence[str], start_idx: int) -> int:
    """Index (0-based, inclusive) of the line closing the block that opens on
    or after lines[start_idx]. Brace-counted on string/comment-blanked text;
    a declaration with no brace (`type X = string`, one-line arrow) ends on
    its own line or at the next blank/dedented line."""
    depth = 0
    opened = False
    indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    for i in range(start_idx, len(lines)):
        line = lines[i]
        for ch in line:
            if ch in "{([":
                depth += 1
                opened = True
            elif ch in "})]":
                depth -= 1
        if opened and depth <= 0:
            return i
        if not opened and i > start_idx:
            cur_indent = len(line) - len(line.lstrip())
            if line.strip() == "" or cur_indent <= indent:
                return i - 1
    return len(lines) - 1


def ts_symbols(text: str) -> List[Symbol]:
    """Heuristic symbol table for TS/TSX/JS: every named declaration with its
    brace-matched range and nesting depth. Good enough to say "which
    function did this hunk land in"; the exact `lui symbols` path replaces it
    when the project's TypeScript is reachable (see node_symbols)."""
    blanked = _blank_strings(text).splitlines()
    raw = text.splitlines()
    symbols: List[Symbol] = []
    for i, line in enumerate(blanked):
        m = _TS_DECL.match(line)
        if not m:
            continue
        name = m.group("fn") or m.group("cls") or m.group("ty") or m.group("var") or m.group("meth")
        if not name or name in ("if", "for", "while", "switch", "return", "catch", "else"):
            continue
        kind = "class" if m.group("cls") else "type" if m.group("ty") else "fn"
        if m.group("var") is not None:
            val = (m.group("varval") or "").strip()
            # Only VALUE declarations that hold code or data blocks are symbols;
            # `const x = 5` on its own line still counts (module constant).
            kind = "const" if not re.match(r"(async\s*)?(\(|[A-Za-z_$][\w$]*\s*=>|function)", val) else "fn"
        end = _block_end(blanked, i)
        depth = (len(line) - len(line.lstrip())) // 2
        # A local `const x = …` inside a function is not a symbol — only
        # module-level constants and anything holding code are.
        if kind == "const" and depth > 0:
            continue
        symbols.append(Symbol(name=name, start=i + 1, end=end + 1, depth=depth, kind=kind))
    # Drop false positives: a JSX line like `<Foo onClick={...}>` or a bare
    # call `foo(x) {` inside JSX is not a declaration.
    symbols = [
        s
        for s in symbols
        if not (s.kind == "fn" and raw[s.start - 1].lstrip().startswith("<"))
    ]
    return symbols


def hook_symbols(text: str) -> List[Symbol]:
    """pb_hooks: routes as 'METHOD /path', cron jobs as 'cron <name>',
    lifecycle hooks as their callback name, plus plain functions."""
    blanked = _blank_strings(text).splitlines()
    symbols: List[Symbol] = []
    for i, line in enumerate(blanked):
        route = _ROUTE.search(text.splitlines()[i]) if i < len(text.splitlines()) else None
        if route:
            end = _block_end(blanked, i)
            symbols.append(
                Symbol(name=f"{route.group('method')} {route.group('path')}", start=i + 1, end=end + 1, kind="route")
            )
            continue
        cron = _CRON.search(text.splitlines()[i])
        if cron:
            end = _block_end(blanked, i)
            symbols.append(Symbol(name=f"cron {cron.group('name')}", start=i + 1, end=end + 1, kind="cron"))
            continue
        hm = re.match(r"^(on[A-Z]\w+)\(", line)
        if hm:
            end = _block_end(blanked, i)
            symbols.append(Symbol(name=f"{hm.group(1)} hook", start=i + 1, end=end + 1, kind="hook"))
            continue
        m = _TS_DECL.match(line)
        if m and (m.group("fn") or m.group("var")):
            name = m.group("fn") or m.group("var")
            depth = (len(line) - len(line.lstrip())) // 2
            if m.group("var") and depth > 0:
                continue  # local inside a route/hook callback
            end = _block_end(blanked, i)
            symbols.append(Symbol(name=name, start=i + 1, end=end + 1, depth=depth))
    return symbols


def _innermost(symbols: Sequence[Symbol], line: int) -> Optional[Symbol]:
    best: Optional[Symbol] = None
    for s in symbols:
        if s.start <= line <= s.end and (best is None or s.span < best.span):
            best = s
    return best


def _symbol_path(symbols: Sequence[Symbol], sym: Symbol) -> str:
    """'Outer > inner' for nested declarations (containers by range)."""
    chain = [
        s for s in symbols
        if s is not sym and s.start <= sym.start and s.end >= sym.end and s.depth < sym.depth
    ]
    chain.sort(key=lambda s: s.span, reverse=True)
    names = [s.name for s in chain] + [sym.name]
    return " > ".join(names)


def attribute_symbols(
    old_text: Optional[str],
    new_text: Optional[str],
    symbols_of: Callable[[str], List[Symbol]],
) -> Tuple[List[str], List[str]]:
    """(changed symbol paths, unchanged TOP-LEVEL symbol names)."""
    old_syms = symbols_of(old_text) if old_text else []
    new_syms = symbols_of(new_text) if new_text else []
    old_lines, new_lines = _changed_line_sets(old_text or "", new_text or "")
    changed: List[str] = []

    def mark(syms: Sequence[Symbol], lines: set, suffix: str = "") -> None:
        for ln in sorted(lines):
            s = _innermost(syms, ln)
            if s is None:
                label = "(module top level)"
            else:
                label = _symbol_path(syms, s)
                # The hunk sits in the function's own body (render/JSX,
                # top-level statements), not in a nested declaration.
                if s.kind == "fn" and any(o is not s and s.start < o.start and o.end < s.end for o in syms):
                    label += " (body)"
            label += suffix
            if label not in changed:
                changed.append(label)

    mark(new_syms, new_lines)
    # Symbols that exist only in the old text were removed.
    new_names = {s.name for s in new_syms}
    for s in old_syms:
        if s.name not in new_names and any(s.start <= ln <= s.end for ln in old_lines):
            label = f"{_symbol_path(old_syms, s)} (removed)"
            if label not in changed:
                changed.append(label)
    # New symbols get an explicit "(new)" marker.
    old_names = {s.name for s in old_syms}
    changed = [
        (c + " (new)") if (c.split(" > ")[-1] in new_names and c.split(" > ")[-1] not in old_names and "(removed)" not in c and old_text is not None) else c
        for c in changed
    ]
    touched_top = {c.split(" > ")[0].replace(" (new)", "").replace(" (removed)", "") for c in changed}
    unchanged = [s.name for s in new_syms if s.depth == 0 and s.name not in touched_top]
    return changed, unchanged


# ── non-code attribution ─────────────────────────────────────────────────────
_MIG_COLLECTION = re.compile(
    r"""findCollectionByNameOrId\(\s*['"](?P<c1>[A-Za-z_]\w*)['"]|new\s+Collection\(\s*\{[^}]*?name\s*:\s*['"](?P<c2>[A-Za-z_]\w*)['"]""",
    re.S,
)
_MIG_FIELD = re.compile(r"""\bname\s*:\s*['"]([A-Za-z_]\w*)['"]""")
_CSS_RULE = re.compile(r"^\s*([^{}\n][^{}\n]*?)\s*\{", re.M)
_CSS_VAR = re.compile(r"(--[\w-]+)\s*:")


def _migration_notes(text: str) -> List[str]:
    cols = []
    for m in _MIG_COLLECTION.finditer(text):
        c = m.group("c1") or m.group("c2")
        if c and c not in cols:
            cols.append(c)
    fields = []
    for m in _MIG_FIELD.finditer(text):
        f = m.group(1)
        if f not in cols and f not in fields and f not in ("id", "created", "updated"):
            fields.append(f)
    notes = []
    if cols:
        notes.append("alters collections: " + ", ".join(cols))
    if fields:
        notes.append("fields named: " + ", ".join(fields[:20]))
    return notes or ["migration (no collection reference found — read it)"]


def _json_key_changes(old_text: Optional[str], new_text: Optional[str]) -> Tuple[List[str], List[str]]:
    def load(t: Optional[str]) -> Any:
        try:
            return json.loads(t) if t else None
        except Exception:
            return None

    a, b = load(old_text), load(new_text)

    def keys(v: Any) -> Dict[str, Any]:
        if isinstance(v, dict):
            return {str(k): val for k, val in v.items()}
        if isinstance(v, list):
            out: Dict[str, Any] = {}
            for i, item in enumerate(v):
                name = item.get("name") if isinstance(item, dict) else None
                out[str(name or i)] = item
            return out
        return {}

    ka, kb = keys(a), keys(b)
    changed = [k for k in kb if k not in ka or ka[k] != kb[k]]
    changed += [f"{k} (removed)" for k in ka if k not in kb]
    unchanged = [k for k in kb if k in ka and ka[k] == kb[k]]
    return changed, unchanged


def _css_changes(old_text: Optional[str], new_text: Optional[str]) -> Tuple[List[str], List[str]]:
    old_lines, new_lines = _changed_line_sets(old_text or "", new_text or "")
    text = new_text or ""
    lines = text.splitlines()
    rules: List[Symbol] = []
    for m in _CSS_RULE.finditer(text):
        start = text.count("\n", 0, m.start()) + 1
        end = _block_end(lines, start - 1) + 1
        rules.append(Symbol(name=m.group(1).strip()[:60], start=start, end=end, kind="rule"))
    changed: List[str] = []
    for ln in sorted(new_lines):
        s = _innermost(rules, ln)
        label = s.name if s else "(top level)"
        var = _CSS_VAR.search(lines[ln - 1]) if 0 < ln <= len(lines) else None
        if var:
            label = f"{label} {var.group(1)}"
        if label not in changed:
            changed.append(label)
    unchanged = [r.name for r in rules if r.name not in {c.split(" --")[0] for c in changed}]
    return changed, unchanged


def _package_changes(old_text: Optional[str], new_text: Optional[str]) -> List[str]:
    def deps(t: Optional[str]) -> Dict[str, str]:
        try:
            pkg = json.loads(t) if t else {}
        except Exception:
            return {}
        out = {}
        for section in ("dependencies", "devDependencies"):
            out.update({k: str(v) for k, v in (pkg.get(section) or {}).items()})
        return out

    a, b = deps(old_text), deps(new_text)
    notes = []
    for k in b:
        if k not in a:
            notes.append(f"{k} added ({b[k]})")
        elif a[k] != b[k]:
            notes.append(f"{k} {a[k]} → {b[k]}")
    for k in a:
        if k not in b:
            notes.append(f"{k} removed")
    return notes


# ── references ───────────────────────────────────────────────────────────────
_REF_MIN_LEN = 4
_REF_SKIP = {"render", "default", "props", "state", "index", "main", "handler", "value", "data", "type", "name"}


def _leaf(label: str) -> str:
    """'Outer > inner (new)' → 'inner'; any trailing '(…)' marker dropped."""
    return re.sub(r"\s*\([^()]*\)\s*$", "", label.split(" > ")[-1]).strip()


def find_references(
    project_path: Path, rel: str, symbol_name: str, own_text: str, own_range: Optional[Tuple[int, int]]
) -> Tuple[int, List[str]]:
    """(same-file references outside the symbol's own range, other files
    referencing the name). Word-boundary grep over the agent-owned source."""
    name = symbol_name
    if len(name) < _REF_MIN_LEN or name.lower() in _REF_SKIP or " " in name:
        return 0, []
    pat = re.compile(rf"\b{re.escape(name)}\b")
    same = 0
    for i, line in enumerate(own_text.splitlines(), start=1):
        if own_range and own_range[0] <= i <= own_range[1]:
            continue
        same += len(pat.findall(line))
    others: List[str] = []
    for root in ("frontend/src/app", "pb/pb_hooks"):
        d = Path(project_path) / root
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".ts", ".tsx", ".js", ".jsx"):
                continue
            prel = _posix(p, Path(project_path))
            if prel == rel:
                continue
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                    others.append(prel)
            except Exception:
                continue
            if len(others) >= 12:
                break
    return same, others


def attribute_changes(project_path: Path, changes: List[FileChange], symbols_for: Optional[Callable[[str, str], Optional[List[Symbol]]]] = None) -> None:
    """Fill changed/unchanged symbols + notes on every FileChange, in place.
    `symbols_for(rel, text)` may return an exact symbol table (lui symbols)
    or None to fall back to the heuristic."""
    project_path = Path(project_path)
    for fc in changes:
        rel = fc.rel
        low = rel.lower()
        try:
            if rel.startswith("frontend/src/kit/"):
                fc.attribution = "file"
                fc.notes.append("kit (system-managed) — re-vendored by tooling, not an agent edit")
            elif rel.startswith("pb/pb_migrations/"):
                fc.attribution = "file"
                fc.notes.extend(_migration_notes(fc.new_text or fc.old_text or ""))
            elif rel.startswith("pb/pb_hooks/"):
                fc.changed_symbols, fc.unchanged_symbols = attribute_symbols(
                    fc.old_text, fc.new_text, hook_symbols
                )
            elif low.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs")):
                def _syms(text: str, _rel=rel) -> List[Symbol]:
                    exact = symbols_for(_rel, text) if symbols_for else None
                    return exact if exact else ts_symbols(text)

                fc.changed_symbols, fc.unchanged_symbols = attribute_symbols(
                    fc.old_text, fc.new_text, _syms
                )
            elif rel == "frontend/package.json":
                fc.attribution = "file"
                fc.notes.extend(_package_changes(fc.old_text, fc.new_text) or ["package.json changed (no dependency delta)"])
            elif low.endswith(".json"):
                fc.changed_symbols, fc.unchanged_symbols = _json_key_changes(fc.old_text, fc.new_text)
                fc.attribution = "key"
            elif low.endswith(".css"):
                fc.changed_symbols, fc.unchanged_symbols = _css_changes(fc.old_text, fc.new_text)
                fc.attribution = "rule"
            elif rel.startswith("reference/"):
                fc.attribution = "file"
                fc.notes.append("spec/reference text — not code")
            else:
                fc.attribution = "file"
            if fc.kind == "added" and fc.attribution == "symbol":
                fc.notes.append("new file — every symbol in it is new")
            if fc.kind == "deleted":
                fc.attribution = "file"
                fc.notes.append("file deleted")
            # References: who else uses the changed symbols.
            if fc.attribution == "symbol" and fc.new_text:
                syms = hook_symbols(fc.new_text) if rel.startswith("pb/pb_hooks/") else ts_symbols(fc.new_text)
                for label in fc.changed_symbols[:12]:
                    leaf = _leaf(label)
                    rng = next(((s.start, s.end) for s in syms if s.name == leaf), None)
                    same, others = find_references(project_path, rel, leaf, fc.new_text, rng)
                    if same or others:
                        parts = []
                        if same:
                            parts.append(f"{same} in-file reference(s)")
                        if others:
                            parts.append("also referenced by " + ", ".join(others[:8]))
                        fc.notes.append(f"{leaf}: " + "; ".join(parts))
        except Exception as e:  # attribution must never break the verify
            fc.attribution = "file"
            fc.notes.append(f"no symbol attribution ({type(e).__name__})")


# ── rendering ────────────────────────────────────────────────────────────────
def _unified(fc: FileChange) -> str:
    a = (fc.old_text or "").splitlines()
    b = (fc.new_text or "").splitlines()
    out = list(
        difflib.unified_diff(a, b, fromfile=f"promoted/{fc.rel}", tofile=f"now/{fc.rel}", lineterm="", n=2)
    )
    if len(out) > MAX_DIFF_LINES_PER_FILE:
        out = out[:MAX_DIFF_LINES_PER_FILE] + [
            f"… {len(out) - MAX_DIFF_LINES_PER_FILE} more diff lines — read_file the file for the rest"
        ]
    return "\n".join(out)


def _join(items: Sequence[str], limit: int = 10) -> str:
    items = list(items)
    if not items:
        return "—"
    if len(items) > limit:
        return ", ".join(items[:limit]) + f", … (+{len(items) - limit} more)"
    return ", ".join(items)


def render_diff_block(changes: List[FileChange], baseline: Optional[Dict[str, Any]], total_watched: int) -> str:
    if baseline is None:
        return (
            "CHANGED SINCE LAST PROMOTE: NO BASELINE — first verify of this code "
            "(no promoted snapshot exists yet). Every feature is in scope; "
            "walk everything."
        )
    when = baseline.get("at_human") or "unknown"
    if not changes:
        return (
            f"CHANGED SINCE LAST PROMOTE ({when}): nothing — the code is "
            "byte-identical to the last promoted version. Only the spec "
            "(## Changes) or a re-verify request can put features in scope."
        )
    kit = [c for c in changes if c.rel.startswith("frontend/src/kit/")]
    rest = [c for c in changes if c not in kit]
    lines = [f"CHANGED SINCE LAST PROMOTE ({when}):"]
    for fc in rest[:MAX_FILES_IN_BLOCK]:
        stat = f"(+{fc.added_lines} / -{fc.removed_lines})" if fc.kind == "modified" else ""
        lines.append(f"  {fc.kind:<9} {fc.rel}   {stat}".rstrip())
        if fc.attribution in ("symbol", "key", "rule"):
            what = {"symbol": "", "key": " (keys)", "rule": " (rules)"}[fc.attribution]
            lines.append(f"    changed{what}:   {_join(fc.changed_symbols)}")
            lines.append(f"    unchanged{what}: {_join(fc.unchanged_symbols)}")
        else:
            lines.append("    attribution: file-level — no symbol attribution")
        for n in fc.notes[:8]:
            lines.append(f"    · {n}")
    if len(rest) > MAX_FILES_IN_BLOCK:
        lines.append(f"  … {len(rest) - MAX_FILES_IN_BLOCK} more changed files")
    if kit:
        lines.append(
            f"  kit       frontend/src/kit/ — {len(kit)} file(s) re-vendored by tooling "
            "(shared UI components/data layer: reaches every feature that uses them)"
        )
    unchanged_n = max(0, total_watched - len(changes))
    lines.append(f"UNCHANGED: {unchanged_n} watched file(s)")
    # Unified diffs below the block (text files only).
    diffs = [
        _unified(fc) for fc in rest[:MAX_FILES_IN_BLOCK] if fc.kind != "deleted" and (fc.old_text or fc.new_text) and not fc.rel.startswith("reference/")
    ]
    if diffs:
        lines.append("")
        lines.append("DIFF (per file, truncated):")
        lines.extend(diffs)
    return "\n".join(lines)


# ── history ──────────────────────────────────────────────────────────────────
def append_history(store_dir: Path, entry: Dict[str, Any]) -> None:
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    f = store_dir / "history.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []
    except Exception:
        data = []
    data.append(entry)
    data = data[-50:]
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_history(store_dir: Path) -> List[Dict[str, Any]]:
    f = Path(store_dir) / "history.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []
    except Exception:
        return []


def render_history_block(store_dir: Path) -> str:
    entries = read_history(store_dir)
    if not entries:
        return "LAST VERIFY RESULTS: none recorded — no feature of this app has a verified history yet."
    delivered = [e for e in entries if e.get("kind") == "delivered"]
    walks = [e for e in entries if e.get("kind") != "delivered"]
    if delivered and not walks:
        d = delivered[-1]
        return (
            f"LAST VERIFY RESULTS: this app arrived finished ({d.get('source', 'delivered')}) on "
            f"{d.get('at_human', '?')} — every shipped feature was verified upstream before "
            "delivery; the baseline is that shipped code. No local walk yet: a feature the "
            "diff cannot reach is as verified as it was on arrival."
        )
    entries = walks
    latest: Dict[str, Tuple[str, str, str]] = {}
    for e in entries:  # oldest → newest, so later entries overwrite
        when = e.get("at_human") or "?"
        mode = (e.get("scope") or {}).get("mode") or "FULL"
        for feat, verdict in (e.get("features") or {}).items():
            latest[feat] = (verdict, when, mode)
    lines = ["LAST VERIFY RESULTS (per feature, most recent walk that exercised it):"]
    for feat, (verdict, when, mode) in sorted(latest.items()):
        lines.append(f"  - {feat} — {verdict} {when} ({mode.lower()} walk)")
    last = entries[-1]
    excluded = (last.get("scope") or {}).get("excluded") or []
    if excluded:
        lines.append(f"  (last walk on {last.get('at_human')} skipped {len(excluded)} feature(s) with reasons)")
    full_walks = [e for e in entries if (e.get("scope") or {}).get("mode", "FULL") == "FULL"]
    if full_walks:
        lines.append(f"  last FULL walk: {full_walks[-1].get('at_human')}")
    return "\n".join(lines)


# ── scope parsing ────────────────────────────────────────────────────────────
_SCOPE_RE = re.compile(r"^\s*SCOPE:\s*(DELTA|FULL)\b", re.I | re.M)
_INCLUDED_RE = re.compile(r"^[ 	]*INCLUDED:[ 	]*(.*)$", re.I | re.M)
_EXCLUDED_HDR = re.compile(r"^[ 	]*EXCLUDED:[ 	]*(.*)$", re.I | re.M)


def parse_scope(text: str) -> Optional[Dict[str, Any]]:
    """The verifier's SCOPE block → {mode, included:[...], excluded:[(feature,
    reason)], excluded_without_reason:[...]}. None when no block."""
    text = text or ""
    m = _SCOPE_RE.search(text)
    if not m:
        return None
    mode = m.group(1).upper()
    included: List[str] = []
    im = _INCLUDED_RE.search(text)
    if im:
        raw = im.group(1).strip()
        if raw and raw.lower() not in ("none", "-", "—"):
            included = [s.strip(" .") for s in re.split(r"[,;]", raw) if s.strip(" .")]
    excluded: List[Tuple[str, str]] = []
    bare: List[str] = []
    em = _EXCLUDED_HDR.search(text)
    if em:
        tail = text[em.end():]
        inline = em.group(1).strip()
        # "none", "none (single-feature walk…)", "nothing excluded", "n/a"
        # all mean: no exclusions. A parenthetical after "none" is a note.
        if re.match(r"^\(?\s*(none|nothing|n/?a|no features?)\b", inline, re.I):
            inline = ""
        if inline and inline not in ("-", "—"):
            for item in re.split(r"[;]", inline):
                if "—" in item or " - " in item or ":" in item:
                    feat, reason = re.split(r"\s+—\s+|\s+-\s+|:\s*", item, maxsplit=1)
                    excluded.append((feat.strip(), reason.strip()))
                elif item.strip():
                    bare.append(item.strip())
        for line in tail.splitlines():
            if re.match(r"^\s*(FEATURES|VERDICT|FAILURES|BLOCKED BY)\b", line, re.I):
                break
            lm = re.match(r"^\s*[-*•]\s*(.+?)\s*(?:—|–|:| - )\s*(.+)$", line)
            if lm:
                excluded.append((lm.group(1).strip(), lm.group(2).strip()))
            elif re.match(r"^\s*[-*•]\s*\S", line):
                bare.append(line.strip(" -*•"))
    return {
        "mode": mode,
        "included": included,
        "excluded": excluded,
        "excluded_without_reason": bare,
    }


_FEATURE_LINE = re.compile(
    r"^-\s+(.{1,160}?)\s*(?:—|–|:|-+)\s*(PASS|FAIL|NOT REACHED)\b", re.M | re.I
)


def feature_verdicts(report_text: str) -> Dict[str, str]:
    """{feature: PASS|FAIL|NOT REACHED} from the FEATURES section only."""
    section = re.split(r"^\s*(?:FAILURES|BLOCKED BY)\b", report_text or "", maxsplit=1, flags=re.M | re.I)[0]
    section = section.split("FEATURES:", 1)[-1] if "FEATURES:" in section else section
    out: Dict[str, str] = {}
    for m in _FEATURE_LINE.finditer(section):
        out[m.group(1).strip()] = m.group(2).upper()
    return out


# ── coverage (Phase 2) ───────────────────────────────────────────────────────
def _norm_cov_path(path: str) -> str:
    p = path.replace("\\", "/")
    i = p.find("/frontend/")
    return p[i + 1:] if i >= 0 else p.lstrip("/")


def fold_coverage(jsonl_path: Path) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """coverage.jsonl (marks interleaved with counter deltas) →
    {feature: {file: [{fn, line}]}}. Counters before the first mark go to
    '(unattributed)'."""
    result: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    current = "(unattributed)"
    p = Path(jsonl_path)
    if not p.is_file():
        return result
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        if "mark" in rec:
            current = str(rec["mark"]).strip() or current
            continue
        counters = rec.get("counters") or {}
        for file, fns in counters.items():
            rel = _norm_cov_path(str(file))
            bucket = result.setdefault(current, {}).setdefault(rel, [])
            seen = {(f["fn"], f.get("line")) for f in bucket}
            for fn in fns or []:
                if not isinstance(fn, dict):
                    continue
                name, line, hits = fn.get("name"), fn.get("line"), fn.get("hits", 0)
                if not hits or (name, line) in seen:
                    continue
                bucket.append({"fn": name, "line": line})
                seen.add((name, line))
    return result


def merge_coverage(store_dir: Path, folded: Dict[str, Any], baseline_at: Optional[float]) -> None:
    if not folded:
        return
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    f = store_dir / "coverage.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except Exception:
        data = {}
    features = data.get("features") or {}
    for feat, files in folded.items():
        if feat == "(unattributed)":
            continue
        features[feat] = {"files": files, "at": time.time(), "at_human": time.strftime("%Y-%m-%d %H:%M")}
    data["features"] = features
    data["recorded_against_promote"] = baseline_at
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_coverage(store_dir: Path) -> Dict[str, Any]:
    f = Path(store_dir) / "coverage.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except Exception:
        return {}


def render_coverage_block(store_dir: Path, changes: List[FileChange]) -> str:
    cov = read_coverage(store_dir)
    features = cov.get("features") or {}
    if not features:
        return ""
    lines = ["CODE ON THE DIFF WAS LAST EXECUTED BY (recorded coverage; information, not a rule):"]
    any_hit = False
    for fc in changes:
        if fc.attribution != "symbol" or not fc.new_text:
            continue
        syms = ts_symbols(fc.new_text)
        for label in fc.changed_symbols:
            leaf = _leaf(label)
            rng = next(((s.start, s.end) for s in syms if s.name == leaf), None)
            hits: List[str] = []
            for feat, rec in features.items():
                for file, fns in (rec.get("files") or {}).items():
                    if not file.endswith(fc.rel) and not fc.rel.endswith(file):
                        continue
                    for fn in fns:
                        if fn.get("fn") == leaf or (rng and fn.get("line") and rng[0] <= int(fn["line"]) <= rng[1]):
                            hits.append(f"{feat} ({rec.get('at_human', '?')})")
                            break
            if hits:
                any_hit = True
                lines.append(f"  {fc.rel}: {label} → " + "; ".join(sorted(set(hits))))
            else:
                lines.append(f"  {fc.rel}: {label} → no coverage recorded (new code, or never walked with coverage on)")
    if not any_hit and len(lines) == 1:
        return ""
    return "\n".join(lines)
