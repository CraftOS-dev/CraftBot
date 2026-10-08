"""Real Windows shell regressions, runnable with only the Python standard library.

Run: python -m unittest discover -s tests/windows_shell -v
Like the action registry, load the function's source without its decorator.
Only unrelated Node PATH setup and cancellation registration are stubbed;
commands execute through the production launcher using real OS processes.
"""

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "app/data/action/run_shell.py"


def load_action():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "shell_exec_windows"
    )
    metadata = {
        keyword.arg: ast.literal_eval(keyword.value)
        for keyword in function.decorator_list[0].keywords
    }
    function.decorator_list = []
    namespace = {}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"),
        namespace,
    )
    return namespace["shell_exec_windows"], metadata


class ShellGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.run_shell, self.metadata = load_action()

    def test_schema_teaches_raw_powershell(self):
        self.assertIn(
            "Raw source", self.metadata["input_schema"]["command"]["description"]
        )
        self.assertEqual(
            self.metadata["input_schema"]["shell"]["example"], "powershell"
        )
        self.assertIn(
            "Get-CimInstance", self.metadata["input_schema"]["command"]["example"]
        )
        self.assertIn("guidance", self.metadata["output_schema"])

    def test_invalid_shell_does_not_launch(self):
        with patch("subprocess.Popen") as spawn:
            result = self.run_shell({"command": "echo x", "shell": "bash"})
        spawn.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["shell"], "bash")
        self.assertIsNone(result["shell_executable"])

    def test_empty_command_reports_default_without_launch(self):
        result = self.run_shell({"command": "", "shell": "auto"})
        self.assertEqual(result["shell"], "cmd")
        self.assertIsNone(result["shell_executable"])
        self.assertEqual(result["message"], "command is required.")


