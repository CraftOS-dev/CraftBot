"""Concurrent settings changes compose, and readers only see complete JSON."""

import asyncio
import json
import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import pytest

from app import config, settings_store
from app.ui_layer.settings import (
    memory_settings,
    model_settings,
    proactive_settings,
    provider_settings,
)
from craftos_integrations.config import ConfigStore
from craftos_integrations.credentials_store import save_credential
from craftos_integrations.llm_oauth import claude_code


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"model": {"llm_provider": "anthropic"}, "sentinel": "keep"})
    )
    for module in (
        config,
        model_settings,
        provider_settings,
        memory_settings,
        proactive_settings,
    ):
        monkeypatch.setattr(module, "SETTINGS_CONFIG_PATH", path)
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    monkeypatch.setattr(config, "_settings_cache", None)
    return path


@pytest.mark.parametrize(
    "other", ["model", "auth", "key", "memory", "proactive", "language"]
)
def test_overlapping_settings_mutations_preserve_both_changes(
    settings_path, monkeypatch, other
):
    first_read = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    real_load = model_settings._load_settings

    def paused_load():
        snapshot = real_load()
        if not first_read.is_set():
            first_read.set()
            assert release_first.wait(5)
        return snapshot

    monkeypatch.setattr(model_settings, "_load_settings", paused_load)

    def second_change():
        second_started.set()
        if other == "model":
            return model_settings.update_model_settings(
                vlm_model="new-vlm", include_subscription_status=False
            )
        if other == "auth":
            return provider_settings._persist_auth_mode("anthropic", "subscription")
        if other == "key":
            return provider_settings.save_settings_to_json("anthropic", "fake-key")
        if other == "memory":
            return memory_settings.set_memory_processing_threshold(25)
        if other == "proactive":
            return proactive_settings.set_proactive_mode(False)
        return config.set_ui_language("fr")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            model_settings.update_model_settings,
            llm_model="new-llm",
            include_subscription_status=False,
        )
        assert first_read.wait(5)
        second = pool.submit(second_change)
        try:
            assert second_started.wait(5)
            # The second transaction cannot finish while the first holds its snapshot.
            with pytest.raises(FutureTimeoutError):
                second.result(timeout=0.1)
        finally:
            release_first.set()
        assert first.result(timeout=5)["success"]
        second.result(timeout=5)

    saved = json.loads(settings_path.read_text())
    assert saved["sentinel"] == "keep"
    assert saved["model"]["llm_model"] == "new-llm"
    expected = {
        "model": ("model", "vlm_model", "new-vlm"),
        "auth": ("auth_mode", "anthropic", "subscription"),
        "key": ("api_keys", "anthropic", "fake-key"),
        "memory": ("memory", "processing_threshold", 25),
        "proactive": ("proactive", "enabled", False),
        "language": ("general", "ui_language", "fr"),
    }
    section, key, value = expected[other]
    assert saved[section][key] == value


def test_subscription_status_does_not_hold_the_settings_lock(
    settings_path, monkeypatch
):
    save_credential(
        claude_code.CRED_FILE,
        claude_code.ClaudeCodeConnection(profile_version=claude_code.PROFILE_VERSION),
    )
    checking_status = threading.Event()
    release_status = threading.Event()

    def slow_status():
        checking_status.set()
        assert release_status.wait(5)
        return {"connected": True}

    monkeypatch.setattr(claude_code, "auth_status", slow_status)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(model_settings.update_model_settings, llm_model="new-llm")
        assert checking_status.wait(5)
        try:
            # Auth-mode persistence must not wait for the CLI's ten-second timeout.
            pool.submit(
                provider_settings._persist_auth_mode, "anthropic", "subscription"
            ).result(timeout=2)
        finally:
            release_status.set()
        assert saving.result(timeout=5)["success"]
    saved = json.loads(settings_path.read_text())
    assert saved["model"]["llm_model"] == "new-llm"
    assert saved["auth_mode"]["anthropic"] == "subscription"


def test_failed_atomic_replace_preserves_the_previous_settings(
    settings_path, monkeypatch
):
    previous = settings_path.read_bytes()

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(settings_store.os, "replace", fail)
    assert not model_settings.update_model_settings(
        llm_model="new-llm", include_subscription_status=False
    )["success"]
    assert settings_path.read_bytes() == previous
    assert list(settings_path.parent.glob(".settings.json.*")) == []


def test_concurrent_readers_never_observe_partial_json(settings_path):
    stop = threading.Event()
    observed = threading.Event()

    def read():
        while not stop.is_set():
            data = model_settings._load_settings()
            assert data["sentinel"] == "keep"
            observed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(read)
        try:
            assert observed.wait(5)
            for i in range(25):
                assert model_settings.update_model_settings(
                    llm_model=f"model-{i}", include_subscription_status=False
                )["success"]
        finally:
            stop.set()
        reader.result(timeout=5)


@pytest.fixture
def adapter(settings_path, monkeypatch):
    from app.ui_layer.adapters import browser_adapter

    monkeypatch.setattr(
        browser_adapter, "validate_can_save", lambda **kwargs: {"can_save": True}
    )
    adapter = object.__new__(browser_adapter.BrowserAdapter)
    agent = SimpleNamespace(provider="anthropic", activations=[])

    def reinitialize(provider):
        agent.provider = provider
        agent.activations.append(provider)
        return True

    agent.reinitialize_llm = reinitialize
    adapter._controller = SimpleNamespace(agent=agent)
    adapter.sent = []

    async def broadcast(message):
        adapter.sent.append(message)

    adapter._broadcast = broadcast
    return adapter


