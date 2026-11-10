"""Install the bundled CLI offline, independently of installing any app."""

from pathlib import Path

from app import agent_app_package
from app.provision.types import Context, LogFn, StageResult, Status


class AgentAppFrameworkStage:
    name = "agent-app-framework"
    description = "Agent-App framework CLI"
    optional = True  # Core chat still works if this feature cannot be provisioned.

    def check(self, ctx: Context) -> StageResult:
        try:
            package = agent_app_package.cached_package(
                Path(ctx.code_root), Path(ctx.state_root)
            )
        except (OSError, ValueError) as exc:
            return StageResult(Status.DEGRADED, str(exc))
        if package is None:
            return StageResult(Status.MISSING, "bundled CLI has not been unpacked")
        return StageResult(
            Status.SATISFIED, "pinned CLI verified", {"package": str(package)}
        )

    def apply(self, ctx: Context, log: LogFn) -> StageResult:
        try:
            package = agent_app_package.ensure_package(
                Path(ctx.code_root), Path(ctx.state_root)
            )
        except (OSError, ValueError) as exc:
            return StageResult(Status.FAILED, str(exc))
        return StageResult(
            Status.SATISFIED, "pinned CLI unpacked", {"package": str(package)}
        )
