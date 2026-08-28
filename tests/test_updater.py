# -*- coding: utf-8 -*-

import asyncio
from pathlib import Path

import pytest

from app import updater


INSIDE_WORK_TREE = ("git", "rev-parse", "--is-inside-work-tree")
CURRENT_BRANCH = ("git", "rev-parse", "--abbrev-ref", "HEAD")
FETCH_MAIN = ("git", "fetch", "origin", "main:refs/remotes/origin/main")
HEAD = ("git", "rev-parse", "HEAD")
ORIGIN_MAIN = ("git", "rev-parse", "origin/main")
COUNT_MAIN = ("git", "rev-list", "--left-right", "--count", "HEAD...origin/main")
SHOW_VERSION_FILE = ("git", "show", "origin/main:VERSION")
SHOW_SETTINGS_FILE = ("git", "show", "origin/main:app/config/settings.json")

LOCAL_REVISION = b"1111111111111111111111111111111111111111\n"
REMOTE_REVISION = b"2222222222222222222222222222222222222222\n"
LOCAL_AHEAD_REVISION = b"3333333333333333333333333333333333333333\n"

ON_MAIN = {INSIDE_WORK_TREE: b"true\n", CURRENT_BRANCH: b"main\n"}


def run(coro):
    return asyncio.run(coro)


def stub_git(monkeypatch, responses):
    calls = []

    async def fake_run_git(cmd, cwd):
        key = tuple(cmd)
        calls.append(key)
        if key not in responses:
            raise AssertionError(f"unexpected git command: {cmd}")
        return responses[key], b""

    monkeypatch.setattr(updater, "_run_git", fake_run_git)
    return calls


def test_source_update_reports_remote_version_when_behind(monkeypatch, tmp_path):
    """Behind main: report main's own version, with no commit suffix."""
    calls = stub_git(
        monkeypatch,
        {
            **ON_MAIN,
            FETCH_MAIN: b"",
            HEAD: LOCAL_REVISION,
            ORIGIN_MAIN: REMOTE_REVISION,
            COUNT_MAIN: b"0\t3\n",
            SHOW_VERSION_FILE: b"1.4.1\n",
        },
    )

    result = run(updater._check_source_update(tmp_path, "1.3.4", branch="main"))

    assert result == updater.UpdateStatus(True, "1.3.4", "1.4.1", None)
    assert FETCH_MAIN in calls


def test_source_update_falls_back_to_settings_json_for_remote_version(
    monkeypatch, tmp_path
):
    """No VERSION file on main — read the version out of settings.json."""

    async def fake_run_git(cmd, cwd):
        key = tuple(cmd)
        if key == SHOW_VERSION_FILE:
            raise RuntimeError("path 'VERSION' does not exist in 'origin/main'")
        responses = {
            **ON_MAIN,
            FETCH_MAIN: b"",
            HEAD: LOCAL_REVISION,
            ORIGIN_MAIN: REMOTE_REVISION,
            COUNT_MAIN: b"0\t3\n",
            SHOW_SETTINGS_FILE: b'{"version": "1.4.1"}',
        }
        if key not in responses:
            raise AssertionError(f"unexpected git command: {cmd}")
        return responses[key], b""

    monkeypatch.setattr(updater, "_run_git", fake_run_git)

    result = run(updater._check_source_update(tmp_path, "1.3.4", branch="main"))

    assert result == updater.UpdateStatus(True, "1.3.4", "1.4.1", None)


def test_source_update_keeps_local_version_when_remote_version_unreadable(
    monkeypatch, tmp_path
):
    """An unreadable remote version must not produce a placeholder string."""

    async def fake_run_git(cmd, cwd):
        key = tuple(cmd)
        if key in (SHOW_VERSION_FILE, SHOW_SETTINGS_FILE):
            raise RuntimeError("no such path")
        responses = {
            **ON_MAIN,
            FETCH_MAIN: b"",
            HEAD: LOCAL_REVISION,
            ORIGIN_MAIN: REMOTE_REVISION,
            COUNT_MAIN: b"0\t3\n",
        }
        if key not in responses:
            raise AssertionError(f"unexpected git command: {cmd}")
        return responses[key], b""

    monkeypatch.setattr(updater, "_run_git", fake_run_git)

    assert run(
        updater._check_source_update(tmp_path, "1.3.4", branch="main")
    ) == updater.UpdateStatus(True, "1.3.4", "1.3.4", None)


def test_source_update_reports_no_update_when_level_with_main(monkeypatch, tmp_path):
    stub_git(
        monkeypatch,
        {
            **ON_MAIN,
            FETCH_MAIN: b"",
            HEAD: LOCAL_REVISION,
            ORIGIN_MAIN: LOCAL_REVISION,
        },
    )

    assert run(
        updater._check_source_update(tmp_path, "1.3.4", branch="main")
    ) == updater.UpdateStatus(False, "1.3.4", "1.3.4", None)


