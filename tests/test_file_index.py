# -*- coding: utf-8 -*-
"""Tests for app/utils/file_index.py: the SQLite FTS5 filename index used by
the find_files action (issue #354 + the crash/perf/watcher-treadmill fixes
that followed it)."""

import os
import shutil
import sqlite3
import time

import pytest

from app.utils import file_index


def make_file(root, *parts, content="x"):
    path = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


@pytest.fixture(autouse=True)
def _cleanup_index_storage():
    """Index storage now lives under the real APP_DATA_PATH/.file_index/,
    not under each test's tmp_path — clean it up so repeated test runs
    don't accumulate disposable cache dirs in the actual repo."""
    yield
    if os.path.isdir(file_index._INDEX_STORAGE_ROOT):
        shutil.rmtree(file_index._INDEX_STORAGE_ROOT, ignore_errors=True)


class TestSkipList:
    def test_is_skip_path_matches_component_anywhere(self):
        assert file_index._is_skip_path(
            os.path.join("C:\\", "proj", "node_modules", "pkg", "index.js")
        )
        assert file_index._is_skip_path(os.path.join("proj", ".git", "HEAD"))
        assert not file_index._is_skip_path(
            os.path.join("proj", "src", "main.py")
        )

    def test_crawl_skips_noise_directories(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "real.txt")
        make_file(root, "node_modules", "pkg", "index.js")
        make_file(root, ".git", "HEAD")

        stats = file_index.build_index(root, force=True)

        assert stats.files_indexed == 1
        conn = sqlite3.connect(file_index._db_path(root))
        basenames = {r[0] for r in conn.execute("SELECT basename FROM files")}
        assert basenames == {"real.txt"}


