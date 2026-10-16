"""Policy tests plus real, non-elevated Windows peer/pipe primitives.

SYSTEM deployment, secure desktop interaction and an actual AppContainer child
require the explicitly installed acceptance runner; these tests do not fake a
successful production deployment.
"""

import os
from pathlib import Path
import tempfile
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from app.credentials.client import CredentialHostUnavailable
from app.credentials.contracts import IsolationUnavailable
from app.credentials.host_service import ProtectedHost, source_files, resolve_envelope
from app.credentials.use_errors import CredentialUseError, UseCode
from app.credentials.windows_host import Peer, check_install


class SnapshotTests(unittest.TestCase):
    def test_hash_pins_names_contents_and_entry_must_exist(self):
        files = {"main.py": "print('synthetic')", "lib/helper.py": "value = 1"}
        first = source_files(files, "main.py")
        self.assertEqual(
            first, source_files(dict(reversed(list(files.items()))), "main.py")
        )
        self.assertNotEqual(
            first, source_files({**files, "main.py": "print('changed')"}, "main.py")
        )
        self.assertNotEqual(
            first, source_files({"other.py": files["main.py"]}, "other.py")
        )
        with self.assertRaises(CredentialUseError):
            source_files(files, "missing.py")
        self.assertNotEqual(
            source_files(files, "main.py"), source_files(files, "lib/helper.py")
        )

    def test_windows_path_aliases_links_and_reserved_files_cannot_escape_snapshot(self):
        for name in (
            "../main.py",
            "C:/main.py",
            "/main.py",
            "a\\main.py",
            "a//b.py",
            "./main.py",
            "NUL.py",
            "a/COM1.py",
            "a./main.py",
            "file:stream.py",
            "credential_client.py",
            "CREDENTIAL_CLIENT.PY",
            "_host_entry.py",
            "_host_entry.py/x.py",
        ):
            with self.subTest(name=name), self.assertRaises(CredentialUseError):
                source_files({name: "value=1"}, name)
        for files in ({"a.py": "", "A.py": ""}, {"a.py": "", "a.py/b.py": ""}):
            with self.assertRaises(CredentialUseError):
                source_files(files, "a.py")
        with self.assertRaises(CredentialUseError):
            source_files({"main.py": "x" * 48001}, "main.py")


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile_id = str(uuid4())
        configuration = {
            "owner_id": str(uuid4()),
            "owner_sid": "S-1-5-21-111-222-333-1001",
            "profiles": [{"id": self.profile_id, "label": "Work"}],
        }
        self.host = ProtectedHost(self.root, self.root, configuration)
        self.owner = SimpleNamespace(
            pid=42,
            sid=configuration["owner_sid"],
            container=False,
            elevated=False,
            session=7,
            alive=lambda: True,
        )

    def tearDown(self):
        for vault in self.host.vaults.values():
            vault.close()
        self.temp.cleanup()

    def test_raw_read_owner_approval_and_context_claims_are_not_public_operations(self):
        for request in (
            {"op": "read_secret"},
            {"op": "approve", "grant_id": str(uuid4())},
            {"op": "status", "isolated": True},
            {"op": "use", "peer_pid": 42},
            {"op": "status", "owner_authenticated": True},
        ):
            with self.assertRaises(CredentialUseError) as caught:
                self.host.dispatch(self.owner, request)
            self.assertEqual(caught.exception.code, UseCode.ISOLATION)

    def test_other_os_users_elevated_callers_and_appcontainers_cannot_manage(self):
        for field, value in (
            ("sid", "S-1-5-21-999"),
            ("container", True),
            ("elevated", True),
        ):
            peer = SimpleNamespace(**vars(self.owner))
            setattr(peer, field, value)
            with self.assertRaises(CredentialUseError) as caught:
                self.host.dispatch(peer, {"op": "profiles"})
            self.assertEqual(caught.exception.code, UseCode.DENIED)

    def test_owner_transport_lists_only_metadata_and_rejects_secret_fields(self):
        result = self.host.dispatch(self.owner, {"op": "profiles"})
        self.assertEqual(
            result, [{"id": self.profile_id, "label": "Work", "state": "locked"}]
        )
        self.assertNotIn(self.owner.sid, repr(result))
        consent = Mock()
        self.host.consent = consent
        with self.assertRaises(CredentialUseError):
            self.host.dispatch(
                self.owner,
                {
                    "op": "entry",
                    "profile_id": self.profile_id,
                    "password": "synthetic-injected-value",
                },
            )
        consent.entry.assert_not_called()

    def test_native_owner_decline_cannot_launch_any_consumer(self):
        self.host.consent = Mock()
        self.host.consent.verify.side_effect = PermissionError("synthetic refusal")
        with patch("app.credentials.host_service.IsolatedProcess") as launch:
            with self.assertRaises(CredentialUseError):
                self.host.dispatch(
                    self.owner,
                    {
                        "op": "launch",
                        "profile_id": self.profile_id,
                        "kind": "agent_app",
                        "subject": "project-a",
                        "deployment": "live",
                        "files": {"main.py": "pass"},
                        "entry": "main.py",
                    },
                )
            launch.assert_not_called()
        self.assertEqual(self.host.leases, {})

    def test_unknown_os_process_never_gains_an_existing_launch_binding(self):
        unknown = SimpleNamespace(**vars(self.owner))
        unknown.container = True
        unknown.app_sid = "S-1-15-2-1"
        with self.assertRaises(CredentialUseError) as caught:
            self.host.dispatch(unknown, {"op": "status"})
        self.assertEqual(caught.exception.code, UseCode.ISOLATION)

    def test_kernel_creation_stamp_and_live_handle_prevent_pid_recycling(self):
        original = {
            "peer_pid": 42,
            "peer_created": "12345",
            "peer_sid": "S-1-5-21-111-222-333-1001",
            "peer_app_sid": None,
            "payload": {"op": "status"},
        }
        for stamp, alive in ((99999, True), (12345, False)):
            peer = SimpleNamespace(created=stamp, alive=lambda: alive, close=Mock())
            with patch("app.credentials.host_service.Peer", return_value=peer):
                with self.assertRaises(CredentialUseError):
                    resolve_envelope(original)
            peer.close.assert_called_once()
        with self.assertRaises(CredentialUseError):
            resolve_envelope({**original, "isolated": True})
        peer = SimpleNamespace(
            created=12345,
            alive=lambda: True,
            close=Mock(),
            sid=original["peer_sid"],
            app_sid="S-1-15-2-999",
        )
        with patch("app.credentials.host_service.Peer", return_value=peer):
            with self.assertRaises(CredentialUseError):
                resolve_envelope(original)
        peer.close.assert_called_once()

        peer = SimpleNamespace(
            created=12345,
            alive=lambda: True,
            close=Mock(),
            sid=original["peer_sid"],
            app_sid=None,
        )
        with patch("app.credentials.host_service.Peer", return_value=peer):
            self.assertIs(resolve_envelope(original), peer)
        peer.close.assert_not_called()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_action_uses_host_only_and_stops_its_run_after_completion(self):
        from app.credentials.consumer_runtime import execute_action

        calls = []

        def host(op, **parameters):
            calls.append((op, parameters))
            return (
                {"run_id": "synthetic-run"}
                if op == "launch"
                else {"result": {"status": "success"}}
            )

        with patch("app.credentials.consumer_runtime.request", side_effect=host):
            result = await execute_action(
                "def action(data): return data",
                {"message": "test"},
                profile_id=str(uuid4()),
                subject="synthetic-action",
                timeout=10,
            )
        self.assertEqual(result, {"status": "success"})
        self.assertEqual([op for op, _ in calls], ["launch", "program_result", "stop"])
        self.assertEqual(calls[0][1]["kind"], "agent_session")
        self.assertNotIn("bridge_token", calls[0][1])
        compile(calls[0][1]["files"]["action.py"], "isolated-action", "exec")

    async def test_unavailable_host_never_falls_back_to_inprocess_execution(self):
        from app.credentials.consumer_runtime import execute_action

        with patch(
            "app.credentials.consumer_runtime.request",
            side_effect=CredentialHostUnavailable("credential_host_unavailable"),
        ):
            with self.assertRaises(CredentialHostUnavailable):
                await execute_action(
                    "raise AssertionError('must not run')",
                    {},
                    profile_id=str(uuid4()),
                    subject="test",
                    timeout=1,
                )


