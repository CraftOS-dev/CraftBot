"""Run a list of stages. The one place install ordering is expressed."""

from __future__ import annotations

import sys
from typing import Iterable, List, Optional

from app.provision.types import (
    Context,
    LogFn,
    PipelineReport,
    Stage,
    StageResult,
    Status,
)


def run(
    stages: Iterable[Stage],
    ctx: Context,
    log: Optional[LogFn] = None,
    check_only: bool = False,
) -> PipelineReport:
    """Check each stage and apply the ones that need it.

    A required stage that fails stops the run: continuing past a failed
    dependency install only produces a second, more confusing error further
    down. Optional stages (Node, Playwright) record the failure and continue —
    core chat works without them, and taking the whole install down for a
    feature the user may never touch is worse than a warning.
    """
    say: LogFn = safe_log(log)
    report = PipelineReport()

    for stage in stages:
        try:
            before = stage.check(ctx)
        except Exception as e:  # a broken check must not abort the install
            before = StageResult(
                Status.DEGRADED, f"check raised {type(e).__name__}: {e}"
            )

        if check_only or before.ok:
            report.results.append((stage.name, before))
            _report_line(say, stage, before, applied=False)
            if not check_only and not before.ok:
                break
            continue

        say(f"  {_marks()[Status.MISSING]} {stage.description}")
        try:
            after = stage.apply(ctx, say)
        except Exception as e:
            after = StageResult(Status.FAILED, f"{type(e).__name__}: {e}")

        report.results.append((stage.name, after))
        _report_line(say, stage, after, applied=True)

        if not after.ok and not stage.optional:
            say(f"  ✗ {stage.name} is required — stopping.")
            break

    return report


_MARKS_UNICODE = {
    Status.SATISFIED: "✓",
    Status.SKIPPED: "–",
    Status.MISSING: "…",
    Status.DEGRADED: "!",
    Status.FAILED: "✗",
}
_MARKS_ASCII = {
    Status.SATISFIED: "OK",
    Status.SKIPPED: "--",
    Status.MISSING: "..",
    Status.DEGRADED: "!!",
    Status.FAILED: "XX",
}


def _stream_encoding() -> str:
    return getattr(sys.stdout, "encoding", None) or "ascii"


def _encodable(text: str) -> bool:
    try:
        text.encode(_stream_encoding())
        return True
    except (LookupError, UnicodeEncodeError):
        return False


def _marks() -> dict:
    """Windows consoles still default to cp1252, which cannot encode these
    glyphs — printing one raises UnicodeEncodeError and takes the install down
    for the sake of a tick mark. Probe the actual stream instead of assuming.
    """
    return (
        _MARKS_UNICODE if _encodable("".join(_MARKS_UNICODE.values())) else _MARKS_ASCII
    )


def safe_log(log: Optional[LogFn]) -> LogFn:
    """Wrap a log sink so no message can kill the install by being unprintable.

    Stage detail comes from subprocess output — pip, npm, node — which is not
    ASCII and not under our control, and the console encoding is not either.
    Sanitising every line in one place beats discovering each offending glyph
    the way this function was written: by crashing on one.
    """
    say: LogFn = log or (lambda _m: None)

    def _emit(message: str) -> None:
        try:
            say(message)
        except UnicodeEncodeError:
            enc = _stream_encoding()
            say(message.encode(enc, errors="replace").decode(enc, errors="replace"))

    return _emit


def _report_line(say: LogFn, stage: Stage, res: StageResult, applied: bool) -> None:
    mark = _marks()[res.status]
    suffix = f" — {res.detail}" if res.detail else ""
    if res.status is Status.SATISFIED and not applied:
        say(f"  {mark} {stage.description} (already done){suffix}")
    else:
        say(f"  {mark} {stage.description}{suffix}")


def format_report(report: PipelineReport) -> str:
    """Human-readable summary, used by `doctor` and by failure output."""
    lines: List[str] = []
    width = max((len(n) for n, _ in report.results), default=0)
    for name, res in report.results:
        detail = f"  {res.detail}" if res.detail else ""
        lines.append(f"  {name.ljust(width)}  {res.status.value}{detail}")
    if report.failures:
        lines.append("")
        lines.append(f"  {len(report.failures)} stage(s) need attention")
    return "\n".join(lines)
