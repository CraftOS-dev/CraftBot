"""Tests for the UI-layer file watchers (app/ui_layer/events/change_watchers.py)."""

import os
import threading
import time
from pathlib import Path

from app.ui_layer.events.change_watchers import ChangeWatcher, WatchTarget

SETTLE = 1.5  # debounce + filesystem notification latency


class Recorder:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, name, ids):
        with self._lock:
            self.calls.append((name, set(ids)))

    def wait(self, count, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if len(self.calls) >= count:
                    break
            time.sleep(0.05)
        time.sleep(0.4)  # catch any extra calls
        with self._lock:
            return list(self.calls)


def _watch(targets, recorder):
    watcher = ChangeWatcher(targets, recorder)
    watcher.start()
    time.sleep(0.3)
    return watcher


def test_file_write_burst_is_one_change(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    rec = Recorder()
    watcher = _watch([WatchTarget("config", config, debounce=0.3)], rec)
    try:
        for i in range(5):
            config.write_text('{"n": %d}' % i)
            time.sleep(0.02)
        calls = rec.wait(1)
    finally:
        watcher.stop()
    assert calls == [("config", set())]


def test_rename_over_and_delete_are_seen(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    rec = Recorder()
    watcher = _watch([WatchTarget("config", config, debounce=0.2)], rec)
    try:
        tmp = tmp_path / "config.json.tmp"
        tmp.write_text('{"a": 1}')
        os.replace(tmp, config)
        assert len(rec.wait(1)) == 1
        config.unlink()
        assert len(rec.wait(2)) == 2
    finally:
        watcher.stop()


def test_file_created_later_is_seen(tmp_path: Path):
    config = tmp_path / "later.json"
    rec = Recorder()
    watcher = _watch([WatchTarget("later", config, debounce=0.2)], rec)
    try:
        config.write_text("{}")
        assert rec.wait(1) == [("later", set())]
    finally:
        watcher.stop()


def test_unrelated_sibling_is_ignored(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    rec = Recorder()
    watcher = _watch([WatchTarget("config", config, debounce=0.2)], rec)
    try:
        (tmp_path / "other.txt").write_text("x")
        time.sleep(SETTLE)
        assert rec.calls == []
    finally:
        watcher.stop()


def test_recursive_directory_with_ids_and_ignore(tmp_path: Path):
    root = tmp_path / "workspace"
    (root / "docs").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    rec = Recorder()
    target = WatchTarget(
        "workspace",
        root,
        recursive=True,
        debounce=0.3,
        id_for=lambda p: str(p.parent.relative_to(root)).replace("\\", "/"),
        ignore=("node_modules",),
    )
    watcher = _watch([target], rec)
    try:
        (root / "docs" / "a.md").write_text("a")
        (root / "b.md").write_text("b")
        (root / "node_modules" / "pkg" / "index.js").write_text("x")
        calls = rec.wait(1)
    finally:
        watcher.stop()
    assert len(calls) == 1
    name, ids = calls[0]
    assert name == "workspace"
    assert "docs" in ids and "." in ids
    assert not any("node_modules" in i for i in ids)


def test_stop_cancels_pending(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    rec = Recorder()
    watcher = _watch([WatchTarget("config", config, debounce=1.0)], rec)
    config.write_text('{"x": 1}')
    time.sleep(0.3)
    watcher.stop()
    time.sleep(1.2)
    assert rec.calls == []


def test_missing_directory_does_not_fail(tmp_path: Path):
    rec = Recorder()
    watcher = ChangeWatcher([WatchTarget("x", tmp_path / "nope" / "x.json")], rec)
    watcher.start()
    watcher.stop()
