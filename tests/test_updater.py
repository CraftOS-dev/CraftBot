# -*- coding: utf-8 -*-

import asyncio
from pathlib import Path

import pytest

from app import updater


INSIDE_WORK_TREE = ("git", "rev-parse", "--is-inside-work-tree")
FETCH_MAIN = ("git", "fetch", "origin", "main:refs/remotes/origin/main")
HEAD = ("git", "rev-parse", "HEAD")
ORIGIN_MAIN = ("git", "rev-parse", "origin/main")
COUNT_MAIN = ("git", "rev-list", "--left-right", "--count", "HEAD...origin/main")

LOCAL_REVISION = b"1111111111111111111111111111111111111111\n"
REMOTE_REVISION = b"2222222222222222222222222222222222222222\n"
LOCAL_AHEAD_REVISION = b"3333333333333333333333333333333333333333\n"


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


def test_source_update_detects_remote_main_ahead(monkeypatch, tmp_path):
    calls = stub_git(
        monkeypatch,
        {
            INSIDE_WORK_TREE: b"true\n",
            FETCH_MAIN: b"",
            HEAD: LOCAL_REVISION,
            ORIGIN_MAIN: REMOTE_REVISION,
            COUNT_MAIN: b"0\t3\n",
        },
    )

    result = run(updater._check_source_update(tmp_path, "1.3.4", branch="main"))

    assert result == (True, "1.3.4", "1.3.4+main.2222222")
    assert FETCH_MAIN in calls


@pytest.mark.parametrize(
    ("local_revision", "remote_revision", "count_output"),
    [
        (LOCAL_REVISION, LOCAL_REVISION, None),
        (LOCAL_AHEAD_REVISION, REMOTE_REVISION, b"2\t0\n"),
    ],
)
def test_source_update_reports_no_update_without_remote_commits(
    monkeypatch, tmp_path, local_revision, remote_revision, count_output
):
    responses = {
        INSIDE_WORK_TREE: b"true\n",
        FETCH_MAIN: b"",
        HEAD: local_revision,
        ORIGIN_MAIN: remote_revision,
    }
    if count_output is not None:
        responses[COUNT_MAIN] = count_output
    stub_git(monkeypatch, responses)

    assert run(updater._check_source_update(tmp_path, "1.3.4", branch="main")) == (
        False,
        "1.3.4",
        "1.3.4",
    )


def test_source_update_returns_none_outside_git_checkout(monkeypatch, tmp_path):
    async def fake_run_git(cmd, cwd):
        raise RuntimeError("not a git checkout")

    monkeypatch.setattr(updater, "_run_git", fake_run_git)

    assert run(updater._check_source_update(tmp_path, "1.3.4", branch="main")) is None


def test_check_for_update_prefers_release_tag_when_semver_is_newer(monkeypatch):
    async def fail_source_update(project_root, current, branch=updater.UPDATE_BRANCH):
        raise AssertionError("source check should not run when release is newer")

    async def newer_release_check(current):
        return True, current, "1.3.5"

    monkeypatch.setattr("app.config.get_app_version", lambda: "1.3.4")
    monkeypatch.setattr(updater, "_check_source_update", fail_source_update)
    monkeypatch.setattr(updater, "_check_release_update", newer_release_check)

    assert run(updater.check_for_update()) == (True, "1.3.4", "1.3.5")


def test_check_for_update_uses_source_checkout_when_release_tag_is_current(monkeypatch):
    async def fake_source_update(project_root, current, branch=updater.UPDATE_BRANCH):
        return True, current, "1.3.4+main.2222222"

    async def current_release_check(current):
        return False, current, current

    monkeypatch.setattr("app.config.get_app_version", lambda: "1.3.4")
    monkeypatch.setattr(updater, "_check_source_update", fake_source_update)
    monkeypatch.setattr(updater, "_check_release_update", current_release_check)

    assert run(updater.check_for_update()) == (
        True,
        "1.3.4",
        "1.3.4+main.2222222",
    )


def test_check_for_update_falls_back_to_release_tags(monkeypatch):
    async def no_source_update(project_root, current, branch=updater.UPDATE_BRANCH):
        return None

    async def fake_release_check(current):
        return False, current, "1.3.4"

    monkeypatch.setattr("app.config.get_app_version", lambda: "1.3.4")
    monkeypatch.setattr(updater, "_check_source_update", no_source_update)
    monkeypatch.setattr(updater, "_check_release_update", fake_release_check)

    assert run(updater.check_for_update()) == (False, "1.3.4", "1.3.4")


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
