"""Living UI build-event pipeline — the Live Construction View's data source.

Derives structured "the app is being built" events from actions the agent
already performs (write_file / stream_edit / run_shell / living_ui_scaffold).
The agent is never asked to narrate its progress: events are classified by
matching the action's file path against projects currently in "creating"
status, and entity names (models, routes, components, tests) are extracted
from the written content by regex.

Wired into ActionManager's on_action_start / on_action_end hooks (see
app/agent_base.py). Every path here is fail-silent — a visualization bug
must never break a build.
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
# hook's first line, so the per-action overhead is one set lookup.
_WATCHED_ACTIONS = frozenset(
    {"write_file", "stream_edit", "run_shell", "living_ui_scaffold"}
)

# run_id -> recorded start info, popped on action end. Bounded as a
# belt-and-braces against end hooks that never fire.
_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_MAX = 500

# Per-project ring buffers so a page refresh mid-build can replay the feed.
_BUFFER_MAX = 200
_BUFFERS: Dict[str, Deque[Dict[str, Any]]] = {}

_SNIPPET_MAX_LINES = 18
_SNIPPET_MAX_CHARS = 900

# ── entity extraction ──────────────────────────────────────────────────────

_MODEL_RE = re.compile(r"^class\s+([A-Z]\w*)\s*\(\s*Base\b", re.MULTILINE)
_ROUTE_RE = re.compile(
    r"@router\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)", re.IGNORECASE
)
_COMPONENT_RE = re.compile(
    r"^export\s+(?:default\s+)?(?:function|const|class)\s+([A-Z]\w*)", re.MULTILINE
)
_TEST_RE = re.compile(r"^def\s+(test_\w+)", re.MULTILINE)
_PYTEST_PASSED_RE = re.compile(r"(\d+)\s+passed")
_PYTEST_FAILED_RE = re.compile(r"(\d+)\s+failed")


def _area_for(rel_path: str) -> str:
    p = rel_path.replace("\\", "/").lower()
    if "/tests/" in p or p.startswith("tests/") or "test_" in p.rsplit("/", 1)[-1]:
        return "tests"
    if p.startswith("backend/"):
        return "backend"
    if p.startswith("frontend/") or p == "index.html":
        return "frontend"
    if p.startswith("config/"):
        return "config"
    if p.endswith(".md"):
        return "docs"
    return "other"


def _extract_entities(rel_path: str, content: str) -> Dict[str, List[str]]:
    """Pull human-recognizable names out of written content, by file kind."""
    if not content:
        return {}
    entities: Dict[str, List[str]] = {}
    p = rel_path.replace("\\", "/").lower()
    if p.endswith("models.py"):
        names = _MODEL_RE.findall(content)
        if names:
            entities["models"] = names
    if p.endswith((".py",)) and "routes" in p:
        routes = [f"{m.upper()} {path}" for m, path in _ROUTE_RE.findall(content)]
        if routes:
            entities["routes"] = routes
    if p.endswith((".tsx", ".ts", ".jsx")) and _area_for(rel_path) == "frontend":
        names = _COMPONENT_RE.findall(content)
        if names:
            entities["components"] = names
    if _area_for(rel_path) == "tests" and p.endswith(".py"):
        names = _TEST_RE.findall(content)
        if names:
            entities["tests"] = names
    return entities


def _snippet_of(content: str) -> str:
    if not content:
        return ""
    lines = content.splitlines()[:_SNIPPET_MAX_LINES]
    return "\n".join(lines)[:_SNIPPET_MAX_CHARS]


# ── project matching ───────────────────────────────────────────────────────


def _creating_projects() -> List[Any]:
    manager = get_living_ui_manager()
    if manager is None:
        return []
    return [
        p
        for p in manager.projects.values()
        if getattr(p, "status", None) == "creating" and getattr(p, "path", "")
    ]


def _match_project_for_path(file_path: str) -> Optional[Tuple[Any, str]]:
    """Return (project, relative_path) for a file inside a creating project."""
    if not file_path:
        return None
    try:
        norm = str(Path(file_path).resolve()).lower().replace("\\", "/")
    except Exception:
        norm = str(file_path).lower().replace("\\", "/")
    for project in _creating_projects():
        try:
            root = str(Path(project.path).resolve()).lower().replace("\\", "/")
        except Exception:
            continue
        if norm.startswith(root.rstrip("/") + "/"):
            rel = norm[len(root) :].lstrip("/")
            return project, rel
    return None


def _match_project_for_command(command: str, cwd: str = "") -> Optional[Any]:
    """Match a shell command (or its cwd) against creating projects' paths."""
    haystack = f"{command or ''} {cwd or ''}".lower().replace("\\", "/")
    for project in _creating_projects():
        root = str(project.path).lower().replace("\\", "/").rstrip("/")
        if root and root in haystack:
            return project
    return None


# ── event assembly ─────────────────────────────────────────────────────────


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
    if tests:
        event["tests"] = tests
    return event


