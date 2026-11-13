"""A service restart must never be reported as an operating-system reboot."""

import pytest

from scripts.verify_restart import require_reboot


@pytest.fixture(autouse=True)
def configured_context_window():
    """The reboot verifier is independent of the model configuration."""


def test_restarting_the_process_without_rebooting_is_rejected():
    before = {"boot": {"machine": "vm-a", "id": "boot-a", "epoch": 100}}
    after = {
        "boot": {"machine": "vm-a", "id": "boot-a", "epoch": 100},
        "process": {"pid": 456},
    }
    with pytest.raises(RuntimeError, match="not a reboot"):
        require_reboot(before, after)


def test_different_machine_is_not_a_reboot():
    with pytest.raises(RuntimeError, match="different machine"):
        require_reboot(
            {"boot": {"machine": "vm-a", "id": "boot-a", "epoch": 100}},
            {"boot": {"machine": "vm-b", "id": "boot-b", "epoch": 200}},
        )


def test_changed_boot_identity_on_the_same_machine_is_accepted():
    require_reboot(
        {"boot": {"machine": "vm-a", "id": "boot-a", "epoch": 100}},
        {"boot": {"machine": "vm-a", "id": "boot-b", "epoch": 200}},
    )
