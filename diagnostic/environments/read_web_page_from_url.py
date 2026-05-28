"""Diagnostic environment for the "read web page from URL" action."""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Mapping

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def _build_requests_stub(
    *,
    html_payload: str,
    final_url: str,
    recorded_calls: list[Mapping[str, Any]],
) -> types.ModuleType:
    module = types.ModuleType("requests")

    class _StubResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.ok = True
            self.headers = {"Content-Type": "text/html; charset=utf-8"}
            self.url = final_url
            self.encoding = "utf-8"
            self._data = html_payload.encode("utf-8")

        def __enter__(self) -> "_StubResponse":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:  # noqa: ANN401
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int = 65536):  # noqa: ANN001, D401 - generator
            yield self._data[: chunk_size // 2]
            yield self._data[chunk_size // 2 :]

    def get(url: str, **kwargs: Any) -> _StubResponse:  # noqa: ANN401
        recorded_calls.append({"url": url, **kwargs})
        return _StubResponse()

    module.get = get  # type: ignore[attr-defined]

    def request(method: str, url: str, **kwargs: Any) -> _StubResponse:  # noqa: ANN401
        recorded_calls.append({"method": method, "url": url, **kwargs})
        return _StubResponse()

    module.request = request  # type: ignore[attr-defined]
    return module


def _build_trafilatura_stub(content: str, title: str) -> dict[str, types.ModuleType]:
    module = types.ModuleType("trafilatura")

    def extract(*args: Any, **kwargs: Any) -> str:  # noqa: ANN401
        return content

    module.extract = extract  # type: ignore[attr-defined]

    metadata_mod = types.ModuleType("trafilatura.metadata")

    class _Meta:
        def __init__(self, value: str) -> None:
            self.title = value

    def extract_metadata(*args: Any, **kwargs: Any) -> _Meta:  # noqa: ANN401
        return _Meta(title)

    metadata_mod.extract_metadata = extract_metadata  # type: ignore[attr-defined]

    module.metadata = metadata_mod  # type: ignore[attr-defined]
    return {"trafilatura": module}


def _build_bs4_stub() -> dict[str, types.ModuleType]:
    bs4_module = types.ModuleType("bs4")

    class BeautifulSoup:  # pragma: no cover - fallback only
        def __init__(self, text: str, parser: str | None = None) -> None:  # noqa: ARG002
            self._text = text
            self.title = types.SimpleNamespace(string="Stub Title")

        def __call__(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            raise NotImplementedError

        def __iter__(self):  # pragma: no cover - unused but for compatibility
            return iter(())

        def __getattr__(self, item: str) -> Any:  # noqa: ANN401
            if item == "find_all":
                return lambda name: []
            if item == "get_text":
                return lambda *args, **kwargs: self._text  # noqa: ARG002
            if item == "decompose":
                return lambda: None
            raise AttributeError(item)

    bs4_module.BeautifulSoup = BeautifulSoup  # type: ignore[attr-defined]
    beautifulsoup4_pkg = types.ModuleType("beautifulsoup4")
    beautifulsoup4_pkg.BeautifulSoup = BeautifulSoup  # type: ignore[attr-defined]
    lxml_stub = types.ModuleType("lxml")
    return {"bs4": bs4_module, "beautifulsoup4": beautifulsoup4_pkg, "lxml": lxml_stub}


def get_test_case() -> ActionTestCase:
    def prepare(tmp_path: Path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001
        html_payload = "<html><head><title>Stub Article</title></head><body><p>Hello world.</p></body></html>"
        final_url = "https://example.test/articles/42"
        recorded: list[Mapping[str, Any]] = []

        extra_modules: dict[str, types.ModuleType] = {
            **_build_trafilatura_stub(content="Markdown body", title="Stub Article"),
            **_build_bs4_stub(),
        }
        extra_modules.update(
            {
                "requests": _build_requests_stub(
                    html_payload=html_payload,
                    final_url=final_url,
                    recorded_calls=recorded,
                )
            }
        )

        context = {
            "final_url": final_url,
            "html": html_payload,
            "calls": recorded,
        }

        return PreparedEnv(
            input_overrides={
                "url": final_url,
                "timeout": 10,
                "extract_main": True,
                "include_html": False,
                "max_bytes": 1024,
            },
            extra_modules=extra_modules,
            context=context,
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
        if payload.get("final_url") != context["final_url"]:
            return "incorrect result", "final_url mismatch."
        if payload.get("title") != "Stub Article":
            return "incorrect result", "Title did not propagate from metadata stub."
        if payload.get("content") != "Markdown body":
            return "incorrect result", "Content did not use trafilatura extract output."
        if "html" in payload:
            return (
                "incorrect result",
                "HTML should be omitted when include_html is False.",
            )

        calls = context["calls"]
        if not calls:
            return "incorrect result", "No HTTP request was recorded."
        first_call = calls[0]
        if first_call.get("url") != context["final_url"]:
            return "incorrect result", "Request executed against unexpected URL."
        if not first_call.get("stream"):
            return (
                "incorrect result",
                "Expected stream=True to be passed to requests.get.",
            )

        return "passed", "Web page retrieved and parsed using stubs."

    return ActionTestCase(
        name="read web page from URL",
        base_input={},
        prepare=prepare,
        validator=validator,
    )
