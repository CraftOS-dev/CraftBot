#!/usr/bin/env python3
"""Build CraftBot-src.zip — the payload the installer provisions around.

This replaces the per-platform frozen agent (CraftBotAgent.spec). One asset
serves every platform: it is pure Python plus data files, and what used to
differ per platform — the bundled interpreter and the compiled wheels — is
now provisioned on the machine by app.provision.

## What goes in, and why it is defined this way

The file list is `git ls-files`, plus a short allow-list of build outputs
that are gitignored but required at runtime (the compiled frontend).

That is deliberate. The obvious alternative — walk the tree and skip an
exclude list — is what the old agent spec did with `datas`, and it shipped
1.1 GB of the *builder's own* runtime state: app/data/.file_index (the memory
index) and app/data/.usage (containing chat.db and integrations.db, i.e. the
builder's conversation history and integration credentials). It only escaped
notice because CI checks out clean, so those directories were absent there.
A local release build would have published them.

Taking the file list from git makes that impossible rather than unlikely:
untracked state is not in `git ls-files`, so it cannot be included by
forgetting an exclusion.

Usage:
    python scripts/package_source.py [--output dist/CraftBot-src.zip]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]

# Gitignored build outputs that ARE required at runtime. Kept short and
# explicit: every entry here is a hole in the "git decides" guarantee.
BUILD_OUTPUTS = [
    # The compiled browser UI. Users have no Node toolchain at install time
    # and must not need one to see a working interface.
    "app/ui_layer/browser/frontend/dist",
]

# Tracked paths that are pure development weight. Excluded to keep the
# download small; none is reachable at runtime.
EXCLUDE_PREFIXES = (
    ".github/",
    "docs/",
    "tests/",
    "diagnostic/",
    "launcher/",  # the native launcher is built and shipped separately
)

EXCLUDE_SUFFIXES = (".md",)

# Kept despite the rules above — README is the one doc worth shipping, and
# the i18n README variants are not.
KEEP_EXACT = {"README.md", "LICENSE"}


def tracked_files() -> List[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def wanted(rel: str) -> bool:
    if rel in KEEP_EXACT:
        return True
    if rel.startswith(EXCLUDE_PREFIXES):
        return False
    if rel.endswith(EXCLUDE_SUFFIXES):
        # Keep per-package docs the agent reads at runtime: integration
        # guidance is loaded from craftos_integrations/providers/*/*.md, and
        # skills are markdown by definition.
        return rel.startswith(("craftos_integrations/", "skills/", "agents/"))
    return True


def build(output: Path) -> int:
    files = [f for f in tracked_files() if wanted(f)]
    if not files:
        print("error: git ls-files returned nothing — not a checkout?", file=sys.stderr)
        return 1

    missing_outputs = [b for b in BUILD_OUTPUTS if not (REPO_ROOT / b).exists()]
    if missing_outputs:
        print(
            "error: required build output missing: "
            + ", ".join(missing_outputs)
            + "\nBuild the frontend first:\n"
            "  cd app/ui_layer/browser/frontend && npx vite build",
            file=sys.stderr,
        )
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    written = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in files:
            src = REPO_ROOT / rel
            if not src.is_file():
                continue  # submodule entry or a deleted-but-staged path
            zf.write(src, rel)
            written += 1

        for base in BUILD_OUTPUTS:
            for path in (REPO_ROOT / base).rglob("*"):
                if path.is_file():
                    zf.write(path, str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
                    written += 1

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"wrote {output} — {written} files, {size_mb:.1f} MB")

    # A payload without these is installable and then broken at runtime, in
    # ways that surface far from the cause. Fail the build instead.
    required = [
        "run.py",
        "main.py",
        "requirements.txt",
        "app/paths.py",
        "app/provision/__init__.py",
        "app/ui_layer/browser/frontend/dist/index.html",
        "craftos_integrations/providers/whatsapp_web/bridge.js",
        # craftbot.py imports these at module scope; without them every
        # command fails before parsing its arguments.
        "installer/helpers.py",
        "installer/metadata.py",
        "installer/payload.py",
    ]
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
    absent = [r for r in required if r not in names]
    if absent:
        print("error: payload is missing " + ", ".join(absent), file=sys.stderr)
        return 1

    if not any(n.startswith("requirements/lock-") for n in names):
        print(
            "error: no requirements/lock-*.txt in the payload — the installer "
            "cannot provision dependencies without a lock.",
            file=sys.stderr,
        )
        return 1

    print(f"verified: {len(required)} required paths present, lock included")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "dist" / "CraftBot-src.zip"),
        help="where to write the payload",
    )
    args = ap.parse_args()
    return build(Path(args.output))


if __name__ == "__main__":
    sys.exit(main())
