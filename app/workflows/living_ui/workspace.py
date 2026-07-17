# -*- coding: utf-8 -*-
"""Workspace — the coding agent's project sandbox (Brick 2).

Owns ONE project directory and the ground-truth operations over it. The
principles from CODING_AGENT_PLAN.md live here:

- **Nothing is off-limits.** read/write ANY file, run ANY command. There is
  no "system-managed" file the agent can't fix — that was a top failure mode
  (a broken platform file the agent couldn't touch, e.g. `lib/utils.ts`).
- **Ground truth, not proxies.** `build()` runs the real build and returns
  its real errors; "does it build" is a fact, not an inference.
- **Root cause, not symptoms.** build errors are parsed into STRUCTURED
  `BuildError`s and grouped by cause, so 590 identical
  "Cannot find module '@/lib/utils'" lines collapse to ONE thing to fix.

A plain synchronous object — no framework/async deps — so it is unit-testable
in isolation. The async agent loop wraps calls in a thread when it needs to.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Union

# The template's legible dev-React build: unminified + development React, so
# runtime errors name the component instead of "#300".
DEFAULT_BUILD_CMD = "npm run build:debug"


def certifi_ssl_env() -> dict:
    """SSL CA bundle env for project subprocesses. Some environments can't
    load the OS cert store from Python — without these vars any HTTPS fetch
    inside a project command dies with SSL errors. Fail-silent.

    The single implementation — manager._run_pipeline_command and
    Workspace.run both inject it, so 'works via the pipeline, fails via
    verify_build' cannot happen for TLS reasons."""
    try:
        import certifi

        ca = certifi.where()
        return {"SSL_CERT_FILE": ca, "REQUESTS_CA_BUNDLE": ca}
    except Exception:
        return {}


@dataclass
class RunResult:
    """Outcome of a shell command run inside the workspace."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        """stdout + stderr, trimmed — what a human would read in the terminal."""
        joined = self.stdout
        if self.stderr:
            joined = f"{joined}\n{self.stderr}" if joined else self.stderr
        return joined.strip()


@dataclass
class BuildError:
    """One structured compiler/build error (currently TypeScript `tsc`)."""

    file: str
    line: int
    col: int
    code: str  # e.g. "TS2307"
    message: str
    raw: str

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"

    @property
    def cause_key(self) -> str:
        """Errors sharing this key have the SAME root cause. The message is
        identical across files for the same underlying problem (e.g. every
        file that can't resolve `@/lib/utils` yields the same message), so
        exact code+message grouping collapses a cascade to its one cause."""
        return f"{self.code}: {self.message}"


@dataclass
class BuildResult:
    """Structured result of a build/typecheck — ok plus grouped errors."""

    ok: bool
    errors: List[BuildError]
    raw: str  # tail of the raw output, for anything the parser missed

    def grouped(self) -> List[Tuple[str, List[BuildError]]]:
        """Errors grouped by root cause, most-frequent first (the biggest
        group is almost always the real root — fix it once, re-build)."""
        groups: Dict[str, List[BuildError]] = {}
        for e in self.errors:
            groups.setdefault(e.cause_key, []).append(e)
        return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


# tsc: "path/to/file.tsx(12,20): error TS2307: Cannot find module 'x'"
_TSC_RE = re.compile(r"^(.+?)\((\d+),(\d+)\):\s*error\s+(TS\d+):\s*(.+)$")


class Workspace:
    """One project directory the agent fully owns."""

    def __init__(
        self, path: Union[str, Path], build_cmd: str = DEFAULT_BUILD_CMD
    ) -> None:
        self.path = Path(path)
        self.build_cmd = build_cmd

    # ── ground truth ────────────────────────────────────────────────────────
    def run(self, cmd: str, timeout: int = 600) -> RunResult:
        """Run a shell command in the project root. Never raises — a timeout or
        launch failure comes back as a non-ok RunResult."""
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.path),
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **certifi_ssl_env()},
            )
            return RunResult(
                ok=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
            )
        except subprocess.TimeoutExpired as e:
            return RunResult(
                ok=False,
                exit_code=-1,
                stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
                stderr=f"command timed out after {timeout}s",
            )

    def build(self) -> BuildResult:
        """Run the project's real build (tsc + vite) and return structured
        errors — the source of truth for 'does it compile'.

        Guarded against a mid-flight npm install: tsc against a half-extracted
        node_modules reports phantom "Cannot find module" errors on system
        files (the R27 590-error cascade), steering the agent into fixing
        symptoms of nothing. Fail-open: if the guard itself can't run, build."""
        try:
            from app.living_ui.type_check import _install_incomplete

            if _install_incomplete(self.path):
                return BuildResult(
                    ok=False,
                    errors=[],
                    raw=(
                        "npm install is still in progress (or has never "
                        "completed) for this project — the build cannot be "
                        "verified yet. Wait for the install to finish, then "
                        "build again. Do NOT start fixing 'Cannot find "
                        "module' errors from this state; they are phantoms "
                        "of the incomplete install."
                    ),
                )
        except Exception:
            pass
        return self._as_build_result(self.run(self.build_cmd))

    @classmethod
    def _as_build_result(cls, r: RunResult) -> BuildResult:
        errors = cls._parse_build_errors(r.output)
        # ok only when the command succeeded AND no errors were parsed.
        return BuildResult(ok=r.ok and not errors, errors=errors, raw=r.output[-4000:])

    @staticmethod
    def _parse_build_errors(output: str) -> List[BuildError]:
        errs: List[BuildError] = []
        for line in output.splitlines():
            m = _TSC_RE.match(line.strip())
            if m:
                errs.append(
                    BuildError(
                        file=m.group(1).strip(),
                        line=int(m.group(2)),
                        col=int(m.group(3)),
                        code=m.group(4),
                        message=m.group(5).strip(),
                        raw=line.strip(),
                    )
                )
        return errs
