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

        class BlockProviderSdks(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if (
                    fullname == "openai"
                    or fullname.startswith("openai.")
                    or fullname == "anthropic"
                    or fullname.startswith("anthropic.")
                ):
                    raise ImportError(f"{{fullname}} intentionally blocked")
                return None

        for name in list(sys.modules):
            if (
                name == "openai"
                or name.startswith("openai.")
                or name == "anthropic"
                or name.startswith("anthropic.")
            ):
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


def test_deferred_openai_compatible_provider_does_not_require_openai_sdk():
    result = _run_with_blocked_sdks(
        """
        from agent_core.core.models.factory import ModelFactory
        from agent_core.core.models.types import InterfaceType

        ctx = ModelFactory.create(
            provider="deepseek",
            interface=InterfaceType.LLM,
            deferred=True,
        )
        assert ctx["initialized"] is False
        assert ctx["client"] is None
        """
    )

    assert result.returncode == 0, result.stderr


def test_openai_compatible_provider_reports_missing_openai_sdk():
    result = _run_with_blocked_sdks(
        """
        from agent_core.core.models.factory import ModelFactory
        from agent_core.core.models.types import InterfaceType

        try:
            ModelFactory.create(
                provider="deepseek",
                interface=InterfaceType.LLM,
                api_key="deepseek-key",
            )
        except ImportError as exc:
            message = str(exc)
            assert "openai package is required" in message
            assert "DeepSeek" in message
        else:
            raise AssertionError("expected missing OpenAI SDK to raise ImportError")
        """
    )

    assert result.returncode == 0, result.stderr
