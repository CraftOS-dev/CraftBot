"""Supabase provider conformance + identity/verify/client-behaviour tests.

No network: every HTTP call is monkeypatched. What's real is conformance,
identity composition, the wrong-key rejections, the auth_type flip, and
the client rules that protect the user — read-only mode, filter-less
writes refused, secret values never surfaced, the right key chosen and
sent in the right header.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

import craftos_integrations.providers.supabase.client as client_mod
import craftos_integrations.providers.supabase.provider as provider_mod
from craftos_integrations.config import ConfigStore
from craftos_integrations.providers.supabase import SupabaseProvider
from craftos_integrations.providers.supabase.client import (
    SupabaseClient,
    SupabaseConfig,
)

from .conformance import ProviderConformance

# Realistic SHAPES, fake values — asdict(SupabaseCredential) as verify_token
# (PAT) and run_login (OAuth) build them.
PAT_CRED = {
    "access_token": "sbp_FAKE-test-token-not-a-real-secret",
    "auth_kind": "token",
    "token_id": "3f1c9a0b7d2e4f60",
    "refresh_token": "",
    "token_expiry": 0.0,
    "user_id": "8C2B6A1E-0000-4000-8000-000000000001",
    "email": "Dev@Acme.com",
    "username": "dev",
    "org_slug": "",
    "org_name": "",
}
OAUTH_CRED = {
    "access_token": "sbp_oauth_fake",
    "auth_kind": "oauth",
    "refresh_token": "refresh_fake",
    "token_expiry": 9999999999.0,
    "user_id": "",
    "email": "",
    "username": "",
    "org_slug": "Acme-Inc",
    "org_name": "Acme Inc",
}


class TestSupabaseConformance(ProviderConformance):
    provider = SupabaseProvider()
    credential_fixtures = [
        PAT_CRED,  # personal access token, post-verify shape
        OAUTH_CRED,  # OAuth grant scoped to one org
        {"access_token": "sbp_x", "email": "Only@Email.com"},  # no gotrue id
        {"access_token": "sbp_x", "token_id": "ABCDEF0123456789"},  # profile 403
        {},  # junk — must not raise
    ]


def run(coro):
    return asyncio.run(coro)


# ── identity ─────────────────────────────────────────────────────────


def test_pat_identity_is_the_user():
    assert (
        SupabaseProvider().identity_of(PAT_CRED)
        == "user:8c2b6a1e-0000-4000-8000-000000000001"
    )


def test_oauth_identity_is_the_org():
    assert SupabaseProvider().identity_of(OAUTH_CRED) == "org:acme-inc"


def test_identity_falls_back_to_email_then_none():
    provider = SupabaseProvider()
    assert provider.identity_of({"email": "A@B.com"}) == "user:a@b.com"
    assert provider.identity_of({}) is None
    assert provider.identity_of({"access_token": "sbp_x"}) is None
    assert provider.identity_of([]) is None  # type: ignore[arg-type]
    assert provider.identity_of({"user_id": {"nested": 1}}) is None


def test_two_oauth_orgs_are_two_accounts():
    provider = SupabaseProvider()
    a = dict(OAUTH_CRED, org_slug="one")
    b = dict(OAUTH_CRED, org_slug="two")
    assert provider.identity_of(a) != provider.identity_of(b)


# ── auth_type follows configuration ──────────────────────────────────


def test_auth_type_is_token_until_oauth_app_configured(monkeypatch):
    monkeypatch.setattr(ConfigStore, "_oauth", {})
    monkeypatch.delenv("SUPABASE_SHARED_CLIENT_ID", raising=False)
    monkeypatch.delenv("SUPABASE_SHARED_CLIENT_SECRET", raising=False)
    assert SupabaseProvider().auth_type == "token"

    monkeypatch.setattr(
        ConfigStore,
        "_oauth",
        {"SUPABASE_SHARED_CLIENT_ID": "id", "SUPABASE_SHARED_CLIENT_SECRET": "secret"},
    )
    assert SupabaseProvider().auth_type == "both"


def test_run_login_refuses_cleanly_without_oauth_app(monkeypatch):
    monkeypatch.setattr(ConfigStore, "_oauth", {})
    monkeypatch.delenv("SUPABASE_SHARED_CLIENT_ID", raising=False)
    monkeypatch.delenv("SUPABASE_SHARED_CLIENT_SECRET", raising=False)
    identity, credential, message = run(SupabaseProvider().run_login())
    assert identity is None and credential is None
    assert "personal access token" in message


# ── verify_token ─────────────────────────────────────────────────────


def _stub_http(monkeypatch, responses: Dict[str, Any]) -> List[str]:
    calls: List[str] = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        for suffix, payload in responses.items():
            if url.endswith(suffix):
                return payload
        return {"error": "API error: 404", "details": "unexpected"}

    monkeypatch.setattr(provider_mod, "http_request", fake_request)
    return calls


@pytest.mark.parametrize(
    "token",
    [
        "sb_secret_abc123",
        "sb_publishable_abc123",
        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.sig",
    ],
)
def test_verify_rejects_project_keys_without_a_request(monkeypatch, token):
    calls = _stub_http(monkeypatch, {})
    ok, message, credential = SupabaseProvider().verify_token({"access_token": token})
    assert not ok and credential is None
    assert "personal access token" in message
    assert calls == []


def test_verify_rejects_empty(monkeypatch):
    calls = _stub_http(monkeypatch, {})
    ok, message, _ = SupabaseProvider().verify_token({"access_token": "  "})
    assert not ok and "Missing" in message
    assert calls == []


def test_verify_success_captures_identity(monkeypatch):
    _stub_http(
        monkeypatch,
        {
            "/v1/profile": {
                "ok": True,
                "result": {
                    "gotrue_id": "abc-123",
                    "primary_email": "dev@acme.com",
                    "username": "dev",
                },
            },
            "/v1/organizations": {
                "ok": True,
                "result": [{"slug": "acme", "name": "Acme"}],
            },
        },
    )
    ok, message, credential = SupabaseProvider().verify_token(
        {"access_token": "sbp_good"}
    )
    assert ok
    assert credential["auth_kind"] == "token"
    assert credential["user_id"] == "abc-123"
    assert SupabaseProvider().identity_of(credential) == "user:abc-123"
    assert "dev@acme.com" in message and "Acme" in message


def test_verify_succeeds_when_profile_is_forbidden(monkeypatch):
    """Real behaviour, seen live 2026-10-05: /v1/profile answers 403 to a
    valid personal access token. That must not fail the connect."""
    _stub_http(
        monkeypatch,
        {
            "/v1/profile": {"error": "API error: 403", "details": "forbidden"},
            "/v1/organizations": {
                "ok": True,
                "result": [{"slug": "acme", "name": "Acme"}],
            },
        },
    )
    ok, message, credential = SupabaseProvider().verify_token(
        {"access_token": "sbp_good"}
    )
    assert ok, message
    assert credential["user_id"] == ""
    assert credential["token_id"] == provider_mod.token_fingerprint("sbp_good")
    identity = SupabaseProvider().identity_of(credential)
    assert identity == f"token:{credential['token_id']}"
    assert "sbp_good" not in identity
    assert "Acme" in message


def test_token_fingerprint_is_stable_and_distinct():
    fp = provider_mod.token_fingerprint
    assert fp("sbp_a") == fp("sbp_a")
    assert fp("sbp_a") != fp("sbp_b")
    assert len(fp("sbp_a")) == 16


def test_verify_reports_revoked_token(monkeypatch):
    _stub_http(
        monkeypatch, {"/v1/organizations": {"error": "API error: 401", "details": ""}}
    )
    ok, message, credential = SupabaseProvider().verify_token(
        {"access_token": "sbp_revoked"}
    )
    assert not ok and credential is None
    assert "401" in message and "revoked" in message


def test_verify_distinguishes_forbidden_from_invalid(monkeypatch):
    _stub_http(
        monkeypatch,
        {"/v1/organizations": {"error": "API error: 403", "details": "no access"}},
    )
    ok, message, _ = SupabaseProvider().verify_token({"access_token": "sbp_x"})
    assert not ok
    assert "403" in message and "accepted the token" in message


# ── client behaviour ─────────────────────────────────────────────────


def _client(monkeypatch, **config) -> SupabaseClient:
    client = SupabaseClient()
    client.bind_credential(dict(PAT_CRED), lambda c: None)
    cfg = SupabaseConfig(**{"default_project_ref": "abcdefghijklmnopqrst", **config})
    monkeypatch.setattr(client, "_config", lambda: cfg)
    return client


def test_read_only_mode_blocks_writes_before_any_request(monkeypatch):
    client = _client(monkeypatch, read_only=True)

    async def boom(*a, **k):
        raise AssertionError("no request may be sent in read-only mode")

    monkeypatch.setattr(client, "_mgmt", boom)
    monkeypatch.setattr(client, "_data", boom)
    for call in (
        lambda: client.run_sql("drop table x"),
        lambda: client.apply_migration("create table x()"),
        lambda: client.insert_rows("t", [{"a": 1}]),
        lambda: client.delete_function("f"),
        lambda: client.delete_project("abcdefghijklmnopqrst"),
    ):
        with pytest.raises(client_mod.ReadOnlyModeError):
            run(call())


def test_read_only_mode_allows_readonly_sql(monkeypatch):
    client = _client(monkeypatch, read_only=True)
    sent = {}

    async def fake_mgmt(method, path, **kwargs):
        sent["path"] = path
        return {"ok": True, "result": [{"n": 1}]}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(client.run_sql_readonly("select 1 as n"))
    assert result["ok"]
    assert sent["path"].endswith("/database/query/read-only")


def test_row_writes_refuse_empty_filters(monkeypatch):
    client = _client(monkeypatch)
    assert "filters are required" in run(client.update_rows("t", {"a": 1}, {}))["error"]
    assert "filters are required" in run(client.delete_rows("t", {}))["error"]


def test_delete_project_never_uses_default_ref(monkeypatch):
    client = _client(monkeypatch)
    assert "required" in run(client.delete_project(""))["error"]


def test_filter_params_support_repeats_and_logic_keys():
    params = SupabaseClient._filter_params(
        {"age": ["gte.18", "lt.65"], "or": "(a.eq.1,b.eq.2)"}
    )
    assert params == [("age", "gte.18"), ("age", "lt.65"), ("or", "(a.eq.1,b.eq.2)")]


def test_list_secrets_strips_values(monkeypatch):
    client = _client(monkeypatch)

    async def fake_mgmt(method, path, **kwargs):
        return {
            "ok": True,
            "result": [{"name": "STRIPE_KEY", "value": "sk_live_x", "updated_at": "t"}],
        }

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(client.list_secrets())
    assert result["result"] == [{"name": "STRIPE_KEY", "updated_at": "t"}]
    assert "sk_live_x" not in repr(result)


def test_service_config_redacts_secrets(monkeypatch):
    client = _client(monkeypatch)

    async def fake_mgmt(method, path, **kwargs):
        return {"ok": True, "result": {"db_schema": "public", "jwt_secret": "s3cret"}}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(client.get_service_config("postgrest"))
    assert result["result"]["jwt_secret"] == "***redacted***"
    assert "s3cret" not in repr(result)


def _fake_keys(api_keys):
    async def fake_mgmt(method, path, **kwargs):
        assert path.endswith("/api-keys") and kwargs["params"] == {"reveal": "true"}
        return {"ok": True, "result": api_keys}

    return fake_mgmt


def test_keys_prefer_new_secret_and_never_leak(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        client,
        "_mgmt",
        _fake_keys(
            [
                {"type": "legacy", "name": "anon", "api_key": "eyJa.nn.on"},
                {"type": "legacy", "name": "service_role", "api_key": "eyJs.rv.ce"},
                {"type": "publishable", "name": "default", "api_key": "sb_publishable_p"},
                {"type": "secret", "name": "default", "api_key": "sb_secret_s"},
            ]
        ),
    )
    keys = run(client._keys_for("abcdefghijklmnopqrst"))
    assert keys["secret"] == "sb_secret_s"
    assert keys["publishable"] == "sb_publishable_p"
    assert keys["jwt"] == "eyJs.rv.ce"

    public = run(client.get_project_keys())
    assert public["result"]["publishable_key"] == "sb_publishable_p"
    assert public["result"]["url"] == "https://abcdefghijklmnopqrst.supabase.co"
    assert "sb_secret_s" not in repr(public) and "eyJs" not in repr(public)


def test_keys_fall_back_to_legacy_service_role(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        client,
        "_mgmt",
        _fake_keys(
            [
                {"type": "legacy", "name": "anon", "api_key": "eyJa.nn.on"},
                {"type": "legacy", "name": "service_role", "api_key": "eyJs.rv.ce"},
            ]
        ),
    )
    keys = run(client._keys_for("abcdefghijklmnopqrst"))
    assert keys["secret"] == "eyJs.rv.ce"
    assert keys["publishable"] == "eyJa.nn.on"


class _Resp:
    def __init__(self, status=200, body=b"[]", headers=None):
        self.status_code = status
        self.content = body
        self.text = body.decode()
        self.headers = headers or {}

    def json(self):
        import json

        return json.loads(self.content)


def _capture_data_requests(monkeypatch, client, keys, responses=None):
    client._project_keys["abcdefghijklmnopqrst"] = keys
    sent: List[Dict[str, Any]] = []
    queue = list(responses or [])

    def fake_request(method, url, **kwargs):
        sent.append({"method": method, "url": url, **kwargs})
        return queue.pop(0) if queue else _Resp()

    monkeypatch.setattr(client_mod.httpx, "request", fake_request)
    return sent


def test_new_secret_key_goes_in_apikey_header_only(monkeypatch):
    client = _client(monkeypatch)
    sent = _capture_data_requests(
        monkeypatch, client, {"secret": "sb_secret_s", "publishable": None, "jwt": None}
    )
    run(client.select_rows("orders", filters={"status": "eq.open"}))
    headers = sent[0]["headers"]
    assert headers["apikey"] == "sb_secret_s"
    assert "Authorization" not in headers
    assert sent[0]["url"] == "https://abcdefghijklmnopqrst.supabase.co/rest/v1/orders"
    assert ("status", "eq.open") in sent[0]["params"]


def test_legacy_jwt_also_goes_in_authorization(monkeypatch):
    client = _client(monkeypatch)
    sent = _capture_data_requests(
        monkeypatch, client, {"secret": "eyJs.rv.ce", "publishable": None, "jwt": "eyJs.rv.ce"}
    )
    run(client.list_buckets())
    assert sent[0]["headers"]["Authorization"] == "Bearer eyJs.rv.ce"


def test_select_rows_reports_total_and_next_offset(monkeypatch):
    client = _client(monkeypatch)
    _capture_data_requests(
        monkeypatch,
        client,
        {"secret": "sb_secret_s", "publishable": None, "jwt": None},
        [_Resp(206, b'[{"id":1},{"id":2}]', {"content-range": "0-1/57"})],
    )
    result = run(client.select_rows("orders", limit=2, count=True))
    assert result["result"]["total"] == 57
    assert result["result"]["next_offset"] == 2


def test_data_plane_retries_once_with_fresh_keys_on_401(monkeypatch):
    client = _client(monkeypatch)
    client._project_keys["abcdefghijklmnopqrst"] = {
        "secret": "sb_secret_stale", "publishable": None, "jwt": None,
    }
    monkeypatch.setattr(
        client, "_mgmt",
        _fake_keys([{"type": "secret", "name": "default", "api_key": "sb_secret_new"}]),
    )
    seen: List[str] = []

    def fake_request(method, url, **kwargs):
        seen.append(kwargs["headers"]["apikey"])
        return _Resp(401, b"{}") if len(seen) == 1 else _Resp(200, b"[]")

    monkeypatch.setattr(client_mod.httpx, "request", fake_request)
    result = run(client.list_buckets())
    assert result["ok"]
    assert seen == ["sb_secret_stale", "sb_secret_new"]


def test_deploy_function_builds_multipart(monkeypatch):
    client = _client(monkeypatch)
    sent = {}

    async def fake_mgmt(method, path, **kwargs):
        sent.update(kwargs, method=method, path=path)
        return {"ok": True, "result": {"slug": "hello", "version": 1}}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(
        client.deploy_function(
            "hello", files={"index.ts": "Deno.serve(() => new Response('hi'))"}
        )
    )
    assert result["ok"]
    assert sent["path"].endswith("/functions/deploy")
    assert sent["params"] == {"slug": "hello"}
    assert '"entrypoint_path": "index.ts"' in sent["data"]["metadata"]
    assert sent["files"][0][0] == "file" and sent["files"][0][1][0] == "index.ts"


def test_deploy_function_requires_entrypoint_in_files(monkeypatch):
    client = _client(monkeypatch)
    result = run(client.deploy_function("hello", files={"main.ts": "x"}))
    assert "Entrypoint" in result["error"]


def test_set_secrets_rejects_reserved_names(monkeypatch):
    client = _client(monkeypatch)
    result = run(client.set_secrets({"SUPABASE_URL": "x"}))
    assert "reserved" in result["error"]


def test_missing_project_ref_is_actionable(monkeypatch):
    client = SupabaseClient()
    client.bind_credential(dict(PAT_CRED), lambda c: None)
    monkeypatch.setattr(client, "_config", lambda: SupabaseConfig())
    with pytest.raises(ValueError, match="list_supabase_projects"):
        run(client.list_tables())


# ── operations wiring ────────────────────────────────────────────────


def test_operation_count():
    names = {op.name for op in SupabaseProvider().operations()}
    assert len(names) == 71


def test_operation_inputs_match_client_signatures():
    """client_op passes input keys straight through as kwargs — a schema
    key the method doesn't accept is a guaranteed runtime TypeError."""
    import inspect

    for op in SupabaseProvider().operations():
        cells = dict(zip(op.fn.__code__.co_freevars, op.fn.__closure__ or ()))
        method_name = cells["method"].cell_contents
        method = getattr(SupabaseClient, method_name)
        params = inspect.signature(method).parameters
        accepted = {n for n in params if n != "self"}
        extra = set(op.input_schema) - accepted
        assert not extra, f"{op.name} → {method_name} rejects {sorted(extra)}"
        required = {
            n
            for n, p in params.items()
            if n != "self"
            and p.default is inspect.Parameter.empty
            and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        }
        missing = required - set(op.input_schema)
        assert not missing, f"{op.name} can never supply {sorted(missing)}"


