"""web_search sends Google Custom Search requests to web_search.google_cse_base_url when set."""

import json
from unittest.mock import patch

import googleapiclient.discovery
import httplib2

import app.config as app_config
from app.data.action.web_search import web_search

_ITEMS = {
    "items": [
        {"title": "Result", "link": "https://example.com/r", "snippet": "Snippet"}
    ]
}


class _RecordingHttp:
    """Stands in for httplib2.Http and records each request URI."""

    def __init__(self):
        self.uris = []

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        self.uris.append(uri)
        return httplib2.Response({"status": "200"}), json.dumps(_ITEMS).encode()


def _run(base_url):
    settings = {
        "api_keys": {"google": "test-key"},
        "web_search": {"google_cse_id": "test-cx", "google_cse_base_url": base_url},
    }
    http = _RecordingHttp()
    real_build = googleapiclient.discovery.build

    def _build(*args, **kwargs):
        return real_build(*args, http=http, **kwargs)

    with (
        patch.object(app_config, "get_settings", return_value=settings),
        patch.object(googleapiclient.discovery, "build", _build),
    ):
        result = web_search({"query": "craftbot", "num_results": 1})
    return result, http.uris


def test_default_uses_google_endpoint():
    result, uris = _run("")
    assert result["status"] == "success"
    assert result["results"][0]["url"] == "https://example.com/r"
    assert len(uris) == 1
    assert uris[0].startswith("https://customsearch.googleapis.com/customsearch/v1?")
    assert "cx=test-cx" in uris[0] and "key=test-key" in uris[0]


def test_base_url_setting_moves_request():
    result, uris = _run("https://cse.example.com")
    assert result["status"] == "success"
    assert result["results"][0]["url"] == "https://example.com/r"
    assert len(uris) == 1
    assert uris[0].startswith("https://cse.example.com/customsearch/v1?")
    assert "cx=test-cx" in uris[0] and "key=test-key" in uris[0]
