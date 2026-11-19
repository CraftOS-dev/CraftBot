"""What a framework build is doing, for CraftBot's construction dock.

Derived from what the builder already does — never asked of it. CraftBot
watches its own agent's actions in a build's session (file writes, reads and
searches, the agent-app verbs it runs) and the person's checkpoint replies,
and turns them into feed rows and a running picture of the build.

The picture moves with the work as it happens, never in one burst at the end:

- Progress walks the creator workflow's stages (setup, questions, the
  requirements, their review, planning, building, the checks, verification,
  launch). Building, the long stretch, follows the task ledger the skill
  ticks as it goes, and every write moves it on a little — with diminishing
  steps, so it never reaches a stage it has not reached. It never goes back.
- The counts are of what the builder has written so far: files, React
  components in them (read from disk right after each write), and ledger
  tasks done. A framework file edited late (the manifest, the operations)
  becomes feed rows naming what was added, not a sudden jump.

Read-only and fail-silent: a visualization must never break a build.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

_FILE_ACTIONS = frozenset({"write_file", "stream_edit"})
_ACTIVITY_ACTIONS = frozenset(
    {
        "read_file",
        "list_folder",
        "find_files",
        "grep_files",
        "run_shell",
        "run_powershell",
    }
)
_WATCHED = (
    _FILE_ACTIONS
    | _ACTIVITY_ACTIONS
    | {"agent_app_command", "agent_app_framework_workflow"}
)

_EVENTS_KEPT = 120
_READ_LIMIT = 512 * 1024

# Stages in workflow order, each with the share of the bar it spans.
STAGES = (
    "setup",
    "questions",
    "requirements",
    "review",
    "planning",
    "building",
    "checking",
    "verifying",
    "launching",
)
_SPAN = {
    "setup": (0, 6),
    "questions": (6, 10),
    "requirements": (10, 18),
    "review": (18, 20),
    "planning": (20, 28),
    "building": (28, 85),
    "checking": (85, 92),
    "verifying": (92, 97),
    "launching": (97, 100),
}

# Not "what was built": the framework's own state, dependencies and docs.
_NOT_BUILT = (".a2app/", "node_modules/", ".git/", "reference/", "dist/", "build/")
_FRAMEWORK_DOCS = {"agent_app.md", "agents.md", "claude.md"}

_DECLARED = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:function\s+([A-Z][A-Za-z0-9]*)|class\s+([A-Z][A-Za-z0-9]*)"
    r"|const\s+([A-Z][a-z][A-Za-z0-9]*)\s*(?::[^=\n]+)?=\s*(?:\(|async\s*\(|(?:React\.)?(?:memo|forwardRef)\b))",
    re.MULTILINE,
)
# Rendered JSX tags (<Card …/>). A '<' after a word character is a type
# argument (useState<Task>), never an element.
_RENDERED = re.compile(r"(?<![\w.])<([A-Z][A-Za-z0-9]*)(?=[\s/>])")
_TASK = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.*\S)", re.MULTILINE)
_HEADING = re.compile(r"^#{2,3}\s+(.+?)\s*$", re.MULTILINE)


def _components(text: str) -> set[str]:
    names = {n for m in _DECLARED.finditer(text) for n in m.groups() if n}
    names.update(_RENDERED.findall(text))
    return names


def _tasks(text: str) -> list[tuple[bool, str]]:
    return [(mark.lower() == "x", body.strip()) for mark, body in _TASK.findall(text)]


def _task_name(body: str) -> str:
    """`T-3 (F-COR-2): Filter by status` → `T-3 Filter by status`."""
    body = re.sub(r"^(T-\d+)\s*\([^)]*\)\s*:?\s*", r"\1 ", body)
    return _clip(body, 70)


def _clip(text, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _area(rel: str) -> str:
    p = rel.lower()
    name = p.rsplit("/", 1)[-1]
    if re.search(r"(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.\w+$", p):
        return "tests"
    if p.endswith((".md", ".txt")):
        return "docs"
    if p.endswith(
        (".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".html")
    ) or re.search(r"(^|/)(frontend|client|web|ui|view|components|pages)/", p):
        return "frontend"
    if name in {"manifest.json", "operations.json", "package.json"} or p.endswith(
        (".json", ".yaml", ".yml", ".toml", ".env")
    ):
        return "config"
    if p.endswith(
        (".rs", ".go", ".py", ".js", ".ts", ".mjs", ".cjs", ".sql")
    ) or re.search(r"(^|/)(server|api|backend|migrations|hooks|db)/", p):
        return "backend"
    return "other"


def _names_phrase(word: str, names: list[str]) -> str:
    shown = ", ".join(names[:3])
    extra = f" +{len(names) - 3}" if len(names) > 3 else ""
    return f"{word}{'' if len(names) == 1 else 's'} {shown}{extra}"


class BuildFeed:
    """The construction dock's source, per build session."""

    def __init__(self, host):
        self.host = host
        self.broadcast = None
        self.states: dict[str, dict] = {}
        self._pending: dict[str, dict] = {}
        self._saving: set[str] = set()

    # ── state ────────────────────────────────────────────────────────────

    def _build(self, session_id):
        """The app directory of the build this session is running, if any."""
        creation = self.host.store.get("creation", session_id) if session_id else None
        if not creation or not creation.get("building") or not creation.get("path"):
            return None
        return Path(creation["path"])

    def _state(self, session_id) -> dict:
        state = self.states.get(session_id)
        if state is None:
            saved = self.host.store.get("build_feed", session_id) or {}
            state = {
                "events": saved.get("events", []),
                "files": saved.get("files", []),
                "components": saved.get("components", {}),
                "tasks": saved.get(
                    "tasks", {"done": 0, "total": 0, "current": "", "checked": []}
                ),
                "modules": saved.get("modules"),
                "operations": saved.get("operations"),
                "stage": saved.get("stage", "setup"),
                "progress": saved.get("progress", 0.0),
                "steps": saved.get("steps", 0),
                "writes": saved.get("writes", 0),
                "since_tick": saved.get("since_tick", 0),
                "fixing": saved.get("fixing", False),
            }
            self.states[session_id] = state
        return state

    def snapshot(self, session_id) -> dict:
        state = self._state(session_id)
        names = set()
        for found in state["components"].values():
            names.update(found)
        tasks = state["tasks"]
        return {
            "files": len(state["files"]),
            "components": len(names),
            "tasksDone": tasks["done"],
            "tasksTotal": tasks["total"],
            "progress": round(state["progress"], 1),
            "stage": state["stage"],
            "task": tasks.get("current", ""),
            "fixing": state["fixing"],
        }

    def replay(self, session_id) -> dict:
        return {
            "events": list(self._state(session_id)["events"]),
            "snapshot": self.snapshot(session_id),
        }

    def _advance(self, state, stage=None, *, step=False):
        """Move to `stage` (never back) and recompute progress, which only grows."""
        if stage and STAGES.index(stage) > STAGES.index(state["stage"]):
            state["stage"] = stage
            state["steps"] = 0
        if step:
            state["steps"] += 1
        lo, hi = _SPAN[state["stage"]]
        if state["stage"] == "building":
            tasks = state["tasks"]
            # The ledger, ticked as the work is done; each write since the last
            # tick is part of the next task. If the ledger is not being ticked,
            # the writes alone still carry the bar, with diminishing steps.
            partial = min(0.85, 1 - 0.85 ** state["since_tick"])
            by_tasks = (
                (tasks["done"] + partial) / tasks["total"] if tasks["total"] else 0
            )
            by_writes = min(0.9, 1 - 0.97 ** state["writes"])
            share = min(0.98, max(by_tasks, by_writes))
        else:
            share = min(0.9, 1 - 0.8 ** state["steps"])
        state["progress"] = max(state["progress"], lo + (hi - lo) * share)

    def _emit(self, session_id, kind, label, *, area="other", file="", tests=None):
        state = self._state(session_id)
        event = {
            "id": f"{int(time.time() * 1000)}-{len(state['events'])}",
            "ts": int(time.time() * 1000),
            "kind": kind,
            "area": area,
            "label": label,
        }
        if file:
            event["file"] = file
        if tests is not None:
            event["tests"] = tests
        event["snapshot"] = self.snapshot(session_id)
        state["events"] = [*state["events"], event][-_EVENTS_KEPT:]
        self._save_soon(session_id)
        if self.broadcast is not None:
            asyncio.ensure_future(
                self.broadcast(
                    {
                        "type": "agent_app_build_event",
                        "data": {
                            "projectId": f"framework-build:{session_id}",
                            "event": event,
                        },
                    }
                )
            )

    def _save_soon(self, session_id):
        """Persist the picture (it survives a restart mid-build), at most once a second."""
        if session_id in self._saving:
            return
        self._saving.add(session_id)

        def save():
            self._saving.discard(session_id)
            try:
                self.host.store.put("build_feed", session_id, self.states[session_id])
            except Exception as error:
                logger.debug(f"[AGENT_APP:BUILD_FEED] save failed: {error}")

        try:
            asyncio.get_running_loop().call_later(1.0, save)
        except RuntimeError:
            save()

    # ── what happened ────────────────────────────────────────────────────

    def on_start(self, run_id, action, input_data, parent_id, started_at):
        try:
            name = getattr(action, "name", "") or ""
            if name in _WATCHED and isinstance(input_data, dict):
                if len(self._pending) > 500:
                    self._pending.pop(next(iter(self._pending)), None)
                self._pending[run_id] = {"name": name, "inputs": dict(input_data)}
        except Exception:
            pass

    def on_end(self, run_id, action, outputs, status, parent_id, ended_at):
        try:
            pending = self._pending.pop(run_id, None)
            if not pending:
                return
            inputs = pending["inputs"]
            session_id = inputs.get("_session_id")
            app = self._build(session_id)
            if app is None:
                return
            out = outputs if isinstance(outputs, dict) else {}
            failed = out.get("status") == "error" or status in ("error", "failed")
            name = pending["name"]
            if name in _FILE_ACTIONS:
                if not failed:
                    self._file(session_id, app, name, inputs)
            elif name == "agent_app_command":
                self._command(session_id, app, inputs.get("args") or [], out, failed)
            elif name == "agent_app_framework_workflow":
                if inputs.get("activity") == "verify":
                    self._verified(session_id, out, failed)
            elif not failed:
                self._activity(session_id, name, inputs)
        except Exception as error:
            logger.debug(f"[AGENT_APP:BUILD_FEED] {error}")

    def person_replied(self, session_id, checkpoint):
        """The person answered in CraftBot's build view."""
        try:
            if self._build(session_id) is None or not isinstance(checkpoint, dict):
                return
            state = self._state(session_id)
            status = checkpoint.get("status")
            if status == "answered":
                self._advance(state, "requirements")
                self._emit(session_id, "todo", "You answered the questions")
            elif status == "changes":
                self._emit(
                    session_id, "todo", "You asked for changes to the requirements"
                )
            elif status == "approved":
                self._advance(state, "planning")
                self._emit(session_id, "todo", "You approved the requirements")
        except Exception as error:
            logger.debug(f"[AGENT_APP:BUILD_FEED] {error}")

    def _file(self, session_id, app, name, inputs):
        path = Path(str(inputs.get("file_path") or ""))
        try:
            rel = path.resolve().relative_to(app.resolve()).as_posix()
        except (ValueError, OSError):
            return
        state = self._state(session_id)
        lower = rel.lower()
        written = str(
            inputs.get("content")
            if name == "write_file"
            else inputs.get("new_string") or ""
        )
        try:
            text = (
                path.read_text(encoding="utf-8", errors="replace")
                if path.stat().st_size <= _READ_LIMIT
                else written
            )
        except OSError:
            text = written
        verb = "updated" if name == "stream_edit" else "created"

        if lower == "reference/requirements.md":
            heading = (_HEADING.findall(written) or [""])[0]
            self._advance(state, "requirements", step=True)
            self._emit(
                session_id,
                "file_edit",
                f"Requirements: {_clip(heading, 50)}"
                if heading
                else "Requirements updated",
                area="docs",
                file=rel,
            )
            return
        if lower == "reference/tasks.md":
            self._ledger(session_id, state, text)
            return
        declared = False
        if lower == "manifest.json":
            declared = self._declared(
                session_id, state, "modules", "Module", _json_names(text, "modules")
            )
        elif lower == "operations.json":
            declared = self._declared(
                session_id,
                state,
                "operations",
                "Operation",
                _json_names(text, "operations"),
            )
        if lower.startswith(_NOT_BUILT) or lower in _FRAMEWORK_DOCS:
            return

        if rel not in state["files"]:
            state["files"] = [*state["files"], rel]
        found = sorted(_components(text)) if lower.endswith((".tsx", ".jsx")) else []
        known = {name for names in state["components"].values() for name in names}
        state["components"] = {**state["components"], rel: found}
        state["writes"] += 1
        state["since_tick"] += 1
        self._advance(state, step=True)
        if declared:
            return  # its row names what was declared
        added = [
            n for n in found if n not in known
        ]  # new to the build, not just to this file
        if added:
            label = f"{_names_phrase('Component', added)} {verb}"
        else:
            label = f"{'Updated' if name == 'stream_edit' else 'Wrote'} {rel}"
        self._emit(
            session_id,
            "file_edit" if name == "stream_edit" else "file_write",
            label,
            area=_area(rel),
            file=rel,
        )

    def _ledger(self, session_id, state, text):
        tasks = _tasks(text)
        done = [body for checked, body in tasks if checked]
        ids = [_task_name(body).split(" ", 1)[0] for body in done]
        before = state["tasks"]
        newly = [
            body for body, tid in zip(done, ids) if tid not in before.get("checked", [])
        ]
        upcoming = next((body for checked, body in tasks if not checked), "")
        state["tasks"] = {
            "done": len(done),
            "total": len(tasks),
            "current": _task_name(upcoming) if upcoming else "",
            "checked": ids,
        }
        if newly:
            state["since_tick"] = 0
        if tasks:
            self._advance(state, "building")
        if not before.get("total") and tasks:
            self._emit(
                session_id,
                "todo",
                f"Planned {len(tasks)} task{'s' if len(tasks) != 1 else ''}",
                area="docs",
                file="reference/tasks.md",
            )
        for body in newly:
            self._emit(session_id, "todo", f"✓ {_task_name(body)}", area="other")
        if not newly and before.get("total"):
            self._advance(state, step=True)

    def _declared(self, session_id, state, key, word, names) -> bool:
        """A row naming what a framework file newly declares; False when it declares nothing new."""
        if names is None:
            return False
        known = state.get(key)
        state[key] = names
        added = [n for n in names if n not in (known or [])]
        if known is None or not added:
            return False
        self._emit(
            session_id,
            "file_edit",
            f"{_names_phrase(word, added)} added",
            area="config",
        )
        return True

    def _command(self, session_id, app, args, out, failed):
        state = self._state(session_id)
        verb = args[1] if len(args) > 1 else (args[0] if args else "")
        doc = out.get("data") if isinstance(out.get("data"), dict) else {}
        if verb == "scaffold" and not failed:
            blueprint = (
                args[args.index("--blueprint") + 1]
                if "--blueprint" in args and args.index("--blueprint") + 1 < len(args)
                else "its blueprint"
            )
            # What the blueprint declares is the baseline; what the builder adds shows.
            for key, file in (
                ("modules", "manifest.json"),
                ("operations", "operations.json"),
            ):
                try:
                    state[key] = (
                        _json_names((app / file).read_text(encoding="utf-8"), key) or []
                    )
                except OSError:
                    state[key] = []
            self._advance(state, step=True)
            self._emit(
                session_id, "scaffold", f"Project created on {blueprint}", area="config"
            )
        elif verb == "checkpoint" and len(args) > 2 and not failed:
            cp = (
                doc.get("checkpoint") if isinstance(doc.get("checkpoint"), dict) else {}
            )
            if args[2] == "ask":
                count = len(cp.get("questions") or [])
                self._advance(state, "questions")
                self._emit(
                    session_id,
                    "todo",
                    f"Asked you {count} question{'s' if count != 1 else ''}",
                )
            elif args[2] == "review":
                self._advance(state, "review")
                self._emit(
                    session_id,
                    "todo",
                    "Requirements ready for your review",
                    area="docs",
                )
            elif cp.get("status") in {"answered", "changes", "approved"}:
                self.person_replied(session_id, cp)
        elif verb == "validate":
            ok = not failed and out.get("exit_code", 0) == 0
            self._advance(state, "checking", step=True)
            state["fixing"] = not ok
            self._emit(
                session_id,
                "test_run",
                "Validation gate passed"
                if ok
                else "Validation gate found problems: fixing",
                area="tests",
                tests={"passed": 1, "failed": 0} if ok else {"passed": 0, "failed": 1},
            )
        elif verb == "dev" and not failed:
            self._advance(state, "checking", step=True)
            self._emit(session_id, "run", "Started the dev instance")
        elif verb == "commit" and not failed:
            message = (
                args[args.index("--message") + 1]
                if "--message" in args and args.index("--message") + 1 < len(args)
                else ""
            )
            self._advance(state, step=True)
            self._emit(
                session_id,
                "run",
                f"Committed: {_clip(message, 60)}"
                if message
                else "Committed the changes",
            )
        elif verb in {"promote", "serve"} and not failed:
            self._advance(state, "launching", step=True)
            self._emit(
                session_id,
                "run",
                "Promoted to live" if verb == "promote" else "App launched",
            )

    def _verified(self, session_id, out, failed):
        state = self._state(session_id)
        verification = (
            out.get("verification") if isinstance(out.get("verification"), dict) else {}
        )
        verdict = verification.get("verdict") or ("error" if failed else "")
        self._advance(state, "verifying", step=True)
        passed = verdict == "pass"
        state["fixing"] = verdict == "defects"
        label = {
            "pass": "Independent verification passed",
            "defects": "Verification found defects: fixing",
        }.get(verdict, "Verification could not finish")
        self._emit(
            session_id,
            "test_run",
            label,
            area="tests",
            tests={"passed": 1, "failed": 0} if passed else {"passed": 0, "failed": 1},
        )

    def _activity(self, session_id, name, inputs):
        def base(p):
            return str(p or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

        if name == "read_file":
            kind, label = "read", f"Read {base(inputs.get('file_path'))}"
        elif name == "list_folder":
            kind, label = (
                "read",
                f"Explored {base(inputs.get('path') or inputs.get('folder') or '.')}/",
            )
        elif name == "find_files":
            kind, label = "search", "Searched the project's files"
        elif name == "grep_files":
            term = _clip(inputs.get("pattern") or inputs.get("query"), 32)
            kind, label = (
                "search",
                f"Searched for “{term}”" if term else "Searched the code",
            )
        else:
            kind, label = (
                "run",
                f"Ran {_clip(inputs.get('command') or inputs.get('script'), 40)}",
            )
        self._advance(self._state(session_id), step=True)
        self._emit(session_id, kind, label)


def _json_names(text: str, key: str):
    """The names a framework file declares under `key`, or None when unreadable."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    items = doc.get(key) if isinstance(doc, dict) else None
    if not isinstance(items, list):
        return None
    return [str(i.get("name")) for i in items if isinstance(i, dict) and i.get("name")]
