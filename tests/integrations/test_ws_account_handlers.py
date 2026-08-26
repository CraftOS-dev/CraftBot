"""WS multi-account handlers on BrowserAdapter (PR 4 backend).

No pytest-asyncio in this repo — async paths are driven with asyncio.run.

The adapter is instantiated without __init__ (object.__new__) and given a
recording ``_broadcast`` plus a stub ``_handle_integration_list``, so the
handlers run in isolation: no aiohttp server, no real websockets. The
integration system and the legacy facade functions are replaced with fakes via
monkeypatching ``app.integrations.get_system`` and the names imported
into the browser_adapter module namespace.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pytest

import app.integrations as integrations
from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from craftos_integrations.contracts import AccountInfo, AccountResolutionError


# ── harness ──────────────────────────────────────────────────────────────


def make_adapter() -> Tuple[BrowserAdapter, List[Dict[str, Any]]]:
    """A BrowserAdapter with only the state the integration handlers touch."""
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
    """Await every task spawned by a handler (handlers use create_task)."""
    while True:
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not others:
            return
        await asyncio.gather(*others)


def results_of(sent: List[Dict[str, Any]], msg_type: str) -> List[Dict[str, Any]]:
    return [m["data"] for m in sent if m["type"] == msg_type]


def acct(identity: str, alias: Optional[str] = None, primary: bool = False,
         listen: bool = True) -> AccountInfo:
    return AccountInfo(
        identity=identity, alias=alias, is_primary=primary, listen=listen,
        added_at="2026-08-10T00:00:00+00:00",
    )


class FakeSystem:
    """Just enough of IntegrationSystem for the WS handlers."""

    def __init__(self, known=("gmail",), accounts: Optional[List[AccountInfo]] = None):
        self._known = set(known)
        self._accounts = list(accounts or [])
        self.removed: List[Tuple[str, str]] = []
        self.applied: List[Tuple[str, Dict[str, Any]]] = []
        self.add_result: Tuple[bool, str, Optional[List[AccountInfo]]] = (
            True, "Connected", None,
        )
        self.apply_error: Optional[Exception] = None

        class _Registry:
            def get(_self, pid):
                return object() if pid in self._known else None

        self.registry = _Registry()

    def list_accounts(self, provider_id: str) -> List[AccountInfo]:
        return list(self._accounts)

    async def add_account(self, provider_id: str):
        ok, message, accounts = self.add_result
        return ok, message, self._accounts if accounts is None else accounts

    def apply_account_changes(self, provider_id: str, batch: Dict[str, Any]):
        if self.apply_error is not None:
            raise self.apply_error
        self.applied.append((provider_id, batch))
        return list(self._accounts)

    def resolve(self, provider_id: str, hint: Optional[str]) -> str:
        match = next(
            (a for a in self._accounts if hint in (a.identity, a.alias)), None
        )
        if match is None:
            raise AccountResolutionError(f"No account matching '{hint}'")
        return match.identity

    def remove_account(self, provider_id: str, hint: Optional[str]) -> str:
        match = next(
            (a for a in self._accounts if hint in (a.identity, a.alias)), None
        )
        if match is None:
            raise AccountResolutionError(f"No account matching '{hint}'")
        self._accounts.remove(match)
        self.removed.append((provider_id, match.identity))
        return match.identity


TWO = lambda: [acct("a@x.com", "work", primary=True), acct("b@y.com", "school")]

WIRE_TWO = [
    {"identity": "a@x.com", "alias": "work", "isPrimary": True, "listen": True},
    {"identity": "b@y.com", "alias": "school", "isPrimary": False, "listen": True},
]


@pytest.fixture
def system(monkeypatch):
    fake = FakeSystem(known=("gmail",), accounts=TWO())
    monkeypatch.setattr(integrations, "get_system", lambda: fake)
    return fake


# ── integration_info: v2 accounts ride TOP-LEVEL ``data.accounts`` ──────────
#
# CONTRACT (frontend): IntegrationsSettings' ``integration_info`` handler
# reads ``data.accounts`` (sibling of ``data.integration``) and renders the
# AccountsManager when that key is a ManagedAccount[] —
# ``{identity, alias, isPrimary, listen}``. Metadata comes from
# ``get_metadata`` (no ``handler.status()`` scraping anymore); ``connected``
# and ``accounts`` inside ``data.integration`` are AccountSet-derived. A
# MISSING top-level key means the account list couldn't be loaded — the
# frontend shows a reload hint (the legacy fallback rows are gone).


def test_info_carries_v2_accounts_at_top_level(system, monkeypatch):
    adapter, sent = make_adapter()
    import craftos_integrations

    monkeypatch.setattr(
        craftos_integrations, "get_metadata", lambda _id: {"id": _id}
    )
    asyncio.run(adapter._handle_integration_info("gmail"))
    (data,) = results_of(sent, "integration_info")
    assert data["success"] is True
    # The exact key the frontend reads:
    assert data["accounts"] == WIRE_TWO
    # Every row carries exactly the ManagedAccount wire keys:
    for row in data["accounts"]:
        assert set(row) == {"identity", "alias", "isPrimary", "listen"}
    # ``integration`` mirrors the AccountSet-derived state:
    assert data["integration"]["connected"] is True
    assert data["integration"]["accounts"] == WIRE_TWO


def test_info_unknown_to_system_reports_disconnected(system, monkeypatch):
    """A provider id the system doesn't know (can't happen for shipped
    integrations, but registry lookups can fail) reports disconnected with
    no top-level accounts key."""
    adapter, sent = make_adapter()
    import craftos_integrations

    monkeypatch.setattr(
        craftos_integrations, "get_metadata", lambda _id: {"id": _id}
    )
    asyncio.run(adapter._handle_integration_info("jira"))
    (data,) = results_of(sent, "integration_info")
    assert "accounts" not in data
    assert data["integration"]["connected"] is False
    assert data["integration"]["accounts"] == []


def test_info_v2_lookup_failure_shows_reload_hint(monkeypatch):
    """get_system() blowing up must not break the payload — success stays
    True, connected reads False, and the missing top-level accounts key
    makes the frontend render its reload hint. The failure is loud in logs."""
    adapter, sent = make_adapter()

    def boom():
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(integrations, "get_system", boom)
    import craftos_integrations

    monkeypatch.setattr(
        craftos_integrations, "get_metadata", lambda _id: {"id": _id}
    )
    asyncio.run(adapter._handle_integration_info("gmail"))
    (data,) = results_of(sent, "integration_info")
    assert data["success"] is True
    assert "accounts" not in data
    assert data["integration"]["connected"] is False
    assert data["integration"]["accounts"] == []


# ── integration_accounts_add ─────────────────────────────────────────────


def test_accounts_add_success_echoes_request_id(system):
    adapter, sent = make_adapter()
    system.add_result = (True, "Connected c@z.com", TWO() + [acct("c@z.com")])

    async def scenario():
        await adapter._handle_integration_accounts_add("gmail", "req-42")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_accounts_add_result")
    assert data["id"] == "gmail"
    assert data["requestId"] == "req-42"
    assert data["ok"] is True
    assert data["message"] == "Connected c@z.com"
    assert [a["identity"] for a in data["accounts"]] == [
        "a@x.com", "b@y.com", "c@z.com",
    ]
    # success refreshes the integration list
    assert results_of(sent, "integration_list")
    # task cleaned itself out of the oauth-task registry
    assert adapter._oauth_tasks == {}


def test_accounts_add_failure_reports_ok_false(system):
    adapter, sent = make_adapter()
    system.add_result = (False, "OAuth timed out", [])

    async def scenario():
        await adapter._handle_integration_accounts_add("gmail", "req-7")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_accounts_add_result")
    assert data["ok"] is False
    assert data["requestId"] == "req-7"
    assert data["message"] == "OAuth timed out"
    assert not results_of(sent, "integration_list")


def test_accounts_add_unknown_provider(system):
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_accounts_add("nope", "req-1")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_accounts_add_result")
    assert data["ok"] is False
    # Add-result failures travel in "message" (types.ts has no error field).
    assert "Unknown integration" in data["message"]
    assert "error" not in data
    assert data["requestId"] == "req-1"


def test_accounts_add_tolerates_none_accounts(system):
    """add_account's failure tuple may carry accounts=None — never a crash."""
    adapter, sent = make_adapter()

    async def none_add(provider_id):
        return False, "OAuth window closed", None

    system.add_account = none_add

    async def scenario():
        await adapter._handle_integration_accounts_add("gmail", "req-n")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_accounts_add_result")
    assert data == {
        "id": "gmail",
        "requestId": "req-n",
        "ok": False,
        "message": "OAuth window closed",
        "accounts": [],
    }