# ── live findings (2026-10-05) ───────────────────────────────────────


def test_verify_describes_reach_by_projects_when_orgs_are_empty(monkeypatch):
    """Seen live: a valid token listed zero organizations but one project."""
    _stub_http(
        monkeypatch,
        {
            "/v1/organizations": {"ok": True, "result": []},
            "/v1/profile": {"error": "API error: 403", "details": ""},
            "/v1/projects": {"ok": True, "result": [{"name": "Test", "ref": "x"}]},
        },
    )
    ok, message, _ = SupabaseProvider().verify_token({"access_token": "sbp_good"})
    assert ok
    assert "1 project(s): Test" in message
    assert "no organizations" not in message


def test_logs_error_inside_200_body_is_a_failure(monkeypatch):
    """The analytics endpoint answers 200 with {"error": ...} on a failed
    query — that must not reach the agent as success."""
    client = _client(monkeypatch)

    async def fake_mgmt(method, path, **kwargs):
        return {"ok": True, "result": {"error": 'Table "postgres_logs" does not exist.'}}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(client.get_logs(source="postgres"))
    assert "error" in result
    assert "does not exist" in result["details"]


def test_logs_query_targets_unified_logs_table(monkeypatch):
    client = _client(monkeypatch)
    sent = {}

    async def fake_mgmt(method, path, **kwargs):
        sent.update(kwargs["params"])
        return {"ok": True, "result": {"result": [{"event_message": "hi"}]}}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(client.get_logs(source="postgres", search="it's"))
    assert result == {"ok": True, "result": [{"event_message": "hi"}]}
    assert "from logs where source_name = 'postgres_logs'" in sent["sql"]
    assert r"match(event_message, '(?i)it\'s')" in sent["sql"]


