"""Which lock file an interpreter must install from.

Stdlib-only, and shared by the two places that need it — app.provision.deps
(reads locks) and scripts/generate_lock.py (writes them). They each had their
own copy, and a name only has to agree with itself to be useless: the reader
and the writer must derive it the same way or a committed lock is invisible.

## Why this is not just sysconfig.get_platform()

That is the platform the interpreter was BUILT for, which on macOS is its
deployment target and whether it is a fat binary — neither of which says
anything about the wheels it can install. Two Pythons on one Apple Silicon
Mac, both able to install exactly the same arm64 wheels:

    python-build-standalone   macosx-11.0-arm64      -> lock-macosx_11_0_arm64
    python.org universal2     macosx-10.9-universal2 -> lock-macosx_10_9_universal2

find_lock matches the filename exactly and on purpose (a Linux lock pins CUDA
torch, so falling back to a near-miss fails later and more confusingly). So
the second interpreter reported "no lock file for macosx_10_9_universal2" at
a repo that had a perfectly good macOS lock committed, and the only fix on
offer was to generate a second one that no other Mac would ever select.

What actually decides which wheels install is the ARCHITECTURE of the running
process, so that is what macOS locks are keyed on. Rosetta is handled for
free: an x86_64 process on an M-series Mac reports x86_64 from
platform.machine() and gets the x86_64 lock, which is correct — it needs
x86_64 wheels.

Windows and Linux keep sysconfig's tag unchanged. It carries no
deployment-target component there, so it is already stable across
interpreters (win_amd64, linux_x86_64).
"""

from __future__ import annotations

import platform
import sys
import sysconfig

#: Run in ANOTHER interpreter to collect what build() needs. Must be kept in
#: step with build()'s signature — that is the whole reason both live here.
PROBE = (
    "import platform,sys,sysconfig;"
    "print(sysconfig.get_platform(), platform.machine(),"
    " sys.version_info[0], sys.version_info[1])"
)


def build(raw_platform: str, machine: str, major: int, minor: int) -> str:
    """The lock tag for an interpreter described by PROBE's four fields."""
    plat = raw_platform.replace(".", "_").replace("-", "_")
    if plat.startswith("macosx"):
        arch = "arm64" if machine.lower() in ("arm64", "aarch64") else "x86_64"
        plat = f"macosx_{arch}"
    return f"{plat}-py{major}{minor}"


def current() -> str:
    """The lock tag for the interpreter running this code."""
    return build(
        sysconfig.get_platform(),
        platform.machine(),
        sys.version_info.major,
        sys.version_info.minor,
    )


def parse_probe(output: str) -> str:
    """The lock tag from PROBE's stdout, as run in another interpreter."""
    raw_plat, machine, major, minor = output.strip().split()[-4:]
    return build(raw_plat, machine, int(major), int(minor))
