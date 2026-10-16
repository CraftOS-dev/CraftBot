"""Regression coverage for the eight pre-install security review findings.

Synthetic vaults only. The .NET probe executes transport serialization methods;
it never starts the service, prompts an owner, or launches an AppContainer.
"""

import ast
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from app.credentials.broker import canonical_request
from app.credentials.contracts import CredentialKind, HelperOperation
from app.credentials.execution import OperationJob, OutputBudget
from app.credentials.host_service import Launch
from app.credentials.helpers import HelperRegistry, HttpsJsonOperation, JsonResult
from app.credentials.request_review import review_request
from app.credentials.use_errors import CredentialUseError, UseCode
from app.credentials.directory import IdentityError
from app.credentials.windows_host import private_acl
import test_broker as broker_support
import test_job_transport as job_support
import test_protected_host as host_support

ROOT = Path(__file__).resolve().parents[2]


class RequestBindingTests(unittest.TestCase):
    def setUp(self):
        self.case = broker_support.CredentialBrokerTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.spec = HttpsJsonOperation(
            HelperOperation("integration_example", "send"),
            CredentialKind.API_KEY,
            "https://example.test/channels/:channel/messages",
            method="POST",
            envelope=True,
            path_fields=("channel",),
            query_fields=("limit",),
        )
        self.case.broker._registry = HelperRegistry((self.spec,))
        self.payload = {
            "body": {
                "path": {"channel": "reviewed"},
                "query": {},
                "data": {"recipient": "alice", "text": "reviewed"},
            }
        }

    def approve(self, payload):
        grant = self.case.broker.approve(
            self.case.context, self.case.reference, self.spec.operation, payload=payload
        )
        return grant, self.case.broker.authorize(self.case.context, grant.grant_id)

    def test_changed_path_query_or_write_body_is_denied_before_network(self):
        for field, value in (
            ("path", {"channel": "other"}),
            ("query", {"limit": 2}),
            ("data", {"recipient": "mallory"}),
        ):
            with self.subTest(field=field):
                grant, capability = self.approve(self.payload)
                changed = json.loads(json.dumps(self.payload))
                changed["body"][field] = value
                with patch("app.credentials.broker._execute_json") as network:
                    with self.assertRaises(CredentialUseError):
                        self.case.broker.execute(self.case.context, capability, changed)
                    network.assert_not_called()
                self.assertNotIn(grant.grant_id, self.case.broker._grants)

    def test_missing_body_approval_cannot_authorize_later_payload(self):
        _, capability = self.approve(None)
        with patch("app.credentials.broker._execute_json") as network:
            with self.assertRaises(CredentialUseError):
                self.case.broker.execute(self.case.context, capability, self.payload)
            network.assert_not_called()

    def test_canonical_order_is_stable_and_approval_is_not_mutable(self):
        grant, capability = self.approve(self.payload)
        equivalent = {"body": dict(reversed(list(self.payload["body"].items())))}
        self.assertEqual(grant.request_digest, canonical_request(equivalent)[1])
        self.payload["body"]["data"]["recipient"] = "changed-after-approval"
        with self.assertRaises(CredentialUseError):
            self.case.broker.execute(self.case.context, capability, self.payload)
        for value in ({"body": float("nan")}, {"body": float("inf")}):
            with self.assertRaises(CredentialUseError):
                self.approve(value)

    def test_review_displays_resolved_resource_recipients_and_exact_hash(self):
        self.payload["body"]["session"] = {
            "access_token": "synthetic-generated-session"
        }
        self.payload["body"]["data"]["attachment"] = "large attachment" * 2000
        view = review_request(self.spec, self.payload)
        self.assertEqual(
            view["Destination"], "https://example.test/channels/reviewed/messages"
        )
        self.assertIn('"recipient": "alice"', view["Parameters"])
        self.assertIn("content_omitted", view["Parameters"])
        self.assertNotIn("synthetic-generated-session", json.dumps(view))
        self.assertEqual(
            view["Request SHA256"], canonical_request(self.payload)[1].hex()
        )

    def test_exact_request_runs_and_replay_is_rejected(self):
        _, capability = self.approve(self.payload)

        def helper(spec, fields, guard, payload, **kwargs):
            guard()
            self.assertEqual(payload, self.payload)
            return JsonResult(200, "{}", "application/json")

        with patch(
            "app.credentials.broker._execute_json", side_effect=helper
        ) as network:
            self.assertEqual(
                self.case.broker.execute(
                    self.case.context, capability, self.payload
                ).status,
                200,
            )
            with self.assertRaises(CredentialUseError):
                self.case.broker.execute(self.case.context, capability, self.payload)
            network.assert_called_once()

    def test_host_requires_staged_request_before_asking_owner(self):
        fixture = job_support.JobTransportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.launch.payload_ready = False
        with self.assertRaises(CredentialUseError):
            fixture.request("POST", False)
        fixture.host.consent.verify.assert_not_called()

    def test_public_payload_swap_after_consent_is_rejected_by_broker(self):
        fixture = job_support.JobTransportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        launch = Launch(
            Mock(),
            fixture.case.context,
            Mock(alive=lambda: True),
            time.monotonic() + 900,
            payload_text='{"recipient":"alice"}',
            payload_ready=True,
        )
        fixture.launch = launch
        fixture.host.leases = {uuid4(): launch}
        fixture.host.output_budget = OutputBudget()
        fixture.host._consumer = Mock(return_value=launch)
        approval = fixture.request("POST", False)
        fixture.host.dispatch(fixture.peer, {"op": "discard_payload"})
        fixture.host.dispatch(
            fixture.peer,
            {
                "op": "upload_payload_part",
                "offset": 0,
                "data": '{"recipient":"mallory"}',
                "done": True,
            },
        )
        with patch("app.credentials.broker._execute_json") as network:
            fixture.host.dispatch(
                fixture.peer,
                {"op": "start_use_staged", "capability": approval["capability"]},
            )
            launch.job.thread.join(2)
            self.assertEqual(launch.job.error, UseCode.DENIED.value)
            network.assert_not_called()
        self.assertEqual(fixture.host.output_budget.used, 0)

    def test_sdk_can_use_two_helpers_then_return_computed_program_result(self):
        from app.credentials import client

        fixture = job_support.JobTransportTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        controller = Mock(pid=42, created=123, alive=lambda: True)
        launch = Launch(
            Mock(), fixture.case.context, controller, time.monotonic() + 900
        )
        key = uuid4()
        fixture.host.leases = {key: launch}
        fixture.host.output_budget = OutputBudget()
        fixture.host._consumer = Mock(return_value=launch)
        spec = HttpsJsonOperation(
            HelperOperation("integration_example", "read"),
            CredentialKind.API_KEY,
            "https://example.test/items",
            method="POST",
        )
        fixture.host.registry = fixture.case.broker._registry = HelperRegistry((spec,))

        def exchange(op, **parameters):
            return fixture.host.dispatch(fixture.peer, {"op": op, **parameters})

        with (
            patch.object(client, "request", side_effect=exchange),
            patch(
                "app.credentials.broker._execute_json",
                return_value=JsonResult(200, '{"n":2}', "application/json"),
            ),
        ):
            values = [
                client.use_json(
                    "integration_example",
                    "read",
                    str(fixture.case.reference.credential_id),
                    body={"input": n},
                    credential_version=1,
                )
                for n in (1, 2)
            ]
            client.complete({"sum": sum(json.loads(v["body"])["n"] for v in values)})
        owner = SimpleNamespace(**vars(fixture.peer), pid=42, created=123)
        result = fixture.host.dispatch(
            owner, {"op": "program_result", "run_id": str(key)}
        )
        self.assertEqual(result, {"result": {"sum": 4}})
        launch.close()


class HostLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.case = host_support.RouterTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.case.owner.created = 123
        self.case.owner.close = Mock()
        self.host = self.case.host
        self.host.consent = Mock()

    def launch(self):
        class Process:
            def __init__(inner, root, *args):
                inner.root, inner.app_sid, inner.pid, inner.handle = (
                    root,
                    "S-1-15-2-111",
                    123,
                    456,
                )
                root.mkdir(parents=True)
                inner.start, inner.close = Mock(), Mock()

        client = self.case.root / "app" / "credentials" / "client.py"
        client.parent.mkdir(parents=True)
        client.write_text("# synthetic client")
        with (
            patch("app.credentials.host_service.IsolatedProcess", Process),
            patch("app.credentials.host_service.private_acl"),
            patch("app.credentials.host_service.Peer", return_value=self.case.owner),
            patch("app.credentials.host_service.Timer") as timer,
            patch("app.credentials.host_service.Thread"),
        ):
            result = self.host.dispatch(
                self.case.owner,
                dict(
                    op="launch",
                    profile_id=self.case.profile_id,
                    kind="agent_app",
                    subject="claimed-trusted-app",
                    deployment="live",
                    files={"main.py": "pass"},
                    entry="main.py",
                ),
            )
        key = next(iter(self.host.leases))
        return key, self.host.leases[key], result, timer.call_args

    def test_claims_are_explicitly_unverified_and_actual_snapshot_is_pinned(self):
        _, launch, result, _ = self.launch()
        self.assertFalse(result["identity_verified"])
        self.assertIn("(unverified)", self.host.consent.message)
        self.assertIn("not trusted enrollment", self.host.consent.message)
        self.assertEqual(result["revision"], launch.context.binding.caller.app_revision)
        self.assertEqual(result["revision"], launch.snapshot_revision)
        launch.close()

    def test_expiry_timer_cancels_helper_closes_peers_and_revokes_without_rpc(self):
        key, launch, _, timer = self.launch()
        launch.job = OperationJob(lambda _: None)
        with patch("app.credentials.host_service.Thread") as thread:
            thread.side_effect = lambda *, target, args, **kw: SimpleNamespace(
                start=lambda: target(*args)
            )
            timer.args[1](*timer.kwargs["args"])
        self.assertTrue(launch.job.cancelled.is_set())
        self.assertTrue(launch.closed.is_set())
        self.assertNotIn(key, self.host.leases)
        launch.process.close.assert_called_once()
        self.case.owner.close.assert_called_once()
        with self.assertRaises(IdentityError):
            self.host.directory.require_current(launch.context)
        self.host._expire(key, launch)
        launch.process.close.assert_called_once()

    def test_disconnected_controller_also_cancels_helper(self):
        key, launch, _, _ = self.launch()
        launch.job = OperationJob(lambda _: None)
        launch.controller.alive = lambda: False
        with (
            patch.object(launch.closed, "wait", return_value=False),
            patch("app.credentials.host_service.Thread"),
        ):
            self.host._watch(key, launch)
        self.assertTrue(launch.job.cancelled.is_set())
        self.assertNotIn(key, self.host.leases)

    def test_completed_program_and_helper_response_have_distinct_channels(self):
        key, launch, _, _ = self.launch()
        launch.job = OperationJob(lambda _: None)
        launch.job._run(
            lambda _: JsonResult(200, '{"data":"synthetic"}', "application/json")
        )
        launch.result = {"result": {"computed": "completed-value"}}
        program = self.host.dispatch(
            self.case.owner, {"op": "program_result", "run_id": str(key)}
        )
        operation = self.host.dispatch(
            self.case.owner, {"op": "result", "run_id": str(key)}
        )
        self.assertEqual(program, launch.result)
        self.assertEqual(operation["response"]["status"], 200)
        body = self.host.dispatch(
            self.case.owner, {"op": "response", "run_id": str(key), "offset": 0}
        )
        self.assertEqual(body["chunk"], '{"data":"synthetic"}')
        other = SimpleNamespace(**vars(self.case.owner))
        other.created += 1
        with self.assertRaises(CredentialUseError):
            self.host.dispatch(other, {"op": "program_result", "run_id": str(key)})
        launch.close()

    def test_profile_preference_requires_owner_consent_and_valid_profile(self):
        self.assertEqual(
            self.host.dispatch(self.case.owner, {"op": "action_profile"}),
            {"profile_id": None},
        )
        self.host.consent.verify.side_effect = PermissionError()
        with self.assertRaises(CredentialUseError):
            self.host.dispatch(
                self.case.owner,
                {"op": "action_profile_set", "profile_id": self.case.profile_id},
            )
        self.assertFalse((self.case.root / "action-profile.json").exists())
        self.host.consent.verify.side_effect = None
        with patch("app.credentials.host_service.private_acl") as acl:
            value = self.host.dispatch(
                self.case.owner,
                {"op": "action_profile_set", "profile_id": self.case.profile_id},
            )
            acl.assert_called_once()
        self.assertEqual(value, {"profile_id": self.case.profile_id})
        self.assertEqual(
            self.host.dispatch(self.case.owner, {"op": "action_profile"}), value
        )
        with self.assertRaises(CredentialUseError):
            self.host.dispatch(
                self.case.owner,
                {"op": "action_profile_set", "profile_id": str(uuid4())},
            )
        with patch("app.credentials.host_service.private_acl"):
            self.assertEqual(
                self.host.dispatch(
                    self.case.owner, {"op": "action_profile_set", "profile_id": None}
                ),
                {"profile_id": None},
            )


class NativePolicyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows security descriptor conversion")
    def test_scratch_has_inheritable_low_label_and_snapshot_does_not(self):
        import win32security

        security = Mock(wraps=win32security)
        for name in (
            "DACL_SECURITY_INFORMATION",
            "PROTECTED_DACL_SECURITY_INFORMATION",
            "OWNER_SECURITY_INFORMATION",
        ):
            setattr(security, name, getattr(win32security, name))
        security.SetFileSecurity = Mock()
        with patch(
            "app.credentials.windows_host.api",
            return_value=(None, None, None, None, security),
        ):
            private_acl(Path("synthetic-scratch"), "S-1-15-2-111", writable=True)
            _, flags, descriptor = security.SetFileSecurity.call_args.args
            self.assertTrue(flags & 0x10)
            label = descriptor.GetSecurityDescriptorSacl().GetAce(0)
            self.assertEqual(label[0], (0x11, 3))
            self.assertEqual(
                win32security.ConvertSidToStringSid(label[-1]), "S-1-16-4096"
            )
            self.assertEqual(
                win32security.ConvertSidToStringSid(
                    descriptor.GetSecurityDescriptorOwner()
                ),
                "S-1-5-18",
            )
            self.assertTrue(descriptor.GetSecurityDescriptorControl()[0] & 0x1000)
            private_acl(Path("synthetic-snapshot"), "S-1-15-2-111")
            _, flags, descriptor = security.SetFileSecurity.call_args.args
            self.assertFalse(flags & 0x10)
            self.assertIsNone(descriptor.GetSecurityDescriptorSacl())

    @unittest.skipUnless(os.name == "nt", "Windows .NET compiler")
    def test_real_native_envelope_accepts_maximum_frame_expansion_before_worker(self):
        compiler = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        )
        if not compiler.exists():
            self.skipTest(".NET Framework compiler unavailable")
        source = ROOT / "app/credentials/native/CredentialHost.cs"
        harness = r"""using System; using System.IO; using System.Text; using System.Reflection; using System.Web.Script.Serialization;
class TransportProbe {
 static void Main() {
  var json=new JavaScriptSerializer { MaxJsonLength=65536, RecursionLimit=16 };
  var envelope=typeof(CredentialHost).GetMethod("Envelope",BindingFlags.Static|BindingFlags.NonPublic);
  foreach(string value in new[]{new string('x',65500),new string('\u00e9',32000)}) {
   string input="{\"op\":\"unknown\",\"padding\":\""+value+"\"}";
   if(Encoding.UTF8.GetByteCount(input)>65536) throw new Exception("bad fixture");
   object payload=json.DeserializeObject(input);
   string result=(string)envelope.Invoke(null,new object[]{(uint)42,(long)123,"S-1-5-21-111-222-333-1001","S-1-15-2-111",payload});
   if(result.Length<=65536 || result.Length>400000) throw new Exception("bad expansion");
   foreach(char ch in result) if(ch>127) throw new Exception("not ascii");
   new JavaScriptSerializer {MaxJsonLength=400000,RecursionLimit=20}.DeserializeObject(result);
  }
  var frame=typeof(CredentialHost).GetMethod("ReadFrame",BindingFlags.Static|BindingFlags.NonPublic);
  using(var stream=new MemoryStream()) {
   byte[] size=BitConverter.GetBytes(65537); stream.Write(size,0,4); stream.Position=0;
   try {frame.Invoke(null,new object[]{stream,65536});throw new Exception("oversize accepted");}
   catch(TargetInvocationException e) {if(!(e.InnerException is IOException)) throw;}
  }
  Console.WriteLine("native envelope/frame checks passed");
 }
}"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            probe = path / "TransportProbe.cs"
            exe = path / "probe.exe"
            probe.write_text(harness)
            result = subprocess.run(
                [
                    str(compiler),
                    "/nologo",
                    "/main:TransportProbe",
                    "/out:" + str(exe),
                    "/r:System.ServiceProcess.dll",
                    "/r:System.Windows.Forms.dll",
                    "/r:System.Drawing.dll",
                    "/r:System.Web.Extensions.dll",
                    str(source),
                    str(probe),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(
                [str(exe)], capture_output=True, text=True, timeout=15
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        code = source.read_text()
        self.assertLess(
            code.index("string envelope=Envelope(pid"),
            code.index("var current=Worker();"),
        )


def extracted_class(path, class_name, methods, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name
    )
    node.bases = []
    node.decorator_list = []
    node.body = [
        n
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in methods
    ]
    unit = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            node,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(unit), str(ROOT / path), "exec"), namespace)
    return namespace[class_name]


class ConsumerEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_app_result_channels_remain_project_scoped(self):
        web = SimpleNamespace(
            json_response=lambda body, status=200: SimpleNamespace(
                body=body, status=status
            )
        )
        cls = extracted_class(
            "app/agent_app/integration_bridge.py",
            "IntegrationBridge",
            {"_handle_credential_worker"},
            {"web": web, "time": time, "asyncio": asyncio},
        )
        bridge = cls()
        bridge._validate_token = lambda _: "project-a"
        bridge._credential_runs = {"run": ("project-a", time.monotonic() + 900)}
        for operation in ("program_result", "response"):
            data = {"operation": operation, "run_id": "run"}
            if operation == "response":
                data["offset"] = 0
            incoming = SimpleNamespace(json=AsyncMock(return_value=data))
            with patch(
                "app.credentials.client.request", return_value={"synthetic": "value"}
            ) as host:
                result = await bridge._handle_credential_worker(incoming)
                self.assertEqual(result.status, 200)
                host.assert_called_once_with(
                    operation, **{k: v for k, v in data.items() if k != "operation"}
                )
                bridge._validate_token = lambda _: "other-project"
                host.reset_mock()
                self.assertEqual(
                    (await bridge._handle_credential_worker(incoming)).status, 403
                )
                host.assert_not_called()
                bridge._validate_token = lambda _: "project-a"

    async def test_executor_uses_owner_resolver_and_ignores_action_claimed_profile(
        self,
    ):
        cls = extracted_class(
            "agent_core/core/impl/action/executor.py",
            "ActionExecutor",
            {"__init__", "execute_atomic_action"},
            {
                "asyncio": asyncio,
                "Optional": Optional,
                "Dict": Dict,
                "Any": Any,
                "DEFAULT_ACTION_TIMEOUT": 60,
                "logger": Mock(),
            },
        )
        selected = str(uuid4())
        resolver = Mock(return_value=selected)
        action = SimpleNamespace(
            execution_mode="credential_isolated",
            requirements=[],
            name="synthetic",
            code="def action(data): return data",
            credential_profile_id=str(uuid4()),
        )
        with patch(
            "app.credentials.consumer_runtime.execute_action", new_callable=AsyncMock
        ) as execute:
            execute.return_value = {"status": "success"}
            executor = cls(credential_profile_resolver=resolver)
            await executor.execute_atomic_action(
                action, {"profile_id": "agent-selected"}
            )
            self.assertEqual(execute.call_args.kwargs["profile_id"], selected)
            resolver.assert_called_once()
            resolver.return_value = "invalid-profile"
            execute.reset_mock()
            result = await executor.execute_atomic_action(action, {})
            self.assertEqual(result["status"], "error")
            execute.assert_not_called()

    async def test_cli_accepts_reference_and_named_public_identifiers_only(self):
        from app.credentials.references import SourceReference

        ref = SourceReference(uuid4(), uuid4(), 1).encode()
        source_helper = SimpleNamespace(
            system_connect_token=Mock(return_value=(True, "connected"))
        )
        namespace = {
            "List": List,
            "CommandResult": lambda **kw: SimpleNamespace(**kw),
            "get_integration_auth_type": lambda _: "token",
            "make_error": Mock(),
        }
        cls = extracted_class(
            "app/ui_layer/commands/builtin/integrations.py",
            "IntegrationCommand",
            {"_connect", "_connect_shared"},
            namespace,
        )
        command = cls()
        command._integration_name = "lark"
        command._system = Mock(return_value=object())
        with patch.dict(
            "sys.modules", {"app.data.action.integrations._helpers": source_helper}
        ):
            response = await command._connect([ref, "app_id=public-app"])
            self.assertTrue(response.success)
            self.assertEqual(
                source_helper.system_connect_token.call_args.args[-1],
                {"source_reference": ref, "app_id": "public-app"},
            )
            source_helper.system_connect_token.reset_mock()
            for args in (
                ["raw-secret"],
                [ref, "app_secret=raw-secret"],
                [ref, "public-app"],
                [ref, "app_id=a", "app_id=b"],
            ):
                response = await command._connect(args)
                self.assertFalse(response.success)
                self.assertNotIn("raw-secret", response.message)
            response = await command._connect([])
            self.assertIn("craftbot-vault://", response.message)
            self.assertNotIn("API Secret", response.message)
            source_helper.system_connect_token.assert_not_called()
            for provider in ("twitter", "telegram_user"):
                command._integration_name = provider
                response = await command._connect([ref, "access_token=secret"])
                self.assertFalse(response.success)
                self.assertIn("Settings", response.message)
            namespace["get_integration_auth_type"] = lambda _: "both"
            command._integration_name = "google"
            system = SimpleNamespace(
                add_account=AsyncMock(return_value=(True, "oauth", []))
            )
            command._system = lambda: system
            self.assertTrue((await command._connect_shared([])).success)
            system.add_account.assert_awaited_once_with("google")
