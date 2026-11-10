#!/usr/bin/env python3
"""Rebuild the bundled, unmodified Agent-App CLI from its pinned Git revision.

Requires Git, Node >=20 and the pinned pnpm on PATH. Builds in a disposable
directory from `git archive`; the supplied checkout is only read. Uses upstream
build/prepack scripts and packs the CLI's complete production dependency closure.

    python scripts/build_agent_app_framework.py --source /path/to/Agent-App

Use --update-pin only when intentionally updating the archive checksum. Normal
rebuilds must reproduce the recorded hash. Runtime/install never runs this script.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "app/vendor/agent-app"
# The CLI's two production dependencies are dependency-free except sdk -> rules.
PACKAGES = {
    "agent-app-framework": ("framework/cli", ""),
    "@a2app/sdk": ("sdks/typescript", "node_modules/@a2app/sdk/"),
    "@a2app/rules": ("adapters/rules", "node_modules/@a2app/rules/"),
}


def tar_files(path: Path) -> dict[str, bytes]:
    files = {}
    with tarfile.open(path) as archive:
        for entry in archive.getmembers():
            name = PurePosixPath(entry.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in entry.name
                or ":" in entry.name
            ):
                raise ValueError(f"Unsafe archive path: {entry.name}")
            if entry.isdir():
                continue
            if not entry.isfile():
                raise ValueError(f"Unexpected archive link/device: {entry.name}")
            files[name.as_posix()] = archive.extractfile(entry).read()
    return files


def make_zip(files: dict[str, bytes]) -> bytes:
    """Stable timestamps, ordering and permissions; no builder-specific paths."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return output.getvalue()


def build(source: Path, *, update_pin: bool = False) -> None:
    pin_path = BUNDLE / "source.json"
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    pnpm = shutil.which("pnpm")
    if not pnpm:
        raise RuntimeError(
            f"Install {pin['packageManager']} to rebuild the distribution."
        )
    with tempfile.TemporaryDirectory(prefix="craftbot-agent-app-build-") as temporary:
        work = Path(temporary)
        source_tar = work / "source.tar"
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "archive",
                "--format=tar",
                "-o",
                str(source_tar),
                pin["revision"],
            ],
            check=True,
        )
        tree = work / "source"
        for name, data in tar_files(source_tar).items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        upstream = json.loads((tree / "package.json").read_text(encoding="utf-8"))
        if upstream["packageManager"] != pin["packageManager"]:
            raise RuntimeError("The build tool pin disagrees with upstream.")
        # Corepack/pnpm selects the version from the project's packageManager.
        version = subprocess.check_output(
            [pnpm, "--version"], cwd=tree, text=True
        ).strip()
        if f"pnpm@{version}" != pin["packageManager"]:
            raise RuntimeError(
                f"Expected {pin['packageManager']}, found pnpm@{version}"
            )

        def run(*args: str, cwd: Path = tree):
            print("pnpm " + " ".join(args), flush=True)
            result = subprocess.run(
                [pnpm, *args],
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode:
                raise RuntimeError((result.stdout + result.stderr)[-8000:])

        run(
            "--filter",
            "agent-app-framework...",
            "install",
            "--frozen-lockfile",
            "--ignore-scripts",
        )
        run("--filter", "agent-app-framework...", "build")
        files = {}
        for name, (relative, prefix) in PACKAGES.items():
            package = tree / relative
            metadata = json.loads(
                (package / "package.json").read_text(encoding="utf-8")
            )
            if metadata["name"] != name or metadata["version"] != pin["version"]:
                raise RuntimeError(f"Unexpected package identity/version: {relative}")
            if set(metadata.get("dependencies", {})) - PACKAGES.keys():
                raise RuntimeError(f"Unbundled runtime dependency in {name}")
            if metadata.get("optionalDependencies") or metadata.get("peerDependencies"):
                raise RuntimeError(f"Review the changed dependency closure of {name}")
            packs = work / name.replace("/", "-")
            packs.mkdir()
            run("pack", "--pack-destination", str(packs), cwd=package)
            (packed,) = packs.glob("*.tgz")
            for entry, data in tar_files(packed).items():
                if not entry.startswith("package/"):
                    raise RuntimeError(f"Unexpected npm archive entry: {entry}")
                files[prefix + entry.removeprefix("package/")] = data
        # Carry upstream's license even if a pack tool omitted the workspace copy.
        files.setdefault("LICENSE", (tree / "LICENSE").read_bytes())
        content = make_zip(files)

    digest = hashlib.sha256(content).hexdigest()
    if not update_pin and digest != pin["sha256"]:
        raise RuntimeError(f"Rebuild differs from the pinned archive: {digest}")
    (BUNDLE / "agent-app-framework.zip").write_bytes(content)
    if update_pin:
        pin["sha256"] = digest
        pin_path.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(files)} files, {len(content)} bytes, sha256 {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--update-pin", action="store_true")
    args = parser.parse_args()
    build(args.source.resolve(), update_pin=args.update_pin)
