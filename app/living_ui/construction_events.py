"""Living UI build-event pipeline — the construction dock's data source.

Derives structured "the app is being built" events from actions the agent
already performs (write_file / stream_edit / living_ui_scaffold /
living_ui_notify_ready). The agent is NEVER asked to narrate progress: events
are classified by matching the action's file path against projects currently
being built, and entity names (React components, PocketBase routes/collections)
are extracted from the written content by regex.

READ-ONLY BY CONTRACT. Wired into ActionManager's on_action_start /
on_action_end hooks (see browser_adapter). Every path here is fail-silent and
mutates nothing about the build — a visualization bug must never break a build.
The executor already wraps these hooks in try/except; we wrap again here and do
only fast, synchronous work, handing the broadcast off to the event loop.
"""

import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from ._state import get_living_ui_manager

# Actions we derive build events from. Everything else is ignored at the
# hook's first line, so the per-action overhead is one set lookup. The read/
# search/run/verify actions don't change the app, but the agent performs them
# constantly — surfacing them keeps the feed lively during the long reasoning
# stretches between file writes.
_FILE_ACTIONS = frozenset({"write_file", "stream_edit"})
_READ_ACTIONS = frozenset({"read_file", "list_folder"})
_SEARCH_ACTIONS = frozenset({"find_files", "grep_files"})
_WATCHED_ACTIONS = (
    _FILE_ACTIONS
    | _READ_ACTIONS
    | _SEARCH_ACTIONS
    | frozenset(
        {
            "living_ui_scaffold",
            "living_ui_notify_ready",
            "run_shell",
            "spawn_subagent",
            "browser_probe",
        }
    )
)

# run_id -> recorded start info, popped on action end. Bounded as a
# belt-and-braces guard against end hooks that never fire.
_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_MAX = 500

# Per-project ring buffers so a page refresh mid-build can replay the feed.
_BUFFER_MAX = 200
_BUFFERS: Dict[str, Deque[Dict[str, Any]]] = {}

# Last-seen todo status per project, for emitting start/complete transitions.
_PREV_TODOS: Dict[str, Dict[str, str]] = {}

_SNIPPET_MAX_LINES = 18
_SNIPPET_MAX_CHARS = 900

# ── entity extraction (V2: PocketBase + React kit) ──────────────────────────

# React components: export function/const/class Foo
_COMPONENT_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:function|const|class)\s+([A-Z]\w*)", re.MULTILINE
)
# Custom API routes in pb_hooks: routerAdd("POST", "/api/ops/x", ...)
_PB_ROUTE_RE = re.compile(
    r"routerAdd\(\s*[\"'](\w+)[\"']\s*,\s*[\"']([^\"']+)", re.IGNORECASE
)
# PocketBase collections in a migration: new Collection({ ... name: "posts" ... })
_PB_COLLECTION_RE = re.compile(
    r"new\s+Collection\([^)]*?[\"']?name[\"']?\s*:\s*[\"'](\w+)[\"']",
    re.IGNORECASE | re.DOTALL,
)


def _area_for(rel_path: str) -> str:
    p = rel_path.replace("\\", "/").lower()
    if p.startswith("pb/pb_migrations/") or p.startswith("pb/pb_hooks/"):
        return "backend"
    if p.startswith("frontend/"):
        return "frontend"
    if p == "operations.json" or p.startswith("config"):
        return "config"
    if p.startswith("reference/") or p.endswith(".md"):
        return "docs"
    return "other"


def _extract_entities(rel_path: str, content: str) -> Dict[str, List[str]]:
    """Pull human-recognizable names out of written content, by file kind."""
    if not content:
        return {}
    entities: Dict[str, List[str]] = {}
    p = rel_path.replace("\\", "/").lower()
    if p.startswith("pb/pb_hooks/") and p.endswith(".js"):
        routes = [f"{m.upper()} {path}" for m, path in _PB_ROUTE_RE.findall(content)]
        if routes:
            entities["routes"] = routes
    if p.startswith("pb/pb_migrations/") and p.endswith(".js"):
        collections = list(dict.fromkeys(_PB_COLLECTION_RE.findall(content)))
        if collections:
            entities["models"] = collections
    if p.startswith("frontend/") and p.endswith((".tsx", ".ts", ".jsx")):
        names = _COMPONENT_RE.findall(content)
        if names:
            entities["components"] = names
    return entities


# ── authoritative project snapshot (source of truth for the dock chips) ─────
# The chips count what actually EXISTS in the project on disk, not what a
# single write payload happened to contain — so scaffold-created collections
# and incremental edits are all reflected, and the numbers can't drift.
# Read-only, fail-silent, cheap (a handful of small files).

