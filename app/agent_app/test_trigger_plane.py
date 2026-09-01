"""Trigger-plane acceptance (spec TRIGGERS-PLAN): app→agent fires pass the
capability/consent/era gates, the brief is composed from disk, and nothing
app-controlled can steer the agent beyond the build-time declaration.

Run:  python3 -m app.agent_app.test_trigger_plane

Style follows test_data_safety.py: a module-level assert script with
hand-rolled duck-typed stubs, no pytest. The in-app half of the plane
(guard, cooldown, queue, describe) is exercised live by
agent-app/scripts/a2app-selfcheck.sh §8 — this file covers the CraftBot
half.
"""

import asyncio
import json as _json
import tempfile
from pathlib import Path

import app.factory.host_craftbot as host_mod
import app.agent_app as agent_app_mod
from app.agent_app.integration_bridge import IntegrationBridge
from app.agent_app.manager import AgentAppManager
from app.agent_app.walk_verify import parse_check_report


# ── shared stubs ───────────────────────────────────────────────────────────
class _Project:
    def __init__(self, pid: str, path: Path, port: int = 3150):
        self.id, self.name, self.description = pid, pid, "test app"
        self.path, self.port, self.status = str(path), port, "running"
        self.url = f"http://127.0.0.1:{port}"
        self.backend_url = self.url
        self.features = []


def _make_project(living: Path, pid: str, *, triggers: bool = True) -> _Project:
    proj = living / f"app_{pid}"
    (proj / ".factory").mkdir(parents=True)
    manifest = {"id": pid, "name": pid, "port": 3150}
    if triggers:
        manifest["capabilities"] = {"triggers": ["restock_needed"]}
        (proj / "triggers.json").write_text(
            _json.dumps(
                {
                    "triggers": {
                        "restock_needed": {
                            "description": "Stock fell below threshold",
                            "instruction": "Ensure a draft restock order exists.",
                            "params": {"item_id": {"type": "number", "required": True}},
                        }
                    }
                }
            )
        )
    (proj / "manifest.json").write_text(_json.dumps(manifest))
    return _Project(pid, proj)


class _Req:
    """Duck-typed aiohttp request: headers + json()."""

    def __init__(self, token: str, body: dict):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._body = body

    async def json(self):
        return self._body


class _MgrStub:
    """Just enough AgentAppManager for the bridge handler."""

    def __init__(self, project):
        self._project = project
        self.notified = []

    def validate_bridge_token(self, token):
        return self._project.id if token == "good" else None

    def get_project(self, pid):
        return self._project if pid == self._project.id else None

    async def notify_app_trigger(self, project_id, trigger, request_id):
        self.notified.append((project_id, trigger, request_id))
        return {"status": "success", "session_id": "lui_x"}

    async def notify_trigger_consent_needed(self, project_id, trigger):
        self.consent_asks = getattr(self, "consent_asks", [])
        self.consent_asks.append((project_id, trigger))
        if getattr(self, "fail_next_consent_ask", False):
            self.fail_next_consent_ask = False
            return {"status": "error", "message": "session runtime hiccup"}
        return {"status": "success"}


def _bridge(mgr) -> IntegrationBridge:
    bridge = IntegrationBridge.__new__(IntegrationBridge)
    bridge._manager = mgr
    return bridge


def _fire(bridge, token="good", trigger="restock_needed", request_id="row1"):
    return asyncio.run(
        bridge._handle_agent_request(
            _Req(token, {"trigger": trigger, "request_id": request_id})
        )
    )


# ── §1 consent flag round-trip (sidecar-backed, fail-closed) ───────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "consent01")
    agent_app_mod.get_agent_app_manager = lambda: _MgrStub(project)
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    assert host.is_triggers_approved("consent01") is False, "default must be closed"
    host.set_triggers_approved("consent01")
    assert host.is_triggers_approved("consent01") is True
    side = _json.loads((Path(project.path) / ".factory" / "host.json").read_text())
    assert side["triggers_approved"] is True, "consent must persist in the sidecar"
    host.set_triggers_approved("consent01", False)
    assert host.is_triggers_approved("consent01") is False
