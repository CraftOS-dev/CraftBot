"""The ONE Python interpreter every CraftBot process runs on.

CraftBot has three launchers — craftbot.py, run.py, install.py — and any of
them may be started by whatever `python` the user happens to type: macOS's
built-in 3.9, a distro 3.12, a Store 3.13, a fresh 3.15. None of those is
used to RUN CraftBot. install.py provisions a private Python on the locked
line (PYTHON_VERSION, environment.yml's pin) under STATE_ROOT/runtime/python
and installs the dependencies there; every launcher then re-launches itself
onto that interpreter, so the Python the user typed is only a trampoline.

Installing into the user's own interpreter was the old behaviour and the
root of a whole family of failures: Ubuntu's system 3.10 has no pip and no
ensurepip, Homebrew's python@3.10 is externally managed (PEP 668), a 3.10
with SQLite < 3.35 cannot load chromadb, and uninstall stripped packages out
from under the user's other projects. The private interpreter has none of
those properties because we choose it.

Resolution order (cached per process):
  1. CRAFTBOT_PYTHON env var — explicit override (Docker, CI, developers).
  2. The interpreter of an ACTIVATED conda env, when this process already
     runs inside it — the user chose that env; never hijack it.
  3. config.json `python_executable` — the interpreter install.py put the
     dependencies into.
  4. The private interpreter, when it exists.
  5. None — run on the current interpreter; only install.py can fix that.

Stdlib-only on purpose: the launchers import this before any dependencies
exist (app/__init__.py is empty), on any Python from 3.8 up.
"""

import functools
import os
import subprocess
import sys
from typing import Dict, Optional, Tuple

PYTHON_VERSION: Tuple[int, int] = (3, 10)  # keep environment.yml's python pin in sync

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(REPO_ROOT, "config.json")

_REEXEC_MARK = "CRAFTBOT_PY_REEXEC"  # set on the child so it never hops again

#: Variables that make an interpreter load code or packages from somewhere
#: other than its own prefix. Any one of them can break the private Python
#: (PYTHONHOME from ArcGIS/QGIS makes it unable to find its stdlib at all).
_FOREIGN_PYTHON_VARS = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONEXECUTABLE",
    "PYTHONUSERBASE",
    "PYTHONSAFEPATH",
    "VIRTUAL_ENV",
    "__PYVENV_LAUNCHER__",
)

#: pip settings that are about the NETWORK, which users legitimately need for
#: mirrors and corporate CAs. Every other PIP_* (require-virtualenv, user,
#: target, prefix, no-binary...) changes where or how pip installs and is
#: stripped.
_KEEP_PIP_VARS = (
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_TRUSTED_HOST",
    "PIP_CERT",
    "PIP_CLIENT_CERT",
    "PIP_PROXY",
    "PIP_TIMEOUT",
    "PIP_DEFAULT_TIMEOUT",
    "PIP_RETRIES",
)

_cached: Optional[str] = None
_resolved = False


def isolated_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """An environment for running CraftBot's own interpreter.

    Strips everything that would make it import from outside its own prefix
    or install somewhere else, keeps network settings (proxies, mirrors,
    certificates), and forces UTF-8 so a Chinese or Japanese Windows locale
    cannot break file reads.
    """
    env = dict(os.environ if base is None else base)
    for name in list(env):
        upper = name.upper()
        if upper in _FOREIGN_PYTHON_VARS:
            del env[name]
        elif upper.startswith("PIP_") and upper not in _KEEP_PIP_VARS:
            del env[name]
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    return env


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
            env=isolated_env(),
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


def private_python() -> Optional[str]:
    """The private interpreter install.py provisions, when it exists."""
    from app import paths

    root = paths.RUNTIME_DIR / "python" / "python"
    exe = root / ("python.exe" if sys.platform == "win32" else "bin/python3")
    return str(exe) if exe.is_file() else None


def resolve(refresh: bool = False) -> Optional[str]:
    """The single interpreter for this CraftBot (cached; refresh re-scans —
    install.py uses that after provisioning one)."""
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

    _cached = recorded() or private_python()
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
    env = isolated_env()
    env[_REEXEC_MARK] = "1"
    argv = [target, *sys.argv]
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.flush()
    if sys.platform == "win32":
        # execv on Windows spawns a detached child and returns the console
        # immediately — run as a subprocess and forward the exit code.
        # Python-level replacements for absent pythonw handles (notably the
        # startup log) are not inherited unless explicitly passed here.
        sys.exit(
            subprocess.run(
                argv,
                env=env,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).returncode
        )
    os.execve(target, argv, env)
