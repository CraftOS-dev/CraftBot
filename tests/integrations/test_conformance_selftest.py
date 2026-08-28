"""Self-test: the conformance suite passes for a well-behaved fake provider
and fails for the specific contract violations it exists to catch."""

from __future__ import annotations

import pytest

from craftos_integrations.contracts import Operation

from .conformance import ProviderConformance
from .test_system import FakeProvider


class TestFakeProviderConformance(ProviderConformance):
    provider = FakeProvider("gmail", family="google")
    credential_fixtures = [{"email": "a@x.com", "access_token": "tok"}]


def _operation(**overrides):
    async def fn(client, input_data):
        return {}

    defaults = dict(
        name="delete_thing",
        description="Delete a thing.",
        input_schema={"id": {"type": "string", "description": "Thing id."}},
        output_schema={"status": {"type": "string"}},
        fn=fn,
        destructive=True,
    )
    defaults.update(overrides)
    return Operation(**defaults)


class _BadProviderBase(FakeProvider):
    def __init__(self, ops):
        super().__init__("gmail")
        self._ops = ops

    def operations(self):
        return self._ops


def _suite_for(provider):
    suite = ProviderConformance()
    suite.provider = provider
    suite.credential_fixtures = [{"email": "a@x.com"}]
    return suite


def test_catches_operation_declaring_account():
    op = _operation(
        input_schema={"account": {"type": "string"}, "id": {"type": "string"}}
    )
    with pytest.raises(AssertionError, match="declares 'account'"):
        _suite_for(_BadProviderBase([op])).test_operations_never_declare_account_input()


def test_catches_unflagged_destructive_operation():
    op = _operation(name="clear_google_calendar", destructive=False)
    with pytest.raises(AssertionError, match="destructive"):
        _suite_for(_BadProviderBase([op])).test_destructive_operations_are_flagged()


def test_catches_duplicate_operation_names():
    ops = [_operation(), _operation()]
    with pytest.raises(AssertionError, match="duplicate"):
        _suite_for(_BadProviderBase(ops)).test_operation_names_unique_and_snake_case()


def test_catches_uppercase_identity():
    class UppercaseIdentity(FakeProvider):
        def identity_of(self, credential):
            return credential.get("email", "").upper() or None

    suite = _suite_for(UppercaseIdentity("gmail"))
    with pytest.raises(AssertionError, match="lowercase"):
        suite.test_identity_of_fixtures_is_lowercase_stable()
