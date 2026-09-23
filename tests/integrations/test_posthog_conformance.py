"""PostHog provider conformance + verify/identity/host tests.

No network: ``verify_token``'s HTTP is monkeypatched. What's real is
conformance, identity composition, host normalization, and the
wrong-key-prefix rejections that spare the user an opaque 401.
"""

from __future__ import annotations

import asyncio

import craftos_integrations.providers.posthog.provider as posthog_mod
from craftos_integrations.providers.posthog import PostHogProvider
from craftos_integrations.providers.posthog.provider import normalize_host

from .conformance import ProviderConformance

# Realistic SHAPE, fake values — asdict(PostHogCredential) as verify_token
# builds it after a successful /api/users/@me/ read.
POSTHOG_CRED = {
    "api_key": "phx_FakeKeyFakeKeyFakeKeyFakeKey",
    "host": "https://us.posthog.com",
    "project_id": "136209",
    "org_id": "01890A5D-0000-0000-0000-000000000000",
    "user_email": "User@Example.com",
    "org_name": "Acme",
    "project_name": "Production",
}


class TestPostHogConformance(ProviderConformance):
    provider = PostHogProvider()
    credential_fixtures = [
        POSTHOG_CRED,  # real post-verify shape
        # key whose /users/@me/ carried no team (no project captured)
        {
            "api_key": "phx_scoped",
            "host": "https://eu.posthog.com",
            "org_id": "org-uuid",
            "project_id": "",
        },
        {},  # junk — must not raise
    ]


# ── identity ─────────────────────────────────────────────────────────


def test_identity_is_org_and_project_lowercased():
    provider = PostHogProvider()
    assert provider.identity_of(POSTHOG_CRED) == (
        "01890a5d-0000-0000-0000-000000000000:136209"
    )


def test_identity_falls_back_to_org_when_project_missing():
    provider = PostHogProvider()
    assert provider.identity_of({"org_id": "ORG-1", "project_id": ""}) == "org-1"
    assert provider.identity_of({"org_id": "  ORG-1  "}) == "org-1"


def test_identity_is_none_without_an_org():
    provider = PostHogProvider()
    assert provider.identity_of({}) is None
    assert provider.identity_of({"project_id": "136209"}) is None
    assert provider.identity_of({"api_key": "phx_x"}) is None


def test_identity_tolerates_non_string_and_non_dict():
    provider = PostHogProvider()
    assert provider.identity_of({"org_id": 123, "project_id": 456}) == "123:456"
    assert provider.identity_of({"org_id": {"nested": 1}}) is None
    assert provider.identity_of([]) is None  # type: ignore[arg-type]


def test_two_projects_in_one_org_are_separate_accounts():
    """The reason identity isn't the email: one user, two projects, two
    accounts."""
    provider = PostHogProvider()
    a = dict(POSTHOG_CRED, project_id="1")
    b = dict(POSTHOG_CRED, project_id="2")
    assert provider.identity_of(a) != provider.identity_of(b)


# ── host normalization ───────────────────────────────────────────────


def test_normalize_host_accepts_region_shorthands():
    assert normalize_host("us") == "https://us.posthog.com"
    assert normalize_host("EU") == "https://eu.posthog.com"


def test_normalize_host_defaults_to_us_cloud():
    assert normalize_host("") == "https://us.posthog.com"
    assert normalize_host(None) == "https://us.posthog.com"


def test_normalize_host_handles_self_hosted_forms():
    assert normalize_host("posthog.acme.com") == "https://posthog.acme.com"
    assert normalize_host("https://posthog.acme.com/") == "https://posthog.acme.com"
    # users paste the API path along with the origin
    assert normalize_host("https://posthog.acme.com/api") == "https://posthog.acme.com"


# ── verify_token ─────────────────────────────────────────────────────


def _stub_me(monkeypatch, payload, *, error=None):
    calls = {}

    def fake_request(method, url, **kwargs):
        calls["method"] = method
        calls["url"] = url
        calls["headers"] = kwargs.get("headers")
        if error is not None:
            return {"error": error, "details": "nope"}
        return {"ok": True, "result": payload}

    monkeypatch.setattr(posthog_mod, "http_request", fake_request)
    return calls


ME_PAYLOAD = {
    "email": "user@example.com",
    "organization": {"id": "ORG-UUID", "name": "Acme"},
    "team": {"id": 136209, "name": "Production"},
}


