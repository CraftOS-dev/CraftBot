"""Real Windows shell regressions, runnable with only the Python standard library.

Run: python -m unittest discover -s tests/windows_shell -v
Like the action registry, load each function's source without its decorator.
Only unrelated Node PATH setup and cancellation registration are stubbed;
commands execute through the production launchers using real OS processes.
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
ACTIONS = ROOT / "app/data/action"
HERE = Path(__file__).resolve().parent


def load_action(file_name, function_name):
    source = ACTIONS / file_name
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    metadata = {
        keyword.arg: ast.literal_eval(keyword.value)
        for keyword in function.decorator_list[0].keywords
    }
    function.decorator_list = []
    namespace = {}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace[function_name], metadata


def load_actions(test):
    test.run_shell, test.shell_metadata = load_action(
        "run_shell.py", "shell_exec_windows"
    )
    test.run_powershell, test.powershell_metadata = load_action(
        "run_powershell.py", "powershell_exec_windows"
    )


class ShellSchemaTests(unittest.TestCase):
    def setUp(self):
        load_actions(self)

    def test_powershell_is_a_windows_only_action_that_takes_a_script(self):
        self.assertEqual(self.powershell_metadata["name"], "run_powershell")
        self.assertEqual(self.powershell_metadata["platforms"], ["windows"])
        params = list(self.powershell_metadata["input_schema"])
        # The interpreter is the action itself, so the model commits to it
        # before it writes any source, and there is no shell left to choose.
        self.assertEqual(params[0], "script")
        self.assertNotIn("command", params)
        self.assertNotIn("shell", params)

    def test_windows_run_shell_is_cmd_only(self):
        self.assertEqual(self.shell_metadata["platforms"], ["windows"])
        self.assertNotIn("shell", self.shell_metadata["input_schema"])
        self.assertIn("cmd.exe", self.shell_metadata["description"])
        self.assertIn("run_powershell", self.shell_metadata["description"])

    def test_results_carry_no_advice_fields(self):
        for metadata in (self.shell_metadata, self.powershell_metadata):
            self.assertEqual(
                sorted(metadata["output_schema"]),
                ["message", "pid", "return_code", "status", "stderr", "stdout"],
            )

    def test_empty_source_does_not_launch(self):
        cases = (
            (self.run_shell, {"command": ""}, "command is required."),
            (self.run_powershell, {"script": ""}, "script is required."),
        )
        for action, payload, message in cases:
            with self.subTest(message=message), patch("subprocess.Popen") as spawn:
                result = action(payload)
                spawn.assert_not_called()
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["message"], message)

    def test_non_cmd_shell_is_rejected_before_launch(self):
        app = types.ModuleType("app")
        child_env = Mock(return_value=os.environ.copy())
        app.node_runtime = types.SimpleNamespace(child_env=child_env)
        shells = ("powershell", "pwsh", "bash", "sh", "zsh", " PowerShell ", None)
        for shell in shells:
            for mode in ({}, {"background": True}, {"simulated_mode": True}):
                with (
                    self.subTest(shell=shell, mode=mode),
                    patch.dict(sys.modules, {"app": app}),
                    patch("subprocess.Popen") as spawn,
                    patch("subprocess.run") as run,
                ):
                    result = self.run_shell(
                        {"command": "echo should-not-run", "shell": shell, **mode}
                    )
                    self.assertEqual(result["status"], "error", result)
                    self.assertEqual(result["return_code"], -1, result)
                    self.assertEqual(result["stdout"], "")
                    self.assertEqual(result["stderr"], "")
                    self.assertIsNone(result["pid"])
                    self.assertIn("cmd.exe", result["message"])
                    self.assertIn("run_powershell", result["message"])
                    spawn.assert_not_called()
                    run.assert_not_called()
                    child_env.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Requires real Windows interpreters")
class WindowsShellTests(unittest.TestCase):
    def setUp(self):
        load_actions(self)
        app = types.ModuleType("app")
        app.node_runtime = types.SimpleNamespace(child_env=lambda: os.environ.copy())
        self.cancellation = types.ModuleType("agent_core.core.impl.action.cancellation")
        self.cancellation.register_process = Mock()
        self.cancellation.unregister_process = Mock()
        self.cancellation.was_killed = Mock(return_value=False)
        modules = patch.dict(
            sys.modules,
            {"app": app, self.cancellation.__name__: self.cancellation},
        )
        modules.start()
        self.addCleanup(modules.stop)

    def powershell(self, script, **kwargs):
        return self.run_powershell({"script": script, "timeout": 15, **kwargs})

    def cmd(self, command, **kwargs):
        return self.run_shell({"command": command, "timeout": 15, **kwargs})

    def assert_output(self, result, expected):
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["return_code"], 0, result)
        self.assertEqual(result["stdout"].replace("\r\n", "\n"), expected)

    # ── run_powershell ───────────────────────────────────────────────────

    def test_scripts_run_as_written(self):
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
        for script, expected in cases:
            with self.subTest(script=script):
                self.assert_output(self.powershell(script), expected)

    def test_disk_query_with_parenthesized_calculated_property(self):
        result = self.powershell(
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

    def test_largest_files_query_keeps_its_pipeline_variable(self):
        # The script a model wrote for "what is taking up my space?". Sent
        # inside a `powershell -Command "..."` wrapper it lost every `$_` to
        # the outer interpreter; as a script it runs as written.
        folder = str(HERE).replace("'", "''")
        result = self.powershell(
            f"Get-ChildItem '{folder}' -Recurse -File -ErrorAction SilentlyContinue | "
            "Sort Length -Descending | Select -First 1 Name, "
            "@{Name='SizeKB';Expression={[math]::round($_.Length/1KB,2)}} "
            "| ConvertTo-Json -Compress"
        )
        self.assertEqual(result["status"], "success", result)
        largest = json.loads(result["stdout"])
        self.assertTrue(largest["Name"])
        self.assertIsInstance(largest["SizeKB"], (int, float))

    def test_literal_percent_expression_is_not_expanded(self):
        result = self.powershell(
            "Write-Output '%CRAFTBOT_QUOTE_REPRO%'",
            env={"CRAFTBOT_QUOTE_REPRO": "expanded-by-cmd"},
        )
        self.assert_output(result, "%CRAFTBOT_QUOTE_REPRO%")

    def test_parser_failure_preserves_native_error(self):
        result = self.powershell("$x = (")
        self.assertEqual(result["status"], "error", result)
        self.assertNotEqual(result["return_code"], 0)
        self.assertTrue(result["stderr"])
        self.assertEqual(result["message"], "")

    def test_application_stderr_and_exit_code_pass_through(self):
        stderr = "UnexpectedToken: application-defined failure"
        result = self.powershell(f"[Console]::Error.WriteLine('{stderr}'); exit 7")
        self.assertEqual(result["return_code"], 7)
        self.assertEqual(result["stderr"], stderr)

    def test_successful_stderr_does_not_imply_failure(self):
        result = self.powershell(
            "[Console]::Error.WriteLine('warning'); Write-Output 'ok'"
        )
        self.assert_output(result, "ok")
        self.assertEqual(result["stderr"], "warning")

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
                result = self.powershell(
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

    # ── run_shell (cmd.exe) ──────────────────────────────────────────────

    def test_cmd_runs_command_lines(self):
        self.assert_output(self.cmd("echo cmd-compatible"), "cmd-compatible")
        self.assert_output(
            self.cmd("echo %CRAFTBOT_SHELL_TEST%", env={"CRAFTBOT_SHELL_TEST": "set"}),
            "set",
        )

    def test_legacy_cmd_selections_still_run(self):
        for shell in ("cmd", " CMD ", "auto", " AUTO ", "", "   "):
            with self.subTest(shell=shell):
                self.assert_output(
                    self.cmd("echo cmd-compatible", shell=shell), "cmd-compatible"
                )

    def test_legacy_powershell_selection_cannot_expand_cmd_variables(self):
        result = self.cmd(
            "echo %CRAFTBOT_SHELL_TEST%",
            shell="powershell",
            env={"CRAFTBOT_SHELL_TEST": "expanded-by-cmd"},
        )
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["stdout"], "")
        self.assertIn("run_powershell", result["message"])

    def test_rejected_shell_has_no_filesystem_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "should-not-exist.txt"
            for shell in ("powershell", "pwsh", "bash"):
                with self.subTest(shell=shell):
                    result = self.cmd(f'echo executed>"{marker}"', shell=shell)
                    self.assertEqual(result["status"], "error", result)
                    self.assertFalse(marker.exists())

    def test_cmd_quoted_executable_path(self):
        result = self.cmd(f'"{sys.executable}" -c "print(123)"')
        self.assert_output(result, "123")

    def test_cmd_can_still_start_powershell_as_a_command_line(self):
        result = self.cmd("powershell -NoProfile -Command \"Write-Output 'ok'\"")
        self.assert_output(result, "ok")
        self.assertEqual(self.cancellation.register_process.call_count, 1)

    # ── both actions ─────────────────────────────────────────────────────

    def test_timeout_unregisters_process(self):
        cases = (
            (self.powershell, "Start-Sleep -Seconds 10"),
            (self.cmd, "ping -n 11 127.0.0.1 >nul"),
        )
        for run, source in cases:
            with self.subTest(source=source):
                self.cancellation.register_process.reset_mock()
                self.cancellation.unregister_process.reset_mock()
                result = run(source, timeout=1)
                self.assertEqual(result["status"], "error")
                self.assertIn("Timed out", result["message"])
                process = self.cancellation.register_process.call_args.args[1]
                self.assertIsNotNone(process.poll())
                self.cancellation.unregister_process.assert_called_once_with(
                    "", process
                )

    def test_user_stop_is_reported_as_a_stop_not_a_failure(self):
        # Stand in for the run-cancel registry: half a second after the
        # process registers, mark it and kill its tree, as a user stop does.
        killed = []

        def stop_soon(_session_id, process):
            def stop():
                killed.append(process)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

            threading.Timer(0.5, stop).start()

        self.cancellation.register_process.side_effect = stop_soon
        self.cancellation.was_killed.side_effect = lambda process: process in killed

        cases = (
            (self.powershell, "Start-Sleep -Seconds 30", "script"),
            (self.cmd, "ping -n 31 127.0.0.1 >nul", "command"),
        )
        for run, source, noun in cases:
            with self.subTest(source=source):
                result = run(source)
                self.assertEqual(result["status"], "error", result)
                self.assertEqual(result["return_code"], -1, result)
                self.assertEqual(
                    result["message"],
                    f"Stopped by the user before the {noun} finished.",
                )


if __name__ == "__main__":
    unittest.main()
