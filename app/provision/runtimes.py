"""Node and Python runtime stages.

Both follow the same rule, which is the whole point of the sidecar approach:
**never touch the system installation.** A machine may pin its default Node to
20.x or its default Python to 3.13 for reasons that have nothing to do with
CraftBot. We resolve something suitable, and if nothing suitable exists we
download a private copy into STATE_ROOT/runtime/.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from app.provision.types import Context, LogFn, StageResult, Status

from app import runtime_manifest

# The dependency locks remain on this Python major/minor line.
TARGET_PYTHON = tuple(int(v) for v in runtime_manifest.version("python").split(".")[:2])


class NodeStage:
    name = "node"
    description = "Node.js runtime"
    optional = False

    def check(self, ctx: Context) -> StageResult:
        from app import node_runtime

        rt = node_runtime.resolve(refresh=True)
        if not node_runtime.usable(rt):
            return StageResult(
                Status.MISSING, "a working Node >= 24 and matching npm are required"
            )
        return StageResult(
            Status.SATISFIED,
            f"{rt.version or '?'} ({rt.source})",
            {"node": rt.node, "version": rt.version, "source": rt.source},
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        from app import node_runtime

        rt = node_runtime.ensure_sidecar(log=log, offline=ctx.offline)
        if rt is None:
            return StageResult(Status.FAILED, "sidecar download failed")
        return StageResult(
            Status.SATISFIED,
            f"{rt.version or '?'} ({rt.source})",
            {"node": rt.node, "version": rt.version},
        )


class RipgrepStage:
    """The rg binary bundled under app/vendor/ripgrep/ runs.

    Nothing to download: the binary ships in the source. Unzipping the install
    payload drops the executable bit on macOS and Linux, so apply() restores
    it. Paths come from ctx.code_root because the installer runs this stage
    from its own copy of the code against the tree it just extracted.
    """

    name = "ripgrep"
    description = "ripgrep (file search)"
    # Only grep_files needs it; the rest of the agent runs without it.
    optional = True

    def check(self, ctx: Context) -> StageResult:
        from app import ripgrep_runtime

        try:
            path = ripgrep_runtime.binary_path(Path(ctx.code_root))
        except RuntimeError as e:
            return StageResult(Status.MISSING, str(e))
        if not path.is_file():
            return StageResult(Status.MISSING, f"bundled binary missing: {path}")
        try:
            res = subprocess.run(
                [str(path), "--version"], capture_output=True, text=True, timeout=30
            )
        except OSError as e:
            return StageResult(
                Status.DEGRADED,
                f"bundled binary will not run: {e}",
                {"path": str(path)},
            )
        if res.returncode != 0:
            return StageResult(
                Status.DEGRADED,
                f"bundled binary exited with {res.returncode}",
                {"path": str(path)},
            )
        version = (res.stdout or "").splitlines()[0] if res.stdout else ""
        return StageResult(Status.SATISFIED, version, {"path": str(path)})

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        from app import ripgrep_runtime

        try:
            path = ripgrep_runtime.binary_path(Path(ctx.code_root))
        except RuntimeError as e:
            return StageResult(Status.FAILED, str(e))
        if not path.is_file():
            return StageResult(Status.FAILED, f"bundled binary missing: {path}")
        if sys.platform != "win32":
            os.chmod(path, 0o755)
        return self.check(ctx)


def _probe_python(exe: str) -> Optional[tuple]:
    """(major, minor) of an interpreter, or None if it will not run.

    Spawned rather than parsed from the path: the Windows Store stubs under
    WindowsApps look like interpreters and exit 9009 when run.
    """
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        out = subprocess.run(
            [exe, "-c", "import sys;print(sys.version_info[0],sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=20,
            **kwargs,
        )
        if out.returncode != 0:
            return None
        major, minor = out.stdout.split()[:2]
        return (int(major), int(minor))
    except Exception:
        return None


def _pbs_triple() -> Optional[str]:
    try:
        return runtime_manifest.target("python")
    except ValueError:
        return None


def _pbs_download_url(log: LogFn) -> Optional[str]:
    """Resolve locally, including offline; never depend on upstream 'latest'."""
    try:
        return runtime_manifest.asset("python")["url"]
    except ValueError as exc:
        log(str(exc))
        return None


class PythonStage:
    """Ensure a real CPython on the locked version line exists.

    Needed even though the app may itself be running on Python: a frozen
    build's sys.executable is the agent EXE, and `pip install` of an action's
    dependency or a Python Agent App needs a genuine interpreter. That is why
    executor.py has _find_real_python() and living_ui has
    _resolve_python_in_command() — this stage is what makes those succeed on a
    machine with no Python at all.
    """

    name = "python"
    description = "Python runtime"
    optional = False

    def _sidecar_exe(self, ctx: Context) -> Path:
        root = Path(ctx.state_root) / "runtime" / "python"
        if sys.platform == "win32":
            return root / "python" / "python.exe"
        return root / "python" / "bin" / "python3"

    def _accept(self, ctx: Context, exe: str, source: str, ver: tuple) -> StageResult:
        """Record the interpreter every later stage must use.

        Writing it back onto the context is what keeps the pipeline coherent:
        python-deps installs into THIS interpreter, and the smoke test probes
        THIS interpreter. install.py's oldest bug class is those two being
        different — packages land in one site-packages and the service starts
        on another.
        """
        ctx.service_python = [exe]
        return StageResult(
            Status.SATISFIED,
            f"{source} {ver[0]}.{ver[1]}",
            {"python": exe, "source": source},
        )

    def check(self, ctx: Context) -> StageResult:
        want = f"{TARGET_PYTHON[0]}.{TARGET_PYTHON[1]}"

        # A conda env is chosen by the caller and owns its own interpreter —
        # environment.yml pins it. Don't second-guess it with a sidecar.
        if ctx.conda_env:
            return StageResult(Status.SKIPPED, f"conda env {ctx.conda_env}")

        # 0. An interpreter the CALLER pinned wins over anything we would
        #    resolve. Without this the stage silently redirected every later
        #    stage at its own choice: an end-to-end test that provisioned into
        #    a fresh venv had its dependencies installed into the developer's
        #    site-packages instead, and then reported success because they
        #    were already there.
        pinned = list(ctx.service_python or [])
        if len(pinned) == 1 and os.path.isfile(pinned[0]):
            ver = _probe_python(pinned[0])
            if ver and ver[:2] == TARGET_PYTHON:
                return self._accept(ctx, pinned[0], "provided", ver)

        # 1. An already-downloaded sidecar wins: it is the one we control.
        sidecar = self._sidecar_exe(ctx)
        if sidecar.is_file():
            ver = _probe_python(str(sidecar))
            if ver and ver[:2] == TARGET_PYTHON:
                return self._accept(ctx, str(sidecar), "sidecar", ver)

        # 2. The interpreter running us, when it is real and the right line.
        if not getattr(sys, "frozen", False):
            ver = sys.version_info[:2]
            if ver == TARGET_PYTHON:
                return self._accept(ctx, sys.executable, "current", ver)

        # 3. Anything matching on PATH. python3 first on unix, python first on
        #    Windows — there python3.exe is usually the Store redirect stub.
        names = ("python", "python3") if os.name == "nt" else ("python3", "python")
        for name in names:
            found = shutil.which(name)
            if not found:
                continue
            if os.name == "nt" and "WindowsApps" in found:
                continue  # Store stub, exits 9009
            ver = _probe_python(found)
            if ver and ver[:2] == TARGET_PYTHON:
                return self._accept(ctx, found, "path", ver)

        running = ".".join(str(v) for v in sys.version_info[:2])
        return StageResult(
            Status.MISSING,
            f"need Python {want} (this is {running}); will fetch a private copy",
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        import tarfile
        import tempfile
        from app import downloads

        dest = Path(ctx.state_root) / "runtime" / "python"
        dest.mkdir(parents=True, exist_ok=True)
        try:
            asset = runtime_manifest.asset("python")
            # Staging keeps failed extraction from leaving a seemingly ready runtime.
            with tempfile.TemporaryDirectory(prefix=".python-", dir=dest) as staging:
                stage = Path(staging)
                archive = stage / "python.tar.gz"
                downloads.download(
                    asset["url"],
                    str(archive),
                    log=log,
                    label="Python " + runtime_manifest.version("python"),
                    expected_sha256=asset["sha256"],
                    offline=ctx.offline,
                )
                log("    extracting Python...")
                with tarfile.open(archive, mode="r:*") as tf:
                    tf.extractall(stage, filter="data")
                relative_exe = (
                    Path("python.exe")
                    if sys.platform == "win32"
                    else Path("bin/python3")
                )
                candidate = stage / "python" / relative_exe
                if _probe_python(str(candidate)) != TARGET_PYTHON:
                    raise RuntimeError("Downloaded Python failed its execution check")
                installed = dest / "python"
                backup = dest / ".python-previous"
                if backup.exists():
                    shutil.rmtree(backup)
                if installed.exists():
                    installed.rename(backup)
                try:
                    (stage / "python").rename(installed)
                except Exception:
                    if backup.exists():
                        backup.rename(installed)
                    raise
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
            return self._accept(
                ctx, str(self._sidecar_exe(ctx)), "sidecar", TARGET_PYTHON
            )
        except Exception as exc:
            return StageResult(Status.FAILED, f"Python setup failed: {exc}")
