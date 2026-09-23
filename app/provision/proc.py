"""Running commands, once.

Every stage shells out, and each had grown its own runner: two `_run`
functions with different signatures, one of which streamed and one of which
did not, plus a hand-rolled stand-in for CompletedProcess. Same job, three
implementations, and the differences between them were accidents rather than
decisions.

One function, one set of behaviours:

  * no console window flashes on Windows (console=False parents make every
    child pop a window otherwise),
  * output can stream to a log as it happens, because a silent ten-minute
    install is indistinguishable from a hung one,
  * children get an environment that makes them line-buffer, since a Python
    child writing to a pipe otherwise withholds ~8KB before flushing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, Iterable, List, Optional, Sequence

LogFn = Callable[[str], None]

#: Line prefixes worth surfacing while a long command runs. pip and npm are
#: both far too verbose to echo wholesale into a UI panel, but these show
#: forward motion, and anything with an error marker explains a failure.
PROGRESS_PREFIXES = (
    "Collecting",
    "Downloading",
    "Using cached",
    "Installing",
    "Building",
    "Successfully",
    "Saved",
    "added",
    "changed",
    "audited",
    "npm",
    "ERROR",
    "WARNING",
)


def _no_window_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _is_interesting(line: str) -> bool:
    return line.startswith(PROGRESS_PREFIXES) or "ERR!" in line


def run(
    cmd: Sequence[str],
    log: Optional[LogFn] = None,
    cwd: Optional[str] = None,
    timeout: int = 3600,
    stream: bool = False,
    env: Optional[dict] = None,
    echo: bool = True,
) -> subprocess.CompletedProcess:
    """Run cmd and return a CompletedProcess.

    stream=True for anything long: its output is echoed to `log` as it
    arrives and also captured, so a failure can still be explained
    afterwards. Without it, capture_output holds everything until the
    process exits.
    """
    say: LogFn = log or (lambda _m: None)
    argv: List[str] = [str(c) for c in cmd]
    if echo:
        head = " ".join(argv[:6])
        say(f"    $ {head}{' ...' if len(argv) > 6 else ''}")

    if not stream:
        return subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            **_no_window_kwargs(),
        )

    child_env = dict(env if env is not None else os.environ)
    # A Python child writing to a pipe block-buffers; without this, pip says
    # nothing for minutes on a slow connection and the install looks hung.
    child_env.setdefault("PYTHONUNBUFFERED", "1")
    child_env.setdefault("PYTHONIOENCODING", "utf-8")

    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        env=child_env,
        **_no_window_kwargs(),
    )
    lines: List[str] = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            lines.append(line)
            if _is_interesting(line):
                say(f"      {line[:160]}")
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return subprocess.CompletedProcess(argv, 1, "\n".join(lines), "timed out")

    return subprocess.CompletedProcess(argv, proc.returncode or 0, "\n".join(lines), "")


def python(
    interpreter: Iterable[str],
    code: str,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Run a snippet in another interpreter and capture the result."""
    return run(list(interpreter) + ["-c", code], timeout=timeout, echo=False)


def failure_detail(res: subprocess.CompletedProcess, fallback: str) -> str:
    """The lines of a failed command that explain WHY.

    Two things this gets right that the obvious version does not. Streaming
    merges stderr into stdout, so reading only stderr yields an empty string
    and a message that says nothing. And npm prints "npm warn cleanup" lines
    containing the word Error, which outrank the real cause if you match on
    "error" alone - a genuine failure was once reported as an unrelated
    rmdir EPERM while "'node' is not recognized" scrolled past unmentioned.
    """
    text = "\n".join(filter(None, [res.stdout or "", res.stderr or ""]))
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return fallback

    hard = [ln for ln in lines if "npm error" in ln.lower() or "ERR!" in ln]
    if not hard:
        hard = [
            ln
            for ln in lines
            if ln.lower().startswith(("error", "fatal")) or "error:" in ln.lower()
        ]
    # npm and pip both put the command and its message at the END of the
    # error block, so take the tail rather than the head.
    chosen = hard[-4:] if hard else lines[-3:]
    return " | ".join(ln.strip()[:200] for ln in chosen)
