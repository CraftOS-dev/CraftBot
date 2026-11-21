#!/usr/bin/env python3
"""Generate a hash-pinned lock file from requirements.txt.

Every install path — pip, conda, and the installer — must install the same
set, and that is only possible if the set is written down. requirements.txt
declares 56 packages; the real closure is 239.

Locks are PER PLATFORM AND PYTHON VERSION (the closure differs: pyobjc only
on macOS, pywin32-style extras only on Windows), but they no longer have to be
generated ON each platform: uv resolves for any target from any machine
(`uv pip compile --python-platform`), so one run writes every shipped lock.
That is what made an Intel-Mac and a Linux-ARM lock possible at all.

Every pinned version carries the hash of EVERY file published for it, not
just the one wheel the generating machine would pick. A lock that hashed only
the macosx_14_0 wheel failed on macOS 12/13 with "THESE PACKAGES DO NOT MATCH
THE HASHES" even where a compatible macosx_12 wheel existed; the same for
manylinux_2_34-only hashes on older glibc. pip picks the best compatible file
and finds its hash.

Every pinned version must also have a WHEEL that fits its target. Left alone,
uv pins a version that has no wheel for that platform and locks its sdist, and
the install then compiles it on the user's machine. cryptography 49 dropped
Intel-Mac wheels; the macosx_x86_64 lock pinned 50.0.1 anyway, and the
Intel-Mac install died building it (rustup, then maturin). So the resolve runs
with --only-binary :all:. uv then picks the newest version that has a fitting
wheel (48.0.1 on that Mac) and other platforms keep theirs. The only packages
allowed to build from source are listed in SDIST_ALLOWED.

Existing pins are PREFERRED, not re-resolved: each lock is seeded into uv's
output file, so regenerating after a requirements.txt edit changes only what
the edit forces instead of bumping every package to today's release.

Needs uv (a build-time tool only, never installed for users):
    pip install uv

Usage:
    python scripts/generate_lock.py                  # write every shipped lock
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
import os
import re
import subprocess
import sys
import tempfile
from typing import Dict, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(REPO_ROOT, "requirements.txt")
LOCK_DIR = os.path.join(REPO_ROOT, "requirements")

#: Platforms a release ships an installer for, as lock-filename prefixes.
#: Exact, not loose: a platform without a lock downloads hundreds of MB and
#: then stops at the python-deps stage, so --require-all must see every one.
#:
#: Keep in step with the launcher matrix in .github/workflows/release.yml.
SHIPPED_PLATFORMS = (
    "win_amd64",
    "linux_x86_64",
    "linux_aarch64",
    "macosx_arm64",
    "macosx_x86_64",
)

#: Lock tag -> (uv --python-platform target, environment for the resolve).
#:
#: Linux targets are manylinux_2_28 (glibc 2.28: RHEL 8, Debian 10, Ubuntu
#: 20.04 and newer), so no package can be pinned to a version whose only
#: wheels need a newer glibc. macOS targets 12.0 for the same reason; keep it
#: in step with MIN_MACOS in the launcher and LSMinimumSystemVersion.
TARGETS = {
    "win_amd64": ("x86_64-pc-windows-msvc", {}),
    "linux_x86_64": ("x86_64-manylinux_2_28", {}),
    "linux_aarch64": ("aarch64-manylinux_2_28", {}),
    "macosx_arm64": ("aarch64-apple-darwin", {"MACOSX_DEPLOYMENT_TARGET": "12.0"}),
    "macosx_x86_64": ("x86_64-apple-darwin", {"MACOSX_DEPLOYMENT_TARGET": "12.0"}),
}

#: Which existing lock seeds a new platform's preferences, so a first-time
#: lock starts from the versions its sibling already proved.
SEED_FROM = {"linux_aarch64": "linux_x86_64", "macosx_x86_64": "macosx_arm64"}

#: The only packages a lock may pin as an sdist (see "Every pinned version must
#: also have a WHEEL" above). Each publishes no wheels at all and is pure
#: Python, so building it needs no compiler. A new sdist-only dependency stops
#: the resolve with "Wheels are required for `name`". Add it here only after
#: checking that its sdist has no native code.
SDIST_ALLOWED = (
    "antlr4-python3-runtime",
    "mouseinfo",
    "pyaes",
    "pyautogui",
    "pygetwindow",
    "pyrect",
    "pyscreeze",
    "python3-xlib",
    "pytweening",
)

PYTHON_LINE = "3.10"  # keep in step with TARGET_PYTHON in app/provision/runtimes.py


def _load_locktag():
    """app/provision/locktag.py, loaded by path rather than imported.

    `from app.provision import locktag` would execute app/provision/__init__.py
    and pull the whole stage pipeline in with it. This script deliberately
    needs nothing but the stdlib — it is what you run to CREATE the dependency
    set, so it has to work in an environment where that set does not exist yet.
    """
    import importlib.util

    path = os.path.join(REPO_ROOT, "app", "provision", "locktag.py")
    spec = importlib.util.spec_from_file_location("_craftbot_locktag", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lock_tag(platform_key: str) -> str:
    """The lock tag for one shipped platform on the locked Python line.

    Built with app/provision/locktag.py's own build(), which is what
    app.provision.deps reads locks with: writer and reader deriving the name
    separately is how a committed macOS lock became invisible to half the
    Pythons that needed it.
    """
    major, minor = (int(v) for v in PYTHON_LINE.split("."))
    raw, machine = {
        "win_amd64": ("win-amd64", "AMD64"),
        "linux_x86_64": ("linux-x86_64", "x86_64"),
        "linux_aarch64": ("linux-aarch64", "aarch64"),
        "macosx_arm64": ("macosx-11.0-arm64", "arm64"),
        "macosx_x86_64": ("macosx-10.9-x86_64", "x86_64"),
    }[platform_key]
    return _load_locktag().build(raw, machine, major, minor)


def lock_path(platform_key: str) -> str:
    return os.path.join(LOCK_DIR, f"lock-{lock_tag(platform_key)}.txt")


def _uv() -> List[str]:
    """The uv command: on PATH, else the module form (pip install uv)."""
    import shutil

    exe = shutil.which("uv")
    if exe:
        return [exe]
    probe = subprocess.run(
        [sys.executable, "-m", "uv", "--version"], capture_output=True, text=True
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "uv"]
    raise SystemExit("uv is required to generate locks: pip install uv")


def compile_args(target: str, out_file: str) -> List[str]:
    """`uv pip compile` arguments for one target, wheels required."""
    args = [
        "pip",
        "compile",
        REQUIREMENTS,
        "--python-version",
        PYTHON_LINE,
        "--python-platform",
        target,
        "--only-binary",
        ":all:",
    ]
    for name in SDIST_ALLOWED:
        # A per-package --no-binary overrides --only-binary :all:.
        args += ["--no-binary", name]
    return args + [
        "--generate-hashes",
        "--no-header",
        "--no-annotate",
        "--quiet",
        "--output-file",
        out_file,
    ]


def resolve(platform_key: str) -> Dict[str, List[str]]:
    """Resolve requirements.txt for one platform: {name==version: [hashes]}.

    The current lock (or its sibling's, for a new platform) is copied into
    uv's output file first, which uv treats as version preferences.
    """
    target, extra_env = TARGETS[platform_key]
    seed = lock_path(platform_key)
    if not os.path.isfile(seed) and platform_key in SEED_FROM:
        seed = lock_path(SEED_FROM[platform_key])

    workdir = tempfile.mkdtemp(prefix="craftbot-lock-")
    out_file = os.path.join(workdir, "lock.txt")
    if os.path.isfile(seed):
        # Versions only, never hashes: uv reuses a seed's hashes for any pin
        # it keeps, so a hand-edited version line shipped with the previous
        # version's hashes and failed every install that resolved it.
        with (
            io.open(seed, encoding="utf-8") as src_fh,
            io.open(out_file, "w", encoding="utf-8") as dst_fh,
        ):
            for line in src_fh:
                pin = _PIN_RE.match(line.strip())
                if pin:
                    dst_fh.write(f"{pin.group(1)}=={pin.group(2)}\n")

    env = dict(os.environ, **extra_env)
    proc = subprocess.run(
        _uv() + compile_args(target, out_file),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        if "Wheels are required for" in proc.stderr:
            sys.stderr.write(
                f"\nA package above has no wheel for {platform_key}. If it is pure "
                "Python and ships only an sdist, add it to SDIST_ALLOWED. "
                "Otherwise, constrain it in requirements.txt to a version that "
                "has a wheel for this platform.\n"
            )
        raise SystemExit(f"uv resolution failed for {platform_key} ({proc.returncode})")

    rows: Dict[str, List[str]] = {}
    key = None
    with io.open(out_file, encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            pin = _PIN_RE.match(text)
            if pin:
                key = f"{pin.group(1)}=={pin.group(2).rstrip(chr(92)).strip()}"
                rows.setdefault(key, [])
            for digest in re.findall(r"--hash=(sha256:[0-9a-f]{64})", text):
                if key:
                    rows[key].append(digest)
    return rows


def render(rows: Dict[str, List[str]], platform_key: str) -> str:
    """Render a pip --require-hashes compatible lock."""
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
        f"# Valid ONLY for: {lock_tag(platform_key)}",
        "# Locks are per platform+python; each pinned version lists the hash of",
        "# every file published for it, so pip can pick the wheel that fits the",
        "# machine (older macOS, older glibc) and still verify it.",
        "#",
        f"# Source: requirements.txt ({_source_digest()})",
        f"# Packages: {len(rows)}",
        "",
        "--require-hashes",
        "",
    ]
    for key in sorted(rows, key=str.lower):
        joined = " \\\n    ".join(f"--hash={h}" for h in sorted(set(rows[key])))
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
        match = re.search(
            r"^# Source: requirements\.txt \((sha256:[0-9a-f]+)\)", header, re.M
        )
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
        if not any(os.path.basename(p).startswith(f"lock-{prefix}") for p in locks)
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
    ap.add_argument(
        "--platform",
        action="append",
        choices=sorted(TARGETS),
        help="only regenerate this platform's lock (repeatable; default: all)",
    )
    args = ap.parse_args()

    if args.retag:
        return _retag_committed_locks()

    if args.check:
        return _check_committed_locks(require_all=args.require_all)

    os.makedirs(LOCK_DIR, exist_ok=True)
    for platform_key in args.platform or list(TARGETS):
        rendered = render(resolve(platform_key), platform_key)
        target = lock_path(platform_key)
        with io.open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(rendered)
        print(f"wrote {os.path.relpath(target, REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
