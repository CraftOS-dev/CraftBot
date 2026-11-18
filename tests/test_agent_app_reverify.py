"""A verification re-verifies from the last finished walk of a commit.

The walk-verify skill re-verifies only what changed since the commit the last
walk verified. CraftBot records that commit with each walk, and hands the
next walk the last finished one (pass, defects, or incomplete for the checks
the verifier did not reach) as its baseline.
"""

import subprocess

import pytest

from app.agent_app.framework_verification import baseline, verified_commit


def _git(path, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def app(tmp_path):
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / "tasks.md").write_text("- [ ] walk-verify\n")
    (tmp_path / "app.js").write_text("export const n = 1;\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "build")
    return tmp_path


def test_a_committed_app_verifies_its_head(app):
    assert verified_commit(app) == _git(app, "rev-parse", "HEAD")


def test_untracked_files_keep_the_commit(app):
    (app / "notes.txt").write_text("untracked\n")  # runtime state is often untracked
    assert verified_commit(app) == _git(app, "rev-parse", "HEAD")


@pytest.mark.parametrize("path", ["app.js", "reference/tasks.md"])
def test_any_uncommitted_change_has_no_verified_commit(app, path):
    (app / path).write_text("changed\n")
    assert verified_commit(app) is None


def test_an_app_without_its_own_repository_has_no_verified_commit(app, tmp_path):
    nested = app / "nested"
    nested.mkdir()
    assert verified_commit(nested) is None  # inside another repository
    assert verified_commit(tmp_path.parent / "no-such-app") is None


class _Host:
    def __init__(self, record, stored=None):
        self.record = record
        self.store = self
        self.stored = stored

    def verification(self, path):
        return self.record

    def get(self, kind, key):
        assert kind == "verification_baseline"
        return self.stored


@pytest.mark.parametrize("verdict", ["pass", "defects", "incomplete"])
def test_a_finished_walk_of_a_commit_is_the_baseline(verdict):
    # An incomplete walk the verifier finished itself names what it did not
    # reach, which the next walk checks; the rest it passed stays passed.
    record = {"verdict": verdict, "commit": "abc", "evidence": "report", "stamp": {}, "walked": True}
    assert baseline(_Host(record), "app") == {
        "verdict": verdict,
        "commit": "abc",
        "evidence": "report",
    }


@pytest.mark.parametrize(
    "record",
    [
        # Recorded by CraftBot for a crash, a cancel or an unreadable result: no walk.
        {"verdict": "incomplete", "commit": "def", "evidence": "cut short"},
        {"verdict": "blocked", "commit": "def", "evidence": "no browser"},
        {"verdict": "pass", "commit": None, "evidence": "uncommitted code"},
        None,
    ],
)
def test_otherwise_the_last_baseline_still_applies(record):
    kept = {"verdict": "pass", "commit": "abc", "evidence": "report"}
    assert baseline(_Host(record, kept), "app") == kept
    assert baseline(_Host(record), "app") is None
