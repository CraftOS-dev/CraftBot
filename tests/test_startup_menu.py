"""Tests for the Start Menu entry + launch-on-startup toggle.

These cover the fix for "CraftBot missing from Start Menu, no launch-on-startup
option": a Start Menu (.lnk / .desktop) launcher created at install time, and a
user-configurable auto-start toggle exposed via the CLI and the wizard API.

The OS-touching bits (PowerShell, schtasks, registry, systemd) are monkeypatched
so the suite runs on any platform without side effects.
"""

from __future__ import annotations

import craftbot
from installer.api import WizardAPI


# ── Start Menu shortcut path ─────────────────────────────────────────────────


def test_start_menu_shortcut_path_layout(monkeypatch):
    """The Start Menu .lnk lives under <Programs>/CraftBot/CraftBot.lnk."""
    monkeypatch.setattr(
        craftbot, "_find_start_menu_programs", lambda: r"C:\Fake\Programs"
    )
    path = craftbot._start_menu_shortcut_path()
    assert path is not None
    assert path.endswith(craftbot.SHORTCUT_NAME)
    parts = path.replace("\\", "/").split("/")
    assert parts[-2] == craftbot.START_MENU_FOLDER  # the CraftBot subfolder
    assert parts[-3] == "Programs"


def test_start_menu_shortcut_path_none_when_no_programs_folder(monkeypatch):
    monkeypatch.setattr(craftbot, "_find_start_menu_programs", lambda: None)
    assert craftbot._start_menu_shortcut_path() is None


def test_write_browser_lnk_hands_ascii_path_to_wscript(monkeypatch, tmp_path):
    """Regression: WScript.Shell.Save() mangles non-ASCII paths (e.g. a
    Japanese "デスクトップ" Desktop) through the ANSI codepage and fails. The
    path passed to CreateShortcut must be the ASCII 8.3 short form."""
    non_ascii_dir = tmp_path / "デスクトップ"
    non_ascii_dir.mkdir()
    shortcut = str(non_ascii_dir / "CraftBot.lnk")

    monkeypatch.setattr(craftbot, "_ensure_ico", lambda: None)
    # Stand in for the OS 8.3 API: non-ASCII → ASCII alias, ASCII → unchanged.
    monkeypatch.setattr(
        craftbot,
        "_to_short_path",
        lambda p: r"C:\PARENT~1" if not p.isascii() else p,
    )

    captured = {}

    def fake_run(cmd, **kwargs):
        ps1 = cmd[cmd.index("-File") + 1]
        with open(ps1, encoding="utf-8-sig") as f:
            captured["script"] = f.read()

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(craftbot.subprocess, "run", fake_run)

    craftbot._write_browser_lnk(shortcut)

    create_line = next(
        ln for ln in captured["script"].splitlines() if "CreateShortcut" in ln
    )
    # The whole CreateShortcut(...) line must be ASCII — no mangling risk.
    assert create_line.isascii(), create_line
    assert "CraftBot.lnk" in create_line


# ── Launch-on-startup CLI ────────────────────────────────────────────────────


def test_cmd_autostart_routes_on_off_status(monkeypatch):
    calls = []
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: True)
    monkeypatch.setattr(
        craftbot, "_enable_autostart", lambda: calls.append("enable") or True
    )
    monkeypatch.setattr(
        craftbot, "_disable_autostart", lambda: calls.append("disable") or True
    )

    craftbot.cmd_autostart(["on"])
    craftbot.cmd_autostart(["off"])
    craftbot.cmd_autostart(["status"])  # must not enable/disable
    craftbot.cmd_autostart([])  # defaults to status
    craftbot.cmd_autostart(["nonsense"])  # unknown → no-op

    assert calls == ["enable", "disable"]


def test_enable_autostart_uses_saved_mode_and_registers(monkeypatch):
    """_enable_autostart reads the install mode and hands the registrar the
    right run args (CLI mode → --cli, browser mode → --no-open-browser)."""
    captured = {}

    monkeypatch.setattr(craftbot, "read_install_metadata", lambda: {"mode": "cli"})
    # dispatch_per_platform(win=..., mac=..., linux=...) → pick the win branch
    monkeypatch.setattr(
        craftbot._helpers, "dispatch_per_platform", lambda win, mac, linux: win
    )
    monkeypatch.setattr(
        craftbot, "_install_windows", lambda run_args: captured.setdefault("args", run_args)
    )
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: True)

    assert craftbot._enable_autostart() is True
    assert "--cli" in captured["args"]


def test_enable_autostart_browser_mode_no_open_browser(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        craftbot, "read_install_metadata", lambda: {"mode": "browser"}
    )
    monkeypatch.setattr(
        craftbot._helpers, "dispatch_per_platform", lambda win, mac, linux: win
    )
    monkeypatch.setattr(
        craftbot, "_install_windows", lambda run_args: captured.setdefault("args", run_args)
    )
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: True)

    craftbot._enable_autostart()
    assert "--no-open-browser" in captured["args"]
    assert "--cli" not in captured["args"]


def test_disable_autostart_calls_unregister(monkeypatch):
    calls = []
    monkeypatch.setattr(
        craftbot._helpers,
        "dispatch_per_platform",
        lambda win, mac, linux: win,
    )
    monkeypatch.setattr(
        craftbot, "_uninstall_windows", lambda: calls.append("unregister")
    )
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: False)

    assert craftbot._disable_autostart() is True
    assert calls == ["unregister"]


# ── Wizard API bridge methods ────────────────────────────────────────────────


def test_wizard_get_autostart_enabled(monkeypatch):
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: True)
    assert WizardAPI().get_autostart_enabled() is True


def test_wizard_set_autostart_enable(monkeypatch):
    calls = []
    monkeypatch.setattr(
        craftbot, "_enable_autostart", lambda: calls.append("enable") or True
    )
    monkeypatch.setattr(
        craftbot, "_disable_autostart", lambda: calls.append("disable") or True
    )
    # After enabling, the OS reports enabled.
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: True)

    res = WizardAPI().set_autostart(True)
    assert res == {"enabled": True, "ok": True}
    assert calls == ["enable"]


def test_wizard_set_autostart_disable(monkeypatch):
    calls = []
    monkeypatch.setattr(
        craftbot, "_enable_autostart", lambda: calls.append("enable") or True
    )
    monkeypatch.setattr(
        craftbot, "_disable_autostart", lambda: calls.append("disable") or True
    )
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: False)

    res = WizardAPI().set_autostart(False)
    assert res == {"enabled": False, "ok": True}
    assert calls == ["disable"]


def test_wizard_set_autostart_reports_failure(monkeypatch):
    def boom():
        raise RuntimeError("schtasks blew up")

    monkeypatch.setattr(craftbot, "_enable_autostart", boom)
    monkeypatch.setattr(craftbot, "_autostart_enabled", lambda: False)

    res = WizardAPI().set_autostart(True)
    assert res["ok"] is False
    assert res["enabled"] is False
    assert "schtasks blew up" in res["error"]
