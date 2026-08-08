"""Generate core/concepts/default-actions.md from the @action decorators in
app/data/action/ at build time, so the catalogue can never drift from the code.

Runs under mkdocs-gen-files. Extraction is static (AST), so importing the app
and its heavy dependencies is never required.
"""

import ast
from pathlib import Path

import mkdocs_gen_files

# mkdocs runs with cwd = the directory containing mkdocs.yml (mkdocs/).
REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_DIR = REPO_ROOT / "app" / "data" / "action"

# Curated presentation: domain title -> ordered list of action names.
# Actions found in source but not listed here are appended under "Other
# actions" so the catalogue is always complete even when new actions land.
DOMAINS = [
    (
        "Task control",
        [
            "task_start",
            "task_end",
            "task_update_todos",
            "set_requirement",
            "send_message",
            "send_message_with_attachment",
            "end_turn",
            "wait",
            "spawn_subagent",
            "sub_task_end",
        ],
    ),
    (
        "Files and search",
        [
            "read_file",
            "write_file",
            "stream_edit",
            "find_files",
            "grep_files",
            "list_folder",
        ],
    ),
    ("Web research", ["web_search", "web_fetch"]),
    ("Shell and HTTP", ["run_shell", "http_request"]),
    ("Clipboard", ["clipboard_read", "clipboard_write"]),
    (
        "Scheduling",
        [
            "schedule_task",
            "scheduled_task_list",
            "schedule_task_toggle",
            "remove_scheduled_task",
        ],
    ),
    (
        "Recurring proactive tasks",
        [
            "recurring_add",
            "recurring_read",
            "recurring_update_task",
            "recurring_remove",
        ],
    ),
    ("Memory", ["memory_search"]),
    (
        "Skills and action sets",
        [
            "list_skills",
            "use_skill",
            "list_action_sets",
            "add_action_sets",
            "remove_action_sets",
        ],
    ),
    (
        "Integration management",
        [
            "list_available_integrations",
            "connect_integration",
            "check_integration_status",
            "disconnect_integration",
        ],
    ),
    (
        "Documents and PDF",
        [
            "read_pdf",
            "edit_pdf",
            "convert_to_pdf",
            "convert_from_pdf",
            "convert_to_markdown",
            "perform_ocr",
        ],
    ),
    (
        "Media understanding and generation",
        [
            "describe_image",
            "understand_video",
            "generate_image",
            "generate_video",
        ],
    ),
    (
        "Living UI",
        [
            "living_ui_scaffold",
            "living_ui_notify_ready",
            "living_ui_restart",
            "living_ui_report_progress",
            "living_ui_import_external",
            "living_ui_import_zip",
            "living_ui_http",
        ],
    ),
]


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def extract_actions():
    """Return {name: {description, params, action_sets, irreversible}} from AST."""
    actions = {}
    files = sorted(ACTION_DIR.glob("*.py"))
    files.append(ACTION_DIR / "integrations" / "integration_management.py")
    for py in files:
        if py.name.startswith("_") or not py.exists():
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                is_action = isinstance(dec, ast.Call) and (
                    (isinstance(dec.func, ast.Name) and dec.func.id == "action")
                    or (
                        isinstance(dec.func, ast.Attribute)
                        and dec.func.attr == "action"
                    )
                )
                if not is_action:
                    continue
                meta = {
                    "description": "",
                    "params": [],
                    "action_sets": [],
                    "irreversible": False,
                }
                if dec.args:
                    meta["name"] = _literal(dec.args[0])
                for kw in dec.keywords:
                    if kw.arg == "name":
                        meta["name"] = _literal(kw.value)
                    elif kw.arg == "description":
                        meta["description"] = (_literal(kw.value) or "").strip()
                    elif kw.arg == "action_sets":
                        meta["action_sets"] = _literal(kw.value) or []
                    elif kw.arg == "irreversible":
                        meta["irreversible"] = bool(_literal(kw.value))
                    elif kw.arg == "input_schema":
                        v = _literal(kw.value)
                        meta["params"] = list(v.keys()) if isinstance(v, dict) else []
                name = meta.get("name")
                if name and name not in actions:
                    actions[name] = meta
    return actions


def first_sentence(text, limit=200):
    text = " ".join(text.split())
    if not text:
        return ""
    for stop in (". ", "! ", "? "):
        i = text.find(stop)
        if 0 < i < limit:
            return text[: i + 1].strip()
    return (text[:limit] + ("..." if len(text) > limit else "")).strip()


def render_row(name, meta):
    params = ", ".join(f"`{p}`" for p in meta["params"]) if meta["params"] else "none"
    desc = first_sentence(meta["description"]) or "See the source for details."
    if meta["irreversible"]:
        desc += " **Irreversible.**"
    sets = ", ".join(f"`{s}`" for s in meta["action_sets"]) or "n/a"
    return f"| `{name}` | {sets} | {params} | {desc} |"


def build_markdown():
    actions = extract_actions()
    used = set()
    lines = [
        "# Default actions",
        "",
        "This page lists every default (built-in, non-integration) action with its "
        "action set, parameters, and purpose. It is generated at build time from the "
        "`@action(...)` decorators in `app/data/action/`, so it never drifts from the "
        "code. For how actions are registered, grouped into sets, selected, and "
        "executed, read [Actions and action sets](actions-and-action-sets.md).",
        "",
        "Two other groups of actions exist beyond this page. Integration actions (for "
        "example `create_github_issue`) are documented on each service's page in "
        "[Integrations](../../integrations/index.md). MCP tool actions are created "
        "dynamically as `mcp_<server>_<tool>` when you connect an "
        "[MCP server](../../integrations/mcp.md).",
        "",
        "The **Set** column shows which [action set](actions-and-action-sets.md#action-sets) "
        "the action belongs to. Actions in `core` are available in every task. Actions "
        "in other sets are available only when the task selected that set. Actions "
        "marked **Irreversible** are guarded so a retried turn does not repeat them.",
        "",
        f"There are **{len(actions)}** default actions.",
        "",
    ]
    for title, names in DOMAINS:
        rows = []
        for name in names:
            if name in actions:
                rows.append(render_row(name, actions[name]))
                used.add(name)
        if not rows:
            continue
        lines += [
            f"## {title}",
            "",
            "| Action | Set | Parameters | What it does |",
            "|---|---|---|---|",
            *rows,
            "",
        ]
    leftover = sorted(n for n in actions if n not in used)
    if leftover:
        lines += [
            "## Other actions",
            "",
            "Actions present in the code that are not yet grouped above.",
            "",
            "| Action | Set | Parameters | What it does |",
            "|---|---|---|---|",
            *(render_row(n, actions[n]) for n in leftover),
            "",
        ]
    lines += [
        "## Next",
        "",
        "- [Actions and action sets](actions-and-action-sets.md): how selection, "
        "compilation, and execution work",
        "- [Integrations](../../integrations/index.md): the per-service action catalogues",
        "- [Write a custom action](../../develop/custom-action.md): add your own entry "
        "to this registry",
        "",
    ]
    return "\n".join(lines)


with mkdocs_gen_files.open("core/concepts/default-actions.md", "w") as f:
    f.write(build_markdown())
