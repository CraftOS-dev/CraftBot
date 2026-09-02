#!/usr/bin/env python3
"""Download every locked wheel into a folder, for fast or offline installs.

Two uses:

1. **Testing.** A clean-machine test spends almost all its time downloading
   ~2 GB of packages. In Windows Sandbox, over a NAT'd connection, that is
   slow enough to look like a hang and slow enough to discourage re-testing —
   which is how install bugs survive. Map a wheelhouse in and the same
   install runs from local files in a couple of minutes.

2. **Offline installs.** Same mechanism serves an air-gapped machine: ship
   the wheelhouse alongside the payload and nothing needs PyPI.

The provisioning pipeline picks it up automatically:
  * $CRAFTBOT_WHEELHOUSE, or
  * <code root>/wheelhouse
and then installs with --no-index --find-links, so pip cannot silently reach
the network and mask a missing wheel.

Wheels are per platform AND per Python version, exactly like the lock they
come from. A wheelhouse built on Windows cannot serve a Linux install.

Usage:
    python scripts/build_wheelhouse.py
    python scripts/build_wheelhouse.py --output D:\\craftbot-wheels
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    from app.provision.deps import _lock_tag, find_lock

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "wheelhouse"),
        help="where to put the wheels (default: <repo>/wheelhouse)",
    )
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter whose platform/version the wheels must match",
    )
    args = ap.parse_args()

    lock = find_lock(str(REPO_ROOT), [args.python])
    if lock is None:
        print(
            f"error: no lock for {_lock_tag([args.python])}.\n"
            "Generate it first: python scripts/generate_lock.py",
            file=sys.stderr,
        )
        return 1

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    print(f"lock  : {lock.name}")
    print(f"target: {out}")
    print("Downloading — this is the whole dependency set, so expect GBs.\n")

    # `pip download` resolves and fetches without installing. --require-hashes
    # is implied by the lock's own directives, so a tampered wheel fails here
    # rather than on the user's machine.
    proc = subprocess.run(
        [
            args.python,
            "-u",
            "-m",
            "pip",
            "download",
            "--no-color",
            "--progress-bar",
            "off",
            "--dest",
            str(out),
            "-r",
            str(lock),
        ],
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        print("\npip download failed", file=sys.stderr)
        return proc.returncode

    # The lock is not the whole story. Nine of its entries have no wheel and
    # are built from sdist at install time, and an isolated PEP 517 build
    # fetches its OWN dependencies — setuptools and wheel — from the index.
    # With --no-index that fetch fails, so an otherwise complete wheelhouse
    # dies on the first sdist with:
    #     ERROR: No matching distribution found for wheel
    # setuptools usually arrives as somebody's transitive dependency; wheel
    # does not, which is why this failed on exactly one package.
    print("\nAdding build backends (needed to build the sdists offline)...")
    build_deps = subprocess.run(
        [
            args.python,
            "-u",
            "-m",
            "pip",
            "download",
            "--no-color",
            "--progress-bar",
            "off",
            "--dest",
            str(out),
            "setuptools",
            "wheel",
        ],
        cwd=str(REPO_ROOT),
    )
    if build_deps.returncode != 0:
        print("\nfailed to fetch build backends", file=sys.stderr)
        return build_deps.returncode

    files = list(out.glob("*"))
    size = sum(f.stat().st_size for f in files if f.is_file()) / (1024 * 1024)
    print(f"\n{len(files)} files, {size:.0f} MB in {out}")
    print("\nTo use it, either:")
    print(f"  set CRAFTBOT_WHEELHOUSE={out}")
    print("  or map it into the test machine and set the variable there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
