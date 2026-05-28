"""Diagnostic tool for validating action implementations."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

if __package__ is None or __package__ == "":
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from diagnostic.environments import load_environment_cases
from diagnostic.framework import (
    ActionExecutor,
    ActionTestCase,
    ExecutionResult,
    slugify,
)

ACTIONS_FILE = Path("agent.agent_actions.json")
LOG_DIR = Path("diagnostic/logs/actions")


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _jsonify(obj: Any) -> Any:
    """Return *obj* in a JSON-serializable form."""
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return json.loads(json.dumps(obj, default=str))


def load_actions() -> Dict[str, Mapping[str, Any]]:
    if not ACTIONS_FILE.exists():
        raise FileNotFoundError(f"Actions file not found: {ACTIONS_FILE}")

    data = json.loads(ACTIONS_FILE.read_text(encoding="utf-8"))
    actions: Dict[str, Mapping[str, Any]] = {}
    for entry in data:
        name = entry.get("name")
        if not name:
            continue
        actions[str(name)] = entry
    return actions


class DiagnosticRecord:
    def __init__(
        self,
        *,
        action: str,
        status: str,
        message: str,
        input_data: Mapping[str, Any],
        result: ExecutionResult,
        timestamp: datetime,
    ) -> None:
        self.action = action
        self.status = status
        self.message = message
        self.input_data = input_data
        self.result = result
        self.timestamp = timestamp

    def to_json(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "message": self.message,
            "input": dict(self.input_data),
            "raw_output": self.result.raw_output,
            "stderr": self.result.stderr,
            "parsed_output": _jsonify(self.result.parsed_output),
            "exception": str(self.result.exception) if self.result.exception else None,
            "traceback": self.result.traceback,
            "timestamp": self.timestamp.isoformat(),
        }


class ActionDiagnoser:
    def __init__(self, actions: Mapping[str, Mapping[str, Any]]) -> None:
        self.actions = actions
        self.executor = ActionExecutor()
        self.testcases: Dict[str, ActionTestCase] = load_environment_cases()

    def available_tests(self) -> List[str]:
        return sorted(self.testcases.keys())

    def run(self, action_names: Iterable[str]) -> List[DiagnosticRecord]:
        _ensure_log_dir()
        records: List[DiagnosticRecord] = []

        for action_name in action_names:
            action = self.actions.get(action_name)
            if not action:
                empty_result = ExecutionResult(
                    raw_output="", stderr="", parsed_output={}
                )
                record = DiagnosticRecord(
                    action=action_name,
                    status="skip",
                    message="Action definition not found.",
                    input_data={},
                    result=empty_result,
                    timestamp=datetime.now(timezone.utc),
                )
                self._write_record(record)
                records.append(record)
                continue

            testcase = self.testcases.get(action_name)
            if not testcase:
                empty_result = ExecutionResult(
                    raw_output="", stderr="", parsed_output={}
                )
                record = DiagnosticRecord(
                    action=action_name,
                    status="skip",
                    message="No diagnostic scenario implemented for this action.",
                    input_data={},
                    result=empty_result,
                    timestamp=datetime.now(timezone.utc),
                )
                self._write_record(record)
                records.append(record)
                continue

            status, message, result, used_input = testcase.run(action, self.executor)
            record = DiagnosticRecord(
                action=action_name,
                status=status,
                message=message,
                input_data=used_input,
                result=result,
                timestamp=datetime.now(timezone.utc),
            )
            self._write_record(record)
            records.append(record)

        return records

    def _write_record(self, record: DiagnosticRecord) -> None:
        slug = slugify(record.action)
        timestamp = record.timestamp.strftime("%Y%m%dT%H%M%S%f")
        path = LOG_DIR / f"{timestamp}_{slug}.log.json"
        path.write_text(
            json.dumps(record.to_json(), indent=2, ensure_ascii=False), encoding="utf-8"
        )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose action implementations.")
    parser.add_argument(
        "-a",
        "--action",
        dest="actions",
        action="append",
        help="Action name to diagnose. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available diagnostic scenarios and exit.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run diagnostics for every action with a configured test scenario.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    actions = load_actions()
    diagnoser = ActionDiagnoser(actions)

    if args.list:
        print("Available diagnostic scenarios:")
        for name in diagnoser.available_tests():
            print(f" - {name}")
        return 0

    if args.actions:
        action_names = args.actions
    elif args.all or not args.actions:
        action_names = diagnoser.available_tests()

    records = diagnoser.run(action_names)

    summary_lines = [
        "Diagnostic summary:",
    ]
    for record in records:
        summary_lines.append(f" - {record.action}: {record.status} - {record.message}")

    print("\n".join(summary_lines))
    failures = [r for r in records if r.status in {"error", "incorrect result"}]
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    import sys

    sys.exit(main())
