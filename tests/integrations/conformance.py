"""Provider conformance suite — the plug-and-play quality gate.

Every provider gets these checks by subclassing:

    class TestGmailConformance(ProviderConformance):
        provider = GmailProvider()
        credential_fixtures = [  # captured real-shape credentials
            {"email": "User@X.com", "access_token": "..."},
        ]

The suite enforces the contract rules that made the abandoned PR
dangerous when they were left to diligence:
  - operations never declare their own ``account`` input (central
    injection would silently collide),
  - destructive-looking operations are flagged ``destructive``,
  - a provider without an OAuth account chooser must say so explicitly
    AND explain the add-account workaround in its guidance.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

import pytest

# Reversible verbs (trash, archive) are deliberately absent — the flag
# exists for operations a wrong-account mistake can't undo.
DESTRUCTIVE_HINTS = re.compile(r"(^|_)(delete|clear|remove|revoke|destroy|cancel)(_|$)")
VALID_OP_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ProviderConformance:
    provider: Any = None  # subclass sets this
    credential_fixtures: List[Dict[str, Any]] = []

    # ── identity ─────────────────────────────────────────────────────────

    def test_provider_id_shape(self):
        assert self.provider.id and VALID_OP_NAME.match(self.provider.id)

    def test_identity_of_fixtures_is_lowercase_stable(self):
        assert self.credential_fixtures, (
            "Provide at least one captured credential fixture — identity "
            "extraction is the root of every multi-account guarantee."
        )
        for fixture in self.credential_fixtures:
            identity = self.provider.identity_of(fixture)
            if identity is not None:
                assert identity == identity.lower(), (
                    f"identity_of must return lowercase, got {identity!r}"
                )
                assert identity.strip() == identity and identity != ""

    def test_identity_of_tolerates_junk(self):
        # Must never raise on malformed input — it runs during migration.
        assert self.provider.identity_of({}) is None or isinstance(
            self.provider.identity_of({}), str
        )

    # ── oauth ────────────────────────────────────────────────────────────

    def _oauth_spec(self):
        """Token-only providers (auth-layer bridge ports) have no OAuth at
        all and raise NotImplementedError — an explicit declaration, like
        ``has_chooser=False``, not an accident."""
        try:
            return self.provider.oauth_spec()
        except NotImplementedError:
            return None

    def test_oauth_spec_urls(self):
        spec = self._oauth_spec()
        if spec is None:
            pytest.skip(f"{self.provider.id} is token-only — no OAuth spec")
        assert spec.authorize_url.startswith("https://")
        assert spec.token_url.startswith("https://")

    def test_missing_chooser_is_declared_and_documented(self):
        spec = self._oauth_spec()
        if spec is None:
            pytest.skip(f"{self.provider.id} is token-only — no OAuth spec")
        if not spec.has_chooser:
            guidance = self.provider.guidance().lower()
            assert "account" in guidance, (
                f"{self.provider.id} declares no OAuth account chooser — its "
                "guidance must explain how a user adds a different account "
                "(e.g. LinkedIn: log out of linkedin.com first)."
            )

    # ── operations ───────────────────────────────────────────────────────

    def test_operation_names_unique_and_snake_case(self):
        names = [op.name for op in self.provider.operations()]
        assert len(names) == len(set(names)), "duplicate operation names"
        for name in names:
            assert VALID_OP_NAME.match(name), f"bad operation name: {name}"

    def test_operations_never_declare_account_input(self):
        # ``account`` is injected centrally by host adapters; a provider
        # declaring its own would silently collide with the injected one.
        for op in self.provider.operations():
            assert "account" not in op.input_schema, (
                f"{op.name} declares 'account' in its input_schema — remove "
                "it; account selection is handled by IntegrationSystem."
            )

    def test_operation_schemas_are_well_formed(self):
        for op in self.provider.operations():
            assert op.description.strip(), f"{op.name} has no description"
            for schema in (op.input_schema, op.output_schema):
                assert isinstance(schema, dict)
                for key, value in schema.items():
                    assert isinstance(value, dict) and "type" in value, (
                        f"{op.name}.{key} schema entry must be a dict with a "
                        f"'type' (got {value!r})"
                    )

    def test_destructive_operations_are_flagged(self):
        unflagged = [
            op.name
            for op in self.provider.operations()
            if DESTRUCTIVE_HINTS.search(op.name) and not op.destructive
        ]
        assert not unflagged, (
            f"Operations that look destructive but aren't flagged "
            f"destructive=True: {unflagged}. Hosts use this flag for "
            "confirm-or-clarify on ambiguous multi-account requests."
        )

    def test_operation_fns_are_async(self):
        for op in self.provider.operations():
            assert asyncio.iscoroutinefunction(op.fn), f"{op.name}.fn not async"

    # ── guidance / listener ──────────────────────────────────────────────

    def test_guidance_is_text(self):
        assert isinstance(self.provider.guidance(), str)

    def test_make_listener_signature(self):
        # None (no inbound events) is fine; raising is not. ``emit`` is the
        # account-bound async event callable the core hands every listener.
        async def emit(event: Dict[str, Any]) -> None:  # no-op
            pass

        result = self.provider.make_listener(object(), None, emit)
        if result is not None:
            assert hasattr(result, "start") and hasattr(result, "stop")
