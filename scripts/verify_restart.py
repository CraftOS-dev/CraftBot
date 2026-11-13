#!/usr/bin/env python3
"""Record proof of an OS reboot, graphical login and CraftBot startup state.

Run on a disposable machine from a separate controller account. This verifier
never starts CraftBot, triggers its startup manager, or logs in the test user.
The provisioning controller must perform those actions independently. In
particular, do not SSH into the Linux test account before checking its GUI
login: doing so could start its systemd user service and mask a login failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.request


def output(command):
    return subprocess.check_output(
        command,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, "LC_ALL": "C"},
    ).strip()


def powershell(script):
    return json.loads(
        output(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); " + script,
            ]
        )
    )


def boot_state():
    if sys.platform == "win32":
        return powershell(
            "$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime; "
            "@{id=$boot.ToUniversalTime().ToString('o'); "
            "epoch=([DateTimeOffset]$boot).ToUnixTimeSeconds(); "
            "machine=(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Cryptography').MachineGuid} "
            "| ConvertTo-Json -Compress"
        )
    if sys.platform == "darwin":
        boot = output(["sysctl", "-n", "kern.boottime"])
        hardware = output(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
        return {
            "id": output(["sysctl", "-n", "kern.bootsessionuuid"]),
            "epoch": int(re.search(r"sec = (\d+)", boot).group(1)),
            "machine": re.search(r'"IOPlatformUUID" = "([^"]+)"', hardware).group(1),
        }
    return {
        "id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "epoch": int(
            re.search(r"^btime (\d+)$", Path("/proc/stat").read_text(), re.M).group(1)
        ),
        "machine": Path("/etc/machine-id").read_text().strip(),
    }


def graphical_login(user, boot):
    if sys.platform == "win32":
        # An SSH/WinRM service session is not proof of desktop login. Require
        # Explorer running as the test user in a nonzero interactive session.
        sessions = powershell(
            "$sessions = @(Get-CimInstance Win32_Process -Filter \"Name='explorer.exe'\" "
            "| ForEach-Object { $owner = Invoke-CimMethod -InputObject $_ -MethodName GetOwner; "
            "@{user=$owner.User; session=$_.SessionId; pid=$_.ProcessId; "
            "created=([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds()} }); "
            "ConvertTo-Json -InputObject $sessions -Compress"
        )
        for session in sessions:
            if (
                session["user"].lower() == user.lower()
                and session["session"] > 0
                and session["created"] >= boot["epoch"]
            ):
                return session
    elif sys.platform == "darwin":
        owner = output(["stat", "-f", "%Su", "/dev/console"])
        if owner == user:
            uid = output(["id", "-u", user])
            # print is read-only: bootstrap/kickstart here would invalidate
            # the test by creating the very login domain being verified.
            output(["launchctl", "print", f"gui/{uid}"])
            return {"user": user, "console_owner": owner, "gui_domain": f"gui/{uid}"}
    else:
        for row in output(
            ["loginctl", "list-sessions", "--no-legend", "--no-pager"]
        ).splitlines():
            session_id = row.split()[0]
            details = output(
                [
                    "loginctl",
                    "show-session",
                    session_id,
                    "-p",
                    "Name",
                    "-p",
                    "Type",
                    "-p",
                    "Class",
                    "-p",
                    "Active",
                    "-p",
                    "Service",
                    "-p",
                    "Remote",
                ]
            )
            session = dict(line.split("=", 1) for line in details.splitlines())
            if (
                session.get("Name") == user
                and session.get("Type") in ("x11", "wayland")
                and session.get("Active") == "yes"
            ):
                return {"id": session_id, **session}
    raise RuntimeError(f"No graphical desktop login found for {user}")


def process_state(tree):
    spec = importlib.util.spec_from_file_location(
        "restart_helpers", tree / "installer/helpers.py"
    )
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    try:
        record = json.loads((tree / "craftbot.pid").read_text())
    except FileNotFoundError:
        return None
    actual = helpers.process_start_time(record["pid"])
    if (
        actual is None
        or record.get("started") is None
        or abs(actual - record["started"]) > 2
    ):
        return None
    return {"pid": record["pid"], "started": actual}


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def observe(tree, state, user, expected, frontend, backend):
    boot = boot_state()
    login = graphical_login(user, boot)
    process = process_state(tree)
    if expected == "running":
        if process is None or process["started"] < boot["epoch"]:
            raise RuntimeError("No live CraftBot process from this boot")
        ready = state / ".agent-ready"
        if not ready.is_file() or ready.stat().st_mtime < boot["epoch"]:
            raise RuntimeError("Missing readiness marker from this boot")
        with urllib.request.urlopen(
            f"http://127.0.0.1:{frontend}", timeout=5
        ) as response:
            assert 'id="root"' in response.read().decode("utf-8"), (
                "Frontend did not serve the app"
            )
        with urllib.request.urlopen(
            f"http://127.0.0.1:{backend}/api/state", timeout=10
        ) as response:
            assert json.load(response), "Backend did not return application state"
    elif process is not None or port_open(frontend) or port_open(backend):
        raise RuntimeError("CraftBot started despite automatic startup being disabled")
    return {"boot": boot, "login": login, "process": process, "expected": expected}


def require_reboot(before, after):
    if before["boot"]["machine"] != after["boot"]["machine"]:
        raise RuntimeError("Evidence comes from a different machine")
    if (
        before["boot"]["id"] == after["boot"]["id"]
        or after["boot"]["epoch"] <= before["boot"]["epoch"]
    ):
        raise RuntimeError("OS boot identity did not change: this was not a reboot")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--expect", choices=("running", "stopped"), default="running")
    parser.add_argument(
        "--baseline", type=Path, help="previous observation; require a new boot"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--frontend-port", type=int, default=7925)
    parser.add_argument("--backend-port", type=int, default=7926)
    args = parser.parse_args()
    previous = json.loads(args.baseline.read_text()) if args.baseline else None
    binding = {
        "tree": str(args.tree.resolve()),
        "state": str(args.state.resolve()),
        "user": args.user,
    }
    if previous and previous["installation"] != binding:
        parser.error("The baseline describes a different installation or user")
    deadline = time.monotonic() + args.timeout
    error = None
    while time.monotonic() < deadline:
        try:
            result = observe(
                args.tree,
                args.state,
                args.user,
                args.expect,
                args.frontend_port,
                args.backend_port,
            )
            if previous:
                require_reboot(previous, result)
            result.update(
                {
                    "installation": binding,
                    "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "os_reboot_verified": bool(previous),
                    "graphical_login_verified": True,
                }
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2))
            return 0
        except (
            OSError,
            ValueError,
            RuntimeError,
            AssertionError,
            subprocess.SubprocessError,
        ) as exc:
            error = exc
            time.sleep(5)
    print(f"FAIL: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