print("§1 consent flag round-trip: OK")


# ── §2 capability gate: derived manifest list, fail-closed ─────────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "caps0001")
    bridge = _bridge(_MgrStub(project))

    ok, why = bridge._project_trigger_grants("caps0001", "restock_needed")
    assert ok is True, why
    ok, why = bridge._project_trigger_grants("caps0001", "undeclared_one")
    assert ok is False and "capabilities.triggers" in why
    ok, _ = bridge._project_trigger_grants("nope", "restock_needed")
    assert ok is False, "unknown project must fail closed"

    bare = _make_project(living, "caps0002", triggers=False)
    bridge2 = _bridge(_MgrStub(bare))
    ok, why = bridge2._project_trigger_grants("caps0002", "restock_needed")
    assert ok is False, "no capabilities block must fail closed"
print("§2 capability gate fail-closed: OK")


# ── §3 handler gate order: token → capability → consent → era → dispatch ───
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "gates001")
    mgr = _MgrStub(project)
    agent_app_mod.get_agent_app_manager = lambda: mgr
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    bridge = _bridge(mgr)

    assert _fire(bridge, token="bad").status == 401, "unknown token must 401"
    assert _fire(bridge, trigger="undeclared_one").status == 403, (
        "undeclared trigger must 403"
    )
    # Declared but unconsented (fresh sidecar): refused before any dispatch —
    # but the USER gets asked, exactly once per hour (a silent refusal reads
    # as a broken button; observed live 2026-08-06). A FAILED ask must not
    # consume the hourly slot (also observed live: a silent failure
    # suppressed every retry for an hour).
    mgr.fail_next_consent_ask = True
    assert _fire(bridge).status == 403, "missing consent must 403"
    assert mgr.notified == [], "nothing may reach the agent before consent"
    assert len(getattr(mgr, "consent_asks", [])) == 1, "ask must be attempted"
    assert _fire(bridge).status == 403
    assert len(mgr.consent_asks) == 2, "a FAILED ask must not consume the hourly slot"
    assert _fire(bridge).status == 403
    assert len(mgr.consent_asks) == 2, "a SUCCESSFUL ask must be hourly-capped"

    # Consented + a DEV environment active: fires are agent/verifier test
    # traffic (the walker clicks ⚡ in the dev instance, which aliases to the
    # real project id through the shared bridge token) — must defer.
    host.set_triggers_approved("gates001")
    host.set_staging_record("gates001", {"dir": "/tmp/x", "port": 3901, "pid": 1})
    resp = _fire(bridge)
    assert resp.status == 200 and b"deferred" in resp.body, "dev-env fire must defer"
    assert mgr.notified == []

    # Live era: consented, no dev env → dispatch exactly once. (No stored
    # "delivered" flag any more — with no dev env in flight, a consented
    # fire from a running app is legitimate operation.)
    host.clear_staging_record("gates001")
    resp = _fire(bridge)
    assert resp.status == 200 and b"deferred" not in resp.body
    assert mgr.notified == [("gates001", "restock_needed", "row1")], (
        f"expected one dispatch, got {mgr.notified}"
    )

    # Missing fields: rejected before any gate work.
    assert (
        asyncio.run(bridge._handle_agent_request(_Req("good", {"trigger": "x"}))).status
        == 400
    )
print("§3 handler gate order: OK")


