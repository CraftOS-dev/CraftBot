"""Removing a saved API key from Settings > Model."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import config
from app.ui_layer.settings import model_settings
from craftos_integrations.config import ConfigStore
from craftos_integrations.credentials_store import save_credential
from craftos_integrations.llm_oauth import claude_code

ANTHROPIC_KEY = "sk-ant-aaaaaaaaaaaaaaaa"
OPENAI_KEY = "sk-oai-bbbbbbbbbbbbbbbb"


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "model": {
                    "llm_provider": "anthropic",
                    "vlm_provider": "anthropic",
                    "image_gen_provider": "openai",
                },
                "api_keys": {"anthropic": ANTHROPIC_KEY, "openai": OPENAI_KEY},
                "sentinel": "keep",
            }
        )
    )
    for module in (config, model_settings):
        monkeypatch.setattr(module, "SETTINGS_CONFIG_PATH", path)
    # Subscription credentials live under the project root: keep them in tmp.
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    monkeypatch.setattr(config, "_settings_cache", None)
    return path


def _saved(path):
    return json.loads(path.read_text())


def _connect_claude_subscription():
    save_credential(
        claude_code.CRED_FILE,
        claude_code.ClaudeCodeConnection(profile_version=claude_code.PROFILE_VERSION),
    )


def test_removes_a_key_the_active_model_does_not_use(settings_path):
    result = model_settings.remove_api_key("openai")

    assert result["success"]
    assert result["api_keys"]["openai"] == {"has_key": False, "masked_key": ""}
    assert result["api_keys"]["anthropic"]["has_key"]
    saved = _saved(settings_path)
    assert saved["api_keys"] == {"anthropic": ANTHROPIC_KEY, "openai": ""}
    assert saved["sentinel"] == "keep"


def test_refuses_the_active_providers_only_credential(settings_path):
    before = settings_path.read_text()

    result = model_settings.remove_api_key("anthropic")

    assert not result["success"]
    assert "Anthropic" in result["error"]
    assert settings_path.read_text() == before


def test_refuses_the_vlm_providers_only_credential(settings_path):
    saved = _saved(settings_path)
    saved["model"]["vlm_provider"] = "openai"
    settings_path.write_text(json.dumps(saved))

    result = model_settings.remove_api_key("openai")

    assert not result["success"]
    assert _saved(settings_path)["api_keys"]["openai"] == OPENAI_KEY


def test_signed_in_subscription_lets_the_active_providers_key_go(settings_path):
    _connect_claude_subscription()

    result = model_settings.remove_api_key("anthropic")

    assert result["success"]
    assert result["api_keys"]["anthropic"]["has_key"] is False
    assert _saved(settings_path)["api_keys"]["anthropic"] == ""


def test_provider_without_an_api_key_setting_is_refused(settings_path):
    before = settings_path.read_text()

    result = model_settings.remove_api_key("remote")

    assert not result["success"]
    assert settings_path.read_text() == before


@pytest.fixture
def adapter(settings_path):
    from app.ui_layer.adapters import browser_adapter

    adapter = object.__new__(browser_adapter.BrowserAdapter)
    agent = SimpleNamespace(llm_reinits=[], media_rebuilds=[])
    agent.reinitialize_llm = lambda *args, **kwargs: agent.llm_reinits.append(args)

    def rebuild(kind):
        def run(provider=None, *, keep_live_on_failure=True):
            agent.media_rebuilds.append((kind, provider, keep_live_on_failure))
            return False

        return run

    agent.reinitialize_image_gen = rebuild("image")
    agent.reinitialize_video_gen = rebuild("video")
    adapter._controller = SimpleNamespace(agent=agent)
    adapter.sent = []

    async def broadcast(message):
        adapter.sent.append(message)

    adapter._broadcast = broadcast
    return adapter


def test_handler_rebuilds_media_that_used_the_key_without_touching_the_llm(
    adapter, settings_path
):
    asyncio.run(adapter._handle_model_api_key_remove("openai"))

    agent = adapter._controller.agent
    # Image generation used the OpenAI key: rebuilt even though it now has
    # no credential, so the removed key is not used again.
    assert agent.media_rebuilds == [("image", "openai", False)]
    # The active model never used this key; a reinit would only cost cache.
    assert agent.llm_reinits == []
    message = adapter.sent[-1]
    assert message["type"] == "model_api_key_remove"
    assert message["data"]["success"]
    assert message["data"]["provider"] == "openai"
    assert message["data"]["api_keys"]["openai"]["has_key"] is False


def test_handler_reports_a_refusal_without_rebuilding(adapter, settings_path):
    asyncio.run(adapter._handle_model_api_key_remove("anthropic"))

    assert adapter._controller.agent.media_rebuilds == []
    data = adapter.sent[-1]["data"]
    assert data["success"] is False
    assert data["provider"] == "anthropic"
    assert _saved(settings_path)["api_keys"]["anthropic"] == ANTHROPIC_KEY


class _FakeMediaInterface:
    def __init__(self, *, provider, model, api_key, deferred):
        self.deferred = deferred
        self.is_initialized = bool(api_key)


@pytest.mark.parametrize("kind", ["image", "video"])
def test_media_rebuild_swaps_in_the_keyless_interface_only_when_asked(
    settings_path, monkeypatch, kind
):
    from app import agent_base, image_gen_interface, video_gen_interface
    from app.internal_action_interface import InternalActionInterface

    module = image_gen_interface if kind == "image" else video_gen_interface
    cls_name = "ImageGenInterface" if kind == "image" else "VideoGenInterface"
    monkeypatch.setattr(module, cls_name, _FakeMediaInterface)
    monkeypatch.setattr(config, "get_api_key", lambda provider: "")
    live = object()
    monkeypatch.setattr(InternalActionInterface, f"{kind}_gen_interface", live)
    agent = object.__new__(agent_base.AgentBase)
    setattr(agent, f"{kind}_gen", live)
    rebuild = getattr(agent, f"reinitialize_{kind}_gen")

    # A failed Save keeps the live interface so its settings can roll back.
    assert rebuild("openai") is False
    assert getattr(agent, f"{kind}_gen") is live

    # After a key removal the keyless interface replaces it, built deferred
    # (as at startup) so construction does not raise.
    assert rebuild("openai", keep_live_on_failure=False) is False
    swapped = getattr(agent, f"{kind}_gen")
    assert isinstance(swapped, _FakeMediaInterface) and swapped.deferred
    assert getattr(InternalActionInterface, f"{kind}_gen_interface") is swapped
