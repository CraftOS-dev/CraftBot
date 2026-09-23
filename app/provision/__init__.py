"""One provisioning pipeline for every install path.

    from app import provision
    report = provision.install(log=print)

`install.py`, `craftbot.py install` and the installer wizard all call this.
That is the entire point: a fix to a stage reaches all three at once, which is
the property they have never had. The differences between the entry points are
what they do *around* the pipeline (auto-start registration, a progress bar),
never what they provision.

Order matters and is expressed once, here:

  disk        → enough free space to finish at all
  python      → the interpreter everything else installs into
  python-deps → the locked package set
  native      → prove the embedding stack loads (not merely installed)
  smoke       → prove what actions import is importable
  node        → the one Node runtime
  frontend    → browser UI's npm tree (default UI, so required)
  whatsapp    → bridge's npm tree
  playwright  → chromium for browser-automation actions

Node comes after Python deps because nothing before it needs Node, and a slow
optional download should not delay the failure of a required stage.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from app import paths
from app.provision.deps import (
    FrontendStage,
    PlaywrightStage,
    PythonDepsStage,
    WhatsAppBridgeStage,
)
from app.provision.pipeline import format_report, run
from app.provision.runtimes import NodeStage, PythonStage
from app.provision.types import (
    Context,
    LogFn,
    PipelineReport,
    Stage,
    StageResult,
    Status,
)
from app.provision.verify import DiskSpaceStage, NativeRuntimeStage, SmokeStage

__all__ = [
    "Context",
    "PipelineReport",
    "Stage",
    "StageResult",
    "Status",
    "default_stages",
    "default_context",
    "install",
    "doctor",
    "format_report",
]


def default_stages() -> List[Stage]:
    return [
        # First: a precondition, not a provisioning step. Cheap, and failing
        # here beats failing three downloads later with an ENOSPC.
        DiskSpaceStage(),
        PythonStage(),
        PythonDepsStage(),
        NativeRuntimeStage(),
        SmokeStage(),
        NodeStage(),
        FrontendStage(),
        WhatsAppBridgeStage(),
        PlaywrightStage(),
    ]


def default_context(
    service_python: Optional[List[str]] = None,
    conda_env: Optional[str] = None,
    offline: bool = False,
) -> Context:
    return Context(
        code_root=str(paths.CODE_ROOT),
        state_root=str(paths.STATE_ROOT),
        conda_env=conda_env,
        service_python=list(service_python) if service_python else [sys.executable],
        offline=offline,
    )


def install(
    log: Optional[LogFn] = None,
    ctx: Optional[Context] = None,
    stages: Optional[List[Stage]] = None,
) -> PipelineReport:
    """Provision everything. Idempotent — safe to re-run, which is what makes
    `repair` the same code path as a first install."""
    return run(stages or default_stages(), ctx or default_context(), log=log)


def doctor(
    log: Optional[LogFn] = None,
    ctx: Optional[Context] = None,
    stages: Optional[List[Stage]] = None,
) -> PipelineReport:
    """Report what is and is not satisfied, changing nothing."""
    return run(
        stages or default_stages(), ctx or default_context(), log=log, check_only=True
    )
