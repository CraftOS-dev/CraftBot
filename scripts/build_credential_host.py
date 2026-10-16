"""Build a reviewable Windows credential-service package without elevation.

No installation, services, keys, vaults or existing token/session state change.
Dependencies are selected from the repository's hashed Windows lock file.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4


def build(
    destination: Path,
    owner_sid: str,
    compiler: Path,
    helpers_file: Path | None = None,
    tenant_origins: tuple[str, ...] = (),
):
    if (
        sys.platform != "win32"
        or sys.version_info[:2] != (3, 12)
        or not re.fullmatch(r"S-1-(?:\d+-)+\d+", owner_sid)
    ):
        raise ValueError("Windows and a verified Windows owner SID are required")
    if destination.exists():
        raise ValueError("Use a new package directory")
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository))
    from app.credentials.catalog import (
        integration_helpers,
        model_helpers,
        specification,
    )
    from app.credentials.helpers import HelperRegistry

    helpers = (
        json.loads(helpers_file.read_text(encoding="utf-8"))
        if helpers_file
        else model_helpers() + integration_helpers()
    )
    helpers = apply_tenant_origins(helpers, tenant_origins)
    if type(helpers) is not list or len(helpers) > 1024:
        raise ValueError("Invalid fixed helper catalog")
    HelperRegistry(tuple(specification(item) for item in helpers))
    destination.mkdir(parents=True)
    payload = destination / "payload"
    payload.mkdir()
    package = payload / "app" / "credentials"
    package.parent.mkdir()
    (package.parent / "__init__.py").write_text("", encoding="utf-8")
    shutil.copytree(
        repository / "app" / "credentials",
        package,
        ignore=shutil.ignore_patterns("__pycache__", "native"),
    )
    shutil.copyfile(
        repository / "app" / "credentials" / "native" / "bootstrap.py",
        payload / "bootstrap.py",
    )
    shutil.copytree(
        Path(sys.base_prefix) / "Lib",
        payload / "python" / "Lib",
        ignore=shutil.ignore_patterns(
            "site-packages", "__pycache__", "test", "idlelib", "ensurepip"
        ),
    )
    shutil.copytree(Path(sys.base_prefix) / "DLLs", payload / "python" / "DLLs")
    for path in Path(sys.base_prefix).iterdir():
        if path.is_file() and (
            path.suffix.lower() == ".dll" or path.name == "python.exe"
        ):
            shutil.copyfile(path, payload / "python" / path.name)
    dependencies = destination / "host-requirements.txt"
    shutil.copyfile(
        repository / "requirements" / "credential-host-win_amd64-py312.txt",
        dependencies,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--isolated",
            "--no-deps",
            "--only-binary=:all:",
            "--require-hashes",
            "--target",
            str(payload / "deps"),
            "-r",
            str(dependencies),
        ],
        check=True,
    )
    vendor_pyaes(payload / "deps")
    subprocess.run(
        [
            str(compiler),
            "/nologo",
            "/target:winexe",
            "/out:" + str(payload / "CredentialHost.exe"),
            "/r:System.ServiceProcess.dll",
            "/r:System.Windows.Forms.dll",
            "/r:System.Drawing.dll",
            "/r:System.Web.Extensions.dll",
            str(repository / "app" / "credentials" / "native" / "CredentialHost.cs"),
        ],
        check=True,
    )
    configuration = {
        "owner_sid": owner_sid,
        "owner_id": str(uuid4()),
        "profiles": [
            {"id": str(uuid4()), "label": label} for label in ("Personal", "Work")
        ],
        "helpers": helpers,
    }
    (payload / "host.json").write_text(
        json.dumps(configuration, indent=2), encoding="utf-8"
    )
    manifest = {
        path.relative_to(payload).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(payload.rglob("*"))
        if path.is_file()
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8"
    )
    shutil.copyfile(
        repository / "scripts" / "install_credential_host.ps1",
        destination / "Install.ps1",
    )
    print("Package:", destination)
    print(
        "ExpectedManifestSha256:",
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )


def vendor_pyaes(destination, *, archive=None):
    """Copy only reviewed pure Python files from a pinned publisher archive.

    pyaes 1.6.1 has no publisher wheel. Do not execute its setup.py, extractall,
    links or build backends, or add build tools to the privileged runtime.
    """
    import io
    import tarfile
    import urllib.request

    expected = "02c1b1405c38d3c370b085fb952dd8bea3fadcee6411ad99f312cc129c536d8f"
    url = "https://files.pythonhosted.org/packages/44/66/2c17bae31c906613795711fc78045c285048168919ace2220daa372c7d72/pyaes-1.6.1.tar.gz"
    if archive is None:
        with urllib.request.urlopen(url, timeout=30) as response:
            archive = response.read(1_000_001)
    if len(archive) > 1_000_000 or hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError("pyaes source hash mismatch")
    selected = (
        "pyaes/__init__.py",
        "pyaes/aes.py",
        "pyaes/blockfeeder.py",
        "pyaes/util.py",
        "LICENSE.txt",
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        for name in selected:
            member = source.getmember("pyaes-1.6.1/" + name)
            if not member.isfile() or member.size > 500_000:
                raise ValueError("invalid pyaes source member")
            target = destination / (
                "pyaes/LICENSE.txt" if name == "LICENSE.txt" else name
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as stream:
                target.write_bytes(stream.read())


def apply_tenant_origins(helpers, values):
    """Build-time policy only: an explicit origin replaces a fixed provider host."""
    from urllib.parse import urlsplit
    from app.credentials.records import origins

    replacements = {
        "jira": "https://jira.example.invalid",
        "posthog": "https://us.posthog.com",
    }
    selected = {}
    for value in values:
        provider, separator, origin = value.partition("=")
        if (
            not separator
            or provider not in replacements
            or provider in selected
            or origins((origin,)) != (origin,)
        ):
            raise ValueError("Invalid reviewed tenant origin")
        selected[provider] = origin
    result = []
    for item in helpers:
        row = dict(item)
        for provider, origin in selected.items():
            if row["helper"] == "integration_" + provider and row[
                "endpoint"
            ].startswith(replacements[provider] + "/"):
                row["endpoint"] = origin + urlsplit(row["endpoint"]).path
        result.append(row)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--owner-sid", required=True)
    parser.add_argument(
        "--tenant-origin",
        action="append",
        default=[],
        help="Reviewed fixed origin: jira=https://tenant.atlassian.net or posthog=https://eu.posthog.com; repeat per provider",
    )
    parser.add_argument(
        "--helpers-file",
        type=Path,
        help="Reviewed fixed HTTPS helper descriptors, never consumer input",
    )
    parser.add_argument(
        "--compiler",
        type=Path,
        default=Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    )
    args = parser.parse_args()
    build(
        args.destination.resolve(),
        args.owner_sid,
        args.compiler,
        args.helpers_file,
        tuple(args.tenant_origin),
    )
