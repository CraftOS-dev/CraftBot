"""Bootstrap tests deliberately run without the application's pytest fixtures.

Run: python -m unittest discover -s tests/install_bootstrap -v
No application dependencies or credentials are needed.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import downloads, node_runtime
from app.provision import default_stages
from app.provision.pipeline import run
from app.provision import proc
from app.provision.types import Context, StageResult, Status


class Response(io.BytesIO):
    def getheader(self, name):
        return str(len(self.getvalue()))


class BootstrapTests(unittest.TestCase):
    def test_failed_windows_stop_keeps_pid_record_and_fails(self):
        import craftbot

        with (
            patch.object(craftbot, "_PLATFORM", "win32"),
            patch.object(craftbot, "_read_pid_record", return_value={"pid": 123}),
            patch.object(craftbot, "_owned_pid", return_value=123),
            patch.object(craftbot, "_remove_pid") as remove,
            patch(
                "app.process_ledger.kill_tree",
                side_effect=RuntimeError("still running"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "still running"):
                craftbot.cmd_stop()
            remove.assert_not_called()

    def test_failed_orphan_stop_is_reported(self):
        import craftbot

        with (
            patch.object(
                craftbot, "_orphan_listeners", return_value=[(123, "owned CraftBot")]
            ),
            patch(
                "app.process_ledger.kill_tree",
                side_effect=RuntimeError("access denied"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "orphaned CraftBot pids: 123"):
                craftbot._stop_orphan_listeners()

    def test_agent_child_can_find_private_npx_without_system_node(self):
        import run as launcher

        private_bin = self.root / "private-node"
        private_bin.mkdir()
        npx = private_bin / ("npx.cmd" if sys.platform == "win32" else "npx")
        npx.write_text("", encoding="utf-8")
        npx.chmod(0o755)
        observed = self.root / "child-env.json"
        script = self.root / "main.py"
        script.write_text(
            "import json, os, shutil\n"
            f"with open({str(observed)!r}, 'w') as output:\n"
            "    json.dump({'npx': shutil.which('npx'), 'node': os.getenv('CRAFTBOT_NODE')}, output)\n",
            encoding="utf-8",
        )
        runtime = SimpleNamespace(
            node=str(private_bin / "node"), bin_dir=str(private_bin)
        )
        with (
            patch.dict(os.environ, {"PATH": ""}),
            patch.object(launcher, "MAIN_APP_SCRIPT", str(script)),
            patch.object(launcher, "_background_processes", []),
            patch.object(launcher, "_record_launched"),
            patch.object(
                launcher.python_runtime, "resolve", return_value=sys.executable
            ),
            patch.object(launcher.node_runtime, "resolve", return_value=runtime),
        ):
            child = launcher.launch_agent_background(None, False, silent=True)
            self.assertIsNotNone(child)
            self.assertEqual(child.wait(timeout=15), 0)
        self.assertEqual(Path(json.loads(observed.read_text())["npx"]), npx)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"CRAFTBOT_DOWNLOAD_CACHE": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ctx = Context(str(self.root), str(self.root))

    def test_subprocess_output_handles_unicode_and_bad_bytes(self):
        result = proc.run(
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.buffer.write(bytes.fromhex('e69687e4bbb6ff'))",
            ],
            echo=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "\u6587\u4ef6\ufffd")

    def test_unix_npm_scripts_work_with_no_shell_on_path(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.platform", "linux"),
            patch.object(node_runtime, "resolve", return_value=None),
            patch.object(
                node_runtime, "path_env", return_value={"PATH": str(self.root)}
            ),
        ):
            self.assertEqual(
                node_runtime.child_env()["npm_config_script_shell"], "/bin/sh"
            )
            self.assertEqual(
                node_runtime.child_env({"npm_config_script_shell": "/custom/sh"})[
                    "npm_config_script_shell"
                ],
                "/custom/sh",
            )

    def test_verified_download_publishes_and_caches(self):
        cache = self.root / "cache"
        cache.mkdir()
        data = b"complete runtime"
        dest = self.root / "runtime"
        digest = hashlib.sha256(data).hexdigest()
        with (
            patch.dict(os.environ, {"CRAFTBOT_DOWNLOAD_CACHE": str(cache)}),
            patch("urllib.request.urlopen", return_value=Response(data)),
        ):
            downloads.download(
                "https://example.test/runtime.zip", str(dest), expected_sha256=digest
            )
        self.assertEqual(dest.read_bytes(), data)
        self.assertEqual((cache / "runtime.zip").read_bytes(), data)
        self.assertEqual(list(self.root.glob("*.part")), [])

    def test_bad_checksum_preserves_existing_destination(self):
        dest = self.root / "runtime"
        dest.write_bytes(b"previous good download")
        with (
            patch("urllib.request.urlopen", return_value=Response(b"corrupt")),
            self.assertRaisesRegex(ValueError, "SHA-256"),
        ):
            downloads.download(
                "https://example.test/runtime.zip", str(dest), expected_sha256="0" * 64
            )
        self.assertEqual(dest.read_bytes(), b"previous good download")
        self.assertEqual(list(self.root.glob("*.part")), [])

    def test_offline_verified_cache_and_corrupt_cache(self):
        cache = self.root / "cache"
        cache.mkdir()
        source = cache / "runtime.zip"
        source.write_bytes(b"good")
        dest = self.root / "runtime"
        digest = hashlib.sha256(b"good").hexdigest()
        with (
            patch.dict(os.environ, {"CRAFTBOT_DOWNLOAD_CACHE": str(cache)}),
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("network forbidden"),
            ),
        ):
            downloads.download(
                "https://example.test/runtime.zip",
                str(dest),
                expected_sha256=digest,
                offline=True,
            )
            source.write_bytes(b"bad")
            with self.assertRaisesRegex(OSError, "Offline"):
                downloads.download(
                    "https://example.test/runtime.zip",
                    str(dest),
                    expected_sha256=digest,
                    offline=True,
                )
        self.assertEqual(dest.read_bytes(), b"good")

    def test_bad_cache_is_replaced_from_network(self):
        cache = self.root / "cache"
        cache.mkdir()
        (cache / "runtime.zip").write_bytes(b"bad")
        with (
            patch.dict(os.environ, {"CRAFTBOT_DOWNLOAD_CACHE": str(cache)}),
            patch("urllib.request.urlopen", return_value=Response(b"good")),
        ):
            downloads.download(
                "https://example.test/runtime.zip",
                str(self.root / "out"),
                expected_sha256=hashlib.sha256(b"good").hexdigest(),
            )
        self.assertEqual((cache / "runtime.zip").read_bytes(), b"good")

    def test_interrupted_download_retries(self):
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[OSError("connection reset"), Response(b"ok")],
            ) as request,
            patch("time.sleep"),
        ):
            downloads.download("https://example.test/file", str(self.root / "out"))
        self.assertEqual(request.call_count, 2)
        self.assertEqual((self.root / "out").read_bytes(), b"ok")

    def test_truncated_response_never_published(self):
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=lambda *a, **k: ResponseWithWrongLength(),
            ),
            patch("time.sleep"),
            self.assertRaisesRegex(OSError, "incomplete"),
        ):
            downloads.download("https://example.test/file", str(self.root / "out"))
        self.assertFalse((self.root / "out").exists())

    def test_node_without_npm_is_not_usable(self):
        rt = node_runtime.NodeRuntime("node", None, "bin", "v24.19.0", "path")
        with patch.object(node_runtime, "npm_command", return_value=None):
            self.assertFalse(node_runtime.usable(rt))

    def test_broken_node_triggers_sidecar_repair(self):
        rt = node_runtime.NodeRuntime("node", None, "bin", "v24.19.0", "path")
        with (
            patch.object(node_runtime, "resolve", return_value=rt),
            patch.object(node_runtime, "usable", return_value=False),
            patch.object(node_runtime, "download_sidecar", return_value=None) as fetch,
        ):
            self.assertIsNone(node_runtime.ensure_sidecar())
            fetch.assert_called_once()

    def test_required_failure_stops_and_is_reported_from_metadata(self):
        class Required:
            name, description, optional = "new-runtime", "Runtime", False

            def check(self, ctx):
                return StageResult(Status.MISSING)

            def apply(self, ctx, log):
                return StageResult(Status.FAILED, "network failed")

        class Never(Required):
            def check(self, ctx):
                raise AssertionError("must not run")

        report = run([Required(), Never()], self.ctx)
        self.assertEqual(
            [name for name, _ in report.required_failures], ["new-runtime"]
        )
        self.assertEqual(len(report.results), 1)

    def test_optional_failure_does_not_prevent_required_stage(self):
        class Optional:
            name, description, optional = "optional", "Optional", True

            def check(self, ctx):
                return StageResult(Status.MISSING)

            def apply(self, ctx, log):
                return StageResult(Status.FAILED)

        class Required(Optional):
            name, optional = "required", False

            def check(self, ctx):
                return StageResult(Status.SATISFIED)

        report = run([Optional(), Required()], self.ctx)
        self.assertFalse(report.ok)
        self.assertEqual(report.required_failures, [])
        self.assertEqual(len(report.results), 2)

    def test_install_order_covers_agent_apps(self):
        stages = default_stages()
        names = [stage.name for stage in stages]
        self.assertLess(names.index("node"), names.index("agent-app-framework"))
        for stage in stages:
            if stage.name in ("pip", "node", "agent-app-framework"):
                self.assertFalse(stage.optional)


class ResponseWithWrongLength(Response):
    def __init__(self):
        super().__init__(b"short")

    def getheader(self, name):
        return "100"


if __name__ == "__main__":
    unittest.main()