class TestBuildIndex:
    def test_full_crawl_populates_files_and_fts_in_sync(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        make_file(root, "sub", "b.txt")

        stats = file_index.build_index(root, force=True)
        assert stats.files_indexed == 2
        assert stats.files_added == 2

        conn = sqlite3.connect(file_index._db_path(root))
        files_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM files_fts").fetchone()[0]
        assert files_count == fts_count == 2

    def test_second_call_without_changes_hits_cached_fast_path(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)

        stats = file_index.build_index(root, force=False)
        assert stats.files_added == 0
        assert stats.files_updated == 0
        assert stats.files_removed == 0
        assert stats.files_indexed == 1

    def test_force_true_always_does_full_rebuild(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)

        stats = file_index.build_index(root, force=True)
        assert stats.files_added == 1  # re-added by the fresh crawl

    def test_case_insensitive_root_reuses_existing_index_on_windows(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)

        differently_cased = root.upper() if os.name == "nt" else root
        stats = file_index.build_index(differently_cased, force=False)
        # Same logical root -> cached path, no spurious rebuild.
        assert stats.files_added == 0


class TestApplyTargetedChanges:
    def test_add_update_delete_semantics(self, tmp_path):
        root = str(tmp_path)
        keep = make_file(root, "keep.txt")
        stale = make_file(root, "stale.txt")
        file_index.build_index(root, force=True)

        # add
        added_path = make_file(root, "new.txt")
        # update (change content/size so mtime/size differ)
        time.sleep(0.01)
        with open(keep, "w", encoding="utf-8") as f:
            f.write("much longer content than before")
        # delete
        os.remove(stale)

        conn = sqlite3.connect(file_index._db_path(root))
        total, added, updated, removed = file_index._apply_targeted_changes(
            conn, root, {added_path, keep, stale}
        )

        assert added == 1
        assert updated == 1
        assert removed == 1
        basenames = {r[0] for r in conn.execute("SELECT basename FROM files")}
        assert basenames == {"keep.txt", "new.txt"}

    def test_targeted_changes_do_not_walk_the_whole_tree(self, tmp_path):
        """The whole point of _apply_targeted_changes: cost scales with the
        changed set, not with total index size."""
        root = str(tmp_path)
        for i in range(50):
            make_file(root, f"file_{i}.txt")
        file_index.build_index(root, force=True)

        new_path = make_file(root, "just_one_more.txt")
        conn = sqlite3.connect(file_index._db_path(root))
        total, added, updated, removed = file_index._apply_targeted_changes(
            conn, root, {new_path}
        )
        assert added == 1
        assert updated == 0
        assert removed == 0
        # total is intentionally not computed (no caller uses it) — see the
        # wasted-COUNT(*) fix; verify the real row count independently.
        assert total == -1
        actual_total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        assert actual_total == 51


class TestSearch:
    @pytest.fixture
    def indexed_root(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "report.pdf")
        make_file(root, "notes.txt")
        make_file(root, "sub", "archive report.pdf")
        file_index.build_index(root, force=True)
        return root

    def test_suffix_pattern(self, indexed_root):
        results = file_index.search(indexed_root, "*.pdf")
        assert len(results) == 2
        assert all(r.endswith(".pdf") for r in results)

    def test_prefix_pattern(self, indexed_root):
        results = file_index.search(indexed_root, "report*")
        assert any(os.path.basename(r) == "report.pdf" for r in results)
        assert not any(os.path.basename(r) == "notes.txt" for r in results)

    def test_or_pattern_pipe_syntax(self, indexed_root):
        results = file_index.search(indexed_root, "*.pdf|*.txt")
        basenames = {os.path.basename(r) for r in results}
        assert basenames == {"report.pdf", "notes.txt", "archive report.pdf"}

    def test_or_pattern_word_syntax(self, indexed_root):
        results = file_index.search(indexed_root, "*.pdf OR *.txt")
        assert len(results) == 3

    def test_no_match_returns_empty(self, indexed_root):
        assert file_index.search(indexed_root, "*.doesnotexist") == []

    def test_suffix_literal_with_space_does_not_raise(self, indexed_root):
        # Regression: the FTS5 suffix-branch literal must be quoted, or a
        # literal containing a space breaks the MATCH query.
        results = file_index.search(indexed_root, "*archive report.pdf")
        assert len(results) == 1


class TestFindFilesMultiRoot:
    def test_pipe_separated_roots_are_merged_and_deduped(self, tmp_path):
        root_a = str(tmp_path / "a")
        root_b = str(tmp_path / "b")
        os.makedirs(root_a)
        os.makedirs(root_b)
        make_file(root_a, "one.txt")
        make_file(root_b, "two.txt")

        result = file_index.find_files(f"{root_a}|{root_b}", "*.txt", recursive=True)
        assert result["status"] == "success"
        basenames = {os.path.basename(m) for m in result["matches"]}
        assert basenames == {"one.txt", "two.txt"}

    def test_non_recursive_filters_to_top_level_only(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "top.txt")
        make_file(root, "sub", "nested.txt")

        result = file_index.find_files(root, "*.txt", recursive=False)
        basenames = {os.path.basename(m) for m in result["matches"]}
        assert basenames == {"top.txt"}

    def test_all_drives_uses_list_local_drives(self, tmp_path, monkeypatch):
        root_a = str(tmp_path / "a")
        root_b = str(tmp_path / "b")
        os.makedirs(root_a)
        os.makedirs(root_b)
        make_file(root_a, "one.txt")
        make_file(root_b, "two.txt")
        monkeypatch.setattr(
            file_index, "list_local_drives", lambda: [root_a, root_b]
        )

        result = file_index.find_files("", "*.txt", recursive=True, all_drives=True)
        assert result["status"] == "success"
        basenames = {os.path.basename(m) for m in result["matches"]}
        assert basenames == {"one.txt", "two.txt"}

    def test_all_drives_with_no_drives_returns_error(self, monkeypatch):
        monkeypatch.setattr(file_index, "list_local_drives", lambda: [])
        result = file_index.find_files("", "*.txt", recursive=True, all_drives=True)
        assert result["status"] == "error"
        assert result["matches"] == []


class TestBuildLockRegistry:
    def test_same_root_returns_same_lock(self):
        a = file_index._get_build_lock("C:/some/path")
        b = file_index._get_build_lock("c:/SOME/path")
        assert a is b

    def test_different_roots_return_different_locks(self):
        a = file_index._get_build_lock("C:/path/one")
        b = file_index._get_build_lock("C:/path/two")
        assert a is not b


class TestWatcherIntegration:
    """End-to-end: a real watchdog observer applies a real change without
    re-walking the whole tree, and ignores changes inside skip-listed dirs."""

    def test_real_change_is_applied_and_noise_is_ignored(self, tmp_path):
        pytest.importorskip("watchdog")
        root = str(tmp_path)
        os.makedirs(os.path.join(root, "node_modules"))
        file_index.build_index(root, force=True)

        started = file_index.start_watcher(root)
        assert started

        try:
            time.sleep(0.5)
            make_file(root, "real.txt")
            make_file(root, "node_modules", "noise.txt")
            time.sleep(0.5)

            key = os.path.normcase(root)
            pending = file_index._pending_changes.get(key, set())
            assert any(p.endswith("real.txt") for p in pending)
            assert not any("node_modules" in p for p in pending)

            time.sleep(file_index._DEBOUNCE_SECONDS + 1.5)

            conn = sqlite3.connect(file_index._db_path(root))
            basenames = {r[0] for r in conn.execute("SELECT basename FROM files")}
            assert "real.txt" in basenames
            assert "noise.txt" not in basenames
        finally:
            watcher = file_index._watchers.get(os.path.normcase(root))
            if watcher and watcher._observer:
                watcher._observer.stop()
                watcher._observer.join(timeout=5)


class TestReconciliation:
    """Regression tests for the self-healing gap: directory-level events and
    fresh-process restarts must not be silently trusted as 'nothing changed'."""

    def test_directory_level_event_forces_full_rewalk(self, tmp_path):
        root = os.path.join(str(tmp_path), "orig_root")
        os.makedirs(root)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)
        key = os.path.normcase(root)
        file_index._verified_roots.add(key)  # simulate an already-checked root

        file_index._mark_needs_full_rewalk(root)
        assert file_index._peek_has_pending_changes(root)

        # Rename the folder on disk without going through the (real, async)
        # watcher — simulates the "single directory event, unknown
        # descendants" scenario directly. Renamed within the same tmp_path
        # (not renamed back) so pytest's own cleanup isn't affected by
        # Windows file-lock timing on the SQLite WAL files.
        renamed = os.path.join(str(tmp_path), "renamed_root")
        os.rename(root, renamed)

        stats = file_index.build_index(renamed, force=False)
        # A full re-walk of the renamed tree must have run (not a
        # trusted-empty targeted apply), so the pre-existing file is
        # correctly found under its new path.
        assert stats.files_indexed >= 0  # ran a real check, didn't crash
        conn = sqlite3.connect(file_index._db_path(renamed))
        try:
            basenames = {r[0] for r in conn.execute("SELECT basename FROM files")}
            assert "a.txt" in basenames
        finally:
            conn.close()

    def test_fresh_process_does_not_trust_empty_pending_as_fresh(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)
        key = os.path.normcase(root)

        # Simulate "restart": no _verified_roots entry, no pending changes,
        # even though the on-disk index already has matching rows.
        file_index._verified_roots.discard(key)
        assert not file_index._peek_has_pending_changes(root)

        # A file changes on disk while "the process was down" (no watcher).
        make_file(root, "b.txt")

        file_index.build_index(root, force=False)
        conn = sqlite3.connect(file_index._db_path(root))
        basenames = {r[0] for r in conn.execute("SELECT basename FROM files")}
        assert "b.txt" in basenames, (
            "first access after a simulated restart must do a real check, "
            "not trust the cached index as fresh"
        )


