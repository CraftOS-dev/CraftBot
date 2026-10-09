# -*- coding: utf-8 -*-
"""Managed-install upgrades: app/state_sync.py and run.py's _bootstrap_state.

A managed install copies app/data, app/config and skills into the per-user
state directory once. These tests pin that an upgrade still delivers what is
NEW in a release (the Mini Browser's action file and skill, the whitelist
entry enabling the skill) without ever overwriting a user's file, restoring a
file the user deleted, or re-enabling a skill the user turned off.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import state_sync
from app.state_sync import MANIFEST_RELPATH, SKILLS_CONFIG_RELPATH, sync_shipped_files

REPO_ROOT = Path(__file__).resolve().parent.parent

OLD_ENABLED = ["docx", "pdf", "playwright-mcp"]
NEW_ENABLED = ["docx", "pdf", "mini-browser", "playwright-mcp"]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _skills_config(enabled, disabled=()) -> str:
    return json.dumps(
        {
            "auto_load": True,
            "enabled_skills": list(enabled),
            "disabled_skills": list(disabled),
            "project_skills_dir": "skills",
        },
        indent=2,
    )


def _make_code(root: Path, *, release: int = 2) -> Path:
    """A shipped code tree. Release 1 predates the Mini Browser."""
    _write(root / "app/data/action/web_fetch.py", f"# web_fetch v{release}\n")
    _write(root / "app/data/action/action_set_management.py", "# sets\n")
    _write(root / "app/data/action/integrations/slack.py", "# slack\n")
    _write(root / "skills/pdf/SKILL.md", "---\nname: pdf\n---\n")
    _write(root / "skills/docx/SKILL.md", "---\nname: docx\n---\n")
    _write(root / "skills/playwright-mcp/SKILL.md", "---\nname: playwright-mcp\n---\n")
    # Never shipped: caches.
    _write(root / "app/data/action/__pycache__/web_fetch.cpython-310.pyc", "x")
    _write(root / "skills/pdf/helper.pyc", "x")
    enabled = OLD_ENABLED
    if release >= 2:
        _write(root / "app/data/action/mini_browser_actions.py", "# mini browser\n")
        _write(root / "skills/mini-browser/SKILL.md", "---\nname: mini-browser\n---\n")
        _write(root / "skills/mini-browser/reference/tabs.md", "tabs\n")
        enabled = NEW_ENABLED
    if release >= 3:
        _write(root / "app/data/action/weather_actions.py", "# weather\n")
        _write(root / "skills/mini-browser/reference/logins.md", "logins\n")
        _write(root / "skills/new-skill/SKILL.md", "---\nname: new-skill\n---\n")
        enabled = enabled + ["new-skill"]
    _write(root / SKILLS_CONFIG_RELPATH, _skills_config(enabled, ["slack"]))
    return root


def _seed_state(code: Path, state: Path) -> Path:
    """What run.py's first-run bootstrap leaves behind: whole-tree copies."""
    for rel in ("app/data", "app/config", "skills"):
        shutil.copytree(code / rel, state / rel)
    return state


def _manifest(state: Path) -> dict:
    return json.loads((state / MANIFEST_RELPATH).read_text(encoding="utf-8"))


def _enabled(state: Path):
    data = json.loads((state / SKILLS_CONFIG_RELPATH).read_text(encoding="utf-8"))
    return data["enabled_skills"], data["disabled_skills"]


@pytest.fixture
def trees(tmp_path):
    return SimpleNamespace(code=tmp_path / "code", state=tmp_path / "state", logs=[])


def _sync(t):
    return sync_shipped_files(t.code, t.state, log=t.logs.append)


# ── fresh install ───────────────────────────────────────────────────────


