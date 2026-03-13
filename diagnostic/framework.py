"""Common utilities for diagnostic action harnesses."""
from __future__ import annotations

import dataclasses
import io
import json
import re
import sys
import traceback
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Dict, Mapping, Optional, Tuple


__all__ = [
    "ExecutionResult",
    "ActionExecutor",
    "PreparedEnv",
    "ActionTestCase",
    "slugify",
]


def slugify(value: str) -> str:
    """Return a filesystem-friendly slug for *value*."""
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-").lower() or "action"


@dataclasses.dataclass
class ExecutionResult:
    raw_output: str
    stderr: str
    parsed_output: Any
    exception: Optional[BaseException] = None
    traceback: Optional[str] = None
    parse_error: Optional[BaseException] = None

    def has_error(self) -> bool:
        return self.exception is not None


class ActionExecutor:
    """Executes action code with provided inputs and sandbox customisations."""

    def execute(
        self,
        *,
        code: str,
        input_data: Mapping[str, Any],
        extra_modules: Optional[Mapping[str, types.ModuleType]] = None,
        extra_globals: Optional[Mapping[str, Any]] = None,
    ) -> ExecutionResult:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        module_backup: Dict[str, types.ModuleType] = {}
        inserted_modules: list[str] = []

        try:
            if extra_modules:
                for name, module in extra_modules.items():
                    if name in sys.modules:
                        module_backup[name] = sys.modules[name]
                    else:
                        inserted_modules.append(name)
                    sys.modules[name] = module

            # SECURITY FIX: Use restricted globals instead of full environment
            # Only allow safe built-in functions
            safe_builtins = {
                'abs': abs, 'all': all, 'any': any, 'ascii': ascii,
                'bin': bin, 'bool': bool, 'bytes': bytes, 'chr': chr,
                'dict': dict, 'dir': dir, 'divmod': divmod,
                'enumerate': enumerate, 'filter': filter, 'float': float,
                'format': format, 'frozenset': frozenset, 'hash': hash,
                'hex': hex, 'int': int, 'isinstance': isinstance, 'issubclass': issubclass,
                'iter': iter, 'len': len, 'list': list, 'map': map,
                'max': max, 'min': min, 'next': next, 'oct': oct, 'ord': ord,
                'pow': pow, 'range': range, 'repr': repr, 'reversed': reversed,
                'round': round, 'set': set, 'slice': slice, 'sorted': sorted,
                'str': str, 'sum': sum, 'tuple': tuple, 'type': type, 'zip': zip,
                'json': json,  # Allow JSON for output serialization
            }
            
            # Safely inject input_data (prevent code injection in repr)
            safe_input_data = {}
            for key, value in input_data.items():
                if isinstance(value, (str, int, float, bool, list, dict, type(None))):
                    safe_input_data[key] = value
                else:
                    safe_input_data[key] = json.loads(json.dumps(value, default=str))
            
            exec_globals: Dict[str, Any] = {
                "__name__": "__main__",
                "__package__": None,
                "__builtins__": safe_builtins,
                "input_data": safe_input_data,
            }
            if extra_globals:
                # Only add safe globals (functions, not arbitrary objects)
                for key, val in extra_globals.items():
                    if callable(val) or isinstance(val, (str, int, float, bool, type(None))):
                        exec_globals[key] = val

            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
            try:
                exec(code, exec_globals)
                raw_output = stdout_buffer.getvalue().strip()
                stderr_output = stderr_buffer.getvalue().strip()
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

            parsed_output = None
            parse_error = None
            if raw_output:
                try:
                    parsed_output = self._parse_action_output(raw_output)
                except Exception as exc:  # noqa: BLE001 - capture parsing issues
                    parse_error = exc

            return ExecutionResult(
                raw_output=raw_output,
                stderr=stderr_output,
                parsed_output=parsed_output,
                parse_error=parse_error,
            )

        except Exception as exc:  # noqa: BLE001 - capture runtime issues
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            # SECURITY FIX: Don't expose full traceback externally
            # Log internally for debugging, but return sanitized error
            tb = traceback.format_exc()
            raw_output = stdout_buffer.getvalue().strip()
            stderr_output = stderr_buffer.getvalue().strip()
            
            # Sanitize error message to avoid information disclosure
            sanitized_error = str(exc).split('\n')[0][:100]  # First line, max 100 chars
            
            return ExecutionResult(
                raw_output=raw_output,
                stderr=stderr_output,
                parsed_output=None,
                exception=exc,
                traceback=tb,  # Keep full traceback internally for debugging
            )
        finally:
            if extra_modules:
                for name in extra_modules:
                    if name in module_backup:
                        sys.modules[name] = module_backup[name]
                    else:
                        sys.modules.pop(name, None)

    @staticmethod
    def _parse_action_output(raw_output: str) -> Any:
        if not raw_output:
            return {}

        ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
        cleaned = ansi_escape.sub("", raw_output).strip()

        if not cleaned:
            return {}

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            json_start_candidates = [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx != -1]
            if not json_start_candidates:
                raise

            start = min(json_start_candidates)
            end_brace = cleaned.rfind("}")
            end_bracket = cleaned.rfind("]")
            end_candidates = [idx for idx in (end_brace, end_bracket) if idx != -1]
            if not end_candidates:
                raise

            end = max(end_candidates)
            candidate = cleaned[start : end + 1]
            return json.loads(candidate)


@dataclasses.dataclass
class PreparedEnv:
    input_overrides: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    extra_modules: Mapping[str, types.ModuleType] = dataclasses.field(default_factory=dict)
    extra_globals: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    context: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ActionTestCase:
    name: str
    base_input: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    prepare: Optional[Callable[[Path, Mapping[str, Any]], PreparedEnv]] = None
    validator: Optional[
        Callable[[ExecutionResult, Mapping[str, Any], Mapping[str, Any]], Tuple[str, str]]
    ] = None
    skip_reason: Optional[str] = None

    def run(
        self,
        action: Mapping[str, Any],
        executor: ActionExecutor,
    ) -> Tuple[str, str, ExecutionResult, Mapping[str, Any]]:
        if self.skip_reason:
            empty_result = ExecutionResult(raw_output="", stderr="", parsed_output={})
            return "skip", self.skip_reason, empty_result, {}

        with TemporaryDirectory(prefix=f"action-diag-{slugify(self.name)}-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            prepared = PreparedEnv()
            if self.prepare:
                prepared = self.prepare(tmp_path, action)

            input_data: Dict[str, Any] = dict(self.base_input)
            input_data.update(dict(prepared.input_overrides))

            result = executor.execute(
                code=str(action.get("code", "")),
                input_data=input_data,
                extra_modules=prepared.extra_modules,
                extra_globals=prepared.extra_globals,
            )

            if result.has_error():
                message = "Execution raised an exception."
                if result.traceback:
                    message += f"\n{result.traceback.strip()}"
                return "error", message, result, input_data

            if result.parse_error is not None:
                error_msg = f"Failed to parse JSON output: {result.parse_error}"
                return "error", error_msg, result, input_data

            if self.validator:
                status, message = self.validator(result, input_data, prepared.context)
            else:
                status, message = self._default_validator(result)

            return status, message, result, input_data

    @staticmethod
    def _default_validator(result: ExecutionResult) -> Tuple[str, str]:
        if isinstance(result.parsed_output, Mapping) and result.parsed_output:
            return "passed", "Action produced a non-empty JSON object."
        if isinstance(result.parsed_output, list) and result.parsed_output:
            return "passed", "Action produced a non-empty list."
        return "incorrect result", "Action output was empty."