# ── second round of live findings ────────────────────────────────────


def test_schema_change_via_run_sql_is_recorded_as_migration(monkeypatch):
    client = _client(monkeypatch)
    sent = {}

    async def fake_mgmt(method, path, **kwargs):
        sent["path"] = path
        sent["body"] = kwargs.get("json_body")
        return {"ok": True, "result": {}}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(client.run_sql(
        "create table public.e2e_tasks (id bigint primary key);"
        " alter table public.e2e_tasks enable row level security;"
    ))
    assert sent["path"].endswith("/database/migrations")
    assert sent["body"]["name"] == "create_table_e2e_tasks"
    assert result["result"]["applied_as_migration"] == "create_table_e2e_tasks"


def test_data_changes_and_parameterised_sql_stay_on_query(monkeypatch):
    client = _client(monkeypatch)
    paths = []

    async def fake_mgmt(method, path, **kwargs):
        paths.append(path)
        return {"ok": True, "result": []}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    run(client.run_sql("update public.t set done = true where id = 2"))
    run(client.run_sql("create table x (a int)", parameters=[1]))
    assert all(p.endswith("/database/query") for p in paths)


@pytest.mark.parametrize("sql, expected", [
    ("create table public.e2e_tasks (id int)", "create_table_e2e_tasks"),
    ('create policy "read own" on public.t for select using (true)', "create_policy_read_own"),
    ("-- note\ncreate index if not exists idx_a on t(a)", "create_index_idx_a"),
    ("create or replace function f() returns int as $$ begin; return 1; end; $$ language plpgsql",
     "create_or_replace_function_f"),
    ("update t set a = 1; drop table if exists public.old_t", "drop_table_old_t"),
    ("create extension if not exists pg_trgm", "create_extension_pg_trgm"),
    ("create temp table scratch (a int)", None),
    ("insert into t values (1)", None),
    ("select 1", None),
])
def test_ddl_migration_name(sql, expected):
    assert client_mod.ddl_migration_name(sql) == expected


