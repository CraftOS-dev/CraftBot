#!/usr/bin/env python3
"""Full install and OS startup-manager acceptance on disposable hosted runners.

This deliberately refuses to run on a developer's machine: it installs real
dependencies, replaces the current user's CraftBot startup registration, and
stops processes on CraftBot's ports. It does NOT reboot the machine or claim
to exercise a real login trigger. See result.json for the exact coverage.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "startup-evidence"


def run(command, *, cwd=None, check=True, timeout=3600):
    print(f"$ {subprocess.list2cmdline([str(arg) for arg in command])}", flush=True)
    # Save complete output without flooding CI logs with pip/npm progress.
    with (EVIDENCE / "commands.log").open("a", encoding="utf-8") as log:
        log.write(f"\n$ {command}\n")
        log.flush()
        result = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    if check and result.returncode:
        raise RuntimeError(f"Command exited {result.returncode}: {command}")
    return result.returncode


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def user_data():
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "CraftBot"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CraftBot"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "craftbot"
    )


def wait_stopped(timeout=30):
    """Allow the OS to finish terminating children after the stop command."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_open(7925) and not port_open(7926):
            return
        time.sleep(0.5)
    raise RuntimeError("stop left a server running after 30 seconds")


def wait_ready(tree, state, timeout=900):
    started = time.monotonic()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (state / ".agent-ready").exists() and (tree / "craftbot.pid").exists():
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:7925", timeout=5
                ) as response:
                    html = response.read().decode("utf-8")
                with urllib.request.urlopen(
                    "http://127.0.0.1:7926/api/state", timeout=5
                ) as response:
                    backend = json.load(response)
                if 'id="root"' in html and isinstance(backend, dict) and backend:
                    return json.loads((tree / "craftbot.pid").read_text())
            except (OSError, ValueError):
                pass
        if time.monotonic() - started > 60:
            # A dead startup process cannot become ready. Fail promptly with
            # its logs instead of waiting the full model-download deadline.
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import craftbot; raise SystemExit(0 if craftbot._owned_pid() else 1)",
                ],
                cwd=tree,
                capture_output=True,
                timeout=30,
            )
            if probe.returncode == 1:
                raise RuntimeError(
                    "Startup process exited before CraftBot became ready"
                )
        time.sleep(5)
    raise RuntimeError(
        "CraftBot did not become ready (PID, agent-ready, frontend and backend)"
    )


def start_registered():
    if sys.platform == "win32":
        run(["schtasks", "/run", "/tn", "CraftBot"], timeout=30)
    elif sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents/com.craftbot.agent.plist"
        run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], timeout=30)
    else:
        # Only the display required by the virtual desktop is supplied. Do
        # not import PATH, conda activation, or the install shell environment.
        run(["systemctl", "--user", "set-environment", "DISPLAY=:99"], timeout=30)
        run(["systemctl", "--user", "start", "craftbot"], timeout=30)


def stop_registered():
    if sys.platform == "win32":
        run(["schtasks", "/end", "/tn", "CraftBot"], check=False, timeout=30)
    elif sys.platform == "darwin":
        run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/com.craftbot.agent"],
            check=False,
            timeout=30,
        )
    else:
        run(["systemctl", "--user", "stop", "craftbot"], check=False, timeout=30)


def check_shortcut():
    desktop = Path.home() / "Desktop"
    if sys.platform == "win32":
        target = str(desktop / "CraftBot.lnk").replace("'", "''")
        ps = EVIDENCE / "shortcut.ps1"
        ps.write_text(
            f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{target}')\n"
            "@{target=$s.TargetPath; arguments=$s.Arguments} | ConvertTo-Json\n",
            encoding="utf-8-sig",
        )
        result = subprocess.check_output(
            ["powershell", "-NoProfile", "-File", str(ps)], text=True
        )
        (EVIDENCE / "shortcut.json").write_text(result, encoding="utf-8")
        data = json.loads(result)
        assert Path(data["target"]).name.lower() == "cmd.exe", data
        assert data["arguments"] == '/c start "" http://localhost:7925', data
    else:
        path = desktop / (
            "CraftBot.command" if sys.platform == "darwin" else "CraftBot.desktop"
        )
        content = path.read_text()
        shutil.copy2(path, EVIDENCE / path.name)
        if sys.platform == "darwin":
            assert content == "#!/bin/sh\nexec open http://localhost:7925\n", content
        else:
            action = next(
                line for line in content.splitlines() if line.startswith("Exec=")
            )
            assert action in (
                "Exec=xdg-open http://localhost:7925",
                "Exec=sensible-browser http://localhost:7925",
            ), action