# Declared components: function/class Foo (any capitalized top-level decl).
_COMPONENT_DECL_RE = re.compile(
    r"(?:export\s+)?(?:default\s+)?(?:function|class)\s+([A-Z]\w*)", re.MULTILINE
)
# Rendered JSX tags: <Card …> / <Button/>. The negative lookbehind drops TS
# generics like useCollection<Task> (the '<' there follows a word char) and
# member access; closing tags never match ('<' followed by '/').
_JSX_TAG_RE = re.compile(r"(?<![\w.])<([A-Z]\w*)(?=[\s/>\n])")

_SNAPSHOT_SKIP_HOOKS = {"_system.pb.js", "_craftbot_bridge.js"}


def _project_snapshot(project_path: Any) -> Optional[Dict[str, int]]:
    """Distinct collections / components / routes present in the project on
    disk right now. Authoritative source for the dock's summary chips."""
    try:
        root = Path(project_path)

        collections: set = set()
        mig = root / "pb" / "pb_migrations"
        if mig.is_dir():
            for f in mig.glob("*.js"):
                collections.update(
                    _PB_COLLECTION_RE.findall(
                        f.read_text(encoding="utf-8", errors="replace")
                    )
                )

        routes: set = set()
        hooks = root / "pb" / "pb_hooks"
        if hooks.is_dir():
            for f in hooks.glob("*.pb.js"):
                if f.name in _SNAPSHOT_SKIP_HOOKS:
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
                for m, path in _PB_ROUTE_RE.findall(text):
                    routes.add(f"{m.upper()} {path}")

        # Components = declared (function/class Foo) ∪ rendered JSX tags
        # (kit + custom) — so a monolithic App that renders Button/Card/Dialog
        # reads as the pieces it's actually assembled from, not just "1".
        components: set = set()
        app_dir = root / "frontend" / "src" / "app"
        if app_dir.is_dir():
            for f in list(app_dir.rglob("*.tsx")) + list(app_dir.rglob("*.jsx")):
                text = f.read_text(encoding="utf-8", errors="replace")
                components.update(_COMPONENT_DECL_RE.findall(text))
                components.update(_JSX_TAG_RE.findall(text))

        return {
            "collections": len(collections),
            "components": len(components),
            "routes": len(routes),
        }
    except Exception:
        return None


def _snippet_of(content: str) -> str:
    if not content:
        return ""
    lines = content.splitlines()[:_SNIPPET_MAX_LINES]
    return "\n".join(lines)[:_SNIPPET_MAX_CHARS]


# ── project matching (path prefix) ──────────────────────────────────────────


def _norm_path(path: Any) -> str:
    """One canonical form for comparison: resolved when possible, lowercase,
    forward slashes, no trailing slash."""
    try:
        text = str(Path(path).resolve())
    except Exception:
        text = str(path)
    return text.lower().replace("\\", "/").rstrip("/")


def _owns(root: Any, norm: str) -> bool:
    r = _norm_path(root)
    return bool(r) and (norm == r or norm.startswith(r + "/"))


def _building_projects() -> List[Any]:
    manager = get_living_ui_manager()
    if manager is None:
        return []
    # "error" is included deliberately: the first failed gate flips status
    # from "creating" to "error", and a status=="creating"-only filter would
    # blind every write-time hook for the rest of the build/fix loop.
    return [
        p
        for p in manager.projects.values()
        if getattr(p, "status", None) in ("creating", "error")
        and getattr(p, "path", "")
    ]


def _match_project_for_path(file_path: str) -> Optional[Tuple[Any, str]]:
    """Return (project, relative_path) for a file inside a building project."""
    if not file_path:
        return None
    norm = _norm_path(file_path)
    for project in _building_projects():
        if _owns(project.path, norm):
            rel = norm[len(_norm_path(project.path)):].lstrip("/")
            return project, rel
    return None


# ── event assembly + buffering ──────────────────────────────────────────────


def _build_event(
    run_id: str,
    kind: str,
    label: str,
    *,
    area: str = "other",
    file: str = "",
    entities: Optional[Dict[str, List[str]]] = None,
    snippet: str = "",
    tests: Optional[Dict[str, int]] = None,
    snapshot: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "id": run_id,
        "ts": int(time.time() * 1000),
        "kind": kind,
        "area": area,
        "label": label,
    }
    if file:
        event["file"] = file.replace("\\", "/")
    if entities:
        event["entities"] = entities
    if snippet:
        event["snippet"] = snippet
    if tests is not None:
        event["tests"] = tests
    if snapshot is not None:
        event["snapshot"] = snapshot
    return event


def _record(project_id: str, event: Dict[str, Any]) -> None:
    buf = _BUFFERS.get(project_id)
    if buf is None:
        buf = deque(maxlen=_BUFFER_MAX)
        _BUFFERS[project_id] = buf
    buf.append(event)
    # Lazy import so this module has no import-time dependency on adapter wiring.
    from .broadcast import dispatch_build_event

    dispatch_build_event(project_id, event)