def test_list_organizations_recovers_from_projects_when_empty(monkeypatch):
    client = _client(monkeypatch)

    async def fake_mgmt(method, path, **kwargs):
        if path == "organizations":
            return {"ok": True, "result": []}
        return {"ok": True, "result": [
            {"name": "Test", "organization_slug": "agrnyy"},
            {"name": "Prod", "organization_slug": "agrnyy"},
        ]}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    orgs = run(client.list_organizations())["result"]
    assert [o["slug"] for o in orgs] == ["agrnyy"]
    assert orgs[0]["projects"] == ["Test", "Prod"]


def test_members_403_explains_itself(monkeypatch):
    client = _client(monkeypatch)

    async def fake_mgmt(method, path, **kwargs):
        return {"error": "API error: 403", "details": '{"message":"Forbidden"}'}

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    result = run(client.list_organization_members("agrnyy"))
    assert "403" in result["error"] and "Project operations are unaffected" in result["details"]


def test_logs_backend_error_is_retried_then_explained(monkeypatch):
    client = _client(monkeypatch)
    calls = []

    async def fake_mgmt(method, path, **kwargs):
        calls.append(path)
        return {"ok": True, "result": {"error": "Backend error! Retry your query."}}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(client, "_mgmt", fake_mgmt)
    monkeypatch.setattr(client_mod.asyncio, "sleep", no_sleep)
    result = run(client.get_logs(source="api"))
    assert len(calls) == 2
    assert "logs service is failing" in result["details"]


