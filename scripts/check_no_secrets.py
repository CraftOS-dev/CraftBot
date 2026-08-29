# -*- coding: utf-8 -*-
"""Fail if provider secrets appear in tracked config files (Phase 0, NFR-7).

Usage:
    python scripts/check_no_secrets.py            # scan tracked config files
    python scripts/check_no_secrets.py --staged   # scan the staged diff only

Intended wiring: CI step and/or pre-commit hook. Exit code 1 on any finding.

Scope is deliberately narrow (config files, not the whole tree) so the scan
is fast and has no false positives from test fixtures or docs that discuss
key FORMATS without containing real keys.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Key-material patterns per provider family. Each must match REAL key shapes
# but not placeholders like "sk-ant-..." or empty strings.
SECRET_PATTERNS = {
    "anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai": re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),
    "openai-legacy": re.compile(r"sk-[A-Za-z0-9]{40,}"),
    "openrouter": re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),
    "aws-access-key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "xai": re.compile(r"xai-[A-Za-z0-9]{20,}"),
    "groq": re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "google": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "hf": re.compile(r"hf_[A-Za-z0-9]{30,}"),
}

# Tracked files worth scanning in full-scan mode.
CONFIG_GLOBS = [
    "app/config/*.json",
    "app/config/**/*.json",
    "*.json",
    "*.env",
]


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", *CONFIG_GLOBS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line for line in out.stdout.splitlines() if line.strip()]


def _staged_diff_text() -> str:
    out = subprocess.run(
        ["git", "diff", "--cached", "--unified=0"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    # Only ADDED lines can introduce a new secret.
    return "\n".join(
        line[1:]
        for line in out.stdout.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def _scan_text(label: str, text: str) -> list[str]:
    findings = []
    for family, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(text):
            secret = match.group(0)
            masked = secret[:12] + "..." + secret[-4:]
            findings.append(f"{label}: {family} key material ({masked})")
    return findings


def main() -> int:
    staged_only = "--staged" in sys.argv
    findings: list[str] = []

    if staged_only:
        findings.extend(_scan_text("staged diff", _staged_diff_text()))
    else:
        for path in _tracked_files():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            findings.extend(_scan_text(str(path.relative_to(REPO_ROOT)), text))

    if findings:
        print("SECRETS DETECTED (rotate the key, then remove it from git):")
        for f in findings:
            print(f"  - {f}")
        return 1

    print("No committed secrets detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
