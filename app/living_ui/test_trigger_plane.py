"""Trigger-plane acceptance (spec TRIGGERS-PLAN): app→agent fires pass the
capability/consent/era gates, the brief is composed from disk, and nothing
app-controlled can steer the agent beyond the build-time declaration.

Run:  python3 -m app.living_ui.test_trigger_plane

Style follows test_data_safety.py: a module-level assert script with
hand-rolled duck-typed stubs, no pytest. The in-app half of the plane
(guard, cooldown, queue, describe) is exercised live by
living-ui-v2/scripts/a2app-selfcheck.sh §8 — this file covers the CraftBot
half.
"""

import asyncio
import json as _json
import tempfile
from pathlib import Path

import app.factory.host_craftbot as host_mod
import app.living_ui as living_ui_mod
from app.living_ui.integration_bridge import IntegrationBridge
from app.living_ui.manager import LivingUIManager
from app.living_ui.walk_verify import parse_check_report


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
    """Just enough LivingUIManager for the bridge handler."""

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
    living = Path(tmp) / "living_ui"
    project = _make_project(living, "consent01")
    living_ui_mod.get_living_ui_manager = lambda: _MgrStub(project)
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
    living = Path(tmp) / "living_ui"
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
    living = Path(tmp) / "living_ui"
    project = _make_project(living, "gates001")
    mgr = _MgrStub(project)
    living_ui_mod.get_living_ui_manager = lambda: mgr
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

    # Consented but NOT delivered: build-era fires are verifier traffic.
    host.set_triggers_approved("gates001")
    resp = _fire(bridge)
    assert resp.status == 200 and b"deferred" in resp.body, (
        "pre-delivery fire must defer, not dispatch"
    )
    assert mgr.notified == []

    # Delivered + staging copy active: modify-era fires must also defer.
    host.mark_delivered("gates001")
    host.set_staging_record("gates001", {"dir": "/tmp/x", "port": 3901, "pid": 1})
    resp = _fire(bridge)
    assert resp.status == 200 and b"deferred" in resp.body, "staging fire must defer"
    assert mgr.notified == []

    # Live era: delivered, no staging → dispatch exactly once.
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
    living = Path(tmp) / "living_ui"
    project = _make_project(living, "brief001")

    class _Session:
        id = "lui_brief001"

    class _TriggerService:
        def __init__(self):
            self.emitted = []

        async def emit(self, spec):
            self.emitted.append(spec)

    mgr = LivingUIManager.__new__(LivingUIManager)
    mgr.projects = {"brief001": project}
    mgr._session_manager = object()
    mgr._trigger_service = _TriggerService()
    mgr.ensure_project_session = lambda p: _Session()

    result = asyncio.run(mgr.notify_app_trigger("brief001", "restock_needed", "rowXYZ"))
    assert result["status"] == "success", result
    (spec,) = mgr._trigger_service.emitted
    from app.triggers import TriggerSource

    assert spec.source == TriggerSource.LIVING_UI_APP_REQUEST
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
    living = Path(tmp) / "living_ui"
    project = _make_project(living, "surface1")
    living_ui_mod.get_living_ui_manager = lambda: _MgrStub(project)
    host_mod._HOST = None
    host = host_mod.get_factory_host()

    mgr = LivingUIManager.__new__(LivingUIManager)
    brief = mgr.declared_triggers_brief(project)
    assert "CONSENT NEEDED" in brief and "restock_needed" in brief
    assert "living_ui_approve_triggers" in brief and "surface1" in brief

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
    living = Path(tmp) / "living_ui"
    project = _make_project(living, "throt001")
    living_ui_mod.get_living_ui_manager = lambda: _MgrStub(project)
    host_mod._HOST = None
    host = host_mod.get_factory_host()
    counts = [host.bump_throttle_retry("throt001") for _ in range(4)]
    assert counts == [1, 2, 3, 4], "throttle retries must count within the window"
    side = _json.loads((Path(project.path) / ".factory" / "host.json").read_text())
    assert side["throttle_retries"] == 4, "count must persist in the sidecar"
print("§6 throttled-verifier classification + bounded retries: OK")


# ── §7 consent ask: composed for the user, from the declaration ────────────
with tempfile.TemporaryDirectory() as tmp:
    living = Path(tmp) / "living_ui"
    project = _make_project(living, "ask00001")
    living_ui_mod.get_living_ui_manager = lambda: _MgrStub(project)
    host_mod._HOST = None

    class _Session:
        id = "lui_ask00001"

    class _TriggerService:
        def __init__(self):
            self.emitted = []

        async def emit(self, spec):
            self.emitted.append(spec)

    mgr = LivingUIManager.__new__(LivingUIManager)
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
    assert "living_ui_approve_triggers" in spec.description
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
    living_ui_project_id = "recpt001"


class _RecvSessionMgr:
    def get(self, sid):
        return _RecvSession()


class _RecvHost:
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
report = AgentBase._report_living_ui_writes.__get__(host)
cli = "node /x/living-ui-v2/tools/src/cli.ts data /apps/proj"
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

print("\nTrigger-plane acceptance: ALL GREEN")