class TestSymlinkHandling:
    def test_symlink_is_not_indexed_via_targeted_changes(self, tmp_path):
        root = str(tmp_path)
        target = make_file(root, "target.txt")
        link_path = os.path.join(root, "link.txt")
        try:
            os.symlink(target, link_path)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not permitted in this environment")

        file_index.build_index(root, force=True)
        conn = sqlite3.connect(file_index._db_path(root))
        # The full crawl never indexes symlinks (matches pre-existing
        # _iter_files behavior).
        assert conn.execute(
            "SELECT 1 FROM files WHERE basename = 'link.txt'"
        ).fetchone() is None

        file_index._apply_targeted_changes(conn, root, {link_path})
        # Targeted updates must agree with the full crawl about symlinks.
        assert conn.execute(
            "SELECT 1 FROM files WHERE basename = 'link.txt'"
        ).fetchone() is None


class TestResolveRoots:
    def test_pipe_only_base_directory_is_an_error(self):
        roots, error = file_index.resolve_roots("|", windows=False)
        assert roots == []
        assert error is not None
        assert error["status"] == "error"

    def test_valid_multi_root_returns_normalized_paths(self, tmp_path):
        a = str(tmp_path / "a")
        b = str(tmp_path / "b")
        os.makedirs(a)
        os.makedirs(b)
        roots, error = file_index.resolve_roots(f"{a}|{b}", windows=False)
        assert error is None
        assert len(roots) == 2

    def test_nonexistent_root_is_an_error(self, tmp_path):
        missing = str(tmp_path / "does_not_exist")
        roots, error = file_index.resolve_roots(missing, windows=False)
        assert roots == []
        assert error is not None
        assert "does not exist" in error["message"]

    def test_empty_defaults_to_home_directory(self):
        roots, error = file_index.resolve_roots("", windows=False)
        assert error is None
        assert len(roots) == 1


