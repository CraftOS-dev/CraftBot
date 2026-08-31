"""Prove the install actually works, before anyone says "complete".

`install.py` already had the right instinct here — `verify_native_imports()`
exists because "INSTALLATION COMPLETE followed by a dead port is worse than a
clear error". This generalises it: a pip success only means files landed, and
the failures that matter are the ones where the files are present but will not
load (a native DLL, a half-bundled package, a model that cannot be reached).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional

from app.provision import proc
from app.provision.types import Context, LogFn, StageResult, Status


def _run(py, code: str, timeout: int = 300):
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        list(py) + ["-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        **kwargs,
    )


def _vcredist_url() -> str:
    """Microsoft's permanent short-link for this machine's architecture."""
    import platform

    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return f"https://aka.ms/vs/17/release/vc_redist.{arch}.exe"


def vcredist_installed() -> bool:
    """Whether the Visual C++ runtime torch needs is present.

    torch's DLLs link against msvcp140.dll and friends, which ship in the
    redistributable rather than with Windows. Without it, importing torch
    fails with "WinError 126: The specified module could not be found",
    naming a DLL that IS on disk — because what is missing is a DEPENDENCY of
    that DLL. Deeply unobvious from the error alone.

    Present on most real machines (countless applications install it) but
    absent from Windows Sandbox and other clean images.

    Falls back to looking for the DLLs themselves when the registry key is
    missing: some machines have the runtime without that key.
    """
    if sys.platform != "win32":
        return True
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\VisualStudio.0\VC\Runtimesd",
        ) as key:
            installed, _ = winreg.QueryValueEx(key, "Installed")
            return bool(installed)
    except OSError:
        sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        return all(
            os.path.isfile(os.path.join(sys32, dll))
            for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
        )


def ensure_native_runtime(log: Optional[LogFn] = None) -> None:
    """OS prerequisites that pip cannot provide for the native wheels
    (torch, onnxruntime, ...) the memory stack imports at boot.

    Windows: the Visual C++ 2015-2022 Redistributable — torch's DLLs link
    against it and a fresh Windows (observed: Windows Sandbox, 2026-08-25)
    lacks it, dying at first boot with WinError 126 on torch_python.dll.
    Installed silently when missing (one-time, machine-wide, UAC prompt).
    Linux: libgomp/libstdc++ (missing on minimal images) — sudo territory,
    so only a hint. macOS: torch wheels are self-contained.

    Lived in install.py, which the installer never runs — so an
    installer-based machine hit exactly the WinError 126 this exists to
    prevent. Moved here so both paths share the one implementation.
    """
    say: LogFn = log or print

    if sys.platform == "win32":
        if vcredist_installed():
            say("  Visual C++ Redistributable present")
            return

        from app import downloads

        url = _vcredist_url()
        dest = os.path.join(tempfile.gettempdir(), os.path.basename(url))
        say("  Visual C++ Redistributable missing — installing (torch needs it)")
        say("    a UAC prompt may appear")
        try:
            downloads.download(url, dest, log=say, label="Visual C++ runtime")
            proc = subprocess.run(
                [dest, "/install", "/quiet", "/norestart"],
                capture_output=True,
                text=True,
                timeout=900,
            )
            code = proc.returncode
            # 0 = installed, 1638 = a newer version is already present,
            # 3010 = success, reboot pending (the DLLs work regardless).
            if code in (0, 1638, 3010) and vcredist_installed():
                say("  Visual C++ Redistributable installed")
            else:
                say(f"  Redistributable installer exited {code} — install it manually:")
                say(f"    {url}")
        except Exception as e:
            say(f"  Could not install the Visual C++ Redistributable: {str(e)[:200]}")
            say(f"    Install it manually: {url}")
        finally:
            try:
                os.remove(dest)
            except OSError:
                pass

    elif sys.platform.startswith("linux"):
        import ctypes.util

        missing = [
            name
            for name, lib in (("libgomp1", "gomp"), ("libstdc++6", "stdc++"))
            if ctypes.util.find_library(lib) is None
        ]
        if missing:
            say(f"  Missing system libraries torch needs: {', '.join(missing)}")
            say(f"    Debian/Ubuntu/Kali:  sudo apt-get install -y {' '.join(missing)}")
            say("    Fedora/RHEL:         sudo dnf install -y libgomp libstdc++")


class NativeRuntimeStage:
    """The memory embedding stack must LOAD, not merely be installed.

    This is the #439 failure class: `sentence_transformers` present on disk,
    `transformers` absent, so the import raises and the agent dies at startup
    with a traceback rather than a message. Catching it here turns a dead
    launch into an install-time error naming the fix.
    """

    name = "native-runtime"
    description = "Embedding stack loads"
    optional = False

    def check(self, ctx: Context) -> StageResult:
        model = os.environ.get("MEMORY_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        if model == "default":
            return StageResult(Status.SKIPPED, "using ChromaDB's bundled embedder")

        res = proc.python(ctx.python(), "import torch, sentence_transformers")
        if res.returncode == 0:
            return StageResult(Status.SATISFIED, "torch + sentence-transformers load")

        tail = (res.stderr or "").strip().splitlines()[-1:] or ["(no output)"]
        fix = (
            "install the Visual C++ Redistributable "
            "(https://aka.ms/vs/17/release/vc_redist.x64.exe)"
            if sys.platform == "win32"
            else "apt-get install -y libgomp1 libstdc++6"
        )
        return StageResult(
            Status.DEGRADED,
            f"{tail[0][:400]} — usual fix: {fix}. "
            "Escape hatch: MEMORY_EMBEDDING_MODEL=default (lower retrieval quality).",
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        """Install the OS-level prerequisite the embedding stack needs.

        PythonDepsStage owns the packages; what can be missing HERE is a
        system library. On Windows that is almost always the VC++
        redistributable, and telling a non-technical user to go download it
        would break the one promise the installer makes. So we fetch it.
        """
        before = self.check(ctx)
        if before.ok:
            return before

        if sys.platform == "win32" and not vcredist_installed():
            if ctx.offline:
                return StageResult(
                    Status.FAILED,
                    "the Visual C++ runtime is missing and cannot be installed "
                    f"offline. Get it from {_vcredist_url()}",
                )
            ensure_native_runtime(log=lambda m: log("  " + m))
            after = self.check(ctx)
            if after.ok:
                return after
            after.detail = (
                "the Visual C++ runtime step ran, but the embedding stack still "
                f"will not load. {after.detail}"
            )
            return after

        # Anything else here is an OS library we cannot supply; the check's
        # message already names the fix.
        return before


class SmokeStage:
    """Import the things actions import.

    Actions are exec'd from source at runtime, so nothing statically verifies
    their imports — that is exactly how the frozen build shipped without
    pdfplumber, trafilatura and pyperclip while openpyxl survived by accident.
    """

    name = "smoke"
    description = "Action dependencies importable"
    optional = False

    MODULES: List[str] = [
        "chromadb",
        "openai",
        "anthropic",
        "tiktoken",
        "rank_bm25",
        "pdfplumber",
        "pypdf",
        "pypdfium2",
        "fitz",
        "pyperclip",
        "websockets",
        "boto3",
        "requests",
        "bs4",
        "trafilatura",
    ]

    def check(self, ctx: Context) -> StageResult:
        code = (
            "import importlib.util as u, json, sys;"
            f"mods={self.MODULES!r};"
            "print(json.dumps([m for m in mods "
            "if u.find_spec(m) is None]))"
        )
        res = proc.python(ctx.python(), code)
        if res.returncode != 0:
            return StageResult(Status.DEGRADED, "probe failed to run")
        import json

        try:
            missing = json.loads((res.stdout or "[]").strip().splitlines()[-1])
        except (ValueError, IndexError):
            return StageResult(Status.DEGRADED, "probe produced no result")
        if missing:
            return StageResult(
                Status.MISSING,
                f"not importable: {', '.join(missing)}",
                {"missing": missing},
            )
        return StageResult(Status.SATISFIED, f"{len(self.MODULES)} modules import")

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        # PythonDepsStage installs; this only reports. If we land here the
        # lock installed "successfully" yet something it declares is absent,
        # which is a lock bug worth surfacing loudly rather than papering over.
        res = self.check(ctx)
        if not res.ok:
            res.detail += " — the lock installed but these are absent; regenerate it."
        return res


class DiskSpaceStage:
    """Refuse to start an install that cannot possibly finish.

    A full CraftBot install is roughly 2.5 GB once torch, the Playwright
    browser and two node_modules trees have landed, and the downloads need
    room on top. Running out halfway produces whatever error the unlucky
    step happens to raise — a failed wheel build, a truncated archive, an
    npm ENOSPC — none of which say "you are out of disk".

    install.py checked this before doing anything; the installer did not, so
    the same machine got the clear message one way and a puzzle the other.
    """

    name = "disk-space"
    description = "Free disk space"
    optional = False

    #: Installed footprint plus headroom for the archives being unpacked.
    REQUIRED_GB = 5.0

    def _free_gb(self, path: str) -> Optional[float]:
        try:
            return shutil.disk_usage(path).free / (1024**3)
        except OSError:
            return None  # unreadable mount: do not block the install over it

    def check(self, ctx: Context) -> StageResult:
        free = self._free_gb(ctx.state_root)
        if free is None:
            return StageResult(Status.SKIPPED, "could not read free space")
        if free >= self.REQUIRED_GB:
            return StageResult(
                Status.SATISFIED, f"{free:.1f} GB free", {"free_gb": round(free, 1)}
            )
        return StageResult(
            Status.FAILED,
            f"only {free:.1f} GB free at {ctx.state_root}; CraftBot needs about "
            f"{self.REQUIRED_GB:.0f} GB (torch, the Playwright browser and the "
            "npm trees). Free some space and re-run.",
            {"free_gb": round(free, 1)},
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        # Nothing to do but report — we cannot make disk space appear.
        return self.check(ctx)
