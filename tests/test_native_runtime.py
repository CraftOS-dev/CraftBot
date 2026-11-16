"""Recognize the Windows runtime installed by Microsoft's redistributable."""

from contextlib import nullcontext
import sys
from types import SimpleNamespace

import pytest

from app.provision import verify


@pytest.fixture(autouse=True)
def configured_context_window():
    """The OS prerequisite probe needs no model configuration."""


@pytest.mark.parametrize("installed", [0, 1])
def test_vcredist_reads_microsoft_runtime_registration(monkeypatch, installed):
    registration = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    key = object()

    def open_key(hive, path):
        if hive != "HKLM" or path != registration:
            raise FileNotFoundError(path)
        return nullcontext(key)

    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM",
        OpenKey=open_key,
        QueryValueEx=lambda handle, name: (installed, 4),
    ))
    monkeypatch.setattr(verify.sys, "platform", "win32")
    monkeypatch.setattr(verify.os.path, "isfile", lambda path: False)
    assert verify.vcredist_installed() is bool(installed)