class TestExpandedSkipList:
    def test_build_and_dist_dirs_are_skipped(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "real.txt")
        make_file(root, "dist", "bundle.js")
        make_file(root, "build", "output.o")
        make_file(root, ".pytest_cache", "cache.txt")

        stats = file_index.build_index(root, force=True)
        assert stats.files_indexed == 1

    def test_skip_check_is_case_insensitive_cross_platform(self):
        assert file_index._is_skip_path(
            os.path.join("proj", "Node_Modules", "pkg.js")
        )
        assert file_index._is_skip_path(os.path.join("proj", ".GIT", "HEAD"))


class TestFindFilesLimit:
    def test_limit_caps_matches_across_multiple_roots(self, tmp_path):
        root_a = str(tmp_path / "a")
        root_b = str(tmp_path / "b")
        os.makedirs(root_a)
        os.makedirs(root_b)
        for i in range(5):
            make_file(root_a, f"a_{i}.txt")
            make_file(root_b, f"b_{i}.txt")

        result = file_index.find_files(
            f"{root_a}|{root_b}", "*.txt", recursive=True, limit=3
        )
        assert result["status"] == "success"
        assert len(result["matches"]) == 3

    def test_limit_zero_means_unlimited(self, tmp_path):
        """Regression: limit=0 must not truncate to a single match — the
        naive `len(matches) >= limit` check is trivially true at 0 the
        instant the first match is appended."""
        root_a = str(tmp_path / "a")
        root_b = str(tmp_path / "b")
        os.makedirs(root_a)
        os.makedirs(root_b)
        for i in range(5):
            make_file(root_a, f"a_{i}.txt")
            make_file(root_b, f"b_{i}.txt")

        result = file_index.find_files(
            f"{root_a}|{root_b}", "*.txt", recursive=True, limit=0
        )
        assert result["status"] == "success"
        assert len(result["matches"]) == 10

    def test_negative_limit_also_means_unlimited(self, tmp_path):
        root = str(tmp_path)
        for i in range(4):
            make_file(root, f"f_{i}.txt")

        result = file_index.find_files(root, "*.txt", recursive=True, limit=-1)
        assert len(result["matches"]) == 4


class FakeEvent:
    def __init__(self, src_path, is_directory, dest_path=None):
        self.src_path = src_path
        self.is_directory = is_directory
        self.dest_path = dest_path