def get_buffered_events(project_id: str) -> List[Dict[str, Any]]:
    """Events recorded so far for a project (for replay on WS connect)."""
    buf = _BUFFERS.get(project_id)
    return list(buf) if buf else []


def clear_buffer(project_id: str) -> None:
    _BUFFERS.pop(project_id, None)
    _PREV_TODOS.pop(project_id, None)


# ── project resolution ──────────────────────────────────────────────────────


def _building_project_from_session(inputs: Dict[str, Any]) -> Optional[Any]:
    """Resolve the building project from the action's injected _session_id
    (works for path-less actions like search/shell/verify)."""
    session_id = inputs.get("_session_id") if isinstance(inputs, dict) else None
    if not session_id:
        return None
    manager = get_living_ui_manager()
    if manager is None:
        return None
    try:
        project = manager.get_project_by_session_id(session_id)
    except Exception:
        project = None
    if project and getattr(project, "status", None) in ("creating", "error"):
        return project
    return None


# ── labels ──────────────────────────────────────────────────────────────────


def _names_phrase(kind_singular: str, names: List[str]) -> str:
    """'Component Header' / 'Components A, B' / 'Components A, B, C +2'."""
    word = kind_singular if len(names) == 1 else kind_singular + "s"
    shown = ", ".join(names[:3])
    extra = f" +{len(names) - 3}" if len(names) > 3 else ""
    return f"{word} {shown}{extra}"


def _label_for_file(
    action_name: str, rel: str, area: str, entities: Dict[str, List[str]]
) -> str:
    """Entity-first labels: say WHAT came into existence, not which file
    changed. Falls back to the path only when nothing was extracted."""
    is_edit = action_name != "write_file"
    filename = rel.replace("\\", "/").rsplit("/", 1)[-1]
    if entities.get("components"):
        verb = "updated" if is_edit else "created"
        return f"{_names_phrase('Component', entities['components'])} {verb}"
    if entities.get("routes"):
        routes = entities["routes"]
        if len(routes) == 1:
            return f"Route {routes[0]} {'updated' if is_edit else 'added'}"
        return f"{len(routes)} routes {'updated' if is_edit else 'added'} ({filename})"
    if entities.get("models"):
        verb = "updated" if is_edit else "created"
        return f"{_names_phrase('Collection', entities['models'])} {verb}"
    if area == "backend":
        return f"Schema/hook {'updated' if is_edit else 'written'}: {filename}"
    if area == "docs":
        return f"Documentation updated: {filename}"
    if area == "config":
        return f"Config {'updated' if is_edit else 'written'}: {filename}"
    return f"{'Updated' if is_edit else 'Wrote'} {rel}"


# ── classification per action ───────────────────────────────────────────────