# ── integration_apply_account_changes ────────────────────────────────────


def test_apply_changes_success(system):
    adapter, sent = make_adapter()
    changes = {
        "disconnect": [],
        "primary": "b@y.com",
        "aliases": {"a@x.com": None},
        "listen": {"b@y.com": False},
    }
    asyncio.run(
        adapter._handle_integration_apply_account_changes("gmail", "req-9", changes)
    )
    (data,) = results_of(sent, "integration_apply_account_changes_result")
    assert data == {
        "id": "gmail",
        "requestId": "req-9",
        "ok": True,
        "accounts": WIRE_TWO,
    }
    assert system.applied == [("gmail", changes)]
    assert results_of(sent, "integration_list")


@pytest.mark.parametrize(
    "error", [ValueError("primary not in set"), AccountResolutionError("no match")]
)
def test_apply_changes_failure_keeps_current_accounts(system, error):
    adapter, sent = make_adapter()
    system.apply_error = error
    asyncio.run(
        adapter._handle_integration_apply_account_changes("gmail", "req-9", {})
    )
    (data,) = results_of(sent, "integration_apply_account_changes_result")
    assert data["ok"] is False
    assert data["error"] == str(error)
    assert data["requestId"] == "req-9"
    # frontend keeps staged edits; payload carries the unchanged current list
    assert data["accounts"] == WIRE_TWO
    assert not results_of(sent, "integration_list")