def collect(tree, state):
    for name, directory in (
        ("code", tree),
        ("state", state),
        ("launcher", user_data()),
    ):
        for filename in (
            "craftbot.log",
            "craftbot.pid",
            "startup.json",
            "launcher.log",
            "config.json",
        ):
            source = directory / filename
            if source.is_file():
                shutil.copy2(source, EVIDENCE / f"{name}-{filename}")
    if sys.platform == "win32":
        run(["schtasks", "/query", "/tn", "CraftBot", "/xml"], check=False, timeout=30)
    elif sys.platform == "darwin":
        run(
            ["launchctl", "print", f"gui/{os.getuid()}/com.craftbot.agent"],
            check=False,
            timeout=30,
        )
    else:
        run(
            ["journalctl", "--user", "-u", "craftbot", "--no-pager", "-n", "250"],
            check=False,
            timeout=30,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=("cli", "installer"), required=True)
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        parser.error(
            "This destructive acceptance test requires a disposable GitHub-hosted runner"
        )
    EVIDENCE.mkdir(exist_ok=True)
    # Startup must use durable registered paths, not a development override.
    for key in list(os.environ):
        if key.startswith(("CRAFTBOT_", "CONDA_")) or key in (
            "PYTHONPATH",
            "VIRTUAL_ENV",
        ):
            os.environ.pop(key)
    (Path.home() / "Desktop").mkdir(exist_ok=True)
    tree = Path(os.environ["RUNNER_TEMP"]) / f"CraftBot {args.method} installation"
    state = tree if args.method == "cli" else user_data()
    python = sys.executable
    installer = (
        ROOT
        / "launcher/target/release"
        / ("CraftBotInstaller.exe" if sys.platform == "win32" else "CraftBotInstaller")
    )
    result = {
        "method": args.method,
        "platform": sys.platform,
        "os_reboot_tested": False,
        "login_trigger_tested": False,
        "passed": [],
    }

    def cli(*arguments, check=True):
        return run(
            [python, str(tree / "craftbot.py"), *arguments], cwd=tree, check=check
        )

    try:
        if port_open(7925) or port_open(7926):
            raise RuntimeError(
                "Fresh runner already has a listener on CraftBot's ports"
            )
        if args.method == "cli":
            with zipfile.ZipFile(ROOT / "dist/CraftBot-src.zip") as archive:
                archive.extractall(tree)
            cli("install", "--no-open-browser")
        else:
            os.environ["CRAFTBOT_SRC_ZIP"] = str(ROOT / "dist/CraftBot-src.zip")
            run([str(installer), "--headless", "install", str(tree)])
            record = json.loads((user_data() / "launcher.json").read_text())
            python = record["python"]
            assert Path(record["install_dir"]).resolve() == tree.resolve()
        initial = wait_ready(tree, state)
        result["passed"].append("full_install_and_readiness")
        assert json.loads((state / "startup.json").read_text())["enabled"] is True
        check_shortcut()
        result["passed"].append("desktop_shortcut_contains_only_browser_open")

        cli("stop", check=False)
        wait_stopped()
        assert not (state / ".agent-ready").exists(), "stop left stale readiness"
        start_registered()
        restarted = wait_ready(tree, state)
        assert initial["pid"] != restarted["pid"], "did not start a new process"
        result["passed"].append("real_os_startup_manager_and_readiness")
        run(
            [
                python,
                str(ROOT / "scripts/verify_startup_ui.py"),
                "--output",
                str(EVIDENCE / "browser"),
            ]
        )
        result["passed"].append("browser_receives_backend_state_after_startup")

        cli("autostart", "disable")
        assert json.loads((state / "startup.json").read_text())["enabled"] is False
        assert wait_ready(tree, state, timeout=30)["pid"] == restarted["pid"], (
            "disable stopped the current app"
        )
        result["passed"].append("disable_keeps_current_app_running")
        stop_registered()
        cli("stop", check=False)

        if args.method == "installer":
            run([str(installer), "--headless", "repair"])
        else:
            cli("install", "--no-open-browser")
        wait_ready(tree, state)
        assert json.loads((state / "startup.json").read_text())["enabled"] is False
        result["passed"].append("repair_preserves_opt_out")
        cli("autostart", "enable")
        cli("stop", check=False)
        start_registered()
        wait_ready(tree, state)
        result["passed"].append("re_enable_and_startup_manager_readiness")
        result["success"] = True
    except Exception as exc:
        result["success"] = False
        result["error"] = str(exc)
        print(f"FAILED: {exc}", flush=True)
    finally:
        (EVIDENCE / "result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        try:
            collect(tree, state)
        finally:
            stop_registered()
            if (tree / "craftbot.py").exists():
                cli("stop", check=False)
                cli("autostart", "disable", check=False)
        print(json.dumps(result, indent=2), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
