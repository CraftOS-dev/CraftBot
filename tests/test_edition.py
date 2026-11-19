"""The edition switch: one backend, a browser or a terminal in front of it."""

import pytest

from app import edition
from app.action.action_set import action_set_manager


def test_unset_means_the_browser_edition(monkeypatch):
    monkeypatch.delenv(edition.ENV_VAR, raising=False)
    assert edition.current() == edition.BROWSER
    assert not edition.is_terminal()
    assert edition.excluded_actions() == frozenset()


def test_terminal_edition(monkeypatch):
    monkeypatch.setenv(edition.ENV_VAR, "terminal")
    assert edition.current() == edition.TERMINAL
    assert edition.is_terminal()
    assert "render_ui" in edition.excluded_actions()


def test_an_unknown_edition_fails_loudly(monkeypatch):
    monkeypatch.setenv(edition.ENV_VAR, "cli")
    with pytest.raises(ValueError, match="not a CraftBot edition"):
        edition.current()


def test_terminal_client_bundle_lives_in_the_terminal_package():
    bundle = edition.terminal_client_bundle()
    assert bundle.name == "craftbot-tui.mjs"
    assert bundle.parent.parent == edition.terminal_client_dir()
    assert edition.terminal_client_dir().parts[-3:] == ("app", "ui_layer", "terminal")


def test_render_ui_is_compiled_only_in_the_browser_edition(monkeypatch):
    import app.data.action.render_ui  # noqa: F401  (registers the action)

    monkeypatch.setenv(edition.ENV_VAR, "browser")
    assert "render_ui" in action_set_manager.compile_action_list([])

    monkeypatch.setenv(edition.ENV_VAR, "terminal")
    terminal_actions = action_set_manager.compile_action_list([])
    assert "render_ui" not in terminal_actions
    # Only the browser-only action goes; the rest of core stays.
    monkeypatch.setenv(edition.ENV_VAR, "browser")
    browser_actions = action_set_manager.compile_action_list([])
    assert set(browser_actions) - set(terminal_actions) == {"render_ui"}
