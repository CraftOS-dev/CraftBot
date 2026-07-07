"""Build-order pace guard for the Live Construction View.

The user watches a Living UI being built through a live preview. The creator
workflow mandates a static UI skeleton BEFORE backend work (skill Phase 1.5),
but a prose mandate alone loses to the model's habitual layer-by-layer plan —
observed in practice: entire backend first, entire frontend last, preview
static for 20+ minutes.

This guard makes the mandate structural: when a file write targets the
backend/ of a project that is still being created and the frontend skeleton
does not exist yet, the write action's RESULT carries a note telling the
agent to build the skeleton first. Advisory, never blocking — a struggling
agent must not get wedged — but it arrives in the action output the model
actually reads on the very next turn, not in a skill it skimmed earlier.

Deliberately filesystem-only (registry JSON + MainView marker): file actions
may execute in contexts without the manager singleton, and this must work in
all of them. Every path is fail-silent.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

# Untouched-template detection: the template MainView carries an EXPLICIT
# sentinel comment (a named contract, not incidental prose); the legacy
# prose marker is kept for projects scaffolded before the sentinel existed.
_PLACEHOLDER_SENTINEL = "CRAFTBOT:TEMPLATE-PLACEHOLDER"
_PLACEHOLDER_MARKER = "Start building your custom interface"  # legacy


def _is_untouched_template(content: str) -> bool:
    return _PLACEHOLDER_SENTINEL in content or _PLACEHOLDER_MARKER in content


# ── template-derived contracts (single-sourced, mtime-cached) ───────────────
# System routes, layout-kit exports, and skeleton component names are READ
# FROM THE TEMPLATE at call time instead of being duplicated here — the
# template is the source of truth and this guard tracks it automatically.
# Hardcoded lists below are FALLBACKS only (template unreadable).

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "data" / "living_ui_template"
_TEMPLATE_CACHE: dict = {}


def _cached_template_parse(rel: str, parser, fallback):
    path = _TEMPLATE_DIR / rel
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return fallback
    hit = _TEMPLATE_CACHE.get(rel)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        value = parser(path.read_text(encoding="utf-8", errors="replace"))
        if not value:
            value = fallback
    except Exception:
        value = fallback
    _TEMPLATE_CACHE[rel] = (mtime, value)
    return value


_FALLBACK_SYSTEM_ROUTES = [
    ("get", "/state"), ("put", "/state"), ("delete", "/state"),
    ("post", "/state/replace"), ("post", "/action"),
    ("get", "/ui-snapshot"), ("post", "/ui-snapshot"),
    ("get", "/ui-screenshot"), ("post", "/ui-screenshot"),
]

# Column-0 anchor: decorators in docstring examples are indented/inline and
# must not count as routes.
_ROUTE_DECORATOR_RE = re.compile(
    r"^@router\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.MULTILINE
)


def _template_system_routes():
    return _cached_template_parse(
        "backend/routes.py",
        lambda text: [(m.lower(), p) for m, p in _ROUTE_DECORATOR_RE.findall(text)],
        _FALLBACK_SYSTEM_ROUTES,
    )


_FALLBACK_KIT_EXPORTS = [
    "AppShell", "Section", "CardGrid", "Toolbar", "IconBadge",
    "StatCard", "SplitView", "SkeletonCard", "SkeletonRow",
]

_KIT_EXPORT_RE = re.compile(r"^export\s+(?:function|const)\s+([A-Za-z]\w*)", re.MULTILINE)


def _kit_export_names():
    return _cached_template_parse(
        "frontend/components/ui/layout.tsx",
        lambda text: _KIT_EXPORT_RE.findall(text),
        _FALLBACK_KIT_EXPORTS,
    )


def _skeleton_component_names():
    return [n for n in _kit_export_names() if n.startswith("Skeleton")]

PACE_NOTE = (
    "NOTE — the user is WATCHING this app being built in a live preview, and "
    "the screen has not changed yet. Before writing more backend code, build "
    "the layout wireframe (skill Phase 1.5): rewrite frontend/components/"
    "MainView.tsx as a Layout Kit assembly (AppShell + one "
    "Section per region holding Skeleton placeholders). Then build one "
    "FEATURE at a time: its backend + tests, then ONE write of the FINAL "
    "live component(s) (never a static stub) mounted into MainView in the "
    "same step — the feature's user flow works end to end before the next "
    "feature starts."
)

# (registry mtime, parsed creating-project paths) — refreshed on change.
_CACHE: Optional[Tuple[float, List[str]]] = None


def _registry_path() -> Path:
    workspace = os.environ.get("CRAFTBOT_WORKSPACE") or str(
        Path(__file__).resolve().parents[2] / "agent_file_system" / "workspace"
    )
    return Path(workspace) / "living_ui_projects.json"


def _creating_project_roots() -> List[str]:
    """Normalized paths of projects currently in 'creating' status."""
    global _CACHE
    registry = _registry_path()
    try:
        mtime = registry.stat().st_mtime
    except OSError:
        return []
    if _CACHE is not None and _CACHE[0] == mtime:
        return _CACHE[1]
    roots: List[str] = []
    try:
        data = json.loads(registry.read_text(encoding="utf-8"))
        for p in data.get("projects", []):
            if p.get("status") == "creating" and p.get("path"):
                try:
                    roots.append(
                        str(Path(p["path"]).resolve()).lower().replace("\\", "/")
                    )
                except Exception:
                    continue
    except Exception:
        return []
    _CACHE = (mtime, roots)
    return roots


def _skeleton_built(project_root: str) -> bool:
    """True once MainView no longer contains the template placeholder."""
    main_view = Path(project_root) / "frontend" / "components" / "MainView.tsx"
    try:
        return not _is_untouched_template(main_view.read_text(encoding="utf-8"))
    except OSError:
        # No MainView (external/imported app) — the guard doesn't apply.
        return True


def skeleton_missing(project_root) -> bool:
    """Public check used by the launch pipeline's completeness gate: True
    when the project's MainView is still the untouched template placeholder
    (i.e. no UI has been built). Fail-open — errors report 'not missing' so
    a guard bug can never block a legitimate launch."""
    try:
        return not _skeleton_built(str(project_root))
    except Exception:
        return False


def pace_note_for(file_path: str) -> Optional[str]:
    """Return the skeleton-first note when `file_path` is a backend write in
    a creating project whose UI skeleton doesn't exist yet, else None.

    Cheap for the common case (no creating projects → one stat call), and
    never raises.
    """
    try:
        match = _match_creating_rel(file_path)
        if not match:
            return None
        root, rel = match
        if not rel.startswith("backend/"):
            return None
        if _skeleton_built(root):
            return None
        return PACE_NOTE
    except Exception:
        return None


def _match_creating_rel(file_path: str) -> Optional[Tuple[str, str]]:
    """(project_root, relative_path) when file_path is inside a creating
    project, else None."""
    roots = _creating_project_roots()
    if not roots:
        return None
    norm = str(Path(file_path).resolve()).lower().replace("\\", "/")
    for root in roots:
        prefix = root.rstrip("/") + "/"
        if norm.startswith(prefix):
            return root, norm[len(prefix):]
    return None


# ── write-time pattern guard ────────────────────────────────────────────────
# Recurring mistakes observed across real builds, flagged the moment the
# file is written instead of being discovered cycles later via 404s or an
# unstyled screen. Deterministic regex only — no judgment calls.

_ROUTE_API_PREFIX_RE = re.compile(
    r"@router\.(get|post|put|delete|patch)\(\s*[\"']/api/", re.IGNORECASE
)
_RAW_CONTROL_RE = re.compile(r"<(input|button|select|textarea)[\s/>]", re.IGNORECASE)
# Empty arrow-function handlers: onClick={() => {}} and friends — the
# signature of a stub/dead control (observed shipping as dead tabs, dead
# search, dead Refresh buttons).
_STUB_HANDLER_RE = re.compile(r"=>\s*\{\s*\}")


def _layout_kit_re() -> re.Pattern:
    """Kit usage detector, derived from the template kit's actual exports
    (plus EmptyState, which lives in the preset index)."""
    names = list(_kit_export_names()) + ["EmptyState"]
    return re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")

ROUTE_API_PREFIX_NOTE = (
    "WARNING — route paths in routes.py must NOT start with /api. The router "
    "is mounted with prefix='/api', so @router.get(\"/api/articles\") becomes "
    "/api/api/articles and your tests will 404. Declare routes WITHOUT /api "
    "(e.g. \"/articles\"); your TESTS call WITH /api "
    "(e.g. client.get(\"/api/articles\")). Fix the decorators now."
)

RAW_CONTROL_NOTE = (
    "WARNING — raw HTML controls (<input>/<button>/<select>/<textarea>) "
    "detected in this component. They render unstyled. Use the preset "
    "components from './components/ui' instead: <Input>, <Button>, "
    "<Select>, <Textarea>."
)

MISSING_CSS_NOTE = (
    "WARNING — this component ships no CSS: it has no <style> block and uses "
    "no layout-kit primitives. CSS comes WITH the component: build it from "
    "the layout kit (AppShell/Section/CardGrid/EmptyState/"
    "Skeleton*) and/or add a scoped <style> block in this same file."
)

STUB_HANDLER_NOTE = (
    "WARNING — empty stub handler detected (e.g. onClick={() => {}}). Dead "
    "controls are a violation: every control ships WIRED in the same write. "
    "If the real handler isn't ready, the control isn't ready — don't render "
    "it yet."
)


def _system_route_notes(content: str) -> List[str]:
    """System routes every scaffolded backend must keep — derived from the
    TEMPLATE's routes.py (whatever it declares is the contract). Whole-file
    rewrites of routes.py from partial reads have deleted them."""
    missing = []
    for method, path in _template_system_routes():
        pattern = (
            r"@router\." + re.escape(method) + r"\(\s*[\"']"
            + re.escape(path) + r"[\"']"
        )
        if not re.search(pattern, content):
            missing.append(f"{method.upper()} {path}")
    if not missing:
        return []
    return [
        "WARNING — this routes.py is MISSING the template's system routes: "
        + ", ".join(missing)
        + ". Your whole-file rewrite deleted them — the agent APIs, console "
        "log capture, and validation smoke tests depend on them. Read the "
        "FULL current file, then rewrite it with the system routes restored "
        "exactly as the template had them. Never rewrite routes.py from a "
        "partial read."
    ]


def _pattern_notes(rel: str, content: str) -> List[str]:
    notes: List[str] = []
    if rel == "backend/routes.py":
        if _ROUTE_API_PREFIX_RE.search(content):
            notes.append(ROUTE_API_PREFIX_NOTE)
        notes.extend(_system_route_notes(content))
    if (
        rel.startswith("frontend/components/")
        and rel.endswith((".tsx", ".jsx"))
        and "/ui/" not in rel
        and "/agent/" not in rel
    ):
        if _RAW_CONTROL_RE.search(content):
            notes.append(RAW_CONTROL_NOTE)
        if "<style" not in content and not _layout_kit_re().search(content):
            notes.append(MISSING_CSS_NOTE)
        if _STUB_HANDLER_RE.search(content):
            notes.append(STUB_HANDLER_NOTE)
    return notes


def review_note_for(file_path: str) -> Optional[str]:
    """Combined write-time note for file actions: build-order pace note plus
    pattern warnings (route /api prefix, raw controls, missing CSS, unmounted
    components). Reads the just-written file from disk. Returns None when
    nothing to say. Never raises."""
    try:
        match = _match_creating_rel(file_path)
        if not match:
            return None
        root, rel = match

        notes: List[str] = []
        if rel.startswith("backend/"):
            if not _skeleton_built(root):
                notes.append(PACE_NOTE)
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        notes.extend(_pattern_notes(rel, content))
        notes.extend(_mount_notes(root, rel))
        # Cross-file import/export drift — checked on any frontend module write
        p = rel.replace("\\", "/").lower()
        if p.endswith((".tsx", ".jsx")) and (
            p == "frontend/app.tsx"
            or (
                p.startswith("frontend/components/")
                and "/ui/" not in p
                and "/agent/" not in p
            )
        ):
            notes.extend(_import_export_notes(root))
        return "\n\n".join(notes) if notes else None
    except Exception:
        return None


# ── import/export consistency guard ─────────────────────────────────────────
# A single batched generation has produced `export function MainView` in one
# file and `import MainView from ...` (default) in another — the app then
# renders NOTHING until validation. Export style vs import style is pure
# regex; catch the drift on the write that creates it.

_DEFAULT_EXPORT_RE = re.compile(r"^\s*export\s+default\b", re.MULTILINE)


def _frontend_module_files(project_root) -> List[Path]:
    """App.tsx + region components + MainView — the files that import each
    other during a build."""
    front = Path(project_root) / "frontend"
    files: List[Path] = []
    app_tsx = front / "App.tsx"
    if app_tsx.exists():
        files.append(app_tsx)
    comp_dir = front / "components"
    if comp_dir.is_dir():
        for f in comp_dir.iterdir():
            if f.is_file() and f.suffix in _COMPONENT_EXTS:
                files.append(f)
    return files


def _import_export_notes(project_root) -> List[str]:
    try:
        files = _frontend_module_files(project_root)
        texts: dict = {}
        for f in files:
            try:
                texts[f.stem] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[f.stem] = ""
        # Export style per module (named export of its own stem vs default)
        has_named = {
            stem: bool(
                re.search(
                    r"export\s+(?:function|const|class)\s+%s\b" % re.escape(stem),
                    text,
                )
            )
            for stem, text in texts.items()
        }
        has_default = {
            stem: bool(_DEFAULT_EXPORT_RE.search(text)) for stem, text in texts.items()
        }
        problems: List[str] = []
        # main.tsx (system-managed) does `import App from './App'` — App.tsx
        # must keep its default export.
        if "App" in texts and texts["App"].strip() and not has_default["App"]:
            problems.append(
                "App.tsx lost its `export default App` — main.tsx imports it "
                "as a default and the app will not render"
            )
        for importer, text in texts.items():
            for target in texts:
                if target == importer:
                    continue
                # import styles used by `importer` for `target`
                default_import = re.search(
                    r"import\s+%s\s+from\s+['\"][./]+(?:components/)?%s['\"]"
                    % (re.escape(target), re.escape(target)),
                    text,
                )
                named_import = re.search(
                    r"import\s*\{[^}]*\b%s\b[^}]*\}\s*from\s+['\"][./]+(?:components/)?%s['\"]"
                    % (re.escape(target), re.escape(target)),
                    text,
                )
                if default_import and not has_default[target]:
                    problems.append(
                        f"{importer}.tsx does `import {target} from ...` "
                        f"(default) but {target}.tsx has no default export — "
                        f"use `import {{ {target} }} from './{target}'`"
                    )
                if named_import and not has_named[target] and has_default[target]:
                    problems.append(
                        f"{importer}.tsx does `import {{ {target} }}` (named) "
                        f"but {target}.tsx only has a default export — "
                        f"use `import {target} from './{target}'`"
                    )
        if not problems:
            return []
        return [
            "WARNING — import/export mismatch (the app will NOT render until "
            "fixed): " + "; ".join(problems[:4])
        ]
    except Exception:
        return []


# ── mounting guard ──────────────────────────────────────────────────────────
# The failure that shipped a wireframe: components fully built, wired to the
# API, and never imported by MainView — invisible forever. A component that
# nothing renders does not exist; say so at write time and refuse at
# validation time.

_COMPONENT_EXTS = (".tsx", ".jsx")


def _region_component_files(project_root) -> List[Path]:
    """Agent-written region components: frontend/components/*.tsx excluding
    MainView (the assembly), ui/ (presets), and agent/ (system)."""
    comp_dir = Path(project_root) / "frontend" / "components"
    if not comp_dir.is_dir():
        return []
    files = []
    for f in comp_dir.iterdir():
        if f.is_file() and f.suffix in _COMPONENT_EXTS and f.stem != "MainView":
            files.append(f)
    return files


def unmounted_components(project_root) -> List[str]:
    """Names of region components referenced by neither MainView nor any
    other region component. Fail-open: unreadable files count as mounted."""
    try:
        main_view = Path(project_root) / "frontend" / "components" / "MainView.tsx"
        if not main_view.exists():
            return []  # not a template-shaped app — guard doesn't apply
        files = _region_component_files(project_root)
        if not files:
            return []
        texts: dict = {}
        for f in files:
            try:
                texts[f.stem] = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[f.stem] = ""
        try:
            mv_text = main_view.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        missing: List[str] = []
        for stem in texts:
            pattern = re.compile(r"\b%s\b" % re.escape(stem))
            referenced = bool(pattern.search(mv_text)) or any(
                other != stem and pattern.search(text)
                for other, text in texts.items()
            )
            if not referenced:
                missing.append(stem)
        return sorted(missing)
    except Exception:
        return []


def mounting_errors(project_root) -> List[str]:
    """Validation-time checks that the built UI is actually ON SCREEN.
    Returns prescriptive errors; empty list when fine. Fail-open."""
    try:
        main_view = Path(project_root) / "frontend" / "components" / "MainView.tsx"
        if not main_view.exists():
            return []
        if _skeleton_missing_marker(main_view):
            return []  # untouched template — the placeholder gate owns this
        files = _region_component_files(project_root)
        if not files:
            return [
                "The app is still only the layout wireframe: no region "
                "component files exist under frontend/components/. Build "
                "each region as its own component file, import it in "
                "MainView, and replace that Section's Skeleton placeholders "
                "with it (skill Phase 2-7)."
            ]
        missing = unmounted_components(project_root)
        if missing:
            names = ", ".join(missing)
            return [
                f"Component(s) built but NEVER MOUNTED: {names}. They are "
                f"not imported or rendered by MainView (or any other "
                f"component), so the user cannot see or use them — the app "
                f"on screen is still the wireframe. Edit MainView.tsx: "
                f"import each component and replace its Section's "
                f"Skeleton placeholders with it, then validate again."
            ]
        # Wireframe remnants: MainView still rendering Skeleton placeholders
        # means planned sections were never implemented (observed: agent
        # marked remaining features "complete", shipped skeleton sections).
        try:
            mv_text = main_view.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        skeleton_names = _skeleton_component_names()
        skeleton_re = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in skeleton_names) + r")\b"
        )
        if skeleton_names and skeleton_re.search(mv_text):
            return [
                "MainView still renders wireframe Skeleton placeholders — "
                "those sections were planned but NEVER IMPLEMENTED. Planned "
                "means built: implement the features that own every "
                "remaining section, then validate again. Do NOT delete "
                "planned sections to pass this check, and do NOT ask the "
                "user for permission to skip them — proposing to shrink "
                "your own committed scope is a violation. Skeletons for "
                "loading states belong INSIDE components, never in MainView."
            ]
        return []
    except Exception:
        return []


def _skeleton_missing_marker(main_view: Path) -> bool:
    try:
        return _is_untouched_template(main_view.read_text(encoding="utf-8"))
    except OSError:
        return False


MOUNT_NOTE_COMPONENT = (
    "WARNING — this component is NOT MOUNTED: MainView.tsx does not import "
    "or render it, so it is invisible to the user. Edit MainView NOW: import "
    "it and replace its Section's Skeleton placeholders with it. Validation "
    "refuses to launch apps with unmounted components."
)


def _mount_notes(project_root: str, rel: str) -> List[str]:
    # NOTE: `rel` comes from _match_creating_rel and is lowercased — all
    # comparisons here must be case-insensitive.
    p = rel.replace("\\", "/").lower()
    # A region component was just written — is it on screen?
    if (
        p.startswith("frontend/components/")
        and p.endswith(_COMPONENT_EXTS)
        and "/ui/" not in p
        and "/agent/" not in p
        and not p.endswith("mainview.tsx")
    ):
        stem = Path(p).stem
        if stem in {m.lower() for m in unmounted_components(project_root)}:
            return [MOUNT_NOTE_COMPONENT]
    # MainView was just written — did it leave anything unmounted?
    if p.endswith("frontend/components/mainview.tsx"):
        missing = unmounted_components(project_root)
        if missing:
            return [
                "WARNING — MainView does not mount these existing "
                f"components: {', '.join(missing)}. Import and render them, "
                "replacing their Sections' Skeleton placeholders — an "
                "unmounted component is invisible to the user."
            ]
    return []