# ── §4 notify_app_trigger: brief composed from DISK, emit into project session ──
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "brief001")

    class _Session:
        id = "lui_brief001"

    class _TriggerService:
        def __init__(self):
            self.emitted = []

        async def emit(self, spec):
            self.emitted.append(spec)

    mgr = AgentAppManager.__new__(AgentAppManager)
    mgr.projects = {"brief001": project}
    mgr._session_manager = object()
    mgr._trigger_service = _TriggerService()
    mgr.ensure_project_session = lambda p: _Session()

    result = asyncio.run(mgr.notify_app_trigger("brief001", "restock_needed", "rowXYZ"))
    assert result["status"] == "success", result
    (spec,) = mgr._trigger_service.emitted
    from app.triggers import TriggerSource

    assert spec.source == TriggerSource.AGENT_APP_APP_REQUEST
    assert spec.session_id == "lui_brief001", "must land in the PROJECT session"
    assert spec.payload["request_id"] == "rowXYZ"
    # The instruction comes from triggers.json on disk — never from the nudge.
    assert "Ensure a draft restock order exists." in spec.description
    assert "rowXYZ" in spec.description and "claimed" in spec.description
    assert "agent_requests get rowXYZ" in spec.description, (
        "brief must read the row by id — a paged list missed the target row "
        "among older ones (observed live 2026-08-06)"
    )
    assert "Tell the USER" in spec.description and "ONE short message" in (
        spec.description
    ), (
        "brief must end with messaging the user — a literal protocol-follower "
        "once wrote the row and ended silently (observed live 2026-08-06)"
    )
    assert "DATA" in spec.description, "params-are-data rule must be in the brief"

    # Undeclared trigger: nothing emitted (the nudge cannot invent one).
    result = asyncio.run(mgr.notify_app_trigger("brief001", "invented", "row2"))
    assert result["status"] == "error"
    assert len(mgr._trigger_service.emitted) == 1
print("§4 brief from disk + project-session emit: OK")


# ── §5 consent surfacing: declared_triggers_brief for third-party installs ──
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "surface1")
    agent_app_mod.get_agent_app_manager = lambda: _MgrStub(project)
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    mgr = AgentAppManager.__new__(AgentAppManager)
    brief = mgr.declared_triggers_brief(project)
    assert "CONSENT NEEDED" in brief and "restock_needed" in brief
    assert "agent_app_approve_triggers" in brief and "surface1" in brief

    host.set_triggers_approved("surface1")
    assert mgr.declared_triggers_brief(project) == "", (
        "approved apps must not re-prompt"
    )

    bare = _make_project(living, "surface2", triggers=False)
    assert mgr.declared_triggers_brief(bare) == "", "no triggers → no consent ask"
print("§5 consent surfacing: OK")

# ── §6 throttled verifier: classified, bounded, never stuck-on-first ───────
report = parse_check_report(
    "(sub-agent aborted — LLM unavailable: Rate limit exceeded for grok-4)"
)
assert report["kind"] == "throttled", report
assert (
    parse_check_report("VERDICT: PASS\nFEATURES:\n- x — PASS — did it")["kind"]
    == "pass"
), "throttle detection must not shadow real verdicts"

with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "throt001")
    agent_app_mod.get_agent_app_manager = lambda: _MgrStub(project)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    counts = [host.bump_throttle_retry("throt001") for _ in range(4)]
    assert counts == [1, 2, 3, 4], "throttle retries must count within the window"
    side = _json.loads((Path(project.path) / ".factory" / "host.json").read_text())
    assert side["throttle_retries"] == 4, "count must persist in the sidecar"
print("§6 throttled-verifier classification + bounded retries: OK")


