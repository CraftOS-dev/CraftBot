"""Install the bundled Kanban as an ordinary Agent App, never on startup.

The install entry points capture eligibility before writing config. A small
receipt survives interrupted installs and records completion even if the user
later deletes the board. The unchanged upstream installer owns project files,
identity, ports, registration and serving; CraftBot stores a startup preference.

This module stays stdlib-only: installers import it before dependencies exist.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
import zipfile
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
                Status.FAILED, proc.failure_detail(result, "Kanban install failed")
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

    from app.agent_app import framework
    from app.agent_app.framework_store import HostStore, app_key

    cli = framework.configured_cli()
    marketplace = await asyncio.to_thread(_local_catalogue, archive, state_root, source["sha256"])
    # Ship the marketplace toolkit beside its app, outside the untrusted app
    # tree. The unchanged CLI resolves and records this source for later use.
    toolkit_env = {"A2APP_TOOLKITS_DIR": str(marketplace / "toolkits")}
    destination = (state_root / "agent-apps/kanban-board").resolve()
    snapshot = await framework._list_apps(cli)
    if snapshot["status"] != "success":
        raise RuntimeError(snapshot.get("message", "Could not read the framework registry"))
    registered = next((row for row in snapshot["data"]["apps"] if Path(row["path"]).resolve() == destination), None)
    if registered:
        # An interrupted installer may have completed registration. Resume only
        # the exact bundled catalogue provenance, never an arbitrary occupied dir.
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        provenance = manifest.get("source", {})
        if provenance.get("catalogueId") != "kanban-board" or provenance.get("location") != str(marketplace):
            raise ValueError("The default app destination belongs to another source; it was not overwritten.")
        if registered["status"] != "running":
            served = await cli.run("agent-app", [str(destination), "serve", "--install"], cwd=cli.package_dir, timeout=900, env_extra=toolkit_env)
            if not served.ok:
                raise RuntimeError(served.stderr or served.stdout)
    else:
        if destination.exists():
            raise ValueError("The default app destination already exists without a registry entry; inspect it before retrying.")
        result = await cli.run("agent-app", ["install", "kanban-board", "--source", str(marketplace), "--into", str(destination)], cwd=cli.package_dir, timeout=900, env_extra=toolkit_env)
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout)
    snapshot = await framework._list_apps(cli)
    registered = next((row for row in snapshot.get("data", {}).get("apps", []) if Path(row["path"]).resolve() == destination), None)
    if not registered or registered["status"] != "running":
        raise RuntimeError("Kanban installation did not produce a running registered app.")
    key = app_key(cli.home, str(destination), registered["id"])
    store = HostStore(state_root / "agent-app-host.sqlite3")
    store.put("attachment", key, {"key": key, "home": str(cli.home), "path": str(destination), "appId": registered["id"], "name": registered["name"], "sessionId": None, "autoStart": True, "tasksAllowed": False})
    _write_receipt(state_root, {"status": "installed", "frameworkAppId": registered["id"], "path": str(destination), "home": str(cli.home), "sha256": source["sha256"]})


def bundled_toolkits(code_root: Path, state_root: Path) -> Path:
    """Resolve shipped toolkits for later imports without installing the board."""
    bundle_dir = code_root / BUNDLE_DIR
    source = json.loads((bundle_dir / "source.json").read_text(encoding="utf-8"))
    archive = bundle_dir / "kanban-board.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("Bundled Kanban Board checksum mismatch")
    return _local_catalogue(archive, state_root, source["sha256"]) / "toolkits"


def _local_catalogue(archive: Path, state_root: Path, digest: str) -> Path:
    """Expose the verified release artifact as an upstream offline catalogue."""
    cache = state_root / "runtime/default-agent-app" / digest
    files = {}
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            name = entry.filename
            if entry.is_dir():
                continue
            parts = Path(name).parts
            if Path(name).is_absolute() or ".." in parts or "\\" in name or ":" in name or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe default app archive entry")
            if name in files:
                raise ValueError("Duplicate default app archive entry")
            files[name] = package.read(entry)
    if "catalogue.json" not in files or "kanban-board/manifest.json" not in files:
        raise ValueError("The default app bundle is not a marketplace catalogue.")
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache.parent, prefix="prepare-") as temporary:
            staged = Path(temporary) / "catalogue"
            for name, value in files.items():
                target = staged / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
            deadline = time.monotonic() + 10
            while True:
                try:
                    staged.rename(cache)
                    break
                except OSError as error:
                    # A concurrent installer can publish the same cache. Verify
                    # it below; never replace an existing destination.
                    if cache.is_dir():
                        break
                    # Windows scanners briefly hold newly extracted files.
                    if getattr(error, "winerror", None) not in {5, 32} or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)
    expected = files
    actual = set()
    for current, dirs, names in os.walk(cache, followlinks=False):
        if Path(current).is_symlink() or any((Path(current) / d).is_symlink() for d in dirs):
            raise ValueError("The default app source cache contains a link.")
        actual.update((Path(current) / n).relative_to(cache).as_posix() for n in names)
    if actual != set(expected):
        raise ValueError("The default app source cache changed; inspect it before reinstalling.")
    for name, value in expected.items():
        path = cache / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != value:
            raise ValueError("The default app source cache changed; inspect it before reinstalling.")
    return cache.resolve()


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