@unittest.skipUnless(os.name == "nt", "Windows kernel test")
class WindowsKernelTests(unittest.TestCase):
    def test_real_peer_is_not_an_appcontainer_and_cannot_boot_a_system_host(self):
        peer = Peer(os.getpid())
        try:
            self.assertTrue(peer.alive())
            if peer.sid == "S-1-5-18":
                self.skipTest(
                    "This check intentionally requires a non-SYSTEM test runner"
                )
            self.assertFalse(peer.container)
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(IsolationUnavailable):
                    check_install(Path(directory), Path(directory))
        finally:
            peer.close()

    def test_real_squatting_pipe_cannot_receive_even_metadata_or_capabilities(self):
        import win32file
        import win32pipe
        from app.credentials import client

        name = r"\\.\pipe\LOCAL\CraftBot.Test." + uuid4().hex
        pipe = win32pipe.CreateNamedPipe(name, 3 | 0x80000, 8, 1, 4096, 4096, 0, None)
        received = []
        errors = []

        def server():
            try:
                win32pipe.ConnectNamedPipe(pipe, None)
                try:
                    received.append(win32file.ReadFile(pipe, 4096)[1])
                except Exception:
                    pass  # Client must disconnect before sending any data.
            except Exception as error:
                errors.append(type(error).__name__)

        thread = Thread(target=server, daemon=True)
        thread.start()
        try:
            with patch.object(client, "PIPE", name):
                with self.assertRaises(CredentialHostUnavailable) as caught:
                    client.request("use", capability="seeded-not-a-real-capability")
            self.assertEqual(str(caught.exception), "credential_host_identity_mismatch")
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertFalse(any(received))
        finally:
            pipe.Close()
