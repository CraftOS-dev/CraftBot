"""Environment and validation for the "google search" action."""

from __future__ import annotations

import subprocess as real_subprocess
import types
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from diagnostic.framework import ActionTestCase, ExecutionResult, PreparedEnv


def _build_google_search_stubs() -> Mapping[str, types.ModuleType]:
    modules: Dict[str, types.ModuleType] = {}

    # googlesearch module
    googlesearch_mod = types.ModuleType("googlesearch")

    class FakeHit:
        def __init__(self, url: str, title: str) -> None:
            self.url = url
            self.title = title

    def search(query: str, num_results: int = 5, advanced: bool = True):  # noqa: ARG001
        hits: List[FakeHit] = []
        for idx in range(num_results):
            hits.append(
                FakeHit(
                    url=f"https://example.com/{idx}", title=f"{query} result {idx + 1}"
                )
            )
        return hits

    googlesearch_mod.search = search  # type: ignore[attr-defined]
    googlesearch_mod.__all__ = ["search"]
    modules["googlesearch"] = googlesearch_mod

    # Package identifiers used by the action's dependency bootstrapper.
    modules["googlesearch_python"] = types.ModuleType("googlesearch_python")
    modules["googlesearch-python"] = types.ModuleType("googlesearch-python")

    # aiohttp module
    aiohttp_mod = types.ModuleType("aiohttp")

    class ClientTimeout:
        def __init__(self, total: int | None = None) -> None:
            self.total = total

    class _FakeResponse:
        def __init__(self, url: str) -> None:
            self.url = url
            self.status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: D401, ANN001, ARG002
            return False

        def raise_for_status(self) -> None:  # noqa: D401
            return None

        async def read(self) -> bytes:  # noqa: D401
            body = f"<html><body>diagnostic content for {self.url}</body></html>"
            return body.encode("utf-8")

    class ClientSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401, ANN401
            self._headers = kwargs.get("headers", {})

        async def __aenter__(self):  # noqa: D401
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: D401, ANN001, ARG002
            return False

        def get(self, url: str, timeout: Any = None, allow_redirects: bool = True):  # noqa: D401, ANN401
            return _FakeResponse(url)

    aiohttp_mod.ClientSession = ClientSession  # type: ignore[attr-defined]
    aiohttp_mod.ClientTimeout = ClientTimeout  # type: ignore[attr-defined]
    modules["aiohttp"] = aiohttp_mod

    # trafilatura module
    trafilatura_mod = types.ModuleType("trafilatura")

    def extract(
        html: str, include_comments: bool = False, include_tables: bool = False
    ) -> str:  # noqa: D401
        return html

    trafilatura_mod.extract = extract  # type: ignore[attr-defined]
    modules["trafilatura"] = trafilatura_mod

    # fake_useragent module
    fake_useragent_mod = types.ModuleType("fake_useragent")

    class UserAgent:
        def __init__(self) -> None:  # noqa: D401
            pass

        @property
        def random(self) -> str:  # noqa: D401
            return "diagnostic-user-agent"

    fake_useragent_mod.UserAgent = UserAgent  # type: ignore[attr-defined]
    modules["fake_useragent"] = fake_useragent_mod

    # tenacity module (minimal stubs)
    tenacity_mod = types.ModuleType("tenacity")

    def retry(*args: Any, **kwargs: Any):  # noqa: D401, ANN401
        def decorator(func):
            return func

        return decorator

    class stop_after_attempt:
        def __init__(self, attempts: int) -> None:
            self.attempts = attempts

        def __call__(self, func):
            return func

    def wait_exponential_jitter(min_value: int, max_value: int):  # noqa: D401, ANN001, ARG001
        return (min_value, max_value)

    tenacity_mod.retry = retry  # type: ignore[attr-defined]
    tenacity_mod.stop_after_attempt = stop_after_attempt  # type: ignore[attr-defined]
    tenacity_mod.wait_exponential_jitter = wait_exponential_jitter  # type: ignore[attr-defined]
    modules["tenacity"] = tenacity_mod

    # chardet module
    chardet_mod = types.ModuleType("chardet")

    def detect(data: bytes) -> Mapping[str, Any]:  # noqa: D401
        return {"encoding": "utf-8"}

    chardet_mod.detect = detect  # type: ignore[attr-defined]
    modules["chardet"] = chardet_mod

    # Ensure subprocess.check_call is a no-op if invoked
    subprocess_mod = types.ModuleType("subprocess")
    for attr in dir(real_subprocess):
        if not hasattr(subprocess_mod, attr):
            setattr(subprocess_mod, attr, getattr(real_subprocess, attr))

    def check_call(cmd: Any, *args: Any, **kwargs: Any) -> int:  # noqa: D401, ANN401
        return 0

    subprocess_mod.check_call = check_call  # type: ignore[attr-defined]
    modules["subprocess"] = subprocess_mod

    return modules


def prepare_google_search(tmp_path: Path, action: Mapping[str, Any]) -> PreparedEnv:  # noqa: ARG001
    modules = _build_google_search_stubs()
    return PreparedEnv(
        input_overrides={"query": "diagnostic", "num_results": 3, "timeout_sec": 5},
        extra_modules=modules,
        context={"expected_results": 3},
    )


def validate_google_search(
    result: ExecutionResult,
    input_data: Mapping[str, Any],
    context: Mapping[str, Any],
) -> Tuple[str, str]:
    output = result.parsed_output or {}
    if not isinstance(output, Mapping):
        return "incorrect result", "Expected dictionary output."

    results = output.get("search_results")
    if not isinstance(results, list):
        return "incorrect result", "'search_results' missing or not a list."

    if not results:
        return "incorrect result", "No search results returned."

    expected_count = context.get("expected_results")
    if expected_count and len(results) != expected_count:
        return (
            "incorrect result",
            f"Expected {expected_count} results, received {len(results)}.",
        )

    for entry in results:
        if not isinstance(entry, Mapping):
            return "incorrect result", "Search result entry is not a mapping."
        if not entry.get("title") or not entry.get("url"):
            return "incorrect result", "Search result missing title or url."
        if not entry.get("content"):
            return "incorrect result", "Search result content is empty."

    return "passed", "Search results returned using diagnostic stubs."


def get_test_case() -> ActionTestCase:
    return ActionTestCase(
        name="google search",
        base_input={},
        prepare=prepare_google_search,
        validator=validate_google_search,
    )