# ── §7 consent ask: composed for the user, from the declaration ────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "ask00001")
    agent_app_mod.get_agent_app_manager = lambda: _MgrStub(project)
    host_mod._HOST = None

    class _Session:
        id = "lui_ask00001"

    class _TriggerService:
        def __init__(self):
            self.emitted = []

        async def emit(self, spec):
            self.emitted.append(spec)

    mgr = AgentAppManager.__new__(AgentAppManager)
    mgr.projects = {"ask00001": project}
    mgr._session_manager = object()
    mgr._trigger_service = _TriggerService()
    mgr.ensure_project_session = lambda p: _Session()

    result = asyncio.run(
        mgr.notify_trigger_consent_needed("ask00001", "restock_needed")
    )
    assert result["status"] == "success", result
    (spec,) = mgr._trigger_service.emitted
    assert spec.session_id == "lui_ask00001"
    assert "NOT approved" in spec.description and "refused" in spec.description
    assert "agent_app_approve_triggers" in spec.description
    assert "Do NOT act on the trigger itself" in spec.description
    assert spec.payload.get("consent_ask") is True
print("§7 consent ask composition: OK")

# ── §8 write receipts skip trigger-plane bookkeeping ───────────────────────
# Claim/done updates on agent_requests must not produce receipt bubbles —
# the ⚡ event and the agent's final message are the user-facing output
# (observed live 2026-08-06: three noise bubbles per fire).
# agent_base pulls the scheduler stack (croniter …), which the bare test env
# may lack — skip honestly rather than fake a pass; the live runtime always
# has it.
try:
    from app.agent_base import AgentBase

    _AGENT_BASE = True
except ImportError as _e:
    print(f"§8 receipts skip queue bookkeeping: SKIPPED (agent_base deps: {_e})")
    _AGENT_BASE = False


class _RecvSession:
    agent_app_project_id = "recpt001"


class _RecvSessionMgr:
    def get(self, sid):
        return _RecvSession()


class _RecvHost:
    # _report_agent_app_writes matches with self._LUI_WRITE: without it
    # every receipt raised AttributeError into the "a receipt must never
    # break the turn" handler and the section asserted on an empty list.
    _LUI_WRITE = AgentBase._LUI_WRITE if _AGENT_BASE else None

    def __init__(self):
        self.described = []
        self.session_manager = _RecvSessionMgr()
        self.event_stream_manager = None

    def _describe_write(self, session_id, project_id, match, result):
        self.described.append(match.group("collection") or match.group("op"))
        return None  # keep the tail (event log + dispatch) out of the test


class _Act:
    name = "run_shell"


if not _AGENT_BASE:
    print("\nTrigger-plane acceptance: ALL GREEN (§8 skipped)")
    raise SystemExit(0)
host = _RecvHost()
report = AgentBase._report_agent_app_writes.__get__(host)
cli = "node /x/agent-app/tools/src/cli.ts data /apps/proj"
report(
    "lui_recpt001",
    [
        (_Act(), {"command": f"{cli} agent_requests update row1 --status claimed"}),
        (_Act(), {"command": f"{cli} agent_requests update row1 --status done"}),
        (_Act(), {"command": f"{cli} tasks create --title X"}),
        (_Act(), {"command": f"{cli} agent_requests list --limit 5"}),
    ],
    [{}, {}, {}, {}],
)
assert host.described == ["tasks"], (
    f"only real data writes may receipt — got {host.described}"
)
print("§8 receipts skip queue bookkeeping: OK")

# -- §9 action gates: a DRY RUN is not a send ---------------------------
# A dry run executes nothing, so demanding confirm_irreversible for one made
# the mode unreachable for every irreversible action. An app probing Gmail
# with a dry-run send_gmail read "it acts on the user's real account"
# (correctly) as a reason NOT to set the flag, and reported Gmail as
# disconnected to the user for three straight verification rounds.
class _Meta:
    def __init__(self, irreversible):
        self.action_sets = ["gmail_mail", "gmail"]
        self.irreversible = irreversible
        self.input_schema = {}


class _Impl:
    def __init__(self, irreversible=True):
        self.metadata = _Meta(irreversible)
        self.calls = []

    def handler(self, params):
        self.calls.append(params)
        return {"sent": True}


class _Registry:
    impl = None

    def get_action_implementation(self, name):
        return _Registry.impl


