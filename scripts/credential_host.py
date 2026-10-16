"""Owner controls for the protected host. Secret values use native entry only."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.credentials.client import request  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles")
    commands.add_parser("action_profile")
    selected = commands.add_parser(
        "action_profile_set",
        help="Owner-approved profile for isolated actions; omit to disable",
    )
    selected.add_argument("profile_id", nargs="?", default=None)
    for operation in ("initialize", "lock", "unlock", "items", "activity"):
        command = commands.add_parser(operation)
        command.add_argument("profile_id")
    profile = commands.add_parser("profile_add")
    profile.add_argument("label")
    view = commands.add_parser(
        "view", help="Show values only on the protected native desktop"
    )
    view.add_argument("profile_id")
    view.add_argument("credential_id")
    view.add_argument("version", type=int)
    for operation in (
        "migrate_settings",
        "migrate_browser",
        "migrate_integration",
        "migrate_environment",
    ):
        migrate = commands.add_parser(
            operation,
            help="Offline source migration; stop all CraftBot instances first",
        )
        migrate.add_argument("profile_id")
        if operation == "migrate_integration":
            migrate.add_argument("provider")
            migrate.add_argument(
                "--source-account",
                dest="source_accounts",
                action="append",
                default=[],
                help="Explicit manual-source account ID for ambiguous legacy auth provenance",
            )
        migrate.add_argument(
            "path",
            help="Absolute legacy settings.json or mini_browser_vault.enc path; no source values",
        )
    entry = commands.add_parser("entry")
    entry.add_argument("profile_id")
    entry.add_argument(
        "--kind", choices=("login", "api_key", "service_secret"), required=True
    )
    entry.add_argument("--service", required=True)
    entry.add_argument("--account", required=True)
    entry.add_argument("--origin", action="append", default=[])
    entry.add_argument(
        "--field", action="append", default=[], help="Service-secret field NAMES only"
    )
    launch = commands.add_parser("launch")
    launch.add_argument("profile_id")
    launch.add_argument("file", type=Path)
    launch.add_argument(
        "--kind",
        choices=("agent_session", "subagent", "agent_app"),
        default="agent_session",
    )
    launch.add_argument("--subject", required=True)
    launch.add_argument("--deployment", choices=("live", "development"))
    for operation in ("result", "program_result", "stop", "response"):
        command = commands.add_parser(operation)
        command.add_argument("run_id")
        if operation == "response":
            command.add_argument("offset", type=int)
    args = parser.parse_args()
    values = vars(args).copy()
    operation = values.pop("command")
    if operation == "entry":
        values["origins"], values["fields"] = values.pop("origin"), values.pop("field")
    if operation == "launch":
        file = values.pop("file")
        values["files"], values["entry"] = (
            {file.name: file.read_text(encoding="utf-8")},
            file.name,
        )
    result = request(operation, **values)
    if operation == "items":
        items = list(result["items"])
        while result["next_offset"] is not None:
            result = request(
                "items_page",
                profile_id=values["profile_id"],
                view_id=result["view_id"],
                offset=result["next_offset"],
            )
            items.extend(result["items"])
        result = items
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
