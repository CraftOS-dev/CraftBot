"""Provision and check both framework CLIs, independently of installing an app."""

import subprocess
import zipfile
from pathlib import Path

from app import agent_app_package, node_runtime
from app.provision import proc
from app.provision.default_agent_app import bundled_toolkits
from app.provision.types import Context, LogFn, StageResult, Status


class AgentAppFrameworkStage:
    name = "agent-app-framework"
    description = "Agent-App, A2App, skills and toolkits"
    optional = False

    def check(self, ctx: Context) -> StageResult:
        try:
            package = agent_app_package.cached_package(
                Path(ctx.code_root), Path(ctx.state_root)
            )
            if package is None:
                return StageResult(
                    Status.MISSING, "bundled framework has not been unpacked"
                )
            toolkits = bundled_toolkits(
                Path(ctx.code_root), Path(ctx.state_root), create=False
            )
            if toolkits is None:
                return StageResult(
                    Status.MISSING, "bundled toolkits have not been unpacked"
                )
            runtime = node_runtime.resolve()
            if runtime is None:
                return StageResult(Status.MISSING, "Node stage must complete first")
            for name in ("agent-app", "a2app"):
                result = proc.run(
                    [runtime.node, str(package / "bin" / f"{name}.js"), "--help"],
                    cwd=str(package),
                    timeout=30,
                    env=node_runtime.child_env(),
                    echo=False,
                )
                if result.returncode != 0 or not result.stdout.strip():
                    return StageResult(
                        Status.DEGRADED,
                        proc.failure_detail(result, f"{name} could not start"),
                    )
        except (
            OSError,
            ValueError,
            zipfile.BadZipFile,
            subprocess.SubprocessError,
        ) as exc:
            return StageResult(Status.DEGRADED, str(exc))
        return StageResult(
            Status.SATISFIED,
            "agent-app and a2app run; pinned dependencies, skills and toolkits verified",
            {"package": str(package), "toolkits": str(toolkits)},
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        try:
            agent_app_package.ensure_package(Path(ctx.code_root), Path(ctx.state_root))
            bundled_toolkits(Path(ctx.code_root), Path(ctx.state_root))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return StageResult(Status.FAILED, str(exc))
        return self.check(ctx)
