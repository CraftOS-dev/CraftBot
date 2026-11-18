"""Dependency stages: Python packages, Playwright browsers, npm trees.

`install.py` provisions more than the plan originally listed. Beyond Python
packages there are Playwright's browser binaries, the browser frontend's npm
tree, and the WhatsApp bridge's npm tree (Baileys). Each is a real
prerequisite, and each was handled differently by the frozen build — which is
how the bridge shipped without its node_modules and could not start at all.

Modelling them as stages means the installer and install.py provision the same
set, in the same order, with the same idempotence.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import List, Optional

from app import paths
from app.provision import locktag, proc
from app.provision.types import Context, LogFn, StageResult, Status


def _lock_tag(python: Optional[List[str]] = None) -> str:
    """Identify the lock valid for an interpreter.

    Must describe the interpreter the packages are being installed INTO, not
    the one running this code. Those differ constantly: install.py may run on
    the system 3.14 while provisioning a 3.10 sidecar, and reading the current
    process's version there picks a lock that does not exist (or worse, one
    that does and is wrong).

    The tag itself is app.provision.locktag's to define — it is the one rule
    that scripts/generate_lock.py must agree with exactly.
    """
    if python:
        try:
            out = proc.python(python, locktag.PROBE, timeout=60)
            if out.returncode == 0:
                return locktag.parse_probe(out.stdout)
        except Exception:
            pass  # fall through to this process's tag

    return locktag.current()


def find_lock(code_root: str, python: Optional[List[str]] = None) -> Optional[Path]:
    """The lock for this (platform, python), or None.

    Deliberately exact — no falling back to another platform's lock. A Linux
    lock pins CUDA-flavoured torch wheels that do not exist for Windows, so a
    'close enough' match fails confusingly at install time instead of clearly
    here.
    """
    candidate = Path(code_root) / "requirements" / f"lock-{_lock_tag(python)}.txt"
    return candidate if candidate.is_file() else None


def find_wheelhouse(code_root: str) -> Optional[Path]:
    """A local directory of wheels to install from instead of PyPI, if any.

    Lets a clean-machine install run from local files: the download is the
    overwhelming majority of install time (~2 GB), and on a slow or absent
    connection it is the difference between a usable install and none.
    Built by scripts/build_wheelhouse.py.

    Checked in order:
      1. $CRAFTBOT_WHEELHOUSE
      2. <code root>/wheelhouse
    """
    env = os.environ.get("CRAFTBOT_WHEELHOUSE", "").strip()
    if env and os.path.isdir(env):
        return Path(env)
    local = Path(code_root) / "wheelhouse"
    return local if local.is_dir() else None


def find_pip_bootstrap(code_root: str) -> Optional[Path]:
    """The pinned-pip requirements file, or None.

    Not per platform: pip is a pure-Python wheel, so one file serves every
    (platform, python) the locks are split across.
    """
    candidate = Path(code_root) / "requirements" / "pip-bootstrap.txt"
    return candidate if candidate.is_file() else None


def _pinned_pip_version(bootstrap: Path, package: str = "pip") -> Optional[str]:
    """The version pip-bootstrap.txt pins for `package`, read from the file.

    Read rather than duplicated as a constant here: two places to edit is how
    the pin and the stage that enforces it drift apart.
    """
    try:
        for line in bootstrap.read_text(encoding="utf-8").splitlines():
            match = re.match(
                rf"^{re.escape(package)}==(\S+?)(?:\s|\\|$)", line.strip() + "\n"
            )
            if match:
                return match.group(1)
    except OSError:
        pass
    return None


def _uv_version(python: List[str]) -> Optional[str]:
    """`python -m uv --version` in the target interpreter, or None."""
    try:
        res = proc.run(python + ["-m", "uv", "--version"], lambda _m: None, timeout=60)
    except OSError:
        return None
    if res.returncode != 0:
        return None
    match = re.search(r"\buv\s+(\S+)", res.stdout or "")
    return match.group(1) if match else None


def npm_tree_stale(tree_dir: str) -> Optional[str]:
    """Why node_modules does NOT satisfy the current package.json, or None.

    Lifted from install.py's _frontend_deps_stale so the installer and
    install.py agree — duplicating it is how they drift. "node_modules exists"
    only proves npm install ran once, not that it ran for the CURRENT
    manifest; pulling a branch that adds a dependency left the naive check
    reporting "already installed" forever.

    Two real conditions:
      1. Every declared dependency resolves to an installed package.json —
         catches added packages.
      2. Neither manifest is newer than npm's own receipt
         (node_modules/.package-lock.json, rewritten by every npm install) —
         catches version bumps, which (1) cannot see.

    (2) also fires after a fresh clone, because git stamps checkout time on
    the manifests. That errs toward reinstalling, which is safe but slow.
    """
    import json

    node_modules = os.path.join(tree_dir, "node_modules")
    if not os.path.isdir(node_modules):
        return "node_modules is missing"

    try:
        with open(os.path.join(tree_dir, "package.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        # Unreadable manifest — run npm install and let npm report the real
        # problem loudly instead of silently skipping.
        return "package.json could not be read"

    declared = {
        **manifest.get("dependencies", {}),
        **manifest.get("devDependencies", {}),
    }
    for name in declared:
        # Scoped names ("@types/react") nest one directory deeper.
        pkg_json = os.path.join(node_modules, *name.split("/"), "package.json")
        if not os.path.isfile(pkg_json):
            return f"declared dependency '{name}' is not installed"

    receipt = os.path.join(node_modules, ".package-lock.json")
    if not os.path.isfile(receipt):
        return "npm's install receipt (node_modules/.package-lock.json) is missing"
    installed_at = os.path.getmtime(receipt)
    for filename in ("package.json", "package-lock.json"):
        path = os.path.join(tree_dir, filename)
        if os.path.isfile(path) and os.path.getmtime(path) > installed_at:
            return f"{filename} changed after the last npm install"

    return None


class PipStage:
    """Pin pip itself, before anything reads a lock.

    The locks exist so every machine installs the same 239 packages. But a
    lock is a set of constraints, and what those constraints MEAN is decided
    by the pip that reads them — which was, until this stage, whatever
    happened to be on the machine. pip 23.1 rejects the committed lock outright
    (see requirements/pip-bootstrap.txt for the mechanism); pip 23.3.2 installs
    it. Nothing in the repo chose between them.

    Two independent sources of that drift:
      * the sidecar's pip is whatever python-build-standalone bundled on the
        day it was downloaded, and the release tag is resolved from
        /releases/latest rather than pinned;
      * PythonStage may hand the install to an interpreter already on the
        machine (steps 2 and 3 of its resolution order), bringing that
        machine's pip with it.

    So this runs between PythonStage and PythonDepsStage: after the
    interpreter is settled, before any lock is read.

    Not skipped for conda. PythonStage defers to conda's own interpreter, but
    PythonDepsStage still installs the lock into it, so the pip that reads it
    matters there for exactly the same reason.
    """

    name = "pip"
    description = "pip and uv (pinned)"
    optional = False

    def _installed_version(self, ctx: Context) -> Optional[str]:
        try:
            res = proc.run(
                ctx.python() + ["-m", "pip", "--version"], lambda _m: None, timeout=120
            )
        except OSError:
            # The interpreter itself is gone or unrunnable. "no pip" is the
            # honest answer; PythonStage owns diagnosing the interpreter, and
            # raising here would take the whole pipeline down with a
            # traceback instead of a stage result.
            return None
        if res.returncode != 0:
            return None
        # "pip 26.2.1 from C:\...\pip (python 3.10)"
        match = re.search(r"\bpip\s+(\S+)", res.stdout or "")
        return match.group(1) if match else None

    def check(self, ctx: Context) -> StageResult:
        bootstrap = find_pip_bootstrap(ctx.code_root)
        if bootstrap is None:
            # Nothing to enforce. Degraded rather than failed: the install can
            # still proceed on the machine's pip, which is what happened
            # before this stage existed.
            return StageResult(
                Status.DEGRADED, "requirements/pip-bootstrap.txt is missing"
            )
        want = _pinned_pip_version(bootstrap)
        if want is None:
            return StageResult(Status.DEGRADED, f"no pip== pin in {bootstrap.name}")
        have = self._installed_version(ctx)
        if have is None:
            return StageResult(Status.MISSING, "pip is not available", {"want": want})
        if have != want:
            return StageResult(
                Status.DEGRADED, f"pip {have}, want {want}", {"pip": have, "want": want}
            )
        want_uv = _pinned_pip_version(bootstrap, "uv")
        have_uv = _uv_version(ctx.python()) if want_uv else None
        if want_uv and have_uv != want_uv:
            return StageResult(
                Status.MISSING if have_uv is None else Status.DEGRADED,
                f"uv {have_uv or 'missing'}, want {want_uv}",
                {"pip": have, "uv": have_uv, "want_uv": want_uv},
            )
        return StageResult(
            Status.SATISFIED,
            f"pip {have}, uv {have_uv}" if want_uv else f"pip {have}",
            {"pip": have, "uv": have_uv, "want": want},
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        py = ctx.python()
        bootstrap = find_pip_bootstrap(ctx.code_root)
        if bootstrap is None:
            return self.check(ctx)

        # No pip at all: bootstrap one from the stdlib before pinning it.
        # python-build-standalone ships pip, but a system interpreter picked
        # up by PythonStage may be a distro build with it split into a
        # separate package.
        if self._installed_version(ctx) is None:
            log("    no pip found — bootstrapping with ensurepip")
            proc.run(py + ["-m", "ensurepip", "--default-pip"], log, stream=True)

        wheelhouse = find_wheelhouse(ctx.code_root)
        wheel_args: List[str] = []
        if wheelhouse:
            wheel_args = ["--no-index", "--find-links", str(wheelhouse)]
        elif ctx.offline:
            # Leave the machine's pip in place rather than failing the whole
            # install: PythonDepsStage reports the offline problem with the
            # actionable message (build a wheelhouse), and duplicating it here
            # would just bury it.
            return StageResult(
                Status.SKIPPED, "offline and no wheelhouse — keeping the current pip"
            )

        # --no-deps because pip has none, so the single pinned entry is the
        # whole requirement set; -m so pip is not replacing a running pip.exe,
        # which fails on Windows.
        res = proc.run(
            py
            + [
                "-u",
                "-m",
                "pip",
                "install",
                "--no-color",
                "--progress-bar",
                "off",
                "--disable-pip-version-check",
                "--require-hashes",
                "--no-deps",
                "-r",
                str(bootstrap),
            ]
            + wheel_args,
            log,
            stream=True,
        )
        if res.returncode != 0:
            return StageResult(Status.FAILED, proc.failure_detail(res, "pip failed"))
        return self.check(ctx)


class PythonDepsStage:
    """Install the locked dependency set into the service interpreter.

    Installs from requirements/lock-*.txt with --require-hashes, never from
    requirements.txt. That is what makes uv, conda and the installer land on
    the same ~200 packages instead of separate resolutions.

    With uv rather than pip: uv downloads and unpacks in parallel and links
    from its cache. Measured on a cold Windows machine: ~11 minutes with pip,
    68 seconds with uv, same lock, same hash checking.

    `--no-deps`: the lock is the full transitive closure (generate_lock.py
    writes the resolved install list, not the lines of requirements.txt), so
    re-deriving it from the pinned entries' metadata on every install is work
    whose answer is already in the file being read.

    Byte-compilation is not part of the install: _byte_compile starts it in
    the background across every core, overlapping the npm stages (~90 s on
    8 cores that used to sit in front of everything else).

    The safety net --no-deps gives up is the "X requires Y, which is not
    installed" complaint, so _audit_closure runs `pip check` to get exactly
    that back.
    """

    name = "python-deps"
    description = "Python dependencies"
    optional = False

    #: Enough of the set to prove the install landed, without importing the
    #: slow ones. A partial install is the common failure, not a total one.
    PROBE = ("chromadb", "openai", "anthropic", "rank_bm25", "pdfplumber", "pypdf")

    def check(self, ctx: Context) -> StageResult:
        py = ctx.python()
        lock = find_lock(ctx.code_root, py)
        if lock is None:
            return StageResult(
                Status.DEGRADED,
                f"no lock for {_lock_tag(py)} — run scripts/generate_lock.py",
            )
        probe = "; ".join(f"import {m}" for m in self.PROBE)
        res = proc.run(
            py + ["-c", probe + "; print('ok')"], lambda _m: None, timeout=180
        )
        if res.returncode == 0:
            return StageResult(
                Status.SATISFIED, f"lock {lock.name}", {"lock": str(lock)}
            )
        missing = (res.stderr or "").strip().splitlines()[-1:] or ["import failed"]
        return StageResult(Status.MISSING, missing[0][:160], {"lock": str(lock)})

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        py = ctx.python()
        lock = find_lock(ctx.code_root, py)
        if lock is None:
            return StageResult(
                Status.FAILED,
                f"no lock file for {_lock_tag(py)}. Generate it with "
                "`python scripts/generate_lock.py` and commit it.",
            )

        wheelhouse = find_wheelhouse(ctx.code_root)
        wheel_args: List[str] = []
        if wheelhouse:
            # --no-index as well as --find-links: without it pip may silently
            # fall back to PyPI for anything the wheelhouse is missing, which
            # turns a fast local install into a slow mixed one and hides an
            # incomplete wheelhouse.
            wheel_args = ["--no-index", "--find-links", str(wheelhouse)]
            log(f"    using local wheelhouse: {wheelhouse}")
        if ctx.offline and not wheelhouse:
            return StageResult(
                Status.FAILED,
                "offline and no wheelhouse — see scripts/build_wheelhouse.py",
            )

        # uv, not pip: it fetches and unpacks in parallel and installs from
        # its cache by link, with the same --require-hashes guarantee. The
        # pip run took ~11 minutes on a cold Windows machine; uv takes ~1.
        # --python names the target explicitly: the interpreter is ours (or
        # the caller's conda env), never an activated virtualenv's.
        target = self._interpreter_path(py) or py[0]
        res = proc.run(
            py
            + [
                "-m",
                "uv",
                "pip",
                "install",
                "--python",
                target,
                "--require-hashes",
                # See the class docstring: the lock is already the closure, and
                # byte-compilation is done in parallel below instead.
                "--no-deps",
                # Trust the OS certificate store (corporate TLS inspection),
                # not only uv's bundled roots.
                "--native-tls",
                "-r",
                str(lock),
            ]
            + _uv_index_args()
            + wheel_args,
            log,
            stream=True,
            env=_uv_env(),
        )
        if res.returncode != 0:
            return StageResult(
                Status.FAILED, proc.failure_detail(res, "uv pip install failed")
            )

        self._byte_compile(py, log)
        self._audit_closure(py, log)
        return self.check(ctx)

    def _interpreter_path(self, python: List[str]) -> Optional[str]:
        """The real executable behind `python` (conda run ... python)."""
        try:
            res = proc.python(python, "import sys; print(sys.executable)", timeout=60)
        except Exception:
            return None
        lines = (res.stdout or "").strip().splitlines()
        return lines[-1].strip() if res.returncode == 0 and lines else None

    def _site_packages(self, python: List[str]) -> List[str]:
        """The directories the lock's packages were installed into.

        Asked of the TARGET interpreter, not this one: the service Python is
        routinely a downloaded sidecar or a conda env, and this process's own
        sysconfig would name a different site-packages every time.
        """
        probe = (
            "import json,sysconfig;p=sysconfig.get_paths();"
            "print(json.dumps(sorted({p['purelib'],p['platlib']})))"
        )
        try:
            res = proc.python(python, probe, timeout=60)
            if res.returncode != 0:
                return []
            import json

            return [d for d in json.loads(res.stdout.strip().splitlines()[-1]) if d]
        except Exception:
            return []

    def _byte_compile(self, python: List[str], log: LogFn) -> None:
        """Write the .pyc files pip was told not to write, using every core.

        Best-effort throughout. A missing .pyc costs a slower first import and
        nothing else — Python writes it on demand — so nothing here is allowed
        to fail an install that pip already completed.

        A non-zero exit is expected, not a warning sign: a few shipped files
        cannot compile under the target Python at all (torch's
        py312_intrinsics.py, olefile's Python-2 olefile2.py). pip hits the
        same two and also just carries on.

        What is NOT expected is compileall failing wholesale — a bad -j on an
        odd build, or no compileall at all. That degrades into an install
        nobody would notice was slow, since every import silently pays the
        compile instead. `-q` prints one block per bad file and nothing else,
        so a handful of lines is the known case and a flood is the other one;
        say so rather than swallowing it.
        """
        targets = self._site_packages(python)
        if not targets:
            log("    (could not locate site-packages — skipping byte-compile)")
            return
        log("    byte-compiling in the background")
        # In the BACKGROUND: it took ~90 s on an 8-core Windows machine and
        # nothing later in the install needs it (Python compiles whatever it
        # imports first, and concurrent .pyc writes are atomic), so it now
        # overlaps the npm stages instead of adding to the wait. Detached so
        # it survives the installer's console closing.
        import subprocess

        from app import python_runtime

        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        try:
            subprocess.Popen(
                python + ["-m", "compileall", "-j", "0", "-q"] + targets,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=python_runtime.isolated_env(),
                **kwargs,
            )
        except Exception as exc:  # OSError — never fatal
            log(f"    WARNING byte-compile skipped: {exc}")

    def _audit_closure(self, python: List[str], log: LogFn) -> None:
        """`pip check` — the one thing --no-deps stops pip doing for us.

        Reported, never fatal. It reads installed metadata only, so it cannot
        tell a genuinely incomplete lock from an upstream package that
        declares a requirement nothing satisfies on any machine; failing the
        install over the second would be wrong. A real gap shows up loudly
        anyway in check()'s import probe.
        """
        try:
            res = proc.run(
                python + ["-m", "pip", "check"],
                lambda _m: None,
                timeout=300,
                echo=False,
            )
        except OSError:
            return
        if res.returncode != 0:
            for line in (res.stdout or "").strip().splitlines()[:5]:
                log(f"    WARNING pip check: {line[:140]}")


def _uv_env() -> dict:
    """The isolated environment, plus pip's custom CA bundle for uv."""
    from app import python_runtime

    from app.downloads import system_proxy_env

    env = python_runtime.isolated_env()
    env.update(system_proxy_env())
    if env.get("PIP_CERT") and not env.get("SSL_CERT_FILE"):
        env["SSL_CERT_FILE"] = env["PIP_CERT"]
    return env


def _uv_index_args() -> List[str]:
    """pip's index settings, which users set for mirrors, translated for uv
    (uv reads its own UV_* variables, not PIP_*)."""
    args: List[str] = []
    index = os.environ.get("PIP_INDEX_URL", "").strip()
    if index:
        args += ["--index-url", index]
    for extra in os.environ.get("PIP_EXTRA_INDEX_URL", "").split():
        args += ["--extra-index-url", extra]
    for host in os.environ.get("PIP_TRUSTED_HOST", "").split():
        args += ["--allow-insecure-host", host]
    return args


class PlaywrightStage:
    """Playwright's Chromium download.

    Separate from PythonDepsStage because the pip package and the browser
    binaries are separate downloads — having the package without the browser
    is a working import that fails at first use.
    """

    name = "playwright"
    description = "Playwright browser"
    optional = True

    def check(self, ctx: Context) -> StageResult:
        py = ctx.python()
        res = proc.run(
            py
            + [
                "-c",
                "from playwright.sync_api import sync_playwright;"
                "p=sync_playwright().start();"
                "print(p.chromium.executable_path);p.stop()",
            ],
            lambda _m: None,
            timeout=180,
        )
        if res.returncode != 0:
            return StageResult(Status.MISSING, "playwright not importable")
        path = (res.stdout or "").strip().splitlines()[-1:] or [""]
        if path[0] and os.path.exists(path[0]):
            return StageResult(Status.SATISFIED, "chromium present", {"path": path[0]})
        return StageResult(Status.MISSING, "chromium not downloaded")

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        if ctx.offline:
            return StageResult(Status.FAILED, "offline: cannot download chromium")
        res = proc.run(
            ctx.python() + ["-m", "playwright", "install", "chromium"],
            log,
            stream=True,
        )
        if res.returncode != 0:
            tail = (res.stderr or "").strip().splitlines()[-2:]
            return StageResult(
                Status.FAILED, " | ".join(tail)[:200] or "install failed"
            )
        return self.check(ctx)


class _NpmTreeStage:
    """Shared logic for the two npm trees CraftBot ships."""

    name = "npm"
    description = "npm dependencies"
    optional = True
    rel_dir = ""
    #: A file that only exists once `npm install` has succeeded.
    sentinel = "node_modules"

    def _dir(self, ctx: Context) -> Path:
        return Path(ctx.code_root) / self.rel_dir

    def check(self, ctx: Context) -> StageResult:
        d = self._dir(ctx)
        if not d.is_dir():
            return StageResult(Status.SKIPPED, f"{self.rel_dir} not present")
        reason = npm_tree_stale(str(d))
        if reason:
            return StageResult(Status.MISSING, reason)
        return StageResult(Status.SATISFIED, "node_modules current")

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        if ctx.offline:
            return StageResult(Status.FAILED, "offline: cannot npm install")
        from app import node_runtime

        npm = node_runtime.npm_cmd()
        if not npm:
            return StageResult(Status.FAILED, "no npm (Node stage must run first)")
        d = self._dir(ctx)
        if not d.is_dir():
            return StageResult(Status.SKIPPED, f"{self.rel_dir} not present")
        cmd = [npm, "install", "--no-audit", "--no-fund"]

        # A pre-warmed npm cache turns ~50 MB from the registry into local
        # reads. --prefer-offline rather than --offline: it uses the cache
        # for anything present but can still reach the registry for what is
        # not, so a partially warmed cache degrades instead of failing.
        npm_cache = os.environ.get("CRAFTBOT_NPM_CACHE", "").strip()
        if npm_cache and os.path.isdir(npm_cache):
            log(f"    using npm cache: {npm_cache}")
            cmd += ["--cache", npm_cache, "--prefer-offline"]

        # npm's lifecycle scripts spawn bare `node` through cmd.exe, which
        # resolves it from PATH. Our Node is a sidecar and is NOT on PATH, so
        # Baileys' engine-requirements.js died with "'node' is not recognized"
        # even though npm itself had been invoked by absolute path.
        # child_env() exists for exactly this and was going unused.
        res = proc.run(cmd, log, cwd=str(d), stream=True, env=node_runtime.child_env())
        if res.returncode != 0:
            return StageResult(Status.FAILED, proc.failure_detail(res, "npm failed"))
        return self.check(ctx)


class FrontendStage(_NpmTreeStage):
    """The browser UI's npm tree — only needed to BUILD it.

    An install ships a compiled dist/ and serves it statically
    (run.py::launch_frontend), so node_modules is a dev-checkout concern.
    Installing it anyway cost a large npm download over the user's network
    and, when that failed, took the whole install down for something the
    installed product never uses.
    """

    name = "frontend"
    description = "Browser frontend dependencies"
    rel_dir = os.path.join("app", "ui_layer", "browser", "frontend")
    optional = False  # browser mode is the default UI

    def check(self, ctx: Context) -> StageResult:
        prebuilt = (
            Path(ctx.code_root) / self.rel_dir / "dist" / "index.html"
        ).is_file()
        if prebuilt and not paths.is_dev_checkout():
            return StageResult(Status.SKIPPED, "prebuilt UI shipped; npm not needed")
        return super().check(ctx)

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        pre = self.check(ctx)
        if pre.status is Status.SKIPPED:
            return pre
        return super().apply(ctx, log)


class WhatsAppBridgeStage(_NpmTreeStage):
    name = "whatsapp-bridge"
    description = "WhatsApp bridge dependencies"
    rel_dir = os.path.join("craftos_integrations", "providers", "whatsapp_web")
    optional = True