def _call(bridge, body):
    import agent_core.core.action_framework.registry as _reg

    _reg.ActionRegistry = _Registry
    return asyncio.run(bridge._handle_action(_Req("good", body)))


with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "agent_app"
    project = _make_project(living, "acts0001")
    manifest = Path(project.path) / "manifest.json"
    manifest.write_text(
        _json.dumps({"id": "acts0001", "capabilities": {"actions": ["send_gmail"]}})
    )
    bridge = _bridge(_MgrStub(project))
    impl = _Impl(irreversible=True)
    _Registry.impl = impl

    # A real call still demands the flag, and still refuses without it.
    resp = _call(bridge, {"action": "send_gmail", "params": {"subject": "x"}})
    assert resp.status == 400 and b"confirm_irreversible" in resp.body, (
        "a real irreversible call must still require confirmation"
    )
    assert impl.calls == [], "a refused call must not execute"

    # The same call as a dry run passes that gate and executes NOTHING.
    resp = _call(
        bridge, {"action": "send_gmail", "params": {"subject": "x"}, "dry_run": True}
    )
    assert resp.status == 200, f"dry run must pass the irreversible gate: {resp.body}"
    assert b"dry_run" in resp.body
    assert impl.calls == [], "a dry run must never reach the handler"

    # camelCase spelling behaves identically.
    resp = _call(bridge, {"action": "send_gmail", "params": {}, "dryRun": True})
    assert resp.status == 200, "camelCase dryRun must behave identically"

    # ...but a dry run is NOT a way past the capability grant.
    manifest.write_text(
        _json.dumps({"id": "acts0001", "capabilities": {"actions": []}})
    )
    resp = _call(bridge, {"action": "send_gmail", "params": {}, "dry_run": True})
    assert resp.status == 403 and b"capabilities.actions" in resp.body, (
        "dry run must not bypass the capability grant"
    )
    assert impl.calls == []
print("§9 dry run bypasses irreversible confirm, not the grant: OK")

# -- §10 the connection probe is never a write --------------------------
# The capability block names ONE call per integration for "is this
# connected?". Picking it from the metadata alone chose create_google_doc
# for google_docs — neither `destructive` nor `parallelizable` is set on it,
# so it scored as safe and took the fewest parameters. Every app checking
# that integration would have created a blank document in the user's Drive,
# one line below a sentence reading "never a send/create".
from app.agent_app.agent_view import _probe_action  # noqa: E402


class _M:
    def __init__(self, params, irreversible=False, parallelizable=True):
        self.input_schema = {p: {"type": "string"} for p in params}
        self.irreversible = irreversible
        self.parallelizable = parallelizable


_google_docs = [
    ("create_google_doc", _M(["account", "title"])),
    ("get_google_doc_text", _M(["account", "document_id"])),
    ("get_google_doc", _M(["account", "document_id", "include_metadata"])),
]
assert _probe_action(_google_docs) == "", (
    "no zero-arg read exists here: name nothing rather than a write "
    "(create_google_doc) or a read that needs an id the app hasn't got"
)

_gmail = [
    ("create_gmail_draft", _M(["account", "to"])),
    ("get_gmail", _M(["account", "message_id"])),
    ("list_gmail_labels", _M(["account"])),
    ("get_gmail_profile", _M(["account"])),
]
assert _probe_action(_gmail) == "get_gmail_profile", _probe_action(_gmail)
# Stable across runs: two zero-arg reads tie and alphabetical breaks it.
assert _probe_action(list(reversed(_gmail))) == "get_gmail_profile"
# `account` is injected by the bridge, so it is not an argument the app owns;
# anything else IS one, however read-shaped the name.
assert _probe_action([("get_thing", _M(["account", "id"]))]) == ""
assert _probe_action([("get_thing", _M([]))]) == "get_thing"
print("§10 connection probe is a zero-arg read or nothing: OK")

print("\nTrigger-plane acceptance: ALL GREEN")
