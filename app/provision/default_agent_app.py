"""Install the bundled Kanban as an ordinary Agent App, never on startup.

The install entry points capture eligibility before writing config. A small
receipt survives interrupted installs and records completion even if the user
later deletes the board. The existing importer owns project files, identity,
ports and registration; normal auto-launch owns serving it.

This module stays stdlib-only: installers import it before dependencies exist.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from app.provision.types import Context, LogFn, StageResult, Status

BUNDLE_DIR = Path("app/data/default_agent_app")
RECEIPT = ".default-agent-app.json"


def is_new_install(state_root: str, code_root: str | None = None) -> bool:
    """Conservatively exclude existing installs, including ones with no apps."""
    root = Path(state_root)
    existing = [
        root / "install.json",
        root / "agent_file_system" / "workspace",
    ]
    # A checkout SHIPS settings.json. Its presence only signals previous
    # runtime state when code and state are separate (e.g. a managed install).
    if code_root is None or root.resolve() != Path(code_root).resolve():
        existing.append(root / "app" / "config" / "settings.json")
    if code_root is not None:
        existing.append(Path(code_root) / "config.json")
    return not any(path.exists() for path in existing)


def _read_receipt(root: Path) -> dict:
    path = root / RECEIPT
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("status") not in ("pending", "installed"):
        raise ValueError(f"Invalid default Agent App receipt: {path}")
    return data


def _write_receipt(root: Path, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = root / RECEIPT
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_install(ctx: Context) -> None:
    """Remember a fresh install before config/dependency stages create state."""
    root = Path(ctx.state_root)
    if ctx.new_install and not (root / RECEIPT).exists():
        _write_receipt(root, {"status": "pending"})


class DefaultAgentAppStage:
    name = "default-agent-app"
    description = "Installing the included Kanban Board"
    optional = False

    def check(self, ctx: Context) -> StageResult:
        receipt = _read_receipt(Path(ctx.state_root))
        if receipt.get("status") == "installed":
            return StageResult(Status.SATISFIED, "Kanban installation completed")
        if not receipt and not ctx.new_install:
            return StageResult(Status.SKIPPED, "existing installation")
        return StageResult(Status.MISSING, "included Kanban Board not installed yet")

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        from app.provision import proc

        prepare_install(ctx)
        before = self.check(ctx)
        if before.ok:
            return before
        # Use the TARGET interpreter and code tree. The installer process may
        # be frozen or may have a completely different dependency set.
        env = dict(os.environ)
        env["CRAFTBOT_HOME"] = str(Path(ctx.state_root).resolve())
        result = proc.run(
            ctx.python()
            + [
                "-c",
                "from app.provision.default_agent_app import main; raise SystemExit(main())",
            ],
            log,
            cwd=ctx.code_root,
            env=env,
            timeout=900,
        )
        if result.returncode:
            return StageResult(
                Status.FAILED, proc.failure_detail(result, "Kanban import failed")
            )
        return self.check(ctx)


async def install_bundled_app(code_root: Path, state_root: Path) -> None:
    """Acquire finished app code without a build mission or agent trigger."""
    if _read_receipt(state_root).get("status") != "pending":
        return
    bundle_dir = code_root / BUNDLE_DIR
    source = json.loads((bundle_dir / "source.json").read_text(encoding="utf-8"))
    archive = bundle_dir / "kanban-board.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Bundled Kanban Board checksum mismatch")

    from app.agent_app.manager import AgentAppManager

    workspace = state_root / "agent_file_system" / "workspace"
    manager = AgentAppManager(workspace)
    # An interrupted install may already have registered the project. Match
    # its source marker, never its display name (which the user can change).
    installed = manager.find_marketplace_installs("kanban-board")
    if installed:
        project = installed[0]
    else:
        project = await manager.import_project_source(str(archive), "Kanban Board")
    # The manager logs persistence errors rather than raising. Do not mark
    # installation complete unless the next startup can actually find it.
    registry = json.loads(
        (workspace / "agent_app_projects.json").read_text(encoding="utf-8")
    )
    if not any(
        record.get("id") == project.id for record in registry.get("projects", [])
    ):
        raise RuntimeError("Kanban Board was not saved in the Agent App registry")
    _write_receipt(state_root, {"status": "installed", "projectId": project.id})


def main() -> int:
    from app.paths import CODE_ROOT, STATE_ROOT

    try:
        asyncio.run(install_bundled_app(CODE_ROOT, STATE_ROOT))
    except Exception as error:
        print(
            f"ERROR: Could not install the included Kanban Board: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