def _classify_file_action(
    run_id: str, action_name: str, inputs: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    match = _match_project_for_path(str(inputs.get("file_path", "")))
    if not match:
        return None
    project, rel = match
    content = str(inputs.get("content") or inputs.get("new_string") or "")
    area = _area_for(rel)
    kind = "file_write" if action_name == "write_file" else "file_edit"
    entities = _extract_entities(rel, content)
    label = _label_for_file(action_name, rel, area, entities)
    event = _build_event(
        run_id,
        kind,
        label,
        area=area,
        file=rel,
        entities=entities,
        snippet=_snippet_of(content),
        snapshot=_project_snapshot(project.path),
    )
    return project.id, event


def _snapshot_for_id(project_id: str) -> Optional[Dict[str, int]]:
    manager = get_living_ui_manager()
    project = manager.projects.get(project_id) if manager else None
    return _project_snapshot(project.path) if project else None


def _classify_scaffold_end(
    run_id: str, outputs: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not isinstance(outputs, dict) or outputs.get("status") == "error":
        return None
    project_id = str(outputs.get("project_id", ""))
    if not project_id:
        return None
    event = _build_event(
        run_id,
        "scaffold",
        "Workspace scaffolded — frontend/, pb/, operations.json",
        area="config",
        snapshot=_snapshot_for_id(project_id),
    )
    return project_id, event


def _classify_notify_ready_end(
    run_id: str, inputs: Dict[str, Any], outputs: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """The validation gate + walk-verify capstone: a single test_run row."""
    project_id = str(inputs.get("project_id", ""))
    if not project_id:
        return None
    ok = isinstance(outputs, dict) and outputs.get("status") == "success"
    if ok:
        label = "Validation gate and walk-verify passed"
        tests = {"passed": 1, "failed": 0}
    else:
        label = "Validation failed: fixing and retrying"
        tests = {"passed": 0, "failed": 1}
    event = _build_event(
        run_id,
        "test_run",
        label,
        area="tests",
        tests=tests,
        snapshot=_snapshot_for_id(project_id),
    )
    return project_id, event


# ── activity actions (read/search/run/verify — no app change, but frequent) ──


def _basename(path: Any) -> str:
    return str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _clip(text: Any, n: int = 48) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _classify_activity(
    run_id: str, name: str, inputs: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """A read/search/run/verify action the agent performed. Attributed to the
    building project via its session; produces a lightweight feed row."""
    project = _building_project_from_session(inputs)
    if project is None:
        return None
    if name == "read_file":
        kind, area, label = "read", "other", f"Read {_basename(inputs.get('file_path'))}"
    elif name == "list_folder":
        kind, area, label = "read", "other", f"Explored {_basename(inputs.get('path') or inputs.get('folder') or '.')}/"
    elif name == "find_files":
        kind, area, label = "search", "other", "Searched project files"
    elif name == "grep_files":
        term = _clip(inputs.get("pattern") or inputs.get("query"), 32)
        kind, area, label = "search", "other", (f"Searched for “{term}”" if term else "Searched the code")
    elif name == "run_shell":
        kind, area, label = "run", "other", f"Ran {_clip(inputs.get('command'), 40)}"
    elif name == "browser_probe":
        kind, area, label = "verify", "tests", "Reviewed the app in a browser"
    elif name == "spawn_subagent":
        agent_type = str(inputs.get("agent_type", ""))
        if agent_type == "walk_verify":
            kind, area, label = "verify", "tests", "Reviewed the app in a browser"
        else:
            kind, area, label = "run", "other", "Delegated a sub-task"
    else:
        return None
    return project.id, _build_event(run_id, kind, label, area=area)


# ── todo transitions (start / complete milestones) ──────────────────────────


def record_todo_transitions(project_id: str, todos: List[Dict[str, Any]]) -> None:
    """Emit a feed row when a todo starts or completes. Diffs against the last
    seen statuses; called from the SessionManager todo hook. Fail-silent."""
    try:
        prev = _PREV_TODOS.get(project_id, {})
        current: Dict[str, str] = {}
        for t in todos or []:
            tid = str(t.get("id") or "")
            if not tid:
                continue
            status = str(t.get("status") or "")
            current[tid] = status
            if status == prev.get(tid):
                continue
            content = _clip(t.get("content") or t.get("active_form"), 60)
            if not content:
                continue
            if status == "in_progress":
                _record(
                    project_id,
                    _build_event(f"todo-{tid}-start", "todo", f"▸ {content}", area="other"),
                )
            elif status == "completed":
                _record(
                    project_id,
                    _build_event(f"todo-{tid}-done", "todo", f"✓ {content}", area="other"),
                )
        _PREV_TODOS[project_id] = current
    except Exception as exc:
        logger.debug(f"[LIVING_UI:BUILD_EVENTS] todo transitions failed: {exc}")


# ── ActionManager hooks (single-callback each; assigned in browser_adapter) ──


def make_action_hooks():
    """Build (on_action_start, on_action_end) observers for ActionManager.

    Start records the inputs we need (the end hook doesn't receive them); end
    classifies and emits. Both are cheap no-ops for unwatched actions and
    swallow every exception — observability must never break a build.
    """

    def on_action_start(run_id, action, input_data, parent_id, started_at):
        try:
            name = getattr(action, "name", "") or ""
            if name not in _WATCHED_ACTIONS:
                return
            inputs = dict(input_data) if isinstance(input_data, dict) else {}
            if len(_PENDING) >= _PENDING_MAX:
                _PENDING.pop(next(iter(_PENDING)), None)
            _PENDING[run_id] = {"name": name, "inputs": inputs}
        except Exception:
            pass

    def on_action_end(run_id, action, outputs, status, parent_id, ended_at):
        try:
            pending = _PENDING.pop(run_id, None)
            if not pending:
                return
            out = outputs if isinstance(outputs, dict) else {}
            failed = out.get("status") == "error" or status in ("error", "failed")
            name = pending["name"]
            inputs = pending["inputs"]

            result: Optional[Tuple[str, Dict[str, Any]]] = None
            if name in _FILE_ACTIONS:
                if not failed:
                    result = _classify_file_action(run_id, name, inputs)
            elif name == "living_ui_scaffold":
                result = _classify_scaffold_end(run_id, out)
            elif name == "living_ui_notify_ready":
                result = _classify_notify_ready_end(run_id, inputs, out)
            elif not failed:
                result = _classify_activity(run_id, name, inputs)

            if result:
                project_id, event = result
                _record(project_id, event)
        except Exception as exc:
            logger.debug(f"[LIVING_UI:BUILD_EVENTS] classify failed: {exc}")

    return on_action_start, on_action_end
