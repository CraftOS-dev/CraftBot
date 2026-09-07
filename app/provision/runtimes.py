"""Node and Python runtime stages.

Both follow the same rule, which is the whole point of the sidecar approach:
**never touch the system installation.** A machine may pin its default Node to
20.x or its default Python to 3.13 for reasons that have nothing to do with
CraftBot. We resolve something suitable, and if nothing suitable exists we
download a private copy into STATE_ROOT/runtime/.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from app.provision.types import Context, LogFn, StageResult, Status

# python-build-standalone: relocatable CPython for all three platforms, with
# pip. python.org's embeddable package is Windows-only and ships without pip,
# so it cannot serve the same role.
#
# The release tag and patch version are RESOLVED FROM THE API, never
# hardcoded. Hardcoding them was tried and produced a silent 404: the guessed
# tag, patch version and platform triple were all wrong, so the download
# failed and the install aborted at the first stage. The asset name embeds
# all three (cpython-3.10.21+20260825-x86_64-pc-windows-msvc-install_only),
# so any one being stale breaks it. Same approach as node_runtime, which
# reads nodejs.org/dist/index.json rather than pinning a version.
PBS_API = (
    "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
)

# The version the locks are generated for. NOT a minimum: a lock is valid
# for exactly one (platform, python) pair, so accepting "3.10 or newer" would
# mean a user on 3.14 has no lock at all — which is precisely what happened on
# a machine whose conda env had drifted to 3.14.7 while environment.yml still
# said 3.10.19. Anything else gets the sidecar, which costs a download and
# buys the reproducibility the lock exists for.
TARGET_PYTHON = (3, 10)


class NodeStage:
    name = "node"
    description = "Node.js runtime"
    # Core chat works without Node; only Living UI hard-requires it. Failing
    # the whole install because a Node download timed out would be worse than
    # the feature being unavailable.
    optional = True

    def check(self, ctx: Context) -> StageResult:
        from app import node_runtime

        rt = node_runtime.resolve(refresh=True)
        if rt is None:
            return StageResult(Status.MISSING, "no Node >= 24 found")
        return StageResult(
            Status.SATISFIED,
            f"{rt.version or '?'} ({rt.source})",
            {"node": rt.node, "version": rt.version, "source": rt.source},
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        if ctx.offline:
            return StageResult(Status.FAILED, "offline: cannot download Node")
        from app import node_runtime

        rt = node_runtime.ensure_sidecar(log=log)
        if rt is None:
            return StageResult(Status.FAILED, "sidecar download failed")
        return StageResult(
            Status.SATISFIED,
            f"{rt.version or '?'} ({rt.source})",
            {"node": rt.node, "version": rt.version},
        )


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
    """The python-build-standalone platform triple for this machine."""
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if sys.platform == "win32":
        # No win-arm64 build is published; arm64 Windows runs the x64 build
        # under emulation, which is slower but works.
        return "x86_64-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def _pbs_download_url(log: LogFn) -> Optional[str]:
    """Resolve the download URL for a TARGET_PYTHON build, or None.

    Asks the API for the newest release and picks the asset matching this
    machine's triple. `install_only` is the variant that extracts to a
    ready-to-run tree; the full builds carry object files and headers nobody
    here needs.
    """
    import json
    import ssl
    import urllib.request

    triple = _pbs_triple()
    if not triple:
        return None

    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    try:
        req = urllib.request.Request(PBS_API, headers={"User-Agent": "CraftBot"})
        data = json.loads(urllib.request.urlopen(req, timeout=60, context=ctx).read())
    except Exception as e:
        log(f"    could not reach the Python download index: {str(e)[:160]}")
        return None

    prefix = f"cpython-{TARGET_PYTHON[0]}.{TARGET_PYTHON[1]}."
    suffix = f"-{triple}-install_only.tar.gz"
    for asset in data.get("assets", []):
        name = asset.get("name") or ""
        if name.startswith(prefix) and name.endswith(suffix):
            return asset.get("browser_download_url")

    log(f"    no {prefix}*{suffix} in release {data.get('tag_name')}")
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
        if ctx.offline:
            return StageResult(Status.FAILED, "offline: cannot download Python")

        import shutil as _shutil
        import tarfile

        from app import downloads

        dest = Path(ctx.state_root) / "runtime" / "python"
        dest.mkdir(parents=True, exist_ok=True)
        archive = dest / "_download.tar.gz"

        # Look in the cache BEFORE asking the network anything. Resolving the
        # URL means fetching a large release index, which is itself a failure
        # point on a slow link - and failing there while holding the very file
        # we need would be perverse.
        triple = _pbs_triple()
        cached = (
            downloads.find_cached(
                f"cpython-{TARGET_PYTHON[0]}.{TARGET_PYTHON[1]}.*-{triple}-install_only.tar.gz"
            )
            if triple
            else None
        )

        url = None
        if not cached:
            url = _pbs_download_url(log)
            if not url:
                return StageResult(
                    Status.FAILED,
                    f"no portable Python {TARGET_PYTHON[0]}.{TARGET_PYTHON[1]} "
                    f"available for {platform.machine()} on {sys.platform}",
                )

        try:
            if cached:
                log(f"    using cached {os.path.basename(cached)}")
                _shutil.copyfile(cached, archive)
            else:
                downloads.download(
                    url,
                    str(archive),
                    log=log,
                    label=f"Python {TARGET_PYTHON[0]}.{TARGET_PYTHON[1]}",
                )
            log("    extracting...")
            # tar preserves the executable bit, which a zip would not — that
            # matters on macOS/Linux where the extracted python must be +x.
            with tarfile.open(archive, mode="r:*") as tf:
                tf.extractall(dest)
        except Exception as e:
            return StageResult(Status.FAILED, f"download failed: {str(e)[:200]}")
        finally:
            try:
                archive.unlink()
            except OSError:
                pass

        exe = self._sidecar_exe(ctx)
        if not exe.is_file():
            return StageResult(Status.FAILED, f"extracted, but {exe} is missing")
        ver = _probe_python(str(exe))
        if not ver or ver[:2] != TARGET_PYTHON:
            return StageResult(Status.FAILED, f"sidecar will not run ({ver})")
        return self._accept(ctx, str(exe), "sidecar", ver)