def test_fresh_install_copies_nothing_and_records_the_shipped_files(trees):
    _make_code(trees.code)
    _seed_state(trees.code, trees.state)

    report = _sync(trees)

    assert report["first_run"] is True
    assert report["copied"] == [] and report["skills_enabled"] == []
    assert report["manifest_written"] is True
    files = _manifest(trees.state)["files"]
    assert "app/data/action/mini_browser_actions.py" in files
    assert "skills/mini-browser/reference/tabs.md" in files
    assert not [f for f in files if "__pycache__" in f or f.endswith(".pyc")]
    assert _enabled(trees.state)[0] == NEW_ENABLED
    assert trees.logs == []  # nothing worth telling the user

    # A second start changes nothing and does not even rewrite the manifest.
    again = _sync(trees)
    assert again["first_run"] is False
    assert again["copied"] == [] and again["manifest_written"] is False


# ── upgrade from a release without a manifest ───────────────────────────


def test_upgrade_brings_new_actions_and_skills_and_enables_the_skill(trees):
    _seed_state(_make_code(trees.code, release=1), trees.state)
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=2)  # the installer replaced CODE

    report = _sync(trees)

    assert report["first_run"] is True
    assert sorted(report["copied"]) == [
        "app/data/action/mini_browser_actions.py",
        "skills/mini-browser/SKILL.md",
        "skills/mini-browser/reference/tabs.md",
    ]
    assert (trees.state / "app/data/action/mini_browser_actions.py").is_file()
    # A changed built-in is NOT overwritten (the user may have edited it).
    assert (trees.state / "app/data/action/web_fetch.py").read_text() == (
        "# web_fetch v1\n"
    )
    enabled, disabled = _enabled(trees.state)
    assert enabled == OLD_ENABLED + ["mini-browser"]
    assert disabled == ["slack"]
    assert report["skills_enabled"] == ["mini-browser"]
    assert any("mini_browser_actions.py" in line for line in trees.logs)
    assert any("mini-browser" in line for line in trees.logs)
    manifest = _manifest(trees.state)
    assert "mini-browser" in manifest["skills_offered"]


def test_later_release_copies_only_files_new_since_the_manifest(trees):
    _make_code(trees.code, release=2)
    _seed_state(trees.code, trees.state)
    _sync(trees)  # release 2 recorded

    # The user removed an action they did not want...
    (trees.state / "app/data/action/action_set_management.py").unlink()
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=3)

    report = _sync(trees)

    assert report["first_run"] is False
    assert sorted(report["copied"]) == [
        "app/data/action/weather_actions.py",
        "skills/mini-browser/reference/logins.md",
        "skills/new-skill/SKILL.md",
    ]
    # ...and it stays removed: it was recorded before they deleted it.
    assert not (trees.state / "app/data/action/action_set_management.py").exists()
    assert _enabled(trees.state)[0] == NEW_ENABLED + ["new-skill"]
    assert "app/data/action/weather_actions.py" in _manifest(trees.state)["files"]


# ── user deletions and edits ────────────────────────────────────────────


def test_files_and_skill_folders_the_user_deleted_are_never_restored(trees):
    _make_code(trees.code, release=2)
    _seed_state(trees.code, trees.state)
    _sync(trees)

    (trees.state / "app/data/action/mini_browser_actions.py").unlink()
    shutil.rmtree(trees.state / "skills/mini-browser")
    for _ in range(2):
        report = _sync(trees)
        assert report["copied"] == []
    assert not (trees.state / "app/data/action/mini_browser_actions.py").exists()
    assert not (trees.state / "skills/mini-browser").exists()

    # A file NEW in a later release, inside the folder the user removed,
    # does not resurrect the folder either; a brand-new skill does arrive.
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=3)
    report = _sync(trees)
    assert "skills/mini-browser/reference/logins.md" in report["skipped_removed"]
    assert not (trees.state / "skills/mini-browser").exists()
    assert (trees.state / "skills/new-skill/SKILL.md").is_file()
    # Respecting the removal is final: no retry, no log spam next start.
    assert _sync(trees)["skipped_removed"] == []


