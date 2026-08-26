"""FileCredentialStore: atomicity, quarantine, permissions, legacy reads."""

from __future__ import annotations

import os
import stat

import pytest

import craftos_integrations.core.storage as storage_mod


DOC = {"version": 2, "primary": "a@x.com", "accounts": {}}


def test_replace_then_load_roundtrip(store):
    store.replace("gmail", DOC)
    assert store.load("gmail") == DOC


def test_replace_is_atomic_under_crash(store, tmp_path, monkeypatch):
    store.replace("gmail", DOC)
    real_replace = os.replace

    def crash(src, dst):
        raise OSError("simulated crash between tmp-write and rename")

    monkeypatch.setattr(storage_mod.os, "replace", crash)
    with pytest.raises(OSError):
        store.replace("gmail", {"version": 2, "primary": "clobbered", "accounts": {}})
    monkeypatch.setattr(storage_mod.os, "replace", real_replace)
    # The original document survived untouched.
    assert store.load("gmail") == DOC


def test_corrupt_document_is_quarantined_not_silently_empty(store, tmp_path):
    path = tmp_path / "gmail.accounts.json"
    path.write_text("{this is not json", encoding="utf-8")
    assert store.load("gmail") is None
    assert not path.exists()
    quarantined = tmp_path / "gmail.accounts.json.corrupt"
    assert quarantined.exists()
    assert quarantined.read_text(encoding="utf-8") == "{this is not json"


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX owner-only modes don't exist on Windows (no os.fchmod; "
    "NTFS ACLs govern access)",
)
def test_written_files_are_owner_only(store, tmp_path):
    store.replace("gmail", DOC)
    mode = stat.S_IMODE(os.stat(tmp_path / "gmail.accounts.json").st_mode)
    assert mode == (stat.S_IRUSR | stat.S_IWUSR)


def test_delete_missing_is_noop(store):
    store.delete("gmail")  # no raise
    assert store.load("gmail") is None
