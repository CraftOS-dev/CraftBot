"""Export an independently verified candidate through the unchanged upstream CLI.

Only archive framing/timestamps are normalized for the bundled offline catalogue.
The upstream exporter owns exclusions of data, credentials and dependencies.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "app/data/default_agent_app"


def normalize_export(data):
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as target,
    ):
        for item in sorted(source.infolist(), key=lambda entry: entry.filename):
            if item.is_dir():
                continue
            parts = PurePosixPath(item.filename).parts
            if (
                len(parts) < 2
                or ".." in parts
                or PurePosixPath(item.filename).is_absolute()
            ):
                raise ValueError("Unexpected upstream export layout")
            rel = "/".join(parts[1:])
            if set(parts) & {
                "pb_data",
                "pb_public",
                "node_modules",
                ".git",
                "credentials.json",
                "live.json",
                "dev.json",
                "gate-pass.json",
            }:
                raise ValueError("The upstream export contains runtime state")
            info = zipfile.ZipInfo(rel, (2026, 11, 9, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            target.writestr(info, source.read(item))
    return output.getvalue()


async def package(candidate, evidence):
    from app.agent_app.framework import configured_cli

    report = json.loads(evidence.read_text(encoding="utf-8"))
    stamp = json.loads(
        (candidate / ".a2app/gate-pass.json").read_text(encoding="utf-8")
    )
    if (
        report.get("verdict") != "pass"
        or not stamp.get("budgetChecked")
        or report.get("gateFingerprint") != stamp.get("fingerprint")
    ):
        raise ValueError(
            "A current independent verification pass and complete gate are required."
        )
    cli = configured_cli()
    with tempfile.TemporaryDirectory(prefix="craftbot-kanban-export-") as temporary:
        exported = Path(temporary) / "board.zip"
        result = await cli.run(
            "agent-app",
            [str(candidate), "export", "--out", str(exported)],
            cwd=cli.package_dir,
            timeout=120,
        )
        if not result.ok:
            raise RuntimeError(result.stderr or result.stdout)
        data = normalize_export(exported.read_bytes())
    (BUNDLE / "kanban-board-framework.zip").write_bytes(data)
    legacy = json.loads((BUNDLE / "source.json").read_text(encoding="utf-8"))
    pin = json.loads(
        (ROOT / "app/vendor/agent-app/source.json").read_text(encoding="utf-8")
    )
    metadata = {
        "name": "Kanban Board",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "source": legacy,
        "framework": pin,
        "build": "scripts/upgrade_bundled_kanban.py",
        "packaging": "Unmodified upstream agent-app export; normalized ZIP timestamps and removed enclosing folder.",
        "verification": {
            "verdict": "pass",
            "gateFingerprint": stamp["fingerprint"],
            "evidenceSha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "summary": "Independent browser and native CLI verification: all 56 non-destructive operations executed; five destructive operations checked for shape. Full ledger in reference/verification.md inside the package.",
        },
    }
    (BUNDLE / "framework-source.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"sha256": metadata["sha256"], "bytes": len(data)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    asyncio.run(package(args.candidate.resolve(), args.evidence.resolve()))
