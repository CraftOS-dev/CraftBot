"""PR 5 host wiring: listener fan-out.

Covers the three host-side pieces:

1. ``CraftBotEventSink`` — enriches listener events with account
   context (``account`` key + ``(alias-or-identity)`` source suffix) and
   forwards them to the host's ``ConfigStore.on_message`` callback.
2. Listening coverage — every client that can listen has a provider, so
   the ListenerManager owns all inbound events. A listen-capable client
   without one would have nothing driving it.
3. Browser-adapter initial connect — ``connect_oauth`` routes through
   ``IntegrationSystem.add_account`` while broadcasting the
   ``integration_connect_result`` shape the frontend expects. An id the
   system does not know is an error, not a fallback.

No pytest-asyncio in this repo — async paths are driven with asyncio.run.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pytest

import app.integrations as integrations
from app.integrations import CraftBotEventSink
from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from craftos_integrations.config import ConfigStore
from craftos_integrations.contracts import AccountInfo


def acct(identity: str, alias: Optional[str] = None) -> AccountInfo:
    return AccountInfo(
        identity=identity, alias=alias, is_primary=False, listen=True,
        added_at="2026-08-10T00:00:00+00:00",
    )


def event() -> Dict[str, Any]:
    """The payload-dict shape every listener emits."""
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


# ── listening coverage ───────────────────────────────────────────────────


def test_every_listening_client_has_a_provider():
    """No client may be left listening outside the ListenerManager.

    The ListenerManager drives listeners through providers. A listen-capable
    client without one has nothing driving it, and its inbound messages
    silently stop arriving. Add the provider alongside the client.
    """
    from craftos_integrations import autoload_integrations, get_all_clients
    from craftos_integrations.providers import provider_ids

    autoload_integrations()
    listening = {
        pid
        for pid, client in get_all_clients().items()
        if getattr(client, "supports_listening", False)
    }
    uncovered = sorted(listening - set(provider_ids()))
    assert not uncovered, (
        f"legacy clients that can listen but have no v2 provider: {uncovered}"
    )


def test_provider_ids_cover_every_client():
    """Ids are 1:1 across the registries — the assumption behind using a
    provider id directly as a slash-command name and credential-file stem."""
    from craftos_integrations import autoload_integrations, get_all_clients
    from craftos_integrations.providers import provider_ids

    autoload_integrations()
    assert not set(get_all_clients()) - set(provider_ids())


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
def system(monkeypatch):
    fake = FakeV2System(known=("gmail",))
    monkeypatch.setattr(integrations, "get_system", lambda: fake)
    return fake


def test_connect_oauth_routes_v2_through_add_account(system):
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_connect_oauth("gmail")
        await drain_tasks()

    asyncio.run(scenario())
    assert system.add_calls == ["gmail"]
    (data,) = results_of(sent, "integration_connect_result")
    assert data == {"success": True, "message": "Connected a@x.com", "id": "gmail"}
    # success still refreshes the integration list, task registry is clean
    assert results_of(sent, "integration_list")
    assert adapter._oauth_tasks == {}


def test_connect_oauth_v2_failure_keeps_result_shape(system):
    adapter, sent = make_adapter()
    system.add_result = (False, "OAuth timed out")

    async def scenario():
        await adapter._handle_integration_connect_oauth("gmail")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_connect_result")
    assert data == {"success": False, "message": "OAuth timed out", "id": "gmail"}
    assert not results_of(sent, "integration_list")


def test_connect_oauth_unknown_id_is_an_error(system):
    """No legacy fallback left: an id the system does not know cannot connect."""
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_connect_oauth("nope")
        await drain_tasks()

    asyncio.run(scenario())
    assert system.add_calls == []
    (data,) = results_of(sent, "integration_connect_result")
    assert data == {
        "success": False,
        "message": "Unknown integration: nope",
        "id": "nope",
    }
    assert not results_of(sent, "integration_list")


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
