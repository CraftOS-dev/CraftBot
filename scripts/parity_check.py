#!/usr/bin/env python3
"""Emit a fingerprint of a CraftBot install, so the three install paths can be
compared mechanically instead of by inspection.

The point is not to pass today — it will not. The point is to make the
divergence a *number* that CI tracks, so later work can drive it to zero and
keep it there.

Usage:
    python scripts/parity_check.py --label pip > pip.json
    python scripts/parity_check.py --label conda > conda.json
    python scripts/parity_check.py --compare pip.json conda.json

Deliberately stdlib-only and importing nothing from app/: it must run in a
half-installed environment (that is exactly the case it exists to detect)
without the import itself failing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from typing import Any, Dict, List

SCHEMA = 1
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Modules the app imports directly and cannot degrade without. Chosen because
# each is genuinely referenced in the codebase, not because it is declared —
# a declared-but-unused package drifting is harmless, a used one is not.
CRITICAL_IMPORTS = [
    "chromadb",
    "openai",
    "anthropic",
    "tiktoken",
    "rank_bm25",
    "pdfplumber",
    "pypdf",
    "pypdfium2",
    "fitz",
    "pyperclip",
    "websockets",
    "boto3",
    "requests",
    "bs4",
    "trafilatura",
    "ddgs",
    "docling",
    "onnxruntime",
    "playwright",
    "cv2",
]

# Non-Python files resolved at runtime by path. PyInstaller does not bundle
# these from module analysis, so they are the frozen build's blind spot.
CRITICAL_DATA_FILES = [
    "craftos_integrations/providers/whatsapp_web/bridge.js",
    "craftos_integrations/providers/gmail/INTEGRATION.md",
    "app/data/action/read_pdf.py",
    "app/i18n/errors.en.json",
]


#: Packaging plumbing that whoever built the environment supplies, not
#: requirements.txt. A venv ships one pip version; conda ships another plus
#: wheel. That is a difference between venv and conda bootstrap, not in what
#: CraftBot installs — recorded for the record, excluded from the comparison.
BOOTSTRAP_PACKAGES = frozenset(
    {"pip", "setuptools", "wheel", "distribute", "pkg-resources"}
)


def _packages() -> Dict[str, Any]:
    """Installed distributions as name==version, plus a digest of the set."""
    try:
        from importlib.metadata import distributions
    except ImportError:  # pragma: no cover - py<3.8
        return {"error": "importlib.metadata unavailable"}

    found: Dict[str, str] = {}
    for dist in distributions():
        name = (dist.metadata["Name"] or "").strip().lower().replace("_", "-")
        if name:
            found[name] = dist.version or "?"

    bootstrap = {k: v for k, v in found.items() if k in BOOTSTRAP_PACKAGES}
    app = {k: v for k, v in found.items() if k not in BOOTSTRAP_PACKAGES}
    joined = "\n".join(f"{k}=={app[k]}" for k in sorted(app))
    return {
        "count": len(app),
        "digest": hashlib.sha256(joined.encode()).hexdigest()[:16],
        "list": dict(sorted(app.items())),
        "bootstrap": dict(sorted(bootstrap.items())),
    }


def _imports() -> Dict[str, bool]:
    """find_spec rather than import: cheap, and importing torch here would
    dominate the runtime of the check for no added signal."""
    out: Dict[str, bool] = {}
    for name in CRITICAL_IMPORTS:
        try:
            out[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            out[name] = False
    return out


def _data_files(root: str) -> Dict[str, bool]:
    return {rel: os.path.isfile(os.path.join(root, rel)) for rel in CRITICAL_DATA_FILES}


def _node() -> Dict[str, Any]:
    """Resolve Node the way the app does, falling back to a bare PATH probe so
    this still reports something when app/ cannot be imported."""
    info: Dict[str, Any] = {"resolved": None, "version": None, "source": None}
    try:
        sys.path.insert(0, REPO_ROOT)
        from app import node_runtime  # type: ignore

        rt = node_runtime.resolve()
        if rt is not None:
            info.update(resolved=rt.node, version=rt.version, source=rt.source)
            return info
        info["source"] = "unresolved"
    except Exception as e:
        info["source"] = f"probe-failed: {type(e).__name__}"

    import shutil

    path_node = shutil.which("node")
    if path_node and not info["resolved"]:
        try:
            out = subprocess.run(
                [path_node, "--version"], capture_output=True, text=True, timeout=15
            ).stdout.strip()
            info.update(resolved=path_node, version=out or None, source="path-fallback")
        except Exception:
            pass
    return info


def _embedding_model() -> Dict[str, Any]:
    """Which embedding model this install would actually use — the difference
    between bge-small and ChromaDB's bundled MiniLM is invisible at rest but
    changes every retrieval score."""
    configured = os.environ.get("MEMORY_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    loadable = False
    try:
        loadable = importlib.util.find_spec("sentence_transformers") is not None and (
            importlib.util.find_spec("transformers") is not None
        )
    except (ImportError, ValueError):
        loadable = False
    return {
        "configured": configured,
        "sentence_transformers_loadable": loadable,
        "effective": configured if (loadable or configured == "default") else "default",
    }


def fingerprint(label: str) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "label": label,
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "packages": _packages(),
        "imports": _imports(),
        "data_files": _data_files(
            getattr(sys, "_MEIPASS", REPO_ROOT)  # frozen builds resolve here
        ),
        "node": _node(),
        "embedding": _embedding_model(),
    }


def compare(paths: List[str]) -> int:
    """Diff two or more fingerprints. Exit 1 on any divergence that matters."""
    prints = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            prints.append(json.load(fh))

    base, *rest = prints
    problems = 0

    def note(msg: str) -> None:
        nonlocal problems
        problems += 1
        print(f"  DIVERGENCE  {msg}")

    for other in rest:
        a, b = base["label"], other["label"]
        print(f"\n=== {a} vs {b} ===")

        if base["packages"]["digest"] != other["packages"]["digest"]:
            note(
                f"package set differs "
                f"({base['packages']['count']} vs {other['packages']['count']})"
            )
            only_a = sorted(
                set(base["packages"]["list"]) - set(other["packages"]["list"])
            )
            only_b = sorted(
                set(other["packages"]["list"]) - set(base["packages"]["list"])
            )
            if only_a:
                print(f"      only in {a}: {', '.join(only_a[:15])}")
            if only_b:
                print(f"      only in {b}: {', '.join(only_b[:15])}")
            shared = set(base["packages"]["list"]) & set(other["packages"]["list"])
            vers = [
                f"{n} ({base['packages']['list'][n]} vs {other['packages']['list'][n]})"
                for n in sorted(shared)
                if base["packages"]["list"][n] != other["packages"]["list"][n]
            ]
            if vers:
                print(f"      version mismatch: {', '.join(vers[:15])}")

        for key, human in (("imports", "import"), ("data_files", "data file")):
            for name, present in base[key].items():
                if other[key].get(name) != present:
                    note(f"{human} {name}: {a}={present} {b}={other[key].get(name)}")

        if base["embedding"]["effective"] != other["embedding"]["effective"]:
            note(
                f"embedding model: {a}={base['embedding']['effective']} "
                f"{b}={other['embedding']['effective']}"
            )

        # Minor version, not patch. Locks are keyed to py310 because the minor
        # is what decides wheel compatibility; setup-python resolves "3.10" to
        # the newest patch while environment.yml pins an exact one, so the
        # patch differs by construction and means nothing here.
        def _minor(fp: Dict[str, Any]) -> str:
            return ".".join(fp["python"]["version"].split(".")[:2])

        if _minor(base) != _minor(other):
            note(
                f"python: {a}={base['python']['version']} "
                f"{b}={other['python']['version']}"
            )

        # Node is reported, never a divergence. This job installs a lock into
        # two PYTHON environments; it never runs app.provision's node stage.
        # So one side reports whatever the runner happened to have on PATH and
        # the other reports what environment.yml's `nodejs` pulled in — a
        # difference between the two bootstraps, not between install paths.
        # installer-e2e is what exercises node provisioning.
        bn, on = base["node"]["version"], other["node"]["version"]
        if bn != on:
            print(f"      note: node {a}={bn} {b}={on} (not compared here)")

    print(f"\n{problems} divergence(s)")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="unnamed", help="name for this install path")
    ap.add_argument("--compare", nargs="+", metavar="FILE", help="diff fingerprints")
    args = ap.parse_args()

    if args.compare:
        return compare(args.compare)

    json.dump(fingerprint(args.label), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
