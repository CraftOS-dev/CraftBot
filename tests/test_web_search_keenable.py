"""web_search uses Keenable when web_search.provider is "keenable"."""

import io
import json
from unittest.mock import patch

import app.config as app_config
from app.data.action.web_search import web_search

_BODY = {
    "results": [
        {"title": "Result", "url": "https://example.com/r", "snippet": "Snippet"},
        {"title": "No url"},
    ]
}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(settings, env=None, body=None):
    requests = []

    def _urlopen(request, timeout=None):
        requests.append(request)
        return _Response(json.dumps(body or _BODY).encode())

    with (
        patch.object(app_config, "get_settings", return_value=settings),
        patch("urllib.request.urlopen", _urlopen),
        patch.dict("os.environ", env or {}, clear=False),
    ):
        result = web_search({"query": "craftbot", "num_results": 3})
    return result, requests


def test_keyless_uses_public_endpoint_with_title():
    result, requests = _run({"web_search": {"provider": "keenable"}})
    assert result["status"] == "success"
    assert [r["url"] for r in result["results"]] == ["https://example.com/r"]
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == "https://api.keenable.ai/v1/search/public"
    assert request.get_header("X-keenable-title") == "CraftBot"
    assert request.get_header("X-api-key") is None
    assert json.loads(request.data) == {"query": "craftbot", "max_results": 3}


def test_api_key_uses_keyed_endpoint():
    settings = {
        "api_keys": {"keenable": "test-key"},
        "web_search": {"provider": "keenable"},
    }
    result, requests = _run(settings)
    assert result["status"] == "success"
    assert requests[0].full_url == "https://api.keenable.ai/v1/search"
    assert requests[0].get_header("X-api-key") == "test-key"


def test_env_key_is_used_when_settings_have_none():
    _, requests = _run(
        {"web_search": {"provider": "keenable"}}, env={"KEENABLE_API_KEY": "env-key"}
    )
    assert requests[0].get_header("X-api-key") == "env-key"


def test_default_provider_does_not_call_keenable():
    with patch(
        "ddgs.DDGS.text",
        return_value=[{"title": "D", "href": "https://ddg.example/", "body": "b"}],
    ):
        _, requests = _run({"web_search": {"provider": ""}})
    assert requests == []
