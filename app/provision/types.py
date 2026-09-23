"""Stage protocol shared by every install path.

The contract that makes "one path" real: a stage answers two questions and
nothing else.

    check()  — is this already satisfied? Cheap, no side effects, safe to call
               on a broken install.
    apply()  — make it so. Idempotent: running it on a satisfied system is a
               no-op, not a reinstall.

Everything else follows from that separation:

  * `python install.py` runs check+apply over the pipeline.
  * `craftbot.py install` runs the same pipeline, then registers auto-start.
  * The installer wizard runs the same pipeline with its progress bar bound
    to the log callback.
  * `repair` is the pipeline again — every check() re-runs and only the
    unsatisfied stages do work.
  * `doctor` is check() alone, printed.

So a fix to a stage reaches all four at once, which is the property the three
entry points have never had.
"""

from __future__ import annotations

import enum
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

# Progress/diagnostic sink. print for CLI, a push-to-webview for the wizard.
LogFn = Callable[[str], None]


class Status(enum.Enum):
    """Outcome of check(), and of apply()."""

    SATISFIED = "satisfied"  # nothing to do
    MISSING = "missing"  # not present; apply() should fix it
    DEGRADED = "degraded"  # present but wrong (bad version, partial install)
    FAILED = "failed"  # apply() tried and could not
    SKIPPED = "skipped"  # not applicable in this context (e.g. conda mode)

    @property
    def ok(self) -> bool:
        return self in (Status.SATISFIED, Status.SKIPPED)


@dataclass
class StageResult:
    status: Status
    detail: str = ""
    # Free-form facts worth surfacing in a report or a bug: resolved paths,
    # versions, counts. Kept JSON-safe so `doctor` can emit it directly.
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status.ok


@dataclass
class Context:
    """Everything a stage needs to know, resolved once by the caller.

    Passed rather than imported so tests can drive a stage against a temp
    directory, and so the wizard can provision into a chosen location without
    the stage caring which entry point invoked it.
    """

    code_root: str
    state_root: str
    # None in dev/pip mode; the env name when installing into conda.
    conda_env: Optional[str] = None
    # Command prefix for the interpreter that will RUN CraftBot — not
    # necessarily the one running the installer. install.py's long-standing
    # bug class is these two diverging (deps land in one site-packages, the
    # service starts on another), so it is explicit here.
    # A LIST, not a path, because conda's interpreter is
    # ["conda", "run", "-n", env, "python"] — several tokens, not a file.
    service_python: Optional[List[str]] = None
    # Skip work that needs the network; used by --offline and by tests.
    offline: bool = False

    def python(self) -> List[str]:
        """The interpreter command every stage should install into and probe.

        Lives here rather than on each stage: four stages had an identical
        private copy of this, which is three too many, and the context is
        what actually knows the answer. PythonStage writes service_python
        back onto the context, so everything downstream agrees by
        construction instead of by convention.
        """
        return list(self.service_python or [sys.executable])


class Stage(Protocol):
    """A unit of provisioning."""

    name: str
    #: Human-readable one-liner shown in progress output.
    description: str
    #: When False, a FAILED result stops the pipeline. Node is not required
    #: for core chat, so it is optional; Python dependencies are not.
    optional: bool

    def check(self, ctx: Context) -> StageResult: ...

    def apply(self, ctx: Context, log: LogFn) -> StageResult: ...


@dataclass
class PipelineReport:
    results: List[tuple] = field(default_factory=list)  # (stage_name, StageResult)

    @property
    def ok(self) -> bool:
        return all(r.ok for _, r in self.results)

    @property
    def failures(self) -> List[tuple]:
        return [(n, r) for n, r in self.results if not r.ok]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "stages": [
                {
                    "name": name,
                    "status": res.status.value,
                    "detail": res.detail,
                    "data": res.data,
                }
                for name, res in self.results
            ],
        }