def _record(project_id: str, event: Dict[str, Any]) -> None:
    buf = _BUFFERS.get(project_id)
    if buf is None:
        buf = deque(maxlen=_BUFFER_MAX)
        _BUFFERS[project_id] = buf
    buf.append(event)
    # Broadcast is imported lazily so this module has no import-time
    # dependency on the adapter wiring.
    from .broadcast import dispatch_build_event

    dispatch_build_event(project_id, event)


def get_buffered_events(project_id: str) -> List[Dict[str, Any]]:
    """Events recorded so far for a project (for replay on WS connect)."""
    buf = _BUFFERS.get(project_id)
    return list(buf) if buf else []


def clear_buffer(project_id: str) -> None:
    _BUFFERS.pop(project_id, None)


# ── classification per action ──────────────────────────────────────────────


def _names_phrase(kind_singular: str, names: List[str]) -> str:
    """'Model Article' / 'Models Article, Source' / 'Models A, B, C +2'."""
    word = kind_singular if len(names) == 1 else kind_singular + "s"
    shown = ", ".join(names[:3])
    extra = f" +{len(names) - 3}" if len(names) > 3 else ""
    return f"{word} {shown}{extra}"


def _label_for_file(
    action_name: str, rel: str, area: str, entities: Dict[str, List[str]]
) -> str:
    """Entity-first labels: say WHAT came into existence, not which file
    changed. Falls back to the file path only when nothing was extracted."""
    is_edit = action_name != "write_file"
    filename = rel.replace("\\", "/").rsplit("/", 1)[-1]
    if entities.get("components"):
        verb = "updated" if is_edit else "created"
        return f"{_names_phrase('Component', entities['components'])} {verb}"
    if entities.get("models"):
        verb = "updated" if is_edit else "defined"
        return f"{_names_phrase('Model', entities['models'])} {verb}"
    if entities.get("routes"):
        routes = entities["routes"]
        if len(routes) == 1:
            return f"Route {routes[0]} {'updated' if is_edit else 'added'}"
        return f"{len(routes)} routes {'updated' if is_edit else 'added'} ({filename})"
    if area == "tests":
        return f"Fixing tests: {filename}" if is_edit else f"Tests written: {filename}"
    if area == "docs":
        return f"Documentation updated: {filename}"
    return f"{'Updated' if is_edit else 'Wrote'} {rel}"


def _classify_file_action(
    run_id: str, action_name: str, inputs: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    match = _match_project_for_path(str(inputs.get("file_path", "")))
    if not match:
        return None
    project, rel = match
    content = str(
        inputs.get("content") or inputs.get("new_string") or ""
    )
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
    )
    return project.id, event


def _classify_shell_end(
    run_id: str, inputs: Dict[str, Any], outputs: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    command = str(inputs.get("command", ""))
    if "pytest" not in command.lower():
        return None
    project = _match_project_for_command(command, str(inputs.get("cwd", "")))
    if not project:
        return None
    stdout = ""
    if isinstance(outputs, dict):
        stdout = f"{outputs.get('stdout', '')}\n{outputs.get('stderr', '')}"
    passed = _PYTEST_PASSED_RE.search(stdout)
    failed = _PYTEST_FAILED_RE.search(stdout)
    tests = {
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
    }
    if tests["failed"]:
        label = f"Tests: {tests['passed']} passed, {tests['failed']} failed"
    elif tests["passed"]:
        label = f"Tests: {tests['passed']} passed"
    else:
        label = "Ran backend tests"
    return project.id, _build_event(run_id, "test_run", label, area="tests", tests=tests)


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
        "Workspace scaffolded — backend/, frontend/, config/",
        area="config",
    )
    return project_id, event


# ── ActionManager hooks ────────────────────────────────────────────────────


def make_action_hooks():
    """Build (on_action_start, on_action_end) hooks for ActionManager.

    Start records the inputs we need (the end hook doesn't receive them);
    end classifies and emits. Both are cheap no-ops for unwatched actions
    and swallow every exception — observability must never break a build.
    """

    def on_action_start(run_id, action, input_data, parent_id, started_at):
        try:
            name = getattr(action, "name", "") or ""
            if name not in _WATCHED_ACTIONS:
                return
            if len(_PENDING) >= _PENDING_MAX:
                _PENDING.pop(next(iter(_PENDING)), None)
            _PENDING[run_id] = {
                "name": name,
                "inputs": dict(input_data) if isinstance(input_data, dict) else {},
            }
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
            if name in ("write_file", "stream_edit"):
                if not failed:
                    result = _classify_file_action(run_id, name, inputs)
            elif name == "run_shell":
                # A failing pytest run is still a build event (n failed).
                result = _classify_shell_end(run_id, inputs, out)
            elif name == "living_ui_scaffold":
                result = _classify_scaffold_end(run_id, out)

            if result:
                project_id, event = result
                _record(project_id, event)
                # Code changed after a validation pass? That pass no longer
                # describes the project — notify_ready must re-validate.
                # Docs-only edits (LIVING_UI.md) don't invalidate.
                if event.get("area") in ("backend", "frontend", "tests", "config"):
                    manager = get_living_ui_manager()
                    if manager is not None:
                        manager.invalidate_validation(project_id)
        except Exception as exc:
            logger.debug(f"[LIVING_UI:BUILD_EVENTS] classify failed: {exc}")

    return on_action_start, on_action_end