def test_verify_token_captures_org_and_project(monkeypatch):
    calls = _stub_me(monkeypatch, ME_PAYLOAD)
    ok, message, credential = PostHogProvider().verify_token(
        {"api_key": "phx_good", "host": "us"}
    )
    assert ok
    assert credential["org_id"] == "ORG-UUID"
    assert credential["project_id"] == "136209"
    assert credential["host"] == "https://us.posthog.com"
    assert "Acme" in message and "Production" in message
    assert calls["url"] == "https://us.posthog.com/api/users/@me/"
    assert calls["headers"]["Authorization"] == "Bearer phx_good"


def test_verify_token_uses_the_eu_host_when_asked(monkeypatch):
    calls = _stub_me(monkeypatch, ME_PAYLOAD)
    ok, message, credential = PostHogProvider().verify_token(
        {"api_key": "phx_good", "host": "eu"}
    )
    assert ok
    assert calls["url"].startswith("https://eu.posthog.com/")
    assert credential["host"] == "https://eu.posthog.com"
    assert "EU Cloud" in message


def test_verify_token_explicit_project_overrides_the_keys_team(monkeypatch):
    _stub_me(monkeypatch, ME_PAYLOAD)
    _, _, credential = PostHogProvider().verify_token(
        {"api_key": "phx_good", "project_id": "999"}
    )
    assert credential["project_id"] == "999"


def test_verify_token_succeeds_without_a_team_but_says_so(monkeypatch):
    _stub_me(
        monkeypatch, {"email": "u@e.com", "organization": {"id": "O", "name": "N"}}
    )
    ok, message, credential = PostHogProvider().verify_token({"api_key": "phx_good"})
    assert ok
    assert credential["project_id"] == ""
    assert "no project detected" in message


def test_verify_token_rejects_project_api_key():
    ok, message, credential = PostHogProvider().verify_token({"api_key": "phc_abc"})
    assert not ok and credential is None
    assert "project API key" in message


def test_verify_token_rejects_project_secret_key():
    ok, message, credential = PostHogProvider().verify_token({"api_key": "phs_abc"})
    assert not ok and credential is None
    assert "project secret key" in message


def test_verify_token_rejects_unknown_prefix():
    ok, message, _ = PostHogProvider().verify_token({"api_key": "sk_live_nope"})
    assert not ok and "phx_" in message


def test_verify_token_rejects_empty_key():
    ok, message, _ = PostHogProvider().verify_token({})
    assert not ok and "Missing" in message


def test_verify_token_surfaces_auth_failure_with_the_host(monkeypatch):
    _stub_me(monkeypatch, None, error="API error: 401")
    ok, message, credential = PostHogProvider().verify_token(
        {"api_key": "phx_bad", "host": "eu"}
    )
    assert not ok and credential is None
    assert "eu.posthog.com" in message
    # the message must name the host-mismatch trap, not just the status
    assert "EU Cloud" in message


# ── oauth / listener ─────────────────────────────────────────────────


def test_oauth_spec_is_declared_even_though_auth_type_is_token():
    """PostHog OAuth is gated on hosting a Client ID Metadata Document, not
    on code — the spec is real so flipping auth_type is a one-line change."""
    provider = PostHogProvider()
    assert provider.auth_type == "token"
    spec = provider.oauth_spec()
    assert spec.authorize_url == "https://oauth.posthog.com/oauth/authorize/"
    assert spec.token_url == "https://oauth.posthog.com/oauth/token/"
    assert "feature_flag:write" in spec.scopes
    assert "query:read" in spec.scopes


def test_no_listener_without_client_support():
    async def emit(event):  # pragma: no cover - never called
        pass

    assert PostHogProvider().make_listener(object(), None, emit) is None


def test_refresh_is_a_noop():
    """Personal API keys never expire, so there is nothing to rotate."""
    assert asyncio.run(PostHogProvider().refresh(POSTHOG_CRED)) is None


# ── client wire format ───────────────────────────────────────────────
#
# The offline gates check structure, not what goes on the wire. These pin
# the request bodies that were verified against PostHog's OpenAPI schema —
# two of them were wrong on the first pass and no structural check caught
# it, because a wrong field name is still a well-formed operation.


def _stub_arequest(monkeypatch):
    """Capture the request a client method would send."""
    import craftos_integrations.providers.posthog.client as client_mod

    sent = {}

    async def fake_arequest(method, url, **kwargs):
        sent["method"] = method
        sent["url"] = url
        sent["json"] = kwargs.get("json")
        sent["params"] = kwargs.get("params")
        return {"ok": True, "result": {}}

    monkeypatch.setattr(client_mod, "arequest", fake_arequest)
    return sent


