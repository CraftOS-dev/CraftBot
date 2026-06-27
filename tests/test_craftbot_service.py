# -*- coding: utf-8 -*-
import subprocess

import craftbot


class _ExitedProcess:
    pid = 12345

    def wait(self, timeout=None):
        return 1


def test_start_reports_immediate_child_failure(tmp_path, monkeypatch, capsys):
    pid_file = tmp_path / "craftbot.pid"
    log_file = tmp_path / "craftbot.log"
    log_file.write_text("dependency failure\n", encoding="utf-8")

    monkeypatch.setattr(craftbot, "PID_FILE", str(pid_file))
    monkeypatch.setattr(craftbot, "LOG_FILE", str(log_file))
    monkeypatch.setattr(craftbot, "RUN_SCRIPT", str(tmp_path / "run.py"))
    monkeypatch.setattr(craftbot, "_create_desktop_shortcut_unix", lambda: None)
    monkeypatch.setattr(craftbot, "_open_browser_detached", lambda url: None)

    def fake_popen(*args, **kwargs):
        return _ExitedProcess()

    monkeypatch.setattr(craftbot.subprocess, "Popen", fake_popen)

    craftbot.cmd_start([])

    output = capsys.readouterr().out
    assert "CraftBot failed to start" in output
    assert "dependency failure" in output
    assert not pid_file.exists()


def test_macos_source_shortcut_starts_service(tmp_path, monkeypatch, capsys):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    base_dir = tmp_path / "CraftBot"
    base_dir.mkdir()

    monkeypatch.setattr(craftbot, "_PLATFORM", "darwin")
    monkeypatch.setattr(craftbot, "IS_FROZEN", False)
    monkeypatch.setattr(craftbot, "BASE_DIR", str(base_dir))
    monkeypatch.setattr(craftbot, "_find_desktop", lambda: str(desktop))
    monkeypatch.setattr(craftbot, "_python_exe", lambda: "/usr/local/bin/python3.10")

    craftbot._create_desktop_shortcut_unix()

    shortcut = desktop / "CraftBot.command"
    content = shortcut.read_text()
    assert f"cd {base_dir}" in content
    assert "exec /usr/local/bin/python3.10 craftbot.py start" in content
    assert "open 'http://localhost:7925'" not in content

    output = capsys.readouterr().out
    assert "Desktop shortcut created" in output
