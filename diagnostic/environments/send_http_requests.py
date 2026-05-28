"""Diagnostic environment for the "send HTTP requests" action."""

from __future__ import annotations

import types
from typing import Any, Mapping

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def _build_requests_stub(recorded_calls: list[Mapping[str, Any]]) -> types.ModuleType:
    module = types.ModuleType("requests")

    class _Response:
        def __init__(self) -> None:
            self.status_code = 200
            self.ok = True
            self.headers = {"Content-Type": "application/json"}
            self.text = '{"ok": true}'
            self.url = "https://api.example.test/v1/items?limit=5"

        def json(self) -> Mapping[str, Any]:
            return {"ok": True}

    def request(method: str, url: str, **kwargs: Any) -> _Response:  # noqa: ANN401
        recorded_calls.append({"method": method, "url": url, **kwargs})
        return _Response()

    module.request = request  # type: ignore[attr-defined]
    return module


def get_test_case() -> ActionTestCase:
    def prepare(tmp_path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001, ANN001
        recorded: list[Mapping[str, Any]] = []
        extra_modules = {"requests": _build_requests_stub(recorded)}

        return PreparedEnv(
            input_overrides={
                "method": "GET",
                "url": "https://api.example.test/v1/items",
                "params": {"limit": "5"},
                "headers": {"Accept": "application/json"},
                "timeout": 5,
                "allow_redirects": True,
                "verify_tls": True,
            },
            extra_modules=extra_modules,
            context={"calls": recorded},
        )

    def validator(
        result: ExecutionResult,
        input_data: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> tuple[str, str]:
        if result.has_error():
            return "error", "Execution raised an exception."

        payload = result.parsed_output or {}
        if payload.get("status") != "success":
            return "incorrect result", f"Unexpected status: {payload.get('status')!r}."
        if payload.get("status_code") != 200:
            return "incorrect result", "status_code should be 200."
        if payload.get("response_json") != {"ok": True}:
            return "incorrect result", "response_json missing expected data."
        if payload.get("final_url") != "https://api.example.test/v1/items?limit=5":
            return "incorrect result", "final_url does not reflect stub response URL."
        if payload.get("message") not in ("", None):
            return (
                "incorrect result",
                "Message should be empty for successful response.",
            )

        calls = context["calls"]
        if len(calls) != 1:
            return "incorrect result", f"Expected one HTTP request, saw {len(calls)}."
        call = calls[0]
        if (
            call.get("method") != "GET"
            or call.get("url") != "https://api.example.test/v1/items"
        ):
            return "incorrect result", "Method or URL recorded incorrectly."
        if call.get("params") != {"limit": "5"}:
            return "incorrect result", "Query parameters were not forwarded."
        if call.get("headers") != {"Accept": "application/json"}:
            return "incorrect result", "Headers were not forwarded."
        if call.get("timeout") != 5:
            return "incorrect result", "Timeout argument mismatch."
        if call.get("allow_redirects") is not True:
            return "incorrect result", "allow_redirects should remain True."
        if call.get("verify") is not True:
            return "incorrect result", "TLS verification flag should be True."

        return "passed", "HTTP request executed using stubbed transport."

    return ActionTestCase(
        name="send HTTP requests",
        base_input={},
        prepare=prepare,
        validator=validator,
    )
