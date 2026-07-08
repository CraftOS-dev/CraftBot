"""
livingui — the Living UI command line.

The agent operates Living UIs the way a human operates a well-made CLI:
`--help` at every level to discover, then navigate. Help is generated live
from the registry, the project's SQLite database, its operations manifest,
and its models — it never goes stale and it works when the app is stopped.

Hierarchy (each level has its own --help; the root stays lean on purpose):

    livingui --help                     top-level commands
    livingui ls                         list projects
    livingui <project> --help           capability card for one project
    livingui <project> <command> --help detailed usage for one command
    livingui <project> run <op> --help  params for one declared operation

Security model: this CLI reads the project's SQLite directly (filesystem =
same-machine only) and talks to app backends over loopback. Lifecycle
commands go through CraftBot's loopback-only control endpoint, authorized by
a token file only the local user can read. Nothing here is reachable from
the network.

Errors are prescriptive: whenever the CLI can compute the fix, the error
ends with an exact `Try: livingui ...` command.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# Bootstrap: this file runs as a standalone script via the generated
# launcher, so put the repo root on sys.path before importing app modules.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.living_ui import data_plane, migration, operations  # noqa: E402
from app.living_ui import triggers as trigger_plane  # noqa: E402

PROG = "livingui"


# ---------------------------------------------------------------------------
# Environment / registry
# ---------------------------------------------------------------------------


def workspace_root() -> Path:
    env = os.environ.get("CRAFTBOT_WORKSPACE")
    if env:
        return Path(env)
    return _REPO_ROOT / "agent_file_system" / "workspace"


def load_registry() -> list:
    registry = workspace_root() / "living_ui_projects.json"
    if not registry.exists():
        fail(f"Project registry not found: {registry}")
    try:
        return json.loads(registry.read_text(encoding="utf-8")).get("projects", [])
    except Exception as e:
        fail(f"Could not read registry: {e}")


class Project:
    def __init__(self, record: dict):
        self.id = record.get("id", "")
        self.name = record.get("name", "")
        self.description = record.get("description", "")
        self.path = record.get("path", "")
        self.status = record.get("status", "unknown")
        self.port = record.get("port")
        self.backend_port = record.get("backendPort")
        self.url = record.get("url")
        self.backend_url = record.get("backendUrl") or (
            f"http://localhost:{self.backend_port}" if self.backend_port else None
        )
        self.project_type = record.get("projectType", "native")
        self.app_runtime = record.get("appRuntime")

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")


def resolve_project(token: str) -> Project:
    """Resolve id, name, slug, or folder name — forgivingly."""
    projects = [Project(r) for r in load_registry()]
    token_lower = token.lower()
    normalized = re.sub(r"[^a-z0-9]+", "", token_lower)

    for p in projects:  # exact id
        if p.id == token:
            return p
    for p in projects:  # exact name / slug / folder name
        folder = Path(p.path).name.lower()
        if token_lower in (p.name.lower(), p.slug, folder):
            return p
    # normalized substring (habit-tracker, habittracker, habit_tracker_e1e957e1)
    matches = [
        p
        for p in projects
        if normalized
        and (
            normalized in re.sub(r"[^a-z0-9]+", "", p.name.lower())
            or normalized in re.sub(r"[^a-z0-9]+", "", Path(p.path).name.lower())
        )
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        options = ", ".join(f"{p.slug} ({p.id})" for p in matches)
        fail(f"'{token}' is ambiguous: {options}\nTry: {PROG} <id>")
    known = "\n  ".join(f"{p.slug:<28} {p.id}  {p.status}" for p in projects)
    fail(f"No project matches '{token}'. Projects:\n  {known}")


def fail(message: str, hint: str = "") -> None:
    print(f"error: {message}")
    if hint:
        print(f"Try: {hint}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Control endpoint client (loopback, token-file authorized)
# ---------------------------------------------------------------------------


def _control_token() -> str:
    token_file = workspace_root() / "living_ui" / ".control_token"
    try:
        return token_file.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def control_call(command: str, project_id: str, payload=None, timeout=600):
    """POST to CraftBot's loopback control endpoint. Returns (ok, response)."""
    port = os.environ.get("BROWSER_PORT", "7926")
    body = json.dumps(
        {
            "token": _control_token(),
            "command": command,
            "projectId": project_id,
            "payload": payload or {},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/living-ui/control",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode("utf-8"))
        except Exception:
            return False, {"error": f"HTTP {e.code}"}
    except Exception as e:
        return False, {"error": f"CraftBot not reachable ({e})"}


def notify_data_changed(project_id: str) -> None:
    """Best-effort iframe refresh after a mutation."""
    try:
        control_call("data_changed", project_id, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Parsers: --where / --set values
# ---------------------------------------------------------------------------

_WHERE_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(<=|>=|!=|=|<|>|\s+not\s+like\s+|\s+like\s+|\s+not\s+in\s+|\s+in\s+"
    r"|\s+is\s+not\s+null\s*$|\s+is\s+null\s*$)"
    r"\s*(.*)$",
    re.IGNORECASE,
)


def _type_value(raw: str):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def parse_where(clauses) -> dict:
    """--where "id<=10" --where "name like %press%" --where "done is null" """
    where = {}
    for clause in clauses or []:
        m = _WHERE_RE.match(clause)
        if not m:
            fail(
                f"Cannot parse --where '{clause}'. "
                "Format: <column><op><value> with op one of "
                "= != < <= > >= like, 'in a,b,c', 'is null', 'is not null'."
            )
        column, op, rest = m.group(1), m.group(2).strip().lower(), m.group(3)
        if op in ("is null", "is not null"):
            where[column] = {"op": op}
        elif op in ("in", "not in"):
            values = [_type_value(v) for v in rest.split(",") if v.strip()]
            where[column] = {"op": op, "value": values}
        elif op == "=":
            where[column] = _type_value(rest)
        else:
            where[column] = {"op": op, "value": _type_value(rest)}
    return where


def parse_set(assignments) -> dict:
    """--set rpe=7.5 --set note='easy day' --set extra:={"a":1} (:= raw JSON)"""
    values = {}
    for assignment in assignments or []:
        if ":=" in assignment:
            key, raw = assignment.split(":=", 1)
            try:
                values[key.strip()] = json.loads(raw)
            except Exception as e:
                fail(f"--set {key.strip()}:= needs valid JSON ({e})")
        elif "=" in assignment:
            key, raw = assignment.split("=", 1)
            values[key.strip()] = _type_value(raw)
        else:
            fail(f"Cannot parse --set '{assignment}'. Use key=value or key:=json.")
    return values


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def print_rows(rows, total=None, as_json=False):
    if as_json:
        print(json.dumps(rows, indent=1, default=str))
        return
    if not rows:
        print("(no rows)")
        return
    columns = list(rows[0].keys())
    widths = {
        c: min(40, max(len(c), *(len(str(r.get(c, ""))) for r in rows)))
        for c in columns
    }
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for r in rows:
        print(
            "  ".join(
                str(r.get(c, ""))[: widths[c]].ljust(widths[c]) for c in columns
            )
        )
    if total is not None and total > len(rows):
        print(f"({len(rows)} of {total} — use --limit/--offset or --where)")


def _drift_warning(project: Project, db_schema) -> str:
    try:
        drift = migration.detect_drift(project.path, db_schema)
    except Exception:
        return ""
    problems = []
    if drift["missing_columns"]:
        problems.append(f"columns missing from DB: {', '.join(drift['missing_columns'][:6])}")
    if drift["missing_tables"]:
        problems.append(f"tables missing from DB: {', '.join(drift['missing_tables'][:4])}")
    if not problems:
        return ""
    return (
        f"WARNING schema drift — {'; '.join(problems)}\n"
        f"  Fix: {PROG} {project.slug} migrate   (then: {PROG} {project.slug} restart)"
    )


# ---------------------------------------------------------------------------
# Help levels
# ---------------------------------------------------------------------------

ROOT_HELP = f"""{PROG} — operate Living UI apps from the command line

usage: {PROG} <command|project> ...

  ls                          list all projects
  <project> --help            capability card: tables, operations, commands
  <project> <command> --help  detailed usage for one command

<project> = id, name, or folder (e.g. e1e957e1, habit-tracker).
Start with: {PROG} ls
"""

PROJECT_COMMANDS_HELP = """\
COMMANDS (each supports --help)
  status | schema [table] | logs [--tail N]     observe
  select|count|insert|update|delete|sql          data (direct DB, works when stopped)
  api <METHOD> <path>                            call an HTTP endpoint
  run <op>                                       fire a declared operation
  triggers | trigger <name> [--set k=v]          app→agent triggers (config/triggers.json)
  ops-sync [--write] | ops-check                 generate/validate operations.json
  migrate                                        apply additive schema migration
  start | stop | restart                         lifecycle (via CraftBot)
  jobs | job <id> [--cancel]                     background operations
  snapshot | screenshot [--out F] | ui --data J  see / drive the live UI"""


def cmd_ls(_args):
    projects = [Project(r) for r in load_registry()]
    if not projects:
        print("(no projects)")
        return 0
    print(f"{'PROJECT':<28} {'ID':<10} {'STATUS':<9} {'TYPE':<9} PORTS")
    for p in projects:
        ports = f"{p.port or '-'}/{p.backend_port or '-'}"
        print(f"{p.slug:<28} {p.id:<10} {p.status:<9} {p.project_type:<9} {ports}")
    print(f"\nNext: {PROG} <project> --help")
    return 0


def project_help(project: Project) -> int:
    lines = [
        f"{project.name} ({project.id}) — {project.status}"
        + (f" · ui :{project.port}" if project.port else "")
        + (f" · api :{project.backend_port}" if project.backend_port else ""),
    ]
    if project.description:
        lines.append(project.description[:120])
    lines.append("")

    db_schema = {}
    db_path = _db_path_or_none(project)
    if db_path:
        try:
            db_schema = data_plane.introspect_schema(db_path)
        except Exception as e:
            lines.append(f"(schema unavailable: {e})")
    if db_schema:
        lines.append("TABLES")
        shown = list(db_schema.items())[:12]
        for table, info in shown:
            lines.append(f"  {table:<24} {info['rowCount']} rows")
        if len(db_schema) > 12:
            lines.append(f"  ... +{len(db_schema) - 12} more — {PROG} {project.slug} schema")
    elif project.project_type != "native":
        lines.append("TABLES: none (external app — use `api` and `run`)")
    else:
        lines.append("TABLES: no database yet (launch once to create it)")

    try:
        ops = operations.load_operations(project)
    except operations.OperationError as e:
        ops = {}
        lines.append(f"(operations manifest broken: {e})")
    lines.append("")
    if ops:
        lines.append(f"OPERATIONS  ({PROG} {project.slug} run <op> --help)")
        for name, op_def in list(ops.items())[:15]:
            description = (op_def.get("description") or "")[:64]
            lines.append(f"  {name:<24} {description}")
        if len(ops) > 15:
            lines.append(f"  ... +{len(ops) - 15} more — {PROG} {project.slug} run")
    else:
        lines.append(
            "OPERATIONS: none declared (config/operations.json missing or empty)"
        )

    try:
        declared_triggers = trigger_plane.load_triggers(project)
    except trigger_plane.TriggerError as e:
        declared_triggers = {}
        lines.append(f"(triggers manifest broken: {e})")
    if declared_triggers:
        lines.append("")
        lines.append(f"TRIGGERS — app→agent  ({PROG} {project.slug} trigger <name>)")
        for name, trig_def in list(declared_triggers.items())[:10]:
            description = (trig_def.get("description") or "")[:64]
            lines.append(f"  {name:<24} {description}")

    lines.append("")
    lines.append(PROJECT_COMMANDS_HELP)

    warning = _drift_warning(project, db_schema) if db_schema else ""
    if warning:
        lines.append("")
        lines.append(warning)
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# Data commands
# ---------------------------------------------------------------------------


def _db_path_or_none(project: Project):
    return data_plane.resolve_db_path(project)


def _require_db(project: Project) -> Path:
    if project.project_type != "native":
        fail(
            f"'{project.slug}' is an external app with no managed database.",
            f"{PROG} {project.slug} run   (its declared operations)",
        )
    db_path = _db_path_or_none(project)
    if not db_path:
        fail(
            "No database yet (backend/living_ui.db missing).",
            f"{PROG} {project.slug} start",
        )
    return db_path


def _prescriptive(project: Project, error: Exception) -> None:
    """Turn a DataPlaneError into an error that names the next command."""
    message = str(error)
    m = re.search(r"Unknown column\(s\) \[([^\]]*)\] on table '(\w+)'", message)
    hint = ""
    if m:
        db_path = _db_path_or_none(project)
        db_schema = data_plane.introspect_schema(db_path) if db_path else {}
        drift = migration.detect_drift(project.path, db_schema)
        wanted = {c.strip().strip("'\"") for c in m.group(1).split(",")}
        drifted = {c.split(".")[1] for c in drift["missing_columns"] if "." in c}
        if wanted & drifted:
            hint = (
                f"{PROG} {project.slug} migrate   "
                "(these columns are declared in models.py but missing from the DB; "
                f"then: {PROG} {project.slug} restart)"
            )
    if "not found. Available tables" in message:
        db_path = _db_path_or_none(project)
        db_schema = data_plane.introspect_schema(db_path) if db_path else {}
        drift = migration.detect_drift(project.path, db_schema)
        if drift["missing_tables"]:
            hint = (
                f"{PROG} {project.slug} migrate   "
                f"(models.py declares {', '.join(drift['missing_tables'])} "
                "but the DB doesn't have them yet)"
            )
    fail(message, hint)


def cmd_select(project, args):
    db_path = _require_db(project)
    try:
        result = data_plane.select_rows(
            db_path,
            args.table,
            where=parse_where(args.where),
            columns=args.columns.split(",") if args.columns else None,
            order_by=args.order.split(",") if args.order else None,
            limit=args.limit,
            offset=args.offset,
        )
    except data_plane.DataPlaneError as e:
        _prescriptive(project, e)
    print_rows(result["rows"], total=result["total_matching"], as_json=args.json)
    return 0


def cmd_count(project, args):
    db_path = _require_db(project)
    try:
        count = data_plane.count_rows(db_path, args.table, where=parse_where(args.where))
    except data_plane.DataPlaneError as e:
        _prescriptive(project, e)
    print(count)
    return 0


def _load_rows(args) -> list:
    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    elif args.stdin:
        raw = sys.stdin.read()
    elif args.set:
        return [parse_set(args.set)]
    else:
        fail(
            "insert needs rows: --file rows.json (a JSON array), --stdin, "
            "or one row via --set k=v ..."
        )
    try:
        rows = json.loads(raw)
    except Exception as e:
        fail(f"rows are not valid JSON ({e})")
    if isinstance(rows, dict):
        rows = [rows]
    return rows


def cmd_insert(project, args):
    db_path = _require_db(project)
    rows = _load_rows(args)
    try:
        result = data_plane.insert_rows(db_path, args.table, rows)
    except data_plane.DataPlaneError as e:
        _prescriptive(project, e)
    note = (
        f" (autofilled: {', '.join(result['autofilled_columns'])})"
        if result.get("autofilled_columns")
        else ""
    )
    print(f"inserted {result['inserted']} rows into {args.table}{note}")
    notify_data_changed(project.id)
    return 0


def cmd_update(project, args):
    db_path = _require_db(project)
    values = parse_set(args.set)
    if not values:
        fail("update needs --set k=v (repeatable)")
    try:
        result = data_plane.update_rows(
            db_path,
            args.table,
            values=values,
            where=parse_where(args.where),
            confirm_full_table=args.all,
        )
    except data_plane.DataPlaneError as e:
        if "Refusing" in str(e):
            fail(str(e), f"{PROG} {project.slug} update {args.table} --set ... --where <filter>  (or add --all)")
        _prescriptive(project, e)
    print(f"updated {result['updated']} rows (backup: {result.get('backup') or 'n/a'})")
    notify_data_changed(project.id)
    return 0


def cmd_delete(project, args):
    db_path = _require_db(project)
    try:
        result = data_plane.delete_rows(
            db_path,
            args.table,
            where=parse_where(args.where),
            confirm_full_table=args.all,
        )
    except data_plane.DataPlaneError as e:
        if "Refusing" in str(e):
            fail(str(e), f"{PROG} {project.slug} delete {args.table} --where <filter>  (or add --all)")
        _prescriptive(project, e)
    print(f"deleted {result['deleted']} rows (backup: {result.get('backup') or 'n/a'})")
    notify_data_changed(project.id)
    return 0


def cmd_sql(project, args):
    db_path = _require_db(project)
    try:
        result = data_plane.run_sql(db_path, args.query, write=args.write)
    except data_plane.DataPlaneError as e:
        if "mode='write'" in str(e):
            fail(str(e), f'{PROG} {project.slug} sql "..." --write')
        _prescriptive(project, e)
    if args.write:
        print(f"affected {result['affected']} rows (backup: {result.get('backup') or 'n/a'})")
        notify_data_changed(project.id)
    else:
        print_rows(result["rows"], as_json=args.json)
        if result.get("note"):
            print(f"({result['note']})")
    return 0


# ---------------------------------------------------------------------------
# HTTP / operations / lifecycle
# ---------------------------------------------------------------------------


def _http(project: Project, method: str, path: str, body=None, query=None, timeout=30):
    base = project.backend_url
    if not base:
        fail(
            f"'{project.slug}' has no backend URL (status: {project.status}).",
            f"{PROG} {project.slug} start",
        )
    url = base.rstrip("/") + path
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        fail(
            f"{method} {url} failed: {e}",
            f"{PROG} {project.slug} status   (is the app running?)",
        )


def cmd_api(project, args):
    query = dict(q.split("=", 1) for q in (args.query or []) if "=" in q)
    body = None
    if args.data:
        try:
            body = json.loads(args.data)
        except Exception as e:
            fail(f"--data is not valid JSON ({e})")
    elif args.file:
        body = json.loads(Path(args.file).read_text(encoding="utf-8"))
    status, text = _http(
        project, args.method.upper(), args.path, body=body, query=query or None
    )
    print(f"HTTP {status}")
    print(text[:4000])
    if args.method.upper() in ("POST", "PUT", "PATCH", "DELETE") and status < 400:
        notify_data_changed(project.id)
    return 0 if status < 400 else 1


def _print_op_help(project: Project, name: str, op_def: dict):
    print(f"{name} — {op_def.get('description', '')}")
    executor = op_def.get("executor") or {}
    print(f"executor: {executor.get('type', 'http')} · mode: {op_def.get('mode', 'sync')}")
    params = op_def.get("params") or {}
    if not params:
        print("params: none")
    else:
        print("params:")
        for param, spec in params.items():
            print(f"  --{param:<20} {json.dumps(spec) if not isinstance(spec, str) else spec}")
    example = " ".join(f"--{p} <value>" for p in list(params)[:3])
    print(f"usage: {PROG} {project.slug} run {name} {example}".rstrip())
    print(
        "       For values with spaces/punctuation, use a JSON file instead of "
        "inline quotes:\n"
        f"       {PROG} {project.slug} run {name} --params-file params.json"
    )


def cmd_run(project, argv):
    try:
        ops = operations.load_operations(project)
    except operations.OperationError as e:
        fail(str(e))
    if not argv or argv[0] in ("-h", "--help"):
        if not ops:
            print(
                "No operations declared. The app's verbs live in "
                "config/operations.json — see the living-ui skills."
            )
            return 0
        print(f"OPERATIONS for {project.slug}  (run <op> --help for params)")
        for name, op_def in ops.items():
            print(f"  {name:<24} {(op_def.get('description') or '')[:70]}")
        return 0

    op_name = argv[0]
    if op_name not in ops:
        available = ", ".join(sorted(ops)) or "(none)"
        fail(
            f"No operation '{op_name}'. Declared: {available}",
            f"{PROG} {project.slug} run",
        )
    op_def = ops[op_name]
    rest = argv[1:]
    if rest and rest[0] in ("-h", "--help"):
        _print_op_help(project, op_name, op_def)
        return 0

    # Parse params: --params-file <json> (the quote-proof form) and/or
    # --param value pairs (also accepts --param=value) which override it.
    params = {}
    i = 0
    while i < len(rest):
        arg = rest[i]
        if not arg.startswith("--"):
            # A bare token right after valued params is the signature of the
            # Windows shell stripping quotes around a value with spaces.
            fail(
                f"Unexpected argument '{arg}'. If a param value contains "
                f"spaces or punctuation, the shell may have stripped your "
                f"quotes — put the params in a JSON file instead:\n"
                f'  1. write params.json, e.g. {{"title": "My card title", "list_id": 3}}\n'
                f"  2. {PROG} {project.slug} run {op_name} --params-file params.json",
                f"{PROG} {project.slug} run {op_name} --help",
            )
        key = arg[2:]
        if key == "params-file":
            if i + 1 >= len(rest):
                fail("--params-file needs a path to a JSON file.")
            params_path = Path(rest[i + 1])
            if not params_path.exists():
                fail(f"params file not found: {params_path}")
            try:
                loaded = json.loads(params_path.read_text(encoding="utf-8"))
            except Exception as e:
                fail(f"params file is not valid JSON ({e})")
            if not isinstance(loaded, dict):
                fail("params file must contain a JSON object of param -> value")
            params.update(loaded)
            i += 2
        elif "=" in key:
            key, raw = key.split("=", 1)
            params[key] = _type_value(raw)
            i += 1
        else:
            if i + 1 >= len(rest):
                fail(f"--{key} needs a value.", f"{PROG} {project.slug} run {op_name} --help")
            params[key] = _type_value(rest[i + 1])
            i += 2

    try:
        filled = operations.validate_and_fill_params(op_name, op_def, params)
    except operations.OperationError as e:
        fail(str(e), f"{PROG} {project.slug} run {op_name} --help")

    executor = op_def.get("executor") or {}
    executor_type = str(executor.get("type", "http")).lower()
    mode = str(op_def.get("mode", "sync")).lower()

    if executor_type == "http":
        method = str(executor.get("method", "POST")).upper()
        path, remaining = operations.render_http_path(
            executor.get("path", "/api/action"), filled
        )
        static_body = executor.get("body") if isinstance(executor.get("body"), dict) else {}
        if method in ("GET", "DELETE"):
            status, text = _http(project, method, path, query={**static_body, **remaining} or None)
        else:
            status, text = _http(project, method, path, body={**static_body, **remaining})
        print(f"HTTP {status}")
        print(text[:4000])
        if status < 400 and method != "GET":
            notify_data_changed(project.id)
        return 0 if status < 400 else 1

    if executor_type == "sql":
        db_path = _require_db(project)
        write = str(executor.get("mode", "read")).lower() == "write"
        try:
            result = data_plane.run_sql(db_path, executor.get("sql", ""), filled, write=write)
        except data_plane.DataPlaneError as e:
            _prescriptive(project, e)
        if write:
            print(f"affected {result['affected']} rows")
            notify_data_changed(project.id)
        else:
            print_rows(result["rows"])
        return 0

    if executor_type == "shell":
        try:
            command = operations.render_shell_command(executor.get("cmd", ""), filled)
            cwd = operations.resolve_op_cwd(Path(project.path), executor)
        except operations.OperationError as e:
            fail(str(e))
        extra_env = executor.get("env") if isinstance(executor.get("env"), dict) else None
        if mode == "job":
            return _spawn_job(project, op_name, command, cwd, extra_env)
        timeout = float(executor.get("timeout", 300))
        try:
            result = operations.run_shell_sync(command, cwd, timeout=timeout, extra_env=extra_env)
        except operations.OperationError as e:
            fail(str(e))
        if result["stdout"]:
            print(result["stdout"])
        if result["stderr"]:
            print(result["stderr"])
        if result["return_code"] == 0:
            notify_data_changed(project.id)
            return 0
        print(f"(exit code {result['return_code']})")
        return 1

    fail(f"Op '{op_name}' has unsupported executor type '{executor_type}'.")


# ---------------------------------------------------------------------------
# Jobs (file-backed — survive across CLI invocations)
# ---------------------------------------------------------------------------


def _jobs_dir(project: Project) -> Path:
    d = Path(project.path) / "logs" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return str(pid) in out.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _spawn_job(project, op_name, command, cwd, extra_env) -> int:
    job_id = uuid.uuid4().hex[:8]
    safe_op = re.sub(r"[^A-Za-z0-9_.-]", "_", op_name)
    log_file = _jobs_dir(project) / f"{safe_op}_{job_id}.log"
    env = os.environ.copy()
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    handle = open(log_file, "w", encoding="utf-8")
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    kwargs = dict(
        shell=True,
        cwd=str(cwd),
        env=env,
        stdout=handle,
        stderr=handle,
        stdin=subprocess.DEVNULL,
    )
    if os.name == "nt":
        kwargs["creationflags"] = creation
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    handle.close()  # child holds its own handle
    job_record = {
        "job_id": job_id,
        "op": op_name,
        "pid": process.pid,
        "command": command,
        "log": str(log_file),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (_jobs_dir(project) / f"{job_id}.json").write_text(
        json.dumps(job_record, indent=1), encoding="utf-8"
    )
    print(f"job {job_id} started (pid {process.pid})")
    print(f"Next: {PROG} {project.slug} job {job_id}")
    return 0


def cmd_jobs(project, _args):
    records = sorted(_jobs_dir(project).glob("*.json"))
    if not records:
        print("(no jobs)")
        return 0
    for record_file in records[-15:]:
        record = json.loads(record_file.read_text(encoding="utf-8"))
        alive = _pid_alive(record["pid"])
        print(
            f"{record['job_id']}  {record['op']:<20} "
            f"{'running' if alive else 'finished'}  started {record['started_at']}"
        )
    return 0


def cmd_job(project, args):
    record_file = _jobs_dir(project) / f"{args.job_id}.json"
    if not record_file.exists():
        fail(f"No job '{args.job_id}'.", f"{PROG} {project.slug} jobs")
    record = json.loads(record_file.read_text(encoding="utf-8"))
    alive = _pid_alive(record["pid"])
    if args.cancel:
        if alive:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(record["pid"])],
                    capture_output=True,
                )
            else:
                os.kill(record["pid"], 15)
            print(f"job {args.job_id} cancelled")
        else:
            print(f"job {args.job_id} already finished")
        return 0
    print(f"job {record['job_id']} · {record['op']} · {'running' if alive else 'finished'}")
    log = Path(record["log"])
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
        print(tail if tail.strip() else "(no output yet)")
    if not alive:
        notify_data_changed(project.id)
    return 0


# ---------------------------------------------------------------------------
# Observe / lifecycle / migrate
# ---------------------------------------------------------------------------


def cmd_status(project, _args):
    print(f"{project.name} ({project.id})")
    print(f"status: {project.status} · type: {project.project_type}")
    print(f"ui: {project.url or '-'} · api: {project.backend_url or '-'}")
    print(f"path: {project.path}")
    db_path = _db_path_or_none(project)
    if db_path:
        schema = data_plane.introspect_schema(db_path)
        total = sum(t["rowCount"] for t in schema.values())
        print(f"db: {len(schema)} tables, {total} rows")
        warning = _drift_warning(project, schema)
        if warning:
            print(warning)
    return 0


def cmd_schema(project, args):
    db_path = _require_db(project)
    schema = data_plane.introspect_schema(db_path)
    if args.table:
        info = schema.get(args.table)
        if not info:
            fail(
                f"No table '{args.table}'. Tables: {', '.join(schema)}",
                f"{PROG} {project.slug} schema",
            )
        print(f"{args.table} ({info['rowCount']} rows)")
        for column, spec in info["columns"].items():
            print(f"  {column:<24} {spec}")
    else:
        for table, info in schema.items():
            print(f"{table:<26} {info['rowCount']} rows · {len(info['columns'])} columns")
        print(f"\nNext: {PROG} {project.slug} schema <table>")
    warning = _drift_warning(project, schema)
    if warning:
        print(warning)
    return 0


def cmd_logs(project, args):
    candidates = {
        "backend": Path(project.path) / "backend" / "logs" / "subprocess_output.log",
        "frontend-console": Path(project.path) / "backend" / "logs" / "frontend_console.log",
        "frontend-console(sidecar)": Path(project.path) / "logs" / "frontend_console.log",
    }
    printed = False
    for name, path in candidates.items():
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            print(f"── {name} (last {min(args.tail, len(lines))} lines) ──")
            print("\n".join(lines[-args.tail:]))
            printed = True
    if not printed:
        print("(no log files found)")
    return 0


def cmd_ops_check(project, _args):
    """Validate operations.json: format, dead routes, coverage."""
    from app.living_ui import ops_analyzer

    spec = None
    if project.status == "running" and project.backend_url:
        spec = ops_analyzer.fetch_openapi(project.backend_url)
    findings = ops_analyzer.check_manifest(Path(project.path), spec)
    errors = [f for f in findings if f["level"] == "error"]
    warnings = [f for f in findings if f["level"] == "warning"]
    if spec is None and project.project_type == "native":
        print(
            "(backend not running — format checks only; start the app for "
            "dead-route and coverage checks)"
        )
    for finding in errors:
        print(f"ERROR   {finding['message']}\n        fix: {finding['fix']}")
    for finding in warnings:
        print(f"WARNING {finding['message']}\n        fix: {finding['fix']}")
    if not findings:
        print("operations manifest OK — no findings")
    else:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def cmd_ops_sync(project, args):
    """Generate op skeletons for uncovered routes from the live OpenAPI."""
    from app.living_ui import ops_analyzer

    if project.project_type != "native":
        fail(
            f"'{project.slug}' is an external app — ops-sync needs a FastAPI "
            "backend. Write its operations.json by hand (see OPERATIONS.md)."
        )
    if project.status != "running" or not project.backend_url:
        fail(
            "ops-sync reads the running backend's OpenAPI spec.",
            f"{PROG} {project.slug} start",
        )
    spec = ops_analyzer.fetch_openapi(project.backend_url)
    if not spec:
        fail("could not fetch openapi.json from the backend")
    result = ops_analyzer.sync_manifest(Path(project.path), spec, write=args.write)
    if result.get("error"):
        fail(result["error"])
    new_ops = result["new_ops"]
    if not new_ops:
        print("nothing to add — every candidate route is declared or ignored")
        return 0
    for name, op in new_ops.items():
        executor = op["executor"]
        params = ", ".join(op.get("params", {}).keys()) or "(none)"
        print(f"{name:<28} {executor['method']} {executor['path']}   params: {params}")
    if result["written"]:
        print(f"\nmerged {len(new_ops)} op(s) into config/operations.json")
        print(
            "Next: 1) edit each new op's description (say WHEN to use it)  "
            f"2) {PROG} {project.slug} ops-check"
        )
    else:
        print(f"\n{len(new_ops)} op(s) would be added.")
        print(f"Next: {PROG} {project.slug} ops-sync --write")
    return 0


def cmd_migrate(project, _args):
    if project.project_type != "native":
        fail(f"'{project.slug}' is an external app — nothing to migrate.")
    result = migration.run_migration(Path(project.path))
    print(result["output"] or result["status"])
    if result["status"] == "error":
        return 1
    if result["added"]:
        print(f"Next: {PROG} {project.slug} restart   (so the app picks up the schema)")
    return 0


def cmd_lifecycle(project, command: str):
    print(f"{command} {project.slug} ... (launch pipelines can take minutes)")
    ok, response = control_call(command, project.id)
    if not ok:
        fail(
            response.get("error", "control call failed"),
            "is the CraftBot app running?",
        )
    print(json.dumps(response, indent=1, default=str)[:3000])
    return 0 if response.get("status") in ("success", "ok") else 1


def cmd_ui(project, args):
    """Push a command into the running app's iframe (useAgentCommand)."""
    try:
        command = json.loads(args.data)
    except Exception as e:
        fail(f"--data must be a JSON object ({e})", f'{PROG} {project.slug} ui --data \'{{"type": "refresh"}}\'')
    ok, response = control_call("ui_command", project.id, payload={"command": command}, timeout=10)
    if not ok:
        fail(response.get("error", "control call failed"), "is the CraftBot app running?")
    print("delivered (takes effect only if the app handles it via useAgentCommand)")
    return 0


def cmd_triggers(project, _args):
    """List the app's declared triggers (config/triggers.json)."""
    try:
        declared = trigger_plane.load_triggers(project)
    except trigger_plane.TriggerError as e:
        fail(str(e))
    if not declared:
        print("(no triggers declared — config/triggers.json missing or empty)")
        return 0
    print(f"TRIGGERS  ({PROG} {project.slug} trigger <name> [--set k=v])")
    for name, trig_def in declared.items():
        description = (trig_def.get("description") or "")[:64]
        print(f"  {name:<24} {description}")
        params = trig_def.get("params") or {}
        if params:
            print(f"  {'':<24} params: {', '.join(sorted(params.keys()))}")
    return 0


def cmd_trigger(project, args):
    """Fire a declared trigger at the CraftBot agent (as the app would)."""
    if args.data:
        try:
            params = json.loads(args.data)
        except Exception as e:
            fail(f"--data must be a JSON object ({e})")
        if not isinstance(params, dict):
            fail("--data must be a JSON object")
    else:
        params = parse_set(args.set)
    ok, response = control_call(
        "trigger",
        project.id,
        payload={"trigger": args.name, "params": params, "origin": "cli"},
        timeout=30,
    )
    if not ok or response.get("error"):
        fail(
            response.get("error", "control call failed"),
            f"{PROG} {project.slug} triggers   (see what's declared)",
        )
    routed = response.get("routed", "?")
    print(f"fired '{args.name}' → agent ({routed} session)")
    return 0


def cmd_snapshot(project, _args):
    status, text = _http(project, "GET", "/api/ui-snapshot", timeout=10)
    print(text[:4000])
    return 0 if status < 400 else 1


def cmd_screenshot(project, args):
    import base64

    status, text = _http(project, "GET", "/api/ui-screenshot", timeout=15)
    if status >= 400:
        fail(f"screenshot endpoint returned {status}")
    payload = json.loads(text)
    image = payload.get("imageData") or payload.get("image_data")
    if not image:
        fail("no screenshot captured yet (open the app in the browser first)")
    out = Path(args.out or (Path(project.path) / "logs" / "screenshots" / f"ui_{int(time.time())}.png"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(image))
    print(f"saved {out}")
    print("Next: view it with the describe_image action")
    return 0


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _make_parsers():
    parsers = {}

    p = argparse.ArgumentParser(prog=f"{PROG} <project> select", add_help=True)
    p.add_argument("table")
    p.add_argument("--where", action="append", help='e.g. --where "id<=10" (repeatable, AND)')
    p.add_argument("--columns", help="comma-separated projection")
    p.add_argument("--order", help="e.g. --order 'date desc'")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--json", action="store_true")
    parsers["select"] = (p, cmd_select)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> count")
    p.add_argument("table")
    p.add_argument("--where", action="append")
    parsers["count"] = (p, cmd_count)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> insert")
    p.add_argument("table")
    p.add_argument("--file", help="JSON array of row objects (bulk)")
    p.add_argument("--stdin", action="store_true", help="read the JSON array from stdin")
    p.add_argument("--set", action="append", help="single row: --set k=v (repeatable)")
    parsers["insert"] = (p, cmd_insert)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> update")
    p.add_argument("table")
    p.add_argument("--set", action="append", required=True, help="--set k=v (repeatable; k:=json for raw JSON)")
    p.add_argument("--where", action="append")
    p.add_argument("--all", action="store_true", help="confirm a whole-table update")
    parsers["update"] = (p, cmd_update)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> delete")
    p.add_argument("table")
    p.add_argument("--where", action="append")
    p.add_argument("--all", action="store_true", help="confirm a whole-table delete")
    parsers["delete"] = (p, cmd_delete)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> sql")
    p.add_argument("query")
    p.add_argument("--write", action="store_true", help="allow a single write statement (DB snapshot taken first)")
    p.add_argument("--json", action="store_true")
    parsers["sql"] = (p, cmd_sql)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> api")
    p.add_argument("method", help="GET|POST|PUT|PATCH|DELETE")
    p.add_argument("path", help="e.g. /api/dashboard")
    p.add_argument("--data", help="JSON body")
    p.add_argument("--file", help="JSON body from file")
    p.add_argument("--query", action="append", help="k=v (repeatable)")
    parsers["api"] = (p, cmd_api)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> schema")
    p.add_argument("table", nargs="?")
    parsers["schema"] = (p, cmd_schema)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> logs")
    p.add_argument("--tail", type=int, default=40)
    parsers["logs"] = (p, cmd_logs)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> job")
    p.add_argument("job_id")
    p.add_argument("--cancel", action="store_true")
    parsers["job"] = (p, cmd_job)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> screenshot")
    p.add_argument("--out", help="output PNG path")
    parsers["screenshot"] = (p, cmd_screenshot)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> ui")
    p.add_argument("--data", required=True, help='JSON command, e.g. \'{"type": "refresh"}\'')
    parsers["ui"] = (p, cmd_ui)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> trigger")
    p.add_argument("name", help="a trigger declared in config/triggers.json")
    p.add_argument("--set", action="append", help="param: --set k=v (repeatable; k:=json for raw JSON)")
    p.add_argument("--data", help="all params as one JSON object")
    parsers["trigger"] = (p, cmd_trigger)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> ops-sync")
    p.add_argument("--write", action="store_true", help="merge generated skeletons into operations.json")
    parsers["ops-sync"] = (p, cmd_ops_sync)

    p = argparse.ArgumentParser(prog=f"{PROG} <project> ops-check")
    parsers["ops-check"] = (p, cmd_ops_check)

    for simple in ("status", "jobs", "migrate", "snapshot", "triggers"):
        p = argparse.ArgumentParser(prog=f"{PROG} <project> {simple}")
        parsers[simple] = (p, {"status": cmd_status, "jobs": cmd_jobs,
                               "migrate": cmd_migrate, "snapshot": cmd_snapshot,
                               "triggers": cmd_triggers}[simple])
    return parsers


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(ROOT_HELP)
        return 0
    if argv[0] == "ls":
        return cmd_ls(argv[1:])

    project = resolve_project(argv[0])
    rest = argv[1:]
    if not rest or rest[0] in ("-h", "--help", "help"):
        return project_help(project)

    command = rest[0]
    command_args = rest[1:]

    if command == "run":
        return cmd_run(project, command_args)
    if command in ("start", "stop", "restart"):
        return cmd_lifecycle(project, command)

    parsers = _make_parsers()
    if command not in parsers:
        fail(
            f"Unknown command '{command}'.",
            f"{PROG} {project.slug} --help",
        )
    parser, handler = parsers[command]
    try:
        parsed = parser.parse_args(command_args)
    except SystemExit as e:
        return int(e.code or 0)
    return handler(project, parsed)


if __name__ == "__main__":
    sys.exit(main())
