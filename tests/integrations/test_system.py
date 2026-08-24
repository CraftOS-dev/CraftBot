"""IntegrationSystem: execute() routing, client caching, invalidation.

No pytest-asyncio in this repo — async paths are driven with asyncio.run.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from craftos_integrations.contracts import (
    AccountResolutionError,
    OAuthSpec,
    Operation,
)
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem

from .conftest import cred


def run(coro):
    return asyncio.run(coro)


@dataclass
class FakeClient:
    credential: Dict[str, Any]
    calls: List[str] = field(default_factory=list)


class FakeProvider:
    def __init__(self, pid: str, family: Optional[str] = None):
        self.id = pid
        self.family = family
        self.built: List[FakeClient] = []

    def identity_of(self, credential):
        return credential.get("email")

    def oauth_spec(self):
        return OAuthSpec(authorize_url="https://auth", token_url="https://token")

    def build_client(self, credential, persist):
        client = FakeClient(credential)
        self.built.append(client)
        return client

    async def refresh(self, credential):
        return None

    def operations(self):
        async def whoami(client, input_data):
            client.calls.append("whoami")
            return {"status": "success", "email": client.credential["email"]}

        return [
            Operation(
                name="whoami",
                description="Report which account this ran as.",
                input_schema={},
                output_schema={"email": {"type": "string"}},
                fn=whoami,
            )
        ]

    def guidance(self):
        return f"## {self.id} guidance"

    def make_listener(self, client, cursor, emit):
        return None


@pytest.fixture
def system(tmp_path):
    gmail = FakeProvider("gmail", family="google")
    calendar = FakeProvider("google_calendar", family="google")
    slack = FakeProvider("slack")
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path),
        providers=[gmail, calendar, slack],
    )
    sys.store_credential("gmail", "a@x.com", cred("a@x.com"))
    sys.store_credential("gmail", "b@y.com", cred("b@y.com"))
    sys.set_alias("gmail", "b@y.com", "school")
    return sys


def test_execute_routes_to_resolved_account(system):
    assert run(system.execute("gmail", "whoami", {}, account="school"))["email"] == "b@y.com"
    assert run(system.execute("gmail", "whoami", {}))["email"] == "a@x.com"  # → primary


def test_client_cached_by_identity_not_hint(system):
    run(system.execute("gmail", "whoami", {}, account="school"))
    run(system.execute("gmail", "whoami", {}, account="SCHOOL"))
    run(system.execute("gmail", "whoami", {}, account="b@y.com"))
    assert len(system.registry.get("gmail").built) == 1  # one client, three spellings


def test_bad_hint_never_pollutes_cache_and_is_llm_friendly(system):
    with pytest.raises(AccountResolutionError) as err:
        run(system.execute("gmail", "whoami", {}, account="ghost"))
    assert "Connected gmail accounts" in str(err.value)
    assert system.registry.get_cached_client("gmail", "ghost") is None


def test_set_alias_invalidates_cached_client(system):
    run(system.execute("gmail", "whoami", {}, account="school"))
    system.set_alias("gmail", "b@y.com", "uni")
    run(system.execute("gmail", "whoami", {}, account="uni"))
    assert len(system.registry.get("gmail").built) == 2  # rebuilt after alias change


def test_remove_account_invalidates_and_repoints_primary(system):
    system.remove_account("gmail", "a@x.com")
    assert run(system.execute("gmail", "whoami", {}))["email"] == "b@y.com"


def test_unknown_provider_and_operation(system):
    with pytest.raises(LookupError, match="Unknown integration"):
        system.operations("github")
    with pytest.raises(LookupError, match="no operation 'nope'"):
        run(system.execute("gmail", "nope", {}))


def test_guidance_connected_only(system):
    text = system.guidance(connected_only=True)
    assert "gmail" in text
    assert "slack" not in text  # not connected
    assert "slack" in system.guidance(connected_only=False)


def test_family_alias_visible_from_sibling(system):
    system.store_credential("google_calendar", "b@y.com", cred("b@y.com"))
    system.set_alias("gmail", "b@y.com", "uni")
    infos = system.list_accounts("google_calendar")
    assert infos[-1].alias == "uni"


def test_apply_account_changes_end_to_end(system):
    result = system.apply_account_changes(
        "gmail",
        {"primary": "school", "aliases": {"a@x.com": "personal"}},
    )
    by_id = {a.identity: a for a in result}
    assert by_id["b@y.com"].is_primary
    assert by_id["a@x.com"].alias == "personal"
    assert run(system.execute("gmail", "whoami", {}))["email"] == "b@y.com"
