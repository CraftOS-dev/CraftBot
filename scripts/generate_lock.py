#!/usr/bin/env python3
"""Generate a hash-pinned lock file from requirements.txt.

Every install path — pip, conda, and the installer — must install the same
set, and that is only possible if the set is written down. requirements.txt
declares 56 packages; the real closure is 239.

Uses pip's own resolver via `--dry-run --report`, so it needs no lock tool
(uv / pip-tools) in the build environment.

Locks are PER PLATFORM AND PYTHON VERSION and are not interchangeable:
`torch==X` means CPU wheels on Windows and CUDA libraries on Linux, so each
one has to be generated on the platform it describes.

Usage:
    python scripts/generate_lock.py                  # write this platform's lock
    python scripts/generate_lock.py --check          # verify committed locks
    python scripts/generate_lock.py --retag          # re-stamp unchanged locks

## What --check means

That every committed lock was generated from the CURRENT requirements.txt —
compared by the source digest in each lock's header, not by re-resolving.

Re-resolving would be wrong. requirements.txt is unpinned, so a fresh resolve
picks up whatever upstream published since, and the check would report STALE
because `fonttools` shipped a patch release overnight. That makes the check
permanently red and, if CI acted on it, would bump all 239 packages on every
run — the opposite of what a lock is for.

Stale therefore means "someone edited requirements.txt without regenerating",
which is the thing worth catching. Upgrading dependencies is a deliberate act:
run this script without --check.

## What --retag means

One edit to requirements.txt does not change the resolved set at all: making
an existing transitive dependency direct. The package and version are already
in the lock, so there is nothing to re-resolve — only the digest is stale.
--retag re-stamps the digest after verifying, offline, that every declared
requirement is already pinned in every lock; if one is not, it refuses.

Use it for that case only. Regenerating instead would bump every unrelated
package to whatever the index serves today, and would fix just one platform.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
from typing import Dict, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(REPO_ROOT, "requirements.txt")
LOCK_DIR = os.path.join(REPO_ROOT, "requirements")

#: Platforms a release ships an installer for, as lock-filename prefixes.
#: Matched by prefix because the macOS tag carries an OS version and arch
#: (macosx_11_0_arm64-py310), so the exact filename is not fixed.
#:
#: Keep in step with the launcher matrix in .github/workflows/release.yml.
SHIPPED_PLATFORMS = ("win_amd64", "linux_x86_64", "macosx")


def lock_tag() -> str:
    """Identify the (platform, python) this lock is valid for.

    sysconfig's platform tag rather than sys.platform: it distinguishes
    macosx arm64 from x86_64, which matters because the wheels differ.
    """
    plat = sysconfig.get_platform().replace(".", "_").replace("-", "_")
    py = f"py{sys.version_info.major}{sys.version_info.minor}"
    return f"{plat}-{py}"


def lock_path() -> str:
    return os.path.join(LOCK_DIR, f"lock-{lock_tag()}.txt")


def resolve() -> List[dict]:
    """Ask pip to resolve requirements.txt without installing anything."""
    fd, report = tempfile.mkstemp(suffix=".json", prefix="craftbot-lock-")
    os.close(fd)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--quiet",
                "--report",
                report,
                "-r",
                REQUIREMENTS,
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout + proc.stderr)
            raise SystemExit(f"pip resolution failed ({proc.returncode})")
        with io.open(report, encoding="utf-8") as fh:
            return json.load(fh).get("install", [])
    finally:
        try:
            os.unlink(report)
        except OSError:
            pass


def render(entries: List[dict]) -> str:
    """Render a pip --require-hashes compatible lock."""
    rows: Dict[str, List[str]] = {}
    for item in entries:
        meta = item.get("metadata", {})
        name = (meta.get("name") or "").strip()
        version = (meta.get("version") or "").strip()
        if not name or not version:
            continue
        hashes = item.get("download_info", {}).get("archive_info", {}).get("hashes", {})
        sha = hashes.get("sha256")
        key = f"{name}=={version}"
        rows.setdefault(key, [])
        if sha:
            rows[key].append(f"sha256:{sha}")

    unhashed = [k for k, v in rows.items() if not v]
    if unhashed:
        raise SystemExit(
            "Cannot lock — no sha256 for: "
            + ", ".join(sorted(unhashed))
            + "\n--require-hashes needs every entry hashed."
        )

    out = [
        "# GENERATED by scripts/generate_lock.py — do not edit by hand.",
        "# Regenerate with: python scripts/generate_lock.py",
        "#",
        f"# Valid ONLY for: {lock_tag()}",
        "# Locks are per platform+python: torch means CPU wheels on Windows and",
        "# CUDA libraries on Linux, so one lock cannot serve every runner.",
        "#",
        f"# Source: requirements.txt ({_source_digest()})",
        f"# Packages: {len(rows)}",
        "",
        "--require-hashes",
        "",
    ]
    for key in sorted(rows, key=str.lower):
        joined = " \\\n    ".join(f"--hash={h}" for h in sorted(rows[key]))
        out.append(f"{key} \\\n    {joined}")
    return "\n".join(out) + "\n"


def _source_digest() -> str:
    with io.open(REQUIREMENTS, encoding="utf-8") as fh:
        body = "".join(
            line.strip()
            for line in fh
            if line.strip() and not line.strip().startswith("#")
        )
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()[:16]


def _normalize(name: str) -> str:
    """PEP 503 name normalization, so Pillow/pillow and mail_parser/mail-parser
    are not mistaken for different packages."""
    return re.sub(r"[-_.]+", "-", name).lower()


#: `name==version` at the start of a lock entry. The renderer always writes a
#: space before the line-continuation backslash, so the version never carries
#: one and there is nothing to strip.
_PIN_RE = re.compile(r"^([A-Za-z0-9._-]+)==([^ \t]+)")


def _lock_pins(path: str) -> Dict[str, str]:
    """The normalized name -> pinned version map a lock file declares."""
    pins: Dict[str, str] = {}
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            match = _PIN_RE.match(line)
            if match:
                pins[_normalize(match.group(1))] = match.group(2)
    return pins


def _retag_committed_locks() -> int:
    """Re-stamp the committed locks with the current requirements digest.

    For the one case where requirements.txt changed but the RESOLVED SET did
    not: a package already in the closure as a transitive dependency is
    promoted to a direct declaration. The digest goes stale, --check fails,
    and the obvious fix — regenerate — is the wrong one twice over. A
    regenerate re-resolves against today's index and bumps a hundred unrelated
    packages (the drift this module's docstring warns about), and it can only
    write THIS platform's lock, so the other platforms would stay red with no
    machine to fix them from.

    Retagging is only honest if the locks really do still cover
    requirements.txt, so that is verified first, offline and with no resolve:
    every declared requirement must already be pinned in every lock at a
    version its specifier accepts. If one is not, the closure genuinely
    changed and no amount of re-stamping can cover it — this refuses and
    sends you to a real regenerate.

    Deliberately NOT an error: a requirement REMOVED from requirements.txt
    leaves its package pinned, so the lock stays a superset of what is
    declared. That installs something no longer asked for, which is worth
    saying out loud but is not the kind of wrong that breaks an install.
    """
    try:
        from packaging.requirements import Requirement
    except ImportError:
        print("--retag needs the `packaging` package: pip install packaging")
        return 1

    declared = []
    with io.open(REQUIREMENTS, encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                declared.append(Requirement(text))
            except Exception as exc:
                print(f"UNPARSEABLE requirement {text!r}: {exc}")
                return 1

    locks = sorted(glob.glob(os.path.join(LOCK_DIR, "lock-*.txt")))
    if not locks:
        print("MISSING: no lock files at all — run this script without --check")
        return 1

    # Verify BEFORE touching anything: a partial retag would leave the locks
    # disagreeing with each other about which requirements.txt they came from.
    blocked: List[str] = []
    for path in locks:
        name = os.path.relpath(path, REPO_ROOT)
        pins = _lock_pins(path)
        for req in declared:
            key = _normalize(req.name)
            if key not in pins:
                blocked.append(f"{name}: {req.name} is not pinned in this lock")
            elif req.specifier and not req.specifier.contains(
                pins[key], prereleases=True
            ):
                blocked.append(f"{name}: {req} not satisfied by {pins[key]}")

    if blocked:
        print("Cannot retag — the resolved set really did change:")
        for line in blocked:
            print(f"  {line}")
        print()
        print("Run `python scripts/generate_lock.py` on each affected platform.")
        return 1

    digest = _source_digest()
    retagged = 0
    for path in locks:
        name = os.path.relpath(path, REPO_ROOT)
        with io.open(path, encoding="utf-8") as fh:
            body = fh.read()
        new_body, count = re.subn(
            r"^# Source: requirements\.txt \(sha256:[0-9a-f]+\)$",
            # A function replacement, so nothing in the digest can be read as
            # a backreference.
            lambda _m: f"# Source: requirements.txt ({digest})",
            body,
            count=1,
            flags=re.M,
        )
        if count == 0:
            print(f"UNREADABLE: {name} has no source digest — regenerate it")
            return 1
        if new_body == body:
            print(f"OK: {name} already current")
            continue
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_body)
        print(f"RETAGGED: {name}")
        retagged += 1

    print()
    print(f"{retagged} lock(s) re-stamped to {digest}.")
    print("Pinned versions and hashes are untouched; only the digest moved.")
    return 0


def _check_committed_locks(require_all: bool = False) -> int:
    """Verify every committed lock came from the current requirements.txt.

    Checks all of them, not just this platform's: a Windows machine should
    still be told that the Linux lock is out of date, because someone has to
    regenerate it somewhere. Needs no pip resolve, so it is instant.

    A platform with no lock at all is reported either way, but only fails the
    run under `require_all`. On a PR that would be noise — you cannot fix a
    missing macOS lock from the branch you are reviewing — while at release
    time it is fatal, because that installer would download hundreds of MB
    and then stop at the dependency step.
    """
    digest = _source_digest()
    locks = sorted(glob.glob(os.path.join(LOCK_DIR, "lock-*.txt")))
    if not locks:
        print("MISSING: no lock files at all — run this script without --check")
        return 1

    stale = []
    for path in locks:
        name = os.path.relpath(path, REPO_ROOT)
        with io.open(path, encoding="utf-8") as fh:
            header = fh.read(2048)
        match = re.search(r"^# Source: requirements\.txt \((sha256:[0-9a-f]+)\)", header, re.M)
        if match is None:
            print(f"UNREADABLE: {name} has no source digest — regenerate it")
            stale.append(name)
        elif match.group(1) != digest:
            print(f"STALE: {name} was generated from a different requirements.txt")
            stale.append(name)
        else:
            print(f"OK: {name}")

    missing = [
        prefix
        for prefix in SHIPPED_PLATFORMS
        if not any(
            os.path.basename(p).startswith(f"lock-{prefix}") for p in locks
        )
    ]
    for prefix in missing:
        # ::warning/::error:: renders on the GitHub summary rather than being
        # buried in the log.
        level = "error" if require_all else "warning"
        print(f"::{level}::no lock for {prefix} - that platform cannot install")

    if stale:
        print()
        print("requirements.txt changed without regenerating these locks.")
        print("Run `python scripts/generate_lock.py` on each affected platform.")
        return 1
    if missing and require_all:
        print()
        print("Generate the missing lock(s) on the platform each describes.")
        return 1
    if missing:
        print()
        print(f"{len(missing)} platform(s) have no lock: {', '.join(missing)}")
        print("Not fatal here; release.yml will refuse to build without them.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="verify every committed lock matches requirements.txt (for CI)",
    )
    ap.add_argument(
        "--require-all",
        action="store_true",
        help="with --check, also fail when a shipped platform has no lock",
    )
    ap.add_argument(
        "--retag",
        action="store_true",
        help="re-stamp the committed locks when requirements.txt changed but "
        "the resolved set did not (refuses if it did)",
    )
    args = ap.parse_args()

    if args.retag:
        return _retag_committed_locks()

    if args.check:
        return _check_committed_locks(require_all=args.require_all)

    target = lock_path()
    rendered = render(resolve())

    os.makedirs(LOCK_DIR, exist_ok=True)
    with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(rendered)
    print(f"wrote {os.path.relpath(target, REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