def test_apply_changes_unknown_provider(system):
    adapter, sent = make_adapter()
    asyncio.run(
        adapter._handle_integration_apply_account_changes("nope", "r", {})
    )
    (data,) = results_of(sent, "integration_apply_account_changes_result")
    assert data["ok"] is False
    assert "Unknown integration" in data["error"]


# ── failure payloads must never fabricate an empty account list ──────────
#
# CONTRACT (frontend): a present ``accounts`` array is authoritative — the
# Manage modal re-renders from it and PRUNES its staged (unsaved) edits
# against it. A failure payload whose current-list lookup also failed used
# to ship ``accounts: []``, which blanked the modal and silently discarded
# every staged edit (e.g. an alias mid-typing). The key must be OMITTED
# when the real list is unavailable, and still carried when it is.


def _raise(*_a, **_k):
    raise RuntimeError("store unavailable")


def test_apply_changes_failure_omits_accounts_when_list_unavailable(system):
    adapter, sent = make_adapter()
    system.apply_error = ValueError("nickname clash")
    system.list_accounts = _raise
    asyncio.run(
        adapter._handle_integration_apply_account_changes("gmail", "req-x", {})
    )
    (data,) = results_of(sent, "integration_apply_account_changes_result")
    assert data["ok"] is False
    assert data["error"] == "nickname clash"
    assert "accounts" not in data


def test_accounts_add_exception_omits_accounts_when_list_unavailable(system):
    adapter, sent = make_adapter()

    async def boom_add(provider_id):
        raise RuntimeError("oauth transport died")

    system.add_account = boom_add
    system.list_accounts = _raise

    async def scenario():
        await adapter._handle_integration_accounts_add("gmail", "req-y")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_accounts_add_result")
    assert data["ok"] is False
    assert data["message"] == "oauth transport died"
    assert "accounts" not in data


def test_accounts_add_exception_keeps_real_accounts_when_available(system):
    adapter, sent = make_adapter()

    async def boom_add(provider_id):
        raise RuntimeError("oauth window closed")

    system.add_account = boom_add

    async def scenario():
        await adapter._handle_integration_accounts_add("gmail", "req-z")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_accounts_add_result")
    assert data["ok"] is False
    # The real (unchanged) list is still useful context and stays present.
    assert data["accounts"] == WIRE_TWO


# ── integration_disconnect: system routing + legacy fallthrough ──────────────


def test_disconnect_targeted_removes_only_that_account(system):
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_disconnect("gmail", "school", "req-d1")
        await drain_tasks()

    asyncio.run(scenario())
    assert system.removed == [("gmail", "b@y.com")]
    (data,) = results_of(sent, "integration_disconnect_result")
    assert data["success"] is True
    assert data["requestId"] == "req-d1"
    assert [a["identity"] for a in data["accounts"]] == ["a@x.com"]
    assert results_of(sent, "integration_list")


def test_disconnect_targeted_unknown_account(system):
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_disconnect("gmail", "ghost", "req-d2")
        await drain_tasks()

    asyncio.run(scenario())
    (data,) = results_of(sent, "integration_disconnect_result")
    assert data["success"] is False
    assert "ghost" in data["message"]
    assert not results_of(sent, "integration_list")


def test_disconnect_all_removes_every_account(system):
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_disconnect("gmail", None, "req-d3")
        await drain_tasks()

    asyncio.run(scenario())
    assert system.removed == [("gmail", "a@x.com"), ("gmail", "b@y.com")]
    (data,) = results_of(sent, "integration_disconnect_result")
    assert data["success"] is True
    assert data["requestId"] == "req-d3"


def test_disconnect_unknown_integration_reports_not_connected(system):
    """Every integration is system-managed, so an id the system does not know
    cannot be disconnected — there is no second path to try."""
    adapter, sent = make_adapter()

    async def scenario():
        await adapter._handle_integration_disconnect("jira", None, "req-d4")
        await drain_tasks()

    asyncio.run(scenario())
    assert system.removed == []
    (data,) = results_of(sent, "integration_disconnect_result")
    assert data["success"] is False
    assert data["requestId"] == "req-d4"
