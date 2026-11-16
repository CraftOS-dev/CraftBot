"""Persistent login preferences and service definitions (stdlib only)."""

import json
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

PORT_FLAGS = ("--frontend-port", "--backend-port", "--agent-app-port")
MODE_FLAGS = ("--cli", "--conda", "--no-conda", "--dev-ui")


def read(state_root) -> dict:
    try:
        data = json.loads(
            (Path(state_root) / "startup.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return {"enabled": True, "args": []}
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("enabled"), bool)
        or not isinstance(data.get("args"), list)
        or not all(isinstance(arg, str) for arg in data["args"])
    ):
        raise ValueError(
            "Invalid startup.json; use 'craftbot.py autostart enable' or 'disable' to reset it"
        )
    return data


def saved_args(args) -> list:
    """Only runtime choices persist; e.g. --no-open-browser is per invocation."""
    result = []
    it = iter(args)
    for arg in it:
        if arg in PORT_FLAGS:
            value = next(it, None)
            if value is not None:
                result.extend([arg, value])
        elif arg.split("=", 1)[0] in PORT_FLAGS or arg in MODE_FLAGS:
            result.append(arg)
    return result


def merge_args(saved, extra) -> list:
    """Reuse installed ports during Repair; explicit arguments override them."""
    replaced = {arg.split("=", 1)[0] for arg in extra}
    if replaced.intersection(("--conda", "--no-conda")):
        replaced.update(("--conda", "--no-conda"))
    result = []
    it = iter(saved_args(saved))
    for arg in it:
        value = next(it, None) if arg in PORT_FLAGS else None
        if arg.split("=", 1)[0] not in replaced:
            result.append(arg)
            if value is not None:
                result.append(value)
    return result + [arg for arg in extra if arg != "--no-autostart"]


def write(state_root, enabled: bool, args) -> None:
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=root,
        prefix=".startup-",
        suffix=".json",
        delete=False,
    ) as f:
        temporary = f.name
        json.dump({"enabled": enabled, "args": saved_args(args)}, f, indent=2)
    try:
        os.replace(temporary, root / "startup.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def windows_task_xml(command, directory: str, user: str) -> str:
    """No battery restrictions, time limit, elevation, or cross-user login trigger."""
    task = ET.Element(
        "Task",
        version="1.2",
        xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task",
    )

    def child(parent, name, text=None, **attrs):
        element = ET.SubElement(parent, name, **attrs)
        element.text = text
        return element

    trigger = child(child(task, "Triggers"), "LogonTrigger")
    child(trigger, "Enabled", "true")
    child(trigger, "UserId", user)
    principal = child(child(task, "Principals"), "Principal", id="Author")
    child(principal, "UserId", user)
    child(principal, "LogonType", "InteractiveToken")
    child(principal, "RunLevel", "LeastPrivilege")
    settings = child(task, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("StartWhenAvailable", "true"),
        ("AllowStartOnDemand", "true"),
        ("Enabled", "true"),
        ("ExecutionTimeLimit", "PT0S"),
    ):
        child(settings, name, value)
    action = child(child(task, "Actions", Context="Author"), "Exec")
    child(action, "Command", command[0])
    child(action, "Arguments", subprocess.list2cmdline(command[1:]))
    child(action, "WorkingDirectory", directory)
    return ET.tostring(task, encoding="unicode")


def systemd_quote(value: str, *, command=False) -> str:
    # Unit-file quoting is not shell quoting. Escape specifiers, and disable
    # environment expansion in ExecStart arguments by doubling dollars.
    value = value.replace("%", "%%")
    if command:
        value = value.replace("$", "$$")
    return json.dumps(value, ensure_ascii=False)


def systemd_path(value: str) -> str:
    # WorkingDirectory is one literal path, not a word list like ExecStart.
    # systemd does not strip quotes here: a quoted path fails the absolute
    # path check. Spaces are literal; only unit specifiers need escaping.
    if "\n" in value or "\r" in value:
        raise ValueError("systemd working directories cannot contain newlines")
    return value.replace("%", "%%")
