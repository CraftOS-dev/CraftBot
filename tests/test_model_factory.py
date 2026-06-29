# -*- coding: utf-8 -*-
from pathlib import Path
import subprocess
import sys
import textwrap

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_with_blocked_sdks(code: str) -> subprocess.CompletedProcess:
    script = textwrap.dedent(
        f"""
        import importlib.abc
        import sys

        # Block the OAuth token lookup so these tests are hermetic: a
        # connected subscription (SuperGrok/ChatGPT Plus) would otherwise take
        # the OAuth-precedence path and eagerly build a client, making the
        # SDK-deferral contract depend on the developer's local credentials.
        _BLOCKED_PREFIXES = ("openai", "anthropic")
        _BLOCKED_EXACT = ("craftos_integrations.integrations.llm_oauth.tokens",)

        def _is_blocked(name):
            return name in _BLOCKED_EXACT or any(
                name == p or name.startswith(p + ".") for p in _BLOCKED_PREFIXES
            )

        class BlockProviderSdks(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if _is_blocked(fullname):
                    raise ImportError(f"{{fullname}} intentionally blocked")
                return None

        for name in list(sys.modules):
            if _is_blocked(name):
                del sys.modules[name]
        sys.meta_path.insert(0, BlockProviderSdks())

        {textwrap.indent(textwrap.dedent(code), "        ")}
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )


def test_importing_model_factory_does_not_require_provider_sdks():
    result = _run_with_blocked_sdks(
        """
        from agent_core.core.models.factory import ModelFactory
        assert ModelFactory is not None
        """
    )

    assert result.returncode == 0, result.stderr


def test_deferred_openai_compatible_providers_do_not_require_openai_sdk():
    result = _run_with_blocked_sdks(
        """
        from agent_core.core.models.factory import ModelFactory
        from agent_core.core.models.types import InterfaceType

        for provider in ("deepseek", "grok", "moonshot", "minimax", "openrouter"):
            ctx = ModelFactory.create(
                provider=provider,
                interface=InterfaceType.LLM,
                deferred=True,
            )
            assert ctx["initialized"] is False
            assert ctx["client"] is None
        """
    )

    assert result.returncode == 0, result.stderr


def test_openai_compatible_providers_report_missing_openai_sdk():
    result = _run_with_blocked_sdks(
        """
        from agent_core.core.models.factory import ModelFactory
        from agent_core.core.models.types import InterfaceType

        providers = {
            "deepseek": "DeepSeek",
            "grok": "Grok",
            "moonshot": "Moonshot",
            "minimax": "MiniMax",
            "openrouter": "OpenRouter",
        }

        for provider, display in providers.items():
            try:
                ModelFactory.create(
                    provider=provider,
                    interface=InterfaceType.LLM,
                    api_key=f"{provider}-key",
                )
            except ImportError as exc:
                message = str(exc)
                assert "openai package is required" in message
                assert display in message
            else:
                raise AssertionError(
                    f"expected missing OpenAI SDK to raise ImportError for {provider}"
                )
        """
    )

    assert result.returncode == 0, result.stderr
