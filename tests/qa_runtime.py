"""Credential-free, disposable runtime for offline tests and local app QA."""

from __future__ import annotations

import json
from pathlib import Path
import shutil


def seed_runtime(code: Path, home: Path) -> None:
    """Seed source assets only; never copy databases, logins or user state.

    Require an empty destination so a test cannot overwrite an existing profile.
    Live QA may explicitly provision credentials after this function returns.
    """
    if home.exists() and any(home.iterdir()):
        raise ValueError(f"QA home must be empty: {home}")
    home.mkdir(parents=True, exist_ok=True)
    for rel in (
        "app/data/action",
        "app/data/agent_app_template",
        "app/data/agent_file_system_template",
        "app/data/agent_profile",
        "app/data/playbooks",
        "app/data/task_document",
        "skills",
        "assets",
        "agents",
    ):
        src = code / rel
        if src.is_dir():
            shutil.copytree(
                src,
                home / rel,
                ignore=shutil.ignore_patterns(
                    "__pycache__",
                    ".git",
                    "node_modules",
                    ".credentials",
                    "*.db",
                    "*.log",
                ),
            )
    settings = json.loads(
        (code / "app/config/settings.json").read_text(encoding="utf-8")
    )
    # A developer checkout may contain local secrets. Carry only configuration,
    # with all credential containers removed rather than copied into fixtures.
    for key in (
        "api_keys",
        "oauth",
        "aws",
        "aws_credentials",
        "credentials",
        "model_pools",
    ):
        settings.pop(key, None)
    settings["api_keys_configured"] = {}
    settings["auth_mode"] = {}
    (home / "app/config").mkdir(parents=True, exist_ok=True)
    (home / "app/config/settings.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("home", type=Path, help="New empty state directory")
    args = parser.parse_args()
    seed_runtime(Path(__file__).resolve().parents[1], args.home.resolve())
