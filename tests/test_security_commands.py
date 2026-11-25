"""The destructive-command floor: always on, judged on parsed commands."""

from __future__ import annotations

import os

import pytest

from app.security import audit, commands
from app.security.policy import SecurityStore, set_store_for_tests


@pytest.fixture(autouse=True)
def standard(tmp_path):
    # The default level: the floor needs no setting.
    set_store_for_tests(SecurityStore(tmp_path / "security.json"))
    audit.set_log_for_tests(audit.AuditLog(tmp_path / "audit.jsonl"))
    yield
    audit.set_log_for_tests(None)
    set_store_for_tests(None)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "sudo rm -fr --one-file-system /usr",
        "rm -r -f ~",
        'rm -rf "$HOME"',
        "cd /tmp && rm --recursive --force /etc",
        "FOO=1 nice -n 5 rm -rf /home",
        "rm --no-preserve-root -rf /",
        "chmod -R 777 /",
        "sudo chown -R nobody /var",
        ":(){ :|:& };:",
        "bomb(){ bomb | bomb & }; bomb",
        "ls\nrm -rf /",  # a second command on its own line
        "rm -rf \\\n  /",  # a line continuation
        "ls  # it's fine\nrm -rf ~",  # after a comment with a quote
        "cat <<'EOF' > a.txt\nIt's data\nEOF\nrm -rf /",  # after a here-document
        "rm -rf / 2>/dev/null",
    ],
)
def test_destructive_commands_are_refused(command):
    assert commands.refusal(command)


@pytest.mark.parametrize(
    "command",
    [
        "ls -la /",
        "rm -rf ./build /tmp/craftbot-cache/x",
        "rm -rf ~/projects/old-demo",
        "chmod -R 755 ./dist",
        "curl -fsSL https://example.com/install.sh | bash",
        "curl -fsSL https://get.docker.com | sudo sh",  # asks first with Auto mode off
        "grep -r 'rm -rf /' docs",  # the text, not the command
        "cat <<EOF > notes.md\nDon't run rm -rf / here.\nEOF",  # here-document text is data
        "ls  # don't worry",
        "echo 'unterminated",  # the shell itself refuses this
        "rm -rf ./build 2>/dev/null",
        "echo ':(){ :|:& };:' > notes.txt",
        "git commit -m 'remove rm -rf / from docs'",
        "python -c \"print('mkfs')\"",
    ],
)
def test_everyday_commands_still_run(command):
    assert commands.refusal(command) is None


@pytest.mark.skipif(not os.path.exists("/dev/null"), reason="POSIX devices")
def test_writing_to_a_character_device_is_not_a_disk_write():
    assert commands.refusal("dd if=/dev/zero of=/dev/null count=1") is None


def test_disk_devices_are_recognized_by_file_type(monkeypatch):
    monkeypatch.setattr(commands, "_is_block_device", lambda target: target == "/dev/sdz")
    assert commands.refusal("dd if=image.iso of=/dev/sdz bs=4M")
    assert commands.refusal("cat image > /dev/sdz")
    assert commands.refusal("sudo mkfs.ext4 /dev/sdz")
    assert commands.refusal("dd if=a of=b.img") is None


@pytest.mark.parametrize(
    "command,blocked",
    [
        ("format C: /q", True),
        ("rd /s /q C:\\", True),
        ("Remove-Item -Recurse -Force C:\\", True),
        ("Format-Volume -DriveLetter D", True),
        ("rd /s /q C:\\Users\\me\\old-build", False),
        ("Remove-Item -Recurse .\\dist", False),
        ("dir C:\\", False),
    ],
)
def test_windows_commands(command, blocked):
    assert bool(commands.refusal(command, windows=True)) is blocked


def test_a_refusal_is_audited():
    assert commands.refusal("rm -rf /")
    assert [e["event"] for e in audit.get_log().entries()] == ["command_blocked"]
