# -*- coding: utf-8 -*-
import json
from pathlib import Path
import subprocess
import sys
import textwrap

from agent_core.core.models.factory import _OpenAICompatibleClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_openai_compatible_fallback_posts_chat_completion(monkeypatch):
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": "{\"ok\":true}"}}],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "prompt_tokens_details": {"cached_tokens": 1},
                    },
                }
            ).encode("utf-8")

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(
        "agent_core.core.models.factory.urllib.request.urlopen",
        fake_urlopen,
    )

    client = _OpenAICompatibleClient(
        api_key="deepseek-key",
        base_url="https://api.deepseek.com",
        timeout=7,
    )
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1,
        extra_body={"prompt_cache_key": "route-1"},
    )

    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["timeout"] == 7
    assert seen["headers"]["Authorization"] == "Bearer deepseek-key"
    assert seen["body"]["prompt_cache_key"] == "route-1"
    assert response.choices[0].message.content == "{\"ok\":true}"
    assert response.usage.prompt_tokens == 3
    assert response.usage.prompt_tokens_details.cached_tokens == 1


def test_deepseek_context_uses_fallback_when_openai_sdk_missing():
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class BlockOpenAI(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "openai" or fullname.startswith("openai."):
                    raise ImportError("openai intentionally blocked")
                return None

        for name in list(sys.modules):
            if name == "openai" or name.startswith("openai."):
                del sys.modules[name]
        sys.meta_path.insert(0, BlockOpenAI())

        from agent_core.core.models.factory import ModelFactory
        from agent_core.core.models.types import InterfaceType

        ctx = ModelFactory.create(
            provider="deepseek",
            interface=InterfaceType.LLM,
            api_key="deepseek-key",
        )
        assert ctx["initialized"] is True
        assert ctx["provider"] == "deepseek"
        assert ctx["client"].__class__.__name__ == "_OpenAICompatibleClient"
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
