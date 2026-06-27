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