@unittest.skipUnless(sys.platform == "win32", "Requires real Windows interpreters")
class WindowsShellTests(unittest.TestCase):
    def setUp(self):
        self.run_shell, self.metadata = load_action()
        app = types.ModuleType("app")
        app.node_runtime = types.SimpleNamespace(child_env=lambda: os.environ.copy())
        self.cancellation = types.ModuleType("agent_core.core.impl.action.cancellation")
        self.cancellation.register_process = Mock()
        self.cancellation.unregister_process = Mock()
        modules = patch.dict(
            sys.modules,
            {"app": app, self.cancellation.__name__: self.cancellation},
        )
        modules.start()
        self.addCleanup(modules.stop)

    def execute(self, command, shell="powershell", **kwargs):
        if not shutil.which(shell + ".exe"):
            self.skipTest(shell + " is unavailable")
        return self.run_shell(
            {"command": command, "shell": shell, "timeout": 15, **kwargs}
        )

    def assert_output(self, result, expected):
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["return_code"], 0, result)
        self.assertEqual(result["stdout"].replace("\r\n", "\n"), expected)

    def test_direct_scripts_preserve_semantics(self):
        cases = [
            ("Write-Output 'hello world'", "hello world"),
            ('Write-Output "hello world"', "hello world"),
            ("$n=2; 1..$n | ForEach-Object { $_ * 2 }", "2\n4"),
            ("$n=2\nWrite-Output $n", "2"),
            (
                '[pscustomobject]@{"Free (GB)"=2} | ConvertTo-Json -Compress',
                '{"Free (GB)":2}',
            ),
            ("Write-Output 'a\\\"b'", 'a\\"b'),
            (
                'Write-Output "a&b|c(d)%CRAFTBOT_QUOTE_REPRO%"',
                "a&b|c(d)%CRAFTBOT_QUOTE_REPRO%",
            ),
        ]
        for shell in ("powershell", "pwsh"):
            if not shutil.which(shell + ".exe"):
                continue
            for command, expected in cases:
                with self.subTest(shell=shell, command=command):
                    result = self.execute(command, shell)
                    self.assert_output(result, expected)
                    self.assertEqual(result["guidance"], "")
                    self.assertEqual(result["shell"], shell)
                    self.assertEqual(
                        result["shell_executable"], shutil.which(shell + ".exe")
                    )

    def test_disk_query_with_parenthesized_calculated_property(self):
        result = self.execute(
            "@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
            'Select-Object @{Name="Free (GB)";Expression={[math]::Round($_.FreeSpace/1GB,2)}}) '
            "| ConvertTo-Json -Compress"
        )
        self.assertEqual(result["status"], "success", result)
        disks = json.loads(result["stdout"])
        self.assertGreater(len(disks), 0)
        self.assertTrue(
            all(isinstance(disk["Free (GB)"], (int, float)) for disk in disks)
        )

    def test_nested_variables_fail_with_actionable_guidance(self):
        result = self.execute('powershell -NoProfile -Command "$n=2; Write-Output $n"')
        self.assertEqual(result["status"], "error", result)
        self.assertIn("=2", result["stderr"])
        self.assertIn("raw script", result["guidance"])
        self.assertEqual(self.cancellation.register_process.call_count, 1)
        self.assertEqual(self.cancellation.unregister_process.call_count, 1)
        self.assert_output(self.execute("$n=2; Write-Output $n"), "2")

    def test_single_quote_wrapper_silent_wrong_output_is_flagged(self):
        result = self.execute(
            "powershell -NoProfile -Command 'Write-Output \"hello world\"'", "cmd"
        )
        self.assert_output(result, "Write-Output hello world")
        self.assertIn("even with exit code 0", result["guidance"])
        self.assert_output(self.execute("Write-Output 'hello world'"), "hello world")

    def test_cmd_percent_expansion_is_flagged_and_raw_script_preserves_literal(self):
        env = {"CRAFTBOT_QUOTE_REPRO": "expanded-by-cmd"}
        result = self.execute(
            "powershell -NoProfile -Command \"Write-Output '%CRAFTBOT_QUOTE_REPRO%'\"",
            "cmd",
            env=env,
        )
        self.assert_output(result, "expanded-by-cmd")
        self.assertIn("expand variables", result["guidance"])
        self.assert_output(
            self.execute("Write-Output '%CRAFTBOT_QUOTE_REPRO%'", env=env),
            "%CRAFTBOT_QUOTE_REPRO%",
        )

    def test_intentional_nested_wrapper_still_executes_once(self):
        result = self.execute(
            "cmd /c powershell -NoProfile -Command \"Write-Output 'ok'\"", "cmd"
        )
        self.assert_output(result, "ok")
        self.assertIn("intentional", result["guidance"])
        self.assertEqual(self.cancellation.register_process.call_count, 1)

    def test_parser_failure_preserves_native_error(self):
        result = self.execute("$x = (")
        self.assertEqual(result["status"], "error", result)
        self.assertNotEqual(result["return_code"], 0)
        self.assertTrue(result["stderr"])
        self.assertEqual(result["guidance"], "")
        self.assertEqual(self.cancellation.register_process.call_count, 1)

    def test_application_error_text_is_not_classified_as_a_parser_failure(self):
        stderr = "UnexpectedToken: application-defined failure"
        result = self.execute(f"[Console]::Error.WriteLine('{stderr}'); exit 7")
        self.assertEqual(result["return_code"], 7)
        self.assertEqual(result["stderr"], stderr)
        self.assertEqual(result["guidance"], "")

    def test_successful_stderr_does_not_imply_failure(self):
        result = self.execute(
            "[Console]::Error.WriteLine('warning'); Write-Output 'ok'"
        )
        self.assert_output(result, "ok")
        self.assertEqual(result["stderr"], "warning")
        self.assertEqual(result["guidance"], "")

    def test_cmd_default_auto_and_explicit_remain_compatible(self):
        for choice in (None, "auto", "cmd"):
            with self.subTest(shell=choice):
                payload = {"command": "echo cmd-compatible", "timeout": 15}
                if choice:
                    payload["shell"] = choice
                result = self.run_shell(payload)
                self.assert_output(result, "cmd-compatible")
                self.assertEqual(result["shell"], "cmd")
                self.assertEqual(result["guidance"], "")

    def test_cmd_quoted_executable_path(self):
        result = self.execute(f'"{sys.executable}" -c "print(123)"', "cmd")
        self.assert_output(result, "123")

    def test_mentions_inside_script_do_not_trigger_wrapper_advice(self):
        result = self.execute("Write-Output 'powershell -Command example'")
        self.assert_output(result, "powershell -Command example")
        self.assertEqual(result["guidance"], "")

    def test_timeout_unregisters_process(self):
        result = self.execute("Start-Sleep -Seconds 10", timeout=1)
        self.assertEqual(result["status"], "error")
        self.assertIn("Timed out", result["message"])
        process = self.cancellation.register_process.call_args.args[1]
        self.assertIsNotNone(process.poll())
        self.cancellation.unregister_process.assert_called_once_with("", process)

    def test_background_returns_pid_and_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "done.txt"
            escaped = str(marker).replace("'", "''")
            processes = []
            real_popen = subprocess.Popen

            def track_process(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process

            with patch("subprocess.Popen", side_effect=track_process):
                result = self.execute(
                    f"Start-Sleep -Milliseconds 300; [IO.File]::WriteAllText('{escaped}', 'done')",
                    background=True,
                )
            self.assertEqual(result["status"], "background", result)
            self.assertGreater(result["pid"], 0)
            try:
                deadline = time.monotonic() + 15
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(marker.read_text(), "done")
            finally:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(result["pid"])],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                processes[0].wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