def test_user_edited_files_are_never_overwritten(trees):
    _make_code(trees.code, release=2)
    _seed_state(trees.code, trees.state)
    _write(trees.state / "app/data/action/mini_browser_actions.py", "# my tweaks\n")
    _write(trees.state / "skills/mini-browser/SKILL.md", "my skill\n")

    _sync(trees)  # first run: no manifest yet
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=3)
    _sync(trees)

    assert (trees.state / "app/data/action/mini_browser_actions.py").read_text() == (
        "# my tweaks\n"
    )
    assert (trees.state / "skills/mini-browser/SKILL.md").read_text() == "my skill\n"


# ── skills_config.json ──────────────────────────────────────────────────


def test_a_skill_the_user_disabled_is_never_reenabled(trees):
    _seed_state(_make_code(trees.code, release=1), trees.state)
    # The user (or /skill disable) turned the skill off before upgrading.
    _write(
        trees.state / SKILLS_CONFIG_RELPATH,
        _skills_config(OLD_ENABLED, ["slack", "mini-browser"]),
    )
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=2)

    report = _sync(trees)

    assert report["skills_enabled"] == []
    enabled, disabled = _enabled(trees.state)
    assert "mini-browser" not in enabled and "mini-browser" in disabled


def test_a_skill_removed_from_the_whitelist_after_it_was_offered_stays_off(trees):
    _seed_state(_make_code(trees.code, release=1), trees.state)
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=2)
    _sync(trees)  # offers and enables mini-browser
    # A hand edit drops it from enabled_skills without listing it as disabled.
    _write(trees.state / SKILLS_CONFIG_RELPATH, _skills_config(OLD_ENABLED, ["slack"]))

    report = _sync(trees)

    assert report["skills_enabled"] == []
    assert "mini-browser" not in _enabled(trees.state)[0]


def test_skill_names_match_case_insensitively(trees):
    _seed_state(_make_code(trees.code, release=1), trees.state)
    _write(
        trees.state / SKILLS_CONFIG_RELPATH,
        _skills_config(OLD_ENABLED, ["Mini-Browser"]),
    )
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=2)
    assert _sync(trees)["skills_enabled"] == []


def test_an_empty_whitelist_is_left_alone(trees):
    _seed_state(_make_code(trees.code, release=1), trees.state)
    _write(trees.state / SKILLS_CONFIG_RELPATH, _skills_config([], ["slack"]))
    before = (trees.state / SKILLS_CONFIG_RELPATH).read_text()
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=2)

    report = _sync(trees)

    assert report["skills_enabled"] == []  # empty list = every skill enabled
    assert (trees.state / SKILLS_CONFIG_RELPATH).read_text() == before


def test_an_unreadable_skills_config_is_untouched_and_retried(trees):
    _seed_state(_make_code(trees.code, release=1), trees.state)
    _write(trees.state / SKILLS_CONFIG_RELPATH, "{ not json")
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=2)

    report = _sync(trees)

    assert report["skills_enabled"] == []
    assert (trees.state / SKILLS_CONFIG_RELPATH).read_text() == "{ not json"
    assert any("could not be read" in line for line in trees.logs)
    assert "mini-browser" not in _manifest(trees.state)["skills_offered"]

    # Once the user repairs the file, the next start enables the skill.
    _write(trees.state / SKILLS_CONFIG_RELPATH, _skills_config(OLD_ENABLED))
    assert _sync(trees)["skills_enabled"] == ["mini-browser"]


# ── robustness ──────────────────────────────────────────────────────────


def test_a_corrupt_manifest_is_rebuilt(trees):
    _make_code(trees.code, release=2)
    _seed_state(trees.code, trees.state)
    (trees.state / "skills/mini-browser/reference/tabs.md").unlink()
    _write(trees.state / MANIFEST_RELPATH, "\x00garbage")

    report = _sync(trees)

    assert report["first_run"] is True
    assert report["copied"] == ["skills/mini-browser/reference/tabs.md"]
    assert any("unreadable" in line for line in trees.logs)
    manifest = _manifest(trees.state)
    assert manifest["version"] == 1
    assert "skills/mini-browser/reference/tabs.md" in manifest["files"]