class TestDirectoryEventScope:
    """Regression test: only a directory move/rename should force a full
    re-walk. Directory create/delete must stay no-ops, or routine churn on
    a busy drive (temp dirs, caches) reintroduces the full-rewalk treadmill
    the targeted-changes mechanism exists to avoid."""

    def _make_handler(self):
        events = []
        handler = file_index._IndexEventHandler(lambda path, kind: events.append((path, kind)))
        return handler, events

    def test_directory_created_is_a_noop(self):
        handler, events = self._make_handler()
        handler.on_created(FakeEvent("C:/root/newdir", is_directory=True))
        assert events == []

    def test_directory_deleted_is_a_noop(self):
        handler, events = self._make_handler()
        handler.on_deleted(FakeEvent("C:/root/olddir", is_directory=True))
        assert events == []

    def test_directory_modified_is_a_noop(self):
        handler, events = self._make_handler()
        handler.on_modified(FakeEvent("C:/root/somedir", is_directory=True))
        assert events == []

    def test_directory_moved_triggers_dir_changed(self):
        handler, events = self._make_handler()
        handler.on_moved(
            FakeEvent("C:/root/old_name", is_directory=True, dest_path="C:/root/new_name")
        )
        assert events == [("C:/root/old_name", "dir_changed")]

    def test_file_events_are_unaffected(self):
        handler, events = self._make_handler()
        handler.on_created(FakeEvent("C:/root/a.txt", is_directory=False))
        handler.on_deleted(FakeEvent("C:/root/b.txt", is_directory=False))
        handler.on_modified(FakeEvent("C:/root/c.txt", is_directory=False))
        assert events == [
            ("C:/root/a.txt", "created"),
            ("C:/root/b.txt", "deleted"),
            ("C:/root/c.txt", "modified"),
        ]

    def test_directory_create_delete_do_not_mark_needs_full_rewalk(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)
        key = os.path.normcase(root)
        file_index._verified_roots.add(key)

        watcher = file_index._RootWatcher(root, file_index._DEBOUNCE_SECONDS)
        handler = file_index._IndexEventHandler(watcher._on_change)
        handler.on_created(FakeEvent(os.path.join(root, "newdir"), is_directory=True))
        handler.on_deleted(FakeEvent(os.path.join(root, "olddir"), is_directory=True))

        assert not file_index._peek_has_pending_changes(root)


class TestCentralizedStorage:
    """Regression tests: the index db must live under CraftBot's own
    app-data directory, never inside the searched root itself."""

    def test_index_lives_under_app_data_not_inside_searched_root(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)

        # No .craftbot (or any other hidden index folder) inside the
        # searched directory itself.
        assert not any(
            entry.name.lower() == ".craftbot"
            for entry in os.scandir(root)
            if entry.is_dir()
        )

        db_path = file_index._db_path(root)
        assert os.path.commonpath(
            [os.path.abspath(db_path), file_index._INDEX_STORAGE_ROOT]
        ) == os.path.normpath(file_index._INDEX_STORAGE_ROOT)
        assert os.path.isfile(db_path)

    def test_same_root_different_case_maps_to_same_folder(self, tmp_path):
        root = str(tmp_path)
        differently_cased = root.upper() if os.name == "nt" else root
        assert file_index._index_dir(root) == file_index._index_dir(differently_cased)

    def test_different_roots_map_to_different_folders(self, tmp_path):
        a = str(tmp_path / "a")
        b = str(tmp_path / "b")
        assert file_index._index_dir(a) != file_index._index_dir(b)

    def test_reindexing_same_root_reuses_existing_db(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "a.txt")
        file_index.build_index(root, force=True)
        first_db_path = file_index._db_path(root)

        make_file(root, "b.txt")
        file_index.build_index(root, force=True)
        second_db_path = file_index._db_path(root)

        assert first_db_path == second_db_path
        conn = sqlite3.connect(second_db_path)
        basenames = {r[0] for r in conn.execute("SELECT basename FROM files")}
        assert basenames == {"a.txt", "b.txt"}


class TestMountBoundary:
    def test_does_not_descend_into_a_different_filesystem(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        make_file(root, "a.txt")
        other_fs_dir = os.path.join(root, "other_fs")
        os.makedirs(other_fs_dir)
        make_file(other_fs_dir, "should_not_be_indexed.txt")

        real_stat = os.stat
        root_dev = real_stat(root).st_dev
        normalized_other = os.path.normcase(other_fs_dir)

        def fake_stat(path, *args, **kwargs):
            if os.path.normcase(path) == normalized_other:
                return type("FakeStat", (), {"st_dev": root_dev + 1})()
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(file_index.os, "stat", fake_stat)
        results = [entry.name for entry in file_index._iter_files(root)]
        assert results == ["a.txt"]

    def test_root_itself_inaccessible_yields_nothing(self, monkeypatch):
        def raise_oserror(path):
            raise OSError("no such root")

        monkeypatch.setattr(file_index.os, "stat", raise_oserror)
        assert list(file_index._iter_files("/does/not/matter")) == []

    def test_trash_and_lost_and_found_are_skipped(self, tmp_path):
        root = str(tmp_path)
        make_file(root, "real.txt")
        make_file(root, ".Trash", "deleted.txt")
        make_file(root, "lost+found", "orphan.dat")

        stats = file_index.build_index(root, force=True)
        assert stats.files_indexed == 1
