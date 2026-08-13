"""PR 5 host wiring: listener fan-out.

Covers the three host-side pieces:

1. ``CraftBotEventSink`` — enriches listener events with account
   context (``account`` key + ``(alias-or-identity)`` source suffix) and
   forwards them to the same ``ConfigStore.on_message`` callback the
   legacy manager uses.
2. ``ExternalCommsManager(exclude_platforms=...)`` — the legacy manager
   never starts listening on platforms owned by the ListenerManager
   (start / start_platform / reload), while staying backward compatible.
3. Browser-adapter initial-connect cut-over — ``connect_oauth`` for a multi-account
   provider id routes through ``IntegrationSystem.add_account`` while
   broadcasting the unchanged ``integration_connect_result`` shape;
   legacy ids keep the legacy handler login.

No pytest-asyncio in this repo — async paths are driven with asyncio.run.
The ListenerManager itself is built by a parallel PR; the one test that
needs the real module skips when it is not importable yet.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pytest

import app.integrations as integrations
import app.ui_layer.adapters.browser_adapter as ba
from app.integrations import CraftBotEventSink
from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from craftos_integrations.config import ConfigStore
from craftos_integrations.contracts import AccountInfo
from craftos_integrations.manager import ExternalCommsManager


def acct(identity: str, alias: Optional[str] = None) -> AccountInfo:
    return AccountInfo(
        identity=identity, alias=alias, is_primary=False, listen=True,
        added_at="2026-08-10T00:00:00+00:00",
    )


def event() -> Dict[str, Any]:
    """The payload-dict shape ExternalCommsManager._handle_platform_message builds."""
    return {
        "source": "Gmail",
        "integrationType": "gmail",
        "contactId": "c-1",
        "contactName": "Carol",
        "messageBody": "hello",
        "channelId": None,
        "channelName": None,
        "messageId": "m-1",
        "is_self_message": False,
        "raw": {},
    }


# ── CraftBotEventSink ────────────────────────────────────────────────────


class _AccountsOnlySystem:
    def __init__(self, accounts: List[AccountInfo], raise_on_list: bool = False):
        outer_accounts = accounts
        outer_raise = raise_on_list

        class _Accounts:
            def list_accounts(self, provider_id: str) -> List[AccountInfo]:
                if outer_raise:
                    raise RuntimeError("accounts unavailable")
                return list(outer_accounts)

        self.accounts = _Accounts()


@pytest.fixture
def captured(monkeypatch):
    """ConfigStore.on_message replaced with a recording async callback."""
    payloads: List[Dict[str, Any]] = []

    async def on_message(payload: Dict[str, Any]) -> None:
        payloads.append(payload)

    monkeypatch.setattr(ConfigStore, "on_message", on_message)
    return payloads


def sink_with_accounts(monkeypatch, accounts, raise_on_list=False) -> CraftBotEventSink:
    fake = _AccountsOnlySystem(accounts, raise_on_list=raise_on_list)
    monkeypatch.setattr(integrations, "get_system", lambda: fake)
    return CraftBotEventSink()


def test_sink_enriches_and_forwards_alias_preferred(monkeypatch, captured):
    sink = sink_with_accounts(
        monkeypatch, [acct("a@x.com", "work"), acct("b@y.com")]
    )
    asyncio.run(sink.on_event("gmail", "a@x.com", event()))
    (payload,) = captured
    assert payload["account"] == "a@x.com"
    assert payload["source"] == "Gmail (work)"  # alias preferred over identity
    # rest of the legacy payload contract travels through untouched
    assert payload["integrationType"] == "gmail"
    assert payload["messageBody"] == "hello"


def test_sink_falls_back_to_identity_without_alias(monkeypatch, captured):
    sink = sink_with_accounts(monkeypatch, [acct("b@y.com", None)])
    asyncio.run(sink.on_event("gmail", "b@y.com", event()))
    (payload,) = captured
    assert payload["source"] == "Gmail (b@y.com)"


def test_sink_alias_lookup_failure_is_best_effort(monkeypatch, captured):
    sink = sink_with_accounts(monkeypatch, [], raise_on_list=True)
    asyncio.run(sink.on_event("gmail", "a@x.com", event()))
    (payload,) = captured
    assert payload["account"] == "a@x.com"
    assert payload["source"] == "Gmail (a@x.com)"


def test_sink_drops_event_when_no_callback(monkeypatch, captured):
    monkeypatch.setattr(ConfigStore, "on_message", None)
    sink = sink_with_accounts(monkeypatch, [acct("a@x.com", "work")])
    asyncio.run(sink.on_event("gmail", "a@x.com", event()))  # must not raise
    assert captured == []


def test_sink_does_not_mutate_the_original_event(monkeypatch, captured):
    sink = sink_with_accounts(monkeypatch, [acct("a@x.com", "work")])
    original = event()
    asyncio.run(sink.on_event("gmail", "a@x.com", original))
    assert original == event()  # enrichment happened on a copy
    assert captured[0] is not original


# ── legacy manager exclusion ─────────────────────────────────────────────


class FakeClient:
    def __init__(self, supports_listening=True, has_creds=True):
        self.supports_listening = supports_listening
        self._has_creds = has_creds
        self.is_listening = False
        self.start_calls = 0

    def has_credentials(self) -> bool:
        return self._has_creds

    async def start_listening(self, callback) -> None:
        self.start_calls += 1
        self.is_listening = True

    async def stop_listening(self) -> None:
        self.is_listening = False


@pytest.fixture
def platforms(monkeypatch):
    """Two listen-capable fake platforms wired into the manager module."""
    clients = {"gmail": FakeClient(), "telegram": FakeClient()}
    import craftos_integrations.manager as manager_mod

    monkeypatch.setattr(manager_mod, "autoload_integrations", lambda: None)
    monkeypatch.setattr(manager_mod, "get_all_clients", lambda: dict(clients))
    monkeypatch.setattr(manager_mod, "get_client", clients.get)
    monkeypatch.setattr(manager_mod, "invalidate_client", lambda pid: None)
    return clients


async def _noop_on_message(payload: Dict[str, Any]) -> None:
    pass


def test_start_skips_excluded_platforms(platforms):
    mgr = ExternalCommsManager(_noop_on_message, exclude_platforms=["gmail"])
    asyncio.run(mgr.start())
    assert platforms["gmail"].start_calls == 0
    assert platforms["telegram"].start_calls == 1
    assert set(mgr.get_status()["channels"]) == {"telegram"}


def test_start_platform_refuses_excluded(platforms):
    mgr = ExternalCommsManager(_noop_on_message, exclude_platforms=["gmail"])
    assert asyncio.run(mgr.start_platform("gmail")) is False
    assert platforms["gmail"].start_calls == 0
    assert asyncio.run(mgr.start_platform("telegram")) is True


def test_reload_never_starts_excluded(platforms):
    mgr = ExternalCommsManager(_noop_on_message, exclude_platforms=["gmail"])
    asyncio.run(mgr.start())
    result = asyncio.run(mgr.reload())
    assert result["success"] is True
    assert "gmail" not in result["started"]
    assert platforms["gmail"].start_calls == 0


def test_no_exclusion_is_backward_compatible(platforms):
    mgr = ExternalCommsManager(_noop_on_message)
    asyncio.run(mgr.start())
    assert platforms["gmail"].start_calls == 1
    assert platforms["telegram"].start_calls == 1


# ── connect_oauth cut-over (browser adapter) ──────────────────────────


def make_adapter() -> Tuple[BrowserAdapter, List[Dict[str, Any]]]:
    """A BrowserAdapter with only the state the OAuth handler touches."""
    adapter = object.__new__(BrowserAdapter)
    adapter._oauth_tasks = {}
    sent: List[Dict[str, Any]] = []

    async def _broadcast(message: Dict[str, Any]) -> None:
        sent.append(message)

    async def _list_stub() -> None:
        sent.append({"type": "integration_list", "data": {"stub": True}})

    adapter._broadcast = _broadcast
    adapter._handle_integration_list = _list_stub
    return adapter, sent


async def drain_tasks() -> None:
    while True:
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not others:
            return
        await asyncio.gather(*others)


def results_of(sent: List[Dict[str, Any]], msg_type: str) -> List[Dict[str, Any]]:
    return [m["data"] for m in sent if m["type"] == msg_type]


class FakeV2System:
    def __init__(self, known=("gmail",)):
        self._known = set(known)
        self.add_calls: List[str] = []
        self.add_result: Tuple[bool, str] = (True, "Connected a@x.com")

        outer = self

        class _Registry:
            def get(_self, pid):
                return object() if pid in outer._known else None

        self.registry = _Registry()

    async def add_account(self, provider_id: str):
        self.add_calls.append(provider_id)
        ok, message = self.add_result
        return ok, message, [acct("a@x.com", "work")]


@pytest.fixture
def v2_system(monkeypatch):
    fake = FakeV2System(known=("gmail",))
    monkeypatch.setattr(integrations, "get_system", lambda: fake)
    return fake


@pytest.fixture
def legacy_oauth(monkeypatch):
    calls: List[str] = []

    async def fake_connect(integration_id: str):
        calls.append(integration_id)
        return True, "legacy connected"

    monkeypatch.setattr(ba, "connect_integration_oauth", fake_connect)
    return calls


def test_connect_oauth_routes_v2_through_add_account(v2_system, legacy_oauth):
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_connect_oauth("gmail")
        await drain_tasks()

    asyncio.run(scenario())
    assert v2_system.add_calls == ["gmail"]
    assert legacy_oauth == []  # legacy login must not run for a multi-account id
    (data,) = results_of(sent, "integration_connect_result")
    assert data == {"success": True, "message": "Connected a@x.com", "id": "gmail"}
    # success still refreshes the integration list, task registry is clean
    assert results_of(sent, "integration_list")
    assert adapter._oauth_tasks == {}


def test_connect_oauth_v2_failure_keeps_result_shape(v2_system, legacy_oauth):
    adapter, sent = make_adapter()
    v2_system.add_result = (False, "OAuth timed out")

    async def scenario():
        await adapter._handle_integration_connect_oauth("gmail")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_connect_result")
    assert data == {"success": False, "message": "OAuth timed out", "id": "gmail"}
    assert not results_of(sent, "integration_list")


def test_connect_oauth_non_v2_uses_legacy_handler(v2_system, legacy_oauth):
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_connect_oauth("jira")
        await drain_tasks()

    asyncio.run(scenario())
    assert legacy_oauth == ["jira"]
    assert v2_system.add_calls == []
    (data,) = results_of(sent, "integration_connect_result")
    assert data == {"success": True, "message": "legacy connected", "id": "jira"}


# ── start_listeners wiring (needs the parallel PR's ListenerManager) ─────

# importorskip would skip this whole module (all tests above included), so
# the optional dependency is probed with a plain try/except + skipif.
try:
    import craftos_integrations.core.listeners as listeners_mod
except ImportError:  # pragma: no cover - parallel PR not merged yet
    listeners_mod = None


class FakeListenerManager:
    instances: List["FakeListenerManager"] = []

    def __init__(self, system, sink, cursors):
        self.system = system
        self.sink = sink
        self.cursors = cursors
        self.started = 0
        self.stopped = 0
        FakeListenerManager.instances.append(self)

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


@pytest.mark.skipif(
    listeners_mod is None,
    reason="ListenerManager lands in a parallel PR; wiring is code-complete",
)
def test_start_listeners_builds_once_and_attaches(monkeypatch):
    FakeListenerManager.instances = []
    system = _AccountsOnlySystem([])
    monkeypatch.setattr(integrations, "get_system", lambda: system)
    monkeypatch.setattr(integrations, "_listeners", None)
    monkeypatch.setattr(integrations, "_listener_task", None)
    monkeypatch.setattr(listeners_mod, "ListenerManager", FakeListenerManager)
    monkeypatch.setattr(listeners_mod, "FileCursorStore", lambda: "cursors")

    asyncio.run(integrations.start_listeners())
    asyncio.run(integrations.start_listeners())  # idempotent construction

    assert len(FakeListenerManager.instances) == 1
    manager = FakeListenerManager.instances[0]
    assert getattr(system, "listeners") is manager
    assert isinstance(manager.sink, CraftBotEventSink)
    assert manager.cursors == "cursors"
    assert manager.started == 2

    asyncio.run(integrations.stop_listeners())
    assert manager.stopped == 1