@pytest.mark.parametrize(
    "content", ['{"files": "nope", "skills_offered": []}', "[]", '{"files": []}']
)
def test_a_manifest_of_the_wrong_shape_counts_as_missing(trees, content):
    _make_code(trees.code, release=2)
    _seed_state(trees.code, trees.state)
    _write(trees.state / MANIFEST_RELPATH, content)
    assert _sync(trees)["first_run"] is True
    assert isinstance(_manifest(trees.state)["files"], list)


def test_a_failed_copy_is_retried_at_the_next_start(trees):
    _make_code(trees.code, release=2)
    _seed_state(trees.code, trees.state)
    _sync(trees)
    shutil.rmtree(trees.code)
    _make_code(trees.code, release=3)
    # Something in the way: the new skill's folder name is taken by a file.
    _write(trees.state / "skills/new-skill", "in the way")

    report = _sync(trees)

    assert report["failed"] == ["skills/new-skill/SKILL.md"]
    assert "skills/new-skill/SKILL.md" not in _manifest(trees.state)["files"]
    (trees.state / "skills/new-skill").unlink()
    assert _sync(trees)["copied"] == ["skills/new-skill/SKILL.md"]


def test_never_raises(trees, tmp_path):
    _make_code(trees.code, release=2)

    def exploding_log(message):
        raise RuntimeError("log sink broken")

    # STATE is a file: every write fails; CODE is missing; the log raises.
    blocker = _write(tmp_path / "state_is_a_file", "x")
    report = sync_shipped_files(trees.code, blocker, log=exploding_log)
    assert report["copied"] == [] and report["manifest_written"] is False
    report = sync_shipped_files(tmp_path / "missing", trees.state, log=exploding_log)
    assert report["copied"] == []
    report = sync_shipped_files(None, None, log=exploding_log)  # type: ignore[arg-type]
    assert report["copied"] == []


def test_a_checkout_is_left_alone(tmp_path):
    root = _make_code(tmp_path / "repo", release=2)
    report = sync_shipped_files(root, root, log=lambda m: None)
    assert report["manifest_written"] is False
    assert not (root / MANIFEST_RELPATH).exists()


def test_the_real_shipped_tree_includes_the_mini_browser_without_caches():
    shipped = set(state_sync._shipped_files(REPO_ROOT, log=lambda m: None))
    assert "app/data/action/mini_browser_actions.py" in shipped
    assert "skills/mini-browser/SKILL.md" in shipped
    assert not [p for p in shipped if "__pycache__" in p or p.endswith(".pyc")]
    shipped_config = json.loads((REPO_ROOT / SKILLS_CONFIG_RELPATH).read_text("utf-8"))
    assert "mini-browser" in shipped_config["enabled_skills"]


# ── run.py wiring ───────────────────────────────────────────────────────


def _bootstrap_state_function(fake_paths):
    """run.py's real _bootstrap_state, compiled against a fake app.paths.

    Importing run.py would bootstrap the developer's real state directory;
    only the function itself is taken from its source.
    """
    source = (REPO_ROOT / "run.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    [node] = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_bootstrap_state"
    ]
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"os": os, "_paths": fake_paths, "print": lambda *a, **k: None}
    exec(compile(module, str(REPO_ROOT / "run.py"), "exec"), namespace)
    return namespace["_bootstrap_state"]


def test_run_py_bootstrap_syncs_an_upgraded_install(tmp_path, monkeypatch):
    code = tmp_path / "code"
    state = tmp_path / "state"
    _seed_state(_make_code(code, release=1), state)
    shutil.rmtree(code)
    _make_code(code, release=2)
    monkeypatch.chdir(tmp_path)  # _bootstrap_state chdirs; restored afterwards
    fake_paths = SimpleNamespace(
        is_dev_checkout=lambda: False, CODE_ROOT=code, STATE_ROOT=state
    )

    _bootstrap_state_function(fake_paths)()

    assert (state / "app/data/action/mini_browser_actions.py").is_file()
    assert "mini-browser" in _enabled(state)[0]
    assert (state / MANIFEST_RELPATH).is_file()