def test_source_update_declines_when_ahead_of_main(monkeypatch, tmp_path):
    """Local commits on main: ff-only cannot land, so offer nothing."""
    stub_git(
        monkeypatch,
        {
            **ON_MAIN,
            FETCH_MAIN: b"",
            HEAD: LOCAL_AHEAD_REVISION,
            ORIGIN_MAIN: REMOTE_REVISION,
            COUNT_MAIN: b"2\t0\n",
        },
    )

    assert run(
        updater._check_source_update(tmp_path, "1.3.4", branch="main")
    ) == updater.UpdateStatus(False, "1.3.4", "1.3.4", "main")


def test_source_update_declines_off_the_update_branch(monkeypatch, tmp_path):
    """A feature branch must never be offered an update that checks out main."""
    calls = stub_git(
        monkeypatch,
        {INSIDE_WORK_TREE: b"true\n", CURRENT_BRANCH: b"V1.4.2\n"},
    )

    assert run(
        updater._check_source_update(tmp_path, "1.4.2", branch="main")
    ) == updater.UpdateStatus(False, "1.4.2", "1.4.2", "V1.4.2")
    # Bails out before touching the network.
    assert FETCH_MAIN not in calls


def test_source_update_returns_none_outside_git_checkout(monkeypatch, tmp_path):
    async def fake_run_git(cmd, cwd):
        raise RuntimeError("not a git checkout")

    monkeypatch.setattr(updater, "_run_git", fake_run_git)

    assert run(updater._check_source_update(tmp_path, "1.3.4", branch="main")) is None


def test_check_for_update_prefers_the_checkout_over_release_tags(monkeypatch):
    """main is the source of truth: a higher stray tag must not override it."""

    async def level_with_main(project_root, current, branch=updater.UPDATE_BRANCH):
        return updater.UpdateStatus(False, current, current)

    async def newer_release_check(current):
        raise AssertionError("release check should not run for a git checkout")

    monkeypatch.setattr("app.config.get_app_version", lambda: "1.3.4")
    monkeypatch.setattr(updater, "_check_source_update", level_with_main)
    monkeypatch.setattr(updater, "_check_release_update", newer_release_check)

    assert run(updater.check_for_update()) == updater.UpdateStatus(
        False, "1.3.4", "1.3.4", None
    )


def test_check_for_update_reports_source_checkout_update(monkeypatch):
    async def fake_source_update(project_root, current, branch=updater.UPDATE_BRANCH):
        return updater.UpdateStatus(True, current, "1.4.1")

    async def unused_release_check(current):
        raise AssertionError("release check should not run for a git checkout")

    monkeypatch.setattr("app.config.get_app_version", lambda: "1.3.4")
    monkeypatch.setattr(updater, "_check_source_update", fake_source_update)
    monkeypatch.setattr(updater, "_check_release_update", unused_release_check)

    assert run(updater.check_for_update()) == updater.UpdateStatus(
        True, "1.3.4", "1.4.1", None
    )


def test_check_for_update_falls_back_to_release_tags(monkeypatch):
    """No checkout to compare against (frozen build): use the tag list."""

    async def no_source_update(project_root, current, branch=updater.UPDATE_BRANCH):
        return None

    async def fake_release_check(current):
        return updater.UpdateStatus(True, current, "1.3.5")

    monkeypatch.setattr("app.config.get_app_version", lambda: "1.3.4")
    monkeypatch.setattr(updater, "_check_source_update", no_source_update)
    monkeypatch.setattr(updater, "_check_release_update", fake_release_check)

    assert run(updater.check_for_update()) == updater.UpdateStatus(
        True, "1.3.4", "1.3.5", None
    )



def test_perform_update_launches_posix_script_with_current_python(monkeypatch):
    class ExitCalled(Exception):
        def __init__(self, code):
            self.code = code
            super().__init__(code)

    launched = {}

    def fake_popen(args, **kwargs):
        launched["args"] = args
        launched["kwargs"] = kwargs

    async def no_sleep(delay):
        return None

    def fake_exit(code):
        raise ExitCalled(code)

    project_root = Path(__file__).resolve().parent.parent
    updater_script = project_root / "scripts" / "updater.sh"

    monkeypatch.setattr(updater.sys, "platform", "linux")
    # _updater_script_path binds its `platform` default at import time, so
    # patching sys.platform alone is not enough on a win32 test host.
    monkeypatch.setattr(updater._updater_script_path, "__defaults__", ("linux",))
    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(updater.os, "_exit", fake_exit)

    with pytest.raises(ExitCalled) as exc_info:
        run(updater.perform_update())

    assert exc_info.value.code == 0
    assert launched["args"] == [
        "sh",
        str(updater_script),
        updater.UPDATE_BRANCH,
        updater.sys.executable,
    ]
    assert launched["kwargs"]["cwd"] == str(project_root)
    assert launched["kwargs"]["start_new_session"] is True


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("win32", "updater.bat"), ("darwin", "updater.sh"), ("linux", "updater.sh")],
)
def test_updater_script_path_is_platform_specific(platform, expected):
    assert updater._updater_script_path(Path("/repo"), platform).name == expected


def test_posix_updater_script_is_versioned():
    assert (Path(__file__).resolve().parent.parent / "scripts" / "updater.sh").is_file()
