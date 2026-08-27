"""The ONE Python interpreter every CraftBot process runs on.

CraftBot has three launchers — craftbot.py, run.py, install.py — and any of
them may be started by whatever `python` the user happens to type. On a
fresh box that is often 3.13/3.14, while the dependencies are pinned to
PYTHON_VERSION (environment.yml: python=3.10.x). Each launcher therefore
calls reexec_if_needed() first thing: if a better-qualified interpreter
resolves, the process re-launches itself on it and the launcher Python
becomes a pure trampoline (same idea as app/node_runtime.py for Node).

Resolution order (cached per process):
  1. CRAFTBOT_PYTHON env var — explicit override.
  2. The interpreter of an ACTIVATED conda env, when this process already
     runs inside it — the user chose that env; never hijack it.
  3. config.json `python_executable` — the interpreter install.py put the
     dependencies into. Authoritative even if its version differs (the user
     may have chosen "continue anyway"); the deps live there.
  4. sys.executable when it already is PYTHON_VERSION.
  5. A PYTHON_VERSION install at the known locations / py launcher / PATH.
  6. None — only install.py may fix that (it downloads and installs one).

Stdlib-only on purpose: the launchers import this before any dependencies
exist (app/__init__.py is empty).
"""

import functools
import os
import subprocess
import sys
from typing import Optional, Tuple

PYTHON_VERSION: Tuple[int, int] = (3, 10)  # keep environment.yml's python pin in sync

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO_ROOT, "config.json")

_REEXEC_MARK = "CRAFTBOT_PY_REEXEC"  # set on the child so it never hops again

_cached: Optional[str] = None
_resolved = False


@functools.lru_cache(maxsize=16)
def version_of(exe: str) -> Optional[Tuple[int, int]]:
    """(major, minor) of an interpreter, or None when it can't be probed."""
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        out = subprocess.run(
            [exe, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=15,
            **kwargs,
        ).stdout.split()
        return (int(out[0]), int(out[1]))
    except Exception:
        return None


def _same(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(
            os.path.abspath(b)
        )


def recorded() -> Optional[str]:
    """config.json `python_executable`, when it still exists."""
    try:
        import json

        with open(CONFIG_FILE, encoding="utf-8") as f:
            path = json.load(f).get("python_executable")
        return path if path and os.path.isfile(path) else None
    except Exception:
        return None


def find_python(version: Tuple[int, int] = PYTHON_VERSION) -> Optional[str]:
    """A `version` interpreter from the usual install locations, the Windows
    py launcher, or PATH — verified by probing. None when absent."""
    import shutil

    tag = f"{version[0]}{version[1]}"  # "310"
    dotted = f"{version[0]}.{version[1]}"  # "3.10"
    candidates = []
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            os.path.join(local_app, "Programs", "Python", f"Python{tag}", "python.exe"),
            rf"C:\Python{tag}\python.exe",
            os.path.join(
                os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                f"Python{tag}",
                "python.exe",
            ),
        ]
        py = shutil.which("py")
        if py:
            # The launcher knows every registered install; ask it for the
            # real binary so callers get a plain interpreter path.
            try:
                out = subprocess.run(
                    [py, f"-{dotted}", "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                ).stdout.strip()
                if out:
                    candidates.append(out)
            except Exception:
                pass
    else:
        candidates += [
            shutil.which(f"python{dotted}") or "",
            f"/usr/local/bin/python{dotted}",
            f"/opt/homebrew/bin/python{dotted}",
            f"/Library/Frameworks/Python.framework/Versions/{dotted}/bin/python{dotted}",
        ]
    for path in candidates:
        if path and os.path.isfile(path) and version_of(path) == version:
            return path
    return None


def resolve(refresh: bool = False) -> Optional[str]:
    """The single interpreter for this CraftBot (cached; refresh re-scans —
    install.py uses that after installing one)."""
    global _cached, _resolved
    if _resolved and not refresh:
        return _cached
    _resolved = True
    _cached = None

    override = os.environ.get("CRAFTBOT_PYTHON", "").strip()
    if override and os.path.isfile(override):
        _cached = override
        return _cached

    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix and os.path.normcase(sys.executable).startswith(
        os.path.normcase(conda_prefix)
    ):
        _cached = sys.executable
        return _cached

    _cached = recorded()
    if _cached:
        return _cached

    if sys.version_info[:2] == PYTHON_VERSION:
        _cached = sys.executable
        return _cached

    _cached = find_python()
    return _cached


def reexec_if_needed() -> None:
    """Re-launch the current script on the resolved interpreter when that is
    a different one, and exit with its code. No-op when already on it, when
    nothing resolves (callers decide what that means), when frozen, or in a
    child that was itself re-launched (loop guard)."""
    if getattr(sys, "frozen", False) or os.environ.get(_REEXEC_MARK):
        return
    target = resolve()
    if not target or _same(target, sys.executable):
        return
    env = {**os.environ, _REEXEC_MARK: "1"}
    argv = [target, *sys.argv]
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":
        # execv on Windows spawns a detached child and returns the console
        # immediately — run as a subprocess and forward the exit code.
        sys.exit(subprocess.run(argv, env=env).returncode)
    os.execve(target, argv, env)
