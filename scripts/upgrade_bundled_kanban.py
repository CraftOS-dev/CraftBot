"""Build the bundled board on the unchanged Agent-App PocketBase blueprint.

The pinned legacy ZIP is source input only. Copy its app-owned domain logic,
schema and View; replace its framework with a fresh upstream scaffold. Never
run this against an installed app or a populated database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "app/data/default_agent_app"
OVERLAYS = BUNDLE / "framework-overlays"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def json_write(path, value):
    write(path, json.dumps(value, indent=2) + "\n")


def canonical_guidance(text, operations):
    """Update operation names in source string literals, never executable code."""

    def literal(match):
        value = match[0]
        if value.startswith(("//", "/*")):
            return value
        for op in operations:
            name = op["name"]
            value = value.replace(name, name.replace(".", "-").replace("_", "-"))
        return value.replace("work.*", "work-*").replace(
            "agent-app run <project>", "a2app <app>"
        )

    return re.sub(
        r"""//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""",
        literal,
        text,
    )


async def build(destination: Path):
    from app.agent_app.framework import configured_cli

    if destination.exists():
        raise ValueError(
            "Choose a new candidate directory; installed apps are never overwritten."
        )
    cli = configured_cli()
    result = await cli.run(
        "agent-app",
        [str(destination), "scaffold", "--blueprint", "blueprint-pocketbase-react"],
        cwd=cli.package_dir,
        timeout=90,
    )
    if not result.ok:
        raise RuntimeError(result.stderr or result.stdout)
    source = json.loads((BUNDLE / "source.json").read_text(encoding="utf-8"))
    archive = BUNDLE / "kanban-board.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Legacy source checksum mismatch")
    with zipfile.ZipFile(archive) as z:
        files = {
            n: z.read(n).decode("utf-8")
            for n in z.namelist()
            if not n.endswith("/")
            and (
                n.startswith("frontend/src/app/")
                or n.startswith("pb/pb_hooks/lib_")
                or n.startswith("pb/pb_migrations/")
                or n
                in {
                    "LICENSE",
                    "operations.json",
                    "pb/pb_hooks/ops.pb.js",
                    "pb/pb_hooks/hooks.pb.js",
                    "frontend/package.json",
                    "frontend/package-lock.json",
                    "frontend/tsconfig.json",
                    "reference/requirements.md",
                    "AGENT_APP.md",
                }
            )
        }
    write(destination / "LICENSE", files["LICENSE"])
    for name, content in files.items():
        if name.startswith("frontend/src/app/"):
            # Only presentation helpers remain; no old theme bridge, auth,
            # request collection, adapter or kit is copied.
            content = content.replace("kit/index.ts", "support.tsx")
            write(destination / name.replace("frontend/", "ui/", 1), content)
        elif (
            name.startswith("pb/pb_hooks/lib_")
            or name.startswith("pb/pb_migrations/")
            or name == "pb/pb_hooks/hooks.pb.js"
        ):
            write(destination / name, content)
    # This is a never-launched scaffold, so the starter migration is unapplied.
    (destination / "pb/pb_migrations/1759622400_created_tasks.js").unlink()
    for name in ("package.json", "package-lock.json", "tsconfig.json"):
        write(destination / "ui" / name, files[f"frontend/{name}"])
    package = json.loads((destination / "ui/package.json").read_text(encoding="utf-8"))
    package["scripts"]["build"] = "tsc -p . && vite build"
    package["devDependencies"].pop("vite-plugin-istanbul", None)
    json_write(destination / "ui/package.json", package)
    write(
        destination / "ui/vite.config.js",
        'import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\nimport tailwindcss from "@tailwindcss/vite";\nexport default defineConfig({plugins:[react(),tailwindcss()],build:{outDir:"../pb/pb_public",emptyOutDir:true}});\n',
    )
    html = (
        (destination / "ui/index.html")
        .read_text(encoding="utf-8")
        .replace("<title>Tasks</title>", "<title>Kanban Board</title>")
        .replace("/src/main.jsx", "/src/main.tsx")
    )
    # Consume the existing shared watcher byte-for-byte. PB's missing View
    # version marker is supplemented by the app's explicit reload notice.
    shutil.copyfile(
        cli.package_dir / "toolkits/blueprint-react-node/template/a2app-update.js",
        destination / "ui/public/a2app-update.js",
    )
    write(destination / "ui/index.html", html)
    (destination / "ui/src/main.jsx").unlink()
    # The current framework owns update notification. Remove the old forced
    # page reload, while preserving the board's PocketBase realtime hub.
    live = destination / "ui/src/app/lib/live.ts"
    content = live.read_text(encoding="utf-8")
    start = content.index("  // Every (re)connect")
    end = content.index("  for (const c", start)
    content = content[:start] + content[end:]
    start = content.index(
        "/* ----------------------------------------------------------- new versions */"
    )
    end = content.index("/** Listen to one collection", start)
    write(live, content[:start] + content[end:])
    api = destination / "ui/src/app/lib/api.ts"
    content = api.read_text(encoding="utf-8").replace(
        "import { getPbClient }", "import { operation }"
    )
    start = content.index("function get<T>")
    end = content.index("export interface CardChanges", start)
    content = (
        content[:start]
        + """function get<T>(op: string, params: Query = {}, silent = false): Promise<T> {
  return operation<T>(op, clean(params), silent);
}
function post<T>(op: string, body: Record<string, unknown> = {}, silent = false): Promise<T> {
  return operation<T>(op, clean(body), silent);
}

"""
        + content[end:]
    )
    write(api, content)
    settings = destination / "ui/src/app/pages/Settings.tsx"
    text = (
        settings.read_text(encoding="utf-8")
        .replace("work_waiting", "kanban.work_waiting")
        .replace(
            "Approve the trigger once in CraftBot;",
            "Enable app tasks in CraftBot's app settings;",
        )
        .replace("agent-app CLI", "A2App CLI")
        .replace("app.guide", "app-guide")
        .replace("work.next", "work-next")
    )
    write(settings, text)
    guide = destination / "pb/pb_hooks/lib_guide.js"
    text = guide.read_text(encoding="utf-8")
    for op in json.loads(files["operations.json"])["operations"]:
        if not op.get("system"):
            text = text.replace(
                op["name"], op["name"].replace(".", "-").replace("_", "-")
            )
    write(guide, text)
    util = destination / "pb/pb_hooks/lib_util.js"
    content = util.read_text(encoding="utf-8")
    start, end = (
        content.index("function agentHeader(e)"),
        content.index("/** True when", content.index("function agentHeader(e)")),
    )
    content = (
        content[:start]
        + "function agentHeader(e) { return e && e.kanbanActor ? e.kanbanActor : ''; }\n\n"
        + content[end:]
    )
    write(util, content)
    work = destination / "pb/pb_hooks/lib_work.js"
    content = (
        work.read_text(encoding="utf-8")
        .replace(
            "const trig = require(`${__hooks}/_triggers_lib.js`);\n  const res = trig.fire(app, 'work_waiting', {}, 'hook');\n  if (res && res.ok)",
            "const trig = require(`${__hooks}/_a2app_impl.js`);\n  const res = trig.trigger('kanban.work_waiting', {}, 'kanban-work', app);\n  if (res && res.taskId)",
        )
        .replace("request: res.id", "request: res.taskId")
    )
    write(work, content)
    operations, runners = [], []
    routes = dict(
        re.findall(
            r"routerAdd\('[^']+', '/api/ops/([^']+)', \(e\) => require\(`\$\{__hooks\}/lib_util.js`\).handle\(e, \([^)]*\) => (.+)\)\);",
            files["pb/pb_hooks/ops.pb.js"],
        )
    )
    for old in json.loads(files["operations.json"])["operations"]:
        if old.get("system"):
            continue
        route = old["executor"]["path"].removeprefix("/api/ops/")
        expression = routes[route]
        name = old["name"].replace(".", "-").replace("_", "-")
        module = old["name"].split(".")[0]
        if name in {
            "cards-move",
            "cards-assign",
            "cards-block",
            "cards-unblock",
            "cards-archive",
            "cards-restore",
            "cards-delete",
        }:
            module = "card-flow"
        elif name in {
            "cards-accept",
            "cards-answer",
            "cards-approve-plan",
            "cards-stop",
            "cards-retry",
        }:
            module = "card-decisions"
        elif name in {
            "work-log",
            "work-plan",
            "work-ask",
            "work-submit",
            "work-return",
            "work-fail",
            "work-release",
        }:
            module = "work-results"
        op = {
            "name": name,
            "module": module,
            "description": old["description"],
            "params": old.get("params", {}),
            "destructive": bool(old.get("destructive")),
        }
        for param_name, param in op["params"].items():
            if param.get("format") == "json":
                param["type"] = "json"
                param.pop("format", None)
            if param_name == "priority":
                param["type"] = "number"
                param.pop("enum", None)
                param["description"] = (
                    "Priority: 0 none, 1 urgent, 2 high, 3 normal, 4 low."
                )
        for flag in ("readOnly", "destructive", "idempotent"):
            if flag in old:
                op[flag] = old[flag]
        operations.append(op)
        runners.append(f"""    {json.dumps(name)}: (p, ctx, a2app) => {{
      if (ctx.role !== 'owner') throw a2app.error(403, 'owner_required', 'This personal board belongs to its owner.');
      const app = a2app.app;
      const e = {{ kanbanActor: ['ui', 'session', 'anonymous'].indexOf(ctx.credentialId) === -1 ? (ctx.agentName || ctx.credentialId) : '' }};
      try {{ return {expression}; }} catch (err) {{ throw a2app.error(err.status || 400, 'kanban_rule', String(err.message || err)); }}
    }}""")
    json_write(destination / "operations.json", {"operations": operations})
    old_operations = [
        op
        for op in json.loads(files["operations.json"])["operations"]
        if not op.get("system")
    ]
    for library in (destination / "pb/pb_hooks").glob("lib_*.js"):
        write(
            library,
            canonical_guidance(library.read_text(encoding="utf-8"), old_operations),
        )
    # Descriptions are app-authored guidance too, not database content.
    json_write(
        destination / "operations.json",
        json.loads(
            canonical_guidance(json.dumps({"operations": operations}), old_operations)
        ),
    )
    scopes = ["op:" + op["name"] for op in operations if not op.get("destructive")]
    code = (
        "module.exports = {\n  events: [{type:'kanban.work_waiting'}],\n  permissionsOf: p => p.role === 'owner' ? ['*'] : [],\n  capabilities: { 'kanban-work': {scopes:"
        + json.dumps(scopes)
        + "} },\n  runners: {\n"
        + ",\n".join(runners)
        + "\n  }\n};\n"
    )
    write(destination / "pb/pb_hooks/operations.js", code)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = "Kanban Board"
    entities = {
        "settings": ["settings"],
        "boards": ["boards"],
        "columns": ["columns"],
        "labels": ["labels"],
        "cards": ["cards"],
        "rules": ["rules"],
        "activity": ["events"],
        "work": ["runs"],
    }
    manifest["modules"] = [
        {"name": m, "summary": "Kanban " + m, "entities": entities.get(m, [])}
        for m in dict.fromkeys(op["module"] for op in operations)
    ]
    json_write(manifest_path, manifest)
    requirements = files.get(
        "reference/requirements.md", files.get("AGENT_APP.md", "# Kanban Board\n")
    )
    write(
        destination / "reference/requirements.md",
        requirements
        + "\n\n## Changes\n\n- 2026-11-09: Preserve the board, card, column-contract, rules, activity, insights, review, lease and question behavior on the current Agent-App PocketBase blueprint.\n- 2026-11-09: All UI and agent operations use canonical declared operations; spoofed headers cannot impersonate an agent. Work requests use the framework task queue and delegated credentials.\n- 2026-11-09: Keep real-time board updates and unsaved input; use the framework update watcher. No legacy framework or request collection is included.\n",
    )
    write(
        destination / "AGENT_APP.md",
        "# Kanban Board\n\nPersonal Kanban board upgraded from the pinned bundled source. Domain schema and behavior are preserved. Framework files come unchanged from blueprint-pocketbase-react. See reference/requirements.md for the full contract.\n\n## Modules\n"
        + "\n".join("- " + m["name"] for m in manifest["modules"])
        + "\n\n## Agent work\nDiscover app-guide, then work-queue and work-next. The requesting principal must be the owner. Follow column contracts; retain heartbeats and report evidence through work-submit. Ask via work-ask, never decide human reviews or Done. Complete the framework task after the board queue is drained or waiting on the person.\n",
    )
    for overlay in OVERLAYS.rglob("*"):
        if overlay.is_file():
            target = destination / overlay.relative_to(OVERLAYS)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(overlay, target)
    with (destination / "reference/requirements.md").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write(
            "\n\n"
            + (OVERLAYS / "reference/framework-upgrade.md").read_text(encoding="utf-8")
        )
    with (destination / "AGENT_APP.md").open("a", encoding="utf-8") as stream:
        stream.write(
            "\n## Plan\nUpgrade existing domain behavior to the canonical adapter; validate and independently verify before packaging.\n## Entities\nsettings, boards, columns, labels, cards, events, runs, rules.\n## Operations\n61 declarations in operations.json with matching canonical runners.\n## Conventions\nPersonal owner only. Use adapter identity, transactional app handle and upstream task queue.\n## Checklist\n- [ ] Upstream gate passes with budget checked.\n- [ ] Independent verification passes.\n- [ ] Package exports and installs with fresh identity and no runtime data.\n"
        )
    # Upstream re-vendors SYSTEM files while explicitly retaining app identity
    # and module mapping. No manual canon hash updates or adapter patches.
    synced = await cli.run(
        "agent-app", [str(destination), "toolkit-sync"], cwd=cli.package_dir, timeout=90
    )
    if not synced.ok:
        raise RuntimeError(synced.stderr or synced.stdout)
    print(
        json.dumps(
            {
                "candidate": str(destination),
                "operations": len(operations),
                "source": source,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    asyncio.run(build(args.destination.resolve()))