def test_default_alias_prefers_what_the_user_knows():
    provider = SupabaseProvider()
    assert provider.default_alias({"email": "dev@acme.com", "display_name": "Test"}) == "dev@acme.com"
    assert provider.default_alias({"org_name": "Acme", "display_name": "Test"}) == "Acme"
    assert provider.default_alias({"display_name": "Test, Prod +1"}) == "Test, Prod +1"
    assert provider.default_alias({}) is None


def test_verify_sets_project_display_name(monkeypatch):
    _stub_http(monkeypatch, {
        "/v1/organizations": {"ok": True, "result": []},
        "/v1/profile": {"error": "API error: 403", "details": ""},
        "/v1/projects": {"ok": True, "result": [
            {"name": "Test"}, {"name": "Prod"}, {"name": "Stage"}]},
    })
    ok, _, credential = SupabaseProvider().verify_token({"access_token": "sbp_good"})
    assert ok and credential["display_name"] == "Test, Prod +1"


def test_management_403_explains_itself(monkeypatch):
    client = _client(monkeypatch)

    async def fake_arequest(method, url, **kwargs):
        return {"error": "API error: 403", "details": '{"message":"Forbidden"}'}

    monkeypatch.setattr(client_mod, "arequest", fake_arequest)
    result = run(client.create_project(name="x", organization_slug="org"))
    assert result["error"] == "API error: 403"
    assert "Retrying won't help" in result["details"]
    assert "organization role" in result["details"]