def _bound_client():
    from craftos_integrations.providers.posthog.client import PostHogClient

    client = PostHogClient()
    client.bind_credential(POSTHOG_CRED, lambda _: None)
    return client


def test_add_persons_to_cohort_uses_person_ids_field(monkeypatch):
    """PostHog names the field person_ids even though the values are uuids."""
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().add_persons_to_cohort("42", ["uuid-1", "uuid-2"]))
    assert sent["json"] == {"person_ids": ["uuid-1", "uuid-2"]}
    assert sent["method"] == "PATCH"
    assert sent["url"].endswith("/cohorts/42/add_persons_to_static_cohort/")


def test_create_text_tile_sends_a_flat_body(monkeypatch):
    """CreateTextTileRequest takes {body}, not a nested {text: {body}}."""
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().create_dashboard_text_tile("1", "## Q3"))
    assert sent["json"] == {"body": "## Q3"}


def test_delete_person_property_uses_the_unset_field(monkeypatch):
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().delete_person_property("uuid-1", "plan"))
    assert sent["json"] == {"$unset": "plan"}


def test_deletes_are_soft(monkeypatch):
    """Every delete_* on a soft-deletable resource is a PATCH, not a DELETE."""
    client = _bound_client()
    for call in (
        client.delete_insight("1"),
        client.delete_dashboard("1"),
        client.delete_feature_flag("1"),
        client.delete_cohort("1"),
        client.delete_annotation("1"),
    ):
        sent = _stub_arequest(monkeypatch)
        asyncio.run(call)
        assert sent["method"] == "PATCH", sent["url"]
        assert sent["json"] == {"deleted": True}


def test_person_deletion_is_the_bulk_endpoint(monkeypatch):
    """Persons have no per-person DELETE — erasure goes through bulk_delete."""
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().delete_persons(person_ids=["u1"], delete_events=True))
    assert sent["method"] == "POST"
    assert sent["url"].endswith("/persons/bulk_delete/")
    assert sent["json"] == {"ids": ["u1"]}
    assert sent["params"] == {"delete_events": "true"}


def test_patch_never_blanks_unset_fields(monkeypatch):
    """_clean drops keys the caller omitted, so a partial update stays partial."""
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().update_dashboard("1", name="Renamed"))
    assert sent["json"] == {"name": "Renamed"}


def test_host_and_project_come_from_the_credential(monkeypatch):
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().list_insights())
    assert sent["url"] == "https://us.posthog.com/api/projects/136209/insights/"


def test_explicit_project_id_overrides_the_credential(monkeypatch):
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().list_insights(project_id="999"))
    assert "/projects/999/" in sent["url"]


def test_limit_is_clamped_to_the_api_maximum(monkeypatch):
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().list_insights(limit=5000))
    assert sent["params"]["limit"] == 100


def test_hogql_string_literals_are_escaped(monkeypatch):
    """list_events composes HogQL from agent-supplied values."""
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().list_events(event="it's a trap"))
    sql = sent["json"]["query"]["query"]
    # the quote is backslash-escaped, so it cannot close the literal early
    assert r"event = 'it\'s a trap'" in sql


def test_async_query_sets_the_async_flag(monkeypatch):
    sent = _stub_arequest(monkeypatch)
    asyncio.run(_bound_client().run_query_async("SELECT 1"))
    assert sent["json"]["async"] is True
    assert sent["json"]["query"] == {"kind": "HogQLQuery", "query": "SELECT 1"}


# ── umbrella lifecycle ───────────────────────────────────────────────


def test_umbrella_can_delete_whatever_it_can_create():
    """Regression: the umbrella once had create_posthog_dashboard but not
    delete_posthog_dashboard. The agent created one, could not remove it,
    fell back to unauthenticated raw HTTP and 401'd. If the default action
    set can make a thing, it must be able to unmake it."""
    operations = PostHogProvider().operations()
    umbrella = {op.name for op in operations if "posthog" in op.tags}
    every = {op.name for op in operations}

    for name in umbrella:
        if not name.startswith("create_"):
            continue
        delete_name = f"delete_{name[len('create_') :]}"
        if delete_name in every:
            assert delete_name in umbrella, (
                f"{name} is in the umbrella set but {delete_name} is not — "
                "an agent could create this and then be unable to delete it"
            )


def test_umbrella_stays_within_the_house_size_convention():
    umbrella = [op for op in PostHogProvider().operations() if "posthog" in op.tags]
    assert 15 <= len(umbrella) <= 25, len(umbrella)