@pytest.mark.parametrize("second", ["save", "connect", "complete", "disconnect"])
def test_slow_status_cannot_reorder_save_and_activation(
    adapter, settings_path, monkeypatch, second
):
    """Exercise actual handlers, settings transactions and cross-client ordering."""
    from app.ui_layer.adapters import browser_adapter

    checking = threading.Event()
    release = threading.Event()
    calls = 0

    def status():
        nonlocal calls
        calls += 1
        if calls == 1:
            checking.set()
            assert release.wait(5)
        return {"connected": True}

    save_credential(
        claude_code.CRED_FILE,
        claude_code.ClaudeCodeConnection(profile_version=claude_code.PROFILE_VERSION),
    )
    monkeypatch.setattr(claude_code, "auth_status", status)

    async def connect(provider):
        return True, "Connected"

    monkeypatch.setattr(browser_adapter, "connect_subscription_async", connect)
    monkeypatch.setattr(
        browser_adapter, "complete_subscription", lambda *args: (True, "Connected")
    )
    monkeypatch.setattr(
        browser_adapter, "disconnect_subscription", lambda *args: (True, "Disconnected")
    )

    async def run():
        first = asyncio.create_task(
            adapter._handle_model_settings_update({"llmProvider": "openai"})
        )
        try:
            assert await asyncio.to_thread(checking.wait, 5)
            # The first provider must already be live while its status is blocked.
            assert adapter._controller.agent.provider == "openai"
            if second == "save":
                await asyncio.wait_for(
                    adapter._handle_model_settings_update({"llmProvider": "gemini"}), 2
                )
            elif second == "connect":
                await asyncio.wait_for(
                    adapter._handle_model_subscription_connect("anthropic"), 2
                )
            elif second == "complete":
                await asyncio.wait_for(
                    adapter._handle_model_subscription_complete(
                        "anthropic", "code", None
                    ),
                    2,
                )
            else:
                await asyncio.wait_for(
                    adapter._handle_model_subscription_disconnect("openai"), 2
                )
        finally:
            release.set()
            await first

    asyncio.run(run())
    expected = {
        "save": "gemini",
        "connect": "anthropic",
        "complete": "anthropic",
        "disconnect": "openai",
    }[second]
    assert json.loads(settings_path.read_text())["model"]["llm_provider"] == expected
    assert adapter._controller.agent.provider == expected
    assert adapter._controller.agent.activations == ["openai", expected]
    assert adapter.sent[-1]["data"]["llm_provider"] == expected
    assert adapter.sent[-1]["data"]["subscription_oauth"]["anthropic"]["connected"]


@pytest.mark.parametrize("operation", ["connect", "complete"])
def test_disconnect_prevents_late_subscription_activation(
    adapter, settings_path, monkeypatch, operation
):
    """Also cover the gap between credential completion and browser activation."""
    from app.ui_layer.adapters import browser_adapter

    ready = threading.Event()
    release = threading.Event()

    async def connect(provider):
        ready.set()
        assert await asyncio.to_thread(release.wait, 5)
        return True, "Connected"

    def complete(*args):
        ready.set()
        assert release.wait(5)
        return True, "Connected"

    monkeypatch.setattr(browser_adapter, "connect_subscription_async", connect)
    monkeypatch.setattr(browser_adapter, "complete_subscription", complete)
    monkeypatch.setattr(
        browser_adapter, "disconnect_subscription", lambda *args: (True, "Disconnected")
    )
    monkeypatch.setattr(
        browser_adapter,
        "get_subscription_status",
        lambda provider: {"connected": False},
    )

    async def run():
        method = (
            adapter._handle_model_subscription_connect("anthropic")
            if operation == "connect"
            else adapter._handle_model_subscription_complete("anthropic", "code", None)
        )
        pending = asyncio.create_task(method)
        try:
            assert await asyncio.to_thread(ready.wait, 5)
            await adapter._handle_model_subscription_disconnect("anthropic")
        finally:
            release.set()
            await pending

    asyncio.run(run())
    assert adapter._controller.agent.activations == ["anthropic"]  # Disconnect only
    assert adapter.sent[-1]["data"]["active_provider"] is None
    assert json.loads(settings_path.read_text())["model"]["llm_provider"] == "anthropic"


@pytest.mark.parametrize("kind", ["image", "video"])
def test_failed_media_activation_rolls_back_before_next_save(
    adapter, settings_path, monkeypatch, kind
):
    from app.ui_layer.adapters import browser_adapter

    entered = threading.Event()
    release = threading.Event()
    real_update = model_settings.update_model_settings
    calls = 0

    def update(**kwargs):
        nonlocal calls
        calls += 1
        result = real_update(**kwargs)
        if calls == 1:
            entered.set()
            assert release.wait(5)
        return result

    setattr(
        adapter._controller.agent, f"reinitialize_{kind}_gen", lambda provider: False
    )
    monkeypatch.setattr(browser_adapter, "update_model_settings", update)
    provider_key = f"{kind}GenProvider"

    async def run():
        first = asyncio.create_task(
            adapter._handle_model_settings_update(
                {provider_key: "gemini" if kind == "image" else "byteplus"}
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            second = asyncio.create_task(
                adapter._handle_model_settings_update({"llmProvider": "openai"})
            )
            await asyncio.sleep(0)
            assert not second.done()
        finally:
            release.set()
            await first
        await second

    asyncio.run(run())
    saved = json.loads(settings_path.read_text())["model"]
    # BytePlus is the only provider with a video model, so the video save
    # rolls back to it as well.
    assert saved[f"{kind}_gen_provider"] == (
        "openai" if kind == "image" else "byteplus"
    )
    assert saved["llm_provider"] == adapter._controller.agent.provider == "openai"
