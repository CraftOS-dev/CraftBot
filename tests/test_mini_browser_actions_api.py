"""Validation and the action entry point (app/mini_browser/actions_api.py)."""

import asyncio
import contextvars
import sys
from types import SimpleNamespace

import pytest

from app.mini_browser import DEFAULT_OWNER, actions_api
from app.mini_browser.errors import MiniBrowserError

validate = actions_api.validate


def _invalid(op, data):
    with pytest.raises(MiniBrowserError) as info:
        validate(op, data)
    assert info.value.code == "MINI_BROWSER_INVALID_INPUT"
    return info.value.fields["detail"]


# ── validate ────────────────────────────────────────────────────────────────


def test_numbers_are_clamped_to_their_ranges():
    assert (
        validate("navigate", {"url": "https://a.example", "timeout_ms": 10})[
            "timeout_ms"
        ]
        == 1000
    )
    assert (
        validate("navigate", {"url": "https://a.example", "timeout_ms": 10**9})[
            "timeout_ms"
        ]
        == 60000
    )
    assert (
        validate("navigate", {"url": "https://a.example", "timeout": "2500"})[
            "timeout_ms"
        ]
        == 2500
    )
    assert validate("navigate", {"url": "https://a.example"})["timeout_ms"] == 30000
    read = validate(
        "read", {"max_text_chars": 100, "max_elements": 0, "text_offset": -5}
    )
    assert read == {"max_text_chars": 500, "max_elements": 1, "text_offset": 0}
    read = validate("read", {"max_text_chars": 99999, "max_elements": 9999})
    assert read == {"max_text_chars": 8000, "max_elements": 500, "text_offset": 0}
    assert validate("read", {}) == {
        "max_text_chars": 4000,
        "max_elements": 150,
        "text_offset": 0,
    }
    assert validate("scroll", {"amount": 10})["amount"] == 50
    assert validate("scroll", {"amount": 99999, "direction": "Down"}) == {
        "direction": "down",
        "amount": 5000,
    }
    assert validate("scroll", {}) == {"direction": "down", "amount": None}


def test_wait_limits_depend_on_for_user():
    assert validate("wait", {}) == {
        "seconds": None,
        "text": None,
        "for_user": False,
        "timeout_ms": 10000,
    }
    assert validate("wait", {"seconds": -1})["seconds"] == 0.0
    assert validate("wait", {"seconds": "999"})["seconds"] == 60.0
    assert validate("wait", {"timeout_ms": 10**9})["timeout_ms"] == 60000
    assert validate("wait", {"for_user": True})["timeout_ms"] == 300000
    assert (
        validate("wait", {"for_user": "true", "timeout_ms": 10**9})["timeout_ms"]
        == 300000
    )
    assert validate("wait", {"for_user": True, "timeout_ms": 5})["timeout_ms"] == 1000
    assert "too long" in _invalid("wait", {"text": "x" * 1001})


def test_element_ids_accept_numbers_and_numeric_strings_only():
    for raw, expected in (
        (12, 12),
        ("12", 12),
        (" [12] ", 12),
        ("#7", 7),
        (3.0, 3),
        (0, 0),
    ):
        assert validate("click", {"element_id": raw})["element_id"] == expected
    for raw in (-1, True, 1.5, "abc", "", None, [1], float("nan"), 10**9):
        _invalid("click", {"element_id": raw})
    assert "required" in _invalid("hover", {})


def test_text_limits_and_types():
    assert (
        validate("type", {"element_id": 1, "text": "  keep spaces  "})["text"]
        == "  keep spaces  "
    )
    assert validate("type", {"element_id": 1, "text": ""})["text"] == ""
    assert validate("type", {"element_id": 1, "text": 42})["text"] == "42"
    assert (
        validate("type", {"element_id": 1, "text": "x" * 20000})["text"] == "x" * 20000
    )
    assert "too long" in _invalid("type", {"element_id": 1, "text": "x" * 20001})
    _invalid("type", {"element_id": 1, "text": ["a"]})
    _invalid("type", {"element_id": 1})
    params = validate(
        "type", {"element_id": "4", "text": "a", "submit": "false", "clear": "no"}
    )
    assert params == {"element_id": 4, "text": "a", "submit": False, "clear": False}
    assert validate("type", {"element_id": 4, "text": "a"})["clear"] is True
    _invalid("type", {"element_id": 4, "text": "a", "submit": "maybe"})


def test_keys_are_checked_and_normalised():
    assert validate("press_key", {"keys": "ctrl + a"}) == {
        "keys": "Control+a",
        "element_id": None,
    }
    assert validate("press_key", {"key": "Enter", "element_id": "2"}) == {
        "keys": "Enter",
        "element_id": 2,
    }
    assert "too long" in _invalid("press_key", {"keys": "a" * 65})
    _invalid("press_key", {"keys": "   "})
    _invalid("press_key", {})


def test_upload_paths():
    assert validate("upload_file", {"element_id": 1, "paths": "cv.pdf"})["paths"] == [
        "cv.pdf"
    ]
    assert validate("upload_file", {"element_id": 1, "path": " a.txt "})["paths"] == [
        "a.txt"
    ]
    assert (
        len(validate("upload_file", {"element_id": 1, "paths": ["f"] * 10})["paths"])
        == 10
    )
    assert "At most 10" in _invalid(
        "upload_file", {"element_id": 1, "paths": ["f"] * 11}
    )
    _invalid("upload_file", {"element_id": 1, "paths": []})
    _invalid("upload_file", {"element_id": 1, "paths": ["ok", 3]})
    _invalid("upload_file", {"element_id": 1, "paths": ["bad\x00name"]})
    _invalid("upload_file", {"element_id": 1})


def test_choices_flags_and_the_remaining_operations():
    assert validate("click", {"element_id": 1, "button": "RIGHT", "double": "yes"}) == {
        "element_id": 1,
        "button": "right",
        "double": True,
    }
    _invalid("click", {"element_id": 1, "button": "side"})
    _invalid("scroll", {"direction": "sideways"})
    assert validate("login", {}) == {"username": None, "submit": True}
    assert validate("login", {"username": " bob ", "submit": 0}) == {
        "username": "bob",
        "submit": False,
    }
    assert validate("screenshot", {"full_page": "1"}) == {"full_page": True}
    assert validate("select_option", {"element_id": 2, "value": 10}) == {
        "element_id": 2,
        "value": "10",
    }
    _invalid("select_option", {"element_id": 2})
    assert "Unknown Mini Browser operation" in _invalid("dance", {})
    assert validate("read", None) == validate("read", {})


def test_tabs_params():
    assert validate("tabs", {}) == {"action": "list", "tab": None, "url": None}
    assert validate("tabs", {"action": "Close"}) == {
        "action": "close",
        "tab": None,
        "url": None,
    }
    assert validate("tabs", {"action": "switch", "tab": "2"})["tab"] == 2
    assert "tab is required" in _invalid("tabs", {"action": "switch"})
    _invalid("tabs", {"action": "switch", "tab": -1})
    _invalid("tabs", {"action": "explode"})
    new = validate("tabs", {"action": "new", "url": "https://example.com/x"})
    assert new["url"] == "https://example.com/x"
    assert validate("tabs", {"action": "new"})["url"] is None


def test_navigate_resolves_with_history_and_search_allowed(monkeypatch):
    from app.mini_browser import urls

    assert validate("navigate", {"url": "Back"})["url"] == "back"
    assert (
        validate("navigate", {"url": "https://example.com/a?b=1"})["url"]
        == "https://example.com/a?b=1"
    )
    searched = validate("navigate", {"url": "best ramen in tokyo"})["url"]
    assert searched.startswith("https://duckduckgo.com/?q=") and "ramen" in searched
    with pytest.raises(MiniBrowserError) as info:
        validate("navigate", {"url": "javascript:alert(1)"})
    assert info.value.code == "MINI_BROWSER_BLOCKED_URL"
    context = {
        "search_url": "https://search.example/?q={query}",
        "allow_file": False,
        "ui_origins": frozenset({"127.0.0.1:7925"}),
    }
    assert validate("navigate", {"url": "two words"}, context)["url"].startswith(
        "https://search.example/?q="
    )
    with pytest.raises(MiniBrowserError) as info:
        validate("navigate", {"url": "http://127.0.0.1:7925/"}, context)
    assert info.value.code == "MINI_BROWSER_BLOCKED_URL"
    _invalid("navigate", {})

    calls = []

    def recorder(text, **kwargs):
        calls.append((text, kwargs))
        return urls.Target(kind="url", url="https://resolved.example/")

    monkeypatch.setattr(urls, "resolve", recorder)
    assert (
        validate("navigate", {"url": "x"}, context)["url"]
        == "https://resolved.example/"
    )
    validate("tabs", {"action": "new", "url": "y"}, context)
    (text, nav), (_t, tab) = calls
    assert nav == {
        "allow_history": True,
        "allow_search": True,
        "search_url": "https://search.example/?q={query}",
        "allow_file": False,
        "ui_origins": frozenset({"127.0.0.1:7925"}),
    }
    assert tab["allow_history"] is False and tab["allow_search"] is True


# ── run_action ──────────────────────────────────────────────────────────────


class _Core:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = (
            {"status": "success", "message": "ok"} if result is None else result
        )
        self.error = error

    async def agent_op(self, owner, op, params):
        self.calls.append((owner, op, params))
        if self.error is not None:
            raise self.error
        return self.result


class _Host:
    def __init__(self, core):
        self.core = core

    async def call(self, fn):
        return await fn(self.core)


@pytest.fixture
def host(monkeypatch):
    """A fake app.mini_browser.host whose get_host() returns a fake host."""
    state = SimpleNamespace(core=_Core(), started=0)

    def get_host():
        state.started += 1
        return _Host(state.core)

    monkeypatch.setitem(
        sys.modules, "app.mini_browser.host", SimpleNamespace(get_host=get_host)
    )
    monkeypatch.setattr(
        actions_api,
        "_load_url_context",
        lambda: {
            "search_url": actions_api.DEFAULT_SEARCH_URL,
            "allow_file": False,
            "ui_origins": frozenset(),
        },
    )
    return state


def test_simulated_mode_never_touches_the_browser(host):
    for op in actions_api.OPS:
        result = asyncio.run(
            actions_api.run_action(op, {"simulated_mode": True, "element_id": 1})
        )
        assert result["status"] == "success", op
    assert host.started == 0 and host.core.calls == []
    assert "page" in asyncio.run(
        actions_api.run_action("click", {"simulated_mode": True})
    )
    assert "note" in asyncio.run(
        actions_api.run_action("read", {"simulated_mode": True})
    )


def test_run_action_routes_to_the_callers_own_tab(host):
    result = asyncio.run(
        actions_api.run_action(
            "click", {"element_id": "3", "_session_id": "chat42", "button": "left"}
        )
    )
    assert result == {"status": "success", "message": "ok"}
    assert host.core.calls == [
        ("chat42", "click", {"element_id": 3, "button": "left", "double": False})
    ]


def test_owner_falls_back_to_the_action_context_then_the_default(host, monkeypatch):
    var = contextvars.ContextVar("current_input_data", default=None)
    monkeypatch.setitem(
        sys.modules,
        actions_api._CONTEXT_MODULE,
        SimpleNamespace(current_input_data=var),
    )

    async def with_context():
        var.set({"_session_id": "sub_1234"})
        return await actions_api.run_action("read", {})

    asyncio.run(with_context())
    asyncio.run(actions_api.run_action("read", {"_session_id": "   "}))
    monkeypatch.delitem(sys.modules, actions_api._CONTEXT_MODULE)
    asyncio.run(actions_api.run_action("read", {"_session_id": 5}))
    owners = [call[0] for call in host.core.calls]
    assert owners == ["sub_1234", DEFAULT_OWNER, DEFAULT_OWNER]


def test_invalid_input_is_answered_without_starting_the_browser(host):
    result = asyncio.run(actions_api.run_action("click", {"element_id": "x"}))
    assert result["status"] == "error"
    assert result["error_code"] == "MINI_BROWSER_INVALID_INPUT"
    assert "element_id" in result["message"]
    assert host.started == 0


def test_errors_from_the_browser_are_mapped(host):
    host.core.error = MiniBrowserError("MINI_BROWSER_USER_IN_CONTROL")
    result = asyncio.run(actions_api.run_action("click", {"element_id": 1}))
    assert (
        result["status"] == "error"
        and result["error_code"] == "MINI_BROWSER_USER_IN_CONTROL"
    )
    assert result["error_category"] and result["message"]

    host.core.error = RuntimeError("driver exploded\nTraceback line two")
    result = asyncio.run(actions_api.run_action("click", {"element_id": 1}))
    assert result["error_code"] == "MINI_BROWSER_INTERNAL"
    assert (
        "driver exploded" in result["message"] and "line two" not in result["message"]
    )

    host.core.error = None
    host.core.result = "not a dict"
    result = asyncio.run(actions_api.run_action("click", {"element_id": 1}))
    assert result["error_code"] == "MINI_BROWSER_INTERNAL"


def test_a_failing_host_start_is_an_internal_error(monkeypatch):
    def broken():
        raise OSError("cannot start thread")

    monkeypatch.setitem(
        sys.modules, "app.mini_browser.host", SimpleNamespace(get_host=broken)
    )
    result = asyncio.run(actions_api.run_action("read", {}))
    assert (
        result["status"] == "error" and result["error_code"] == "MINI_BROWSER_INTERNAL"
    )


def test_cancellation_still_propagates(host):
    host.core.error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(actions_api.run_action("read", {}))


def test_url_operations_use_the_live_settings_and_ui_origins(monkeypatch):
    core = _Core()
    monkeypatch.setitem(
        sys.modules,
        "app.mini_browser.host",
        SimpleNamespace(get_host=lambda: _Host(core)),
    )
    from app.mini_browser import config

    monkeypatch.setattr(
        config,
        "load_settings",
        lambda: SimpleNamespace(
            search_url="https://find.example/?q={query}", allow_file_urls=False
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.mini_browser.bridge",
        SimpleNamespace(ui_origins=lambda: frozenset({"localhost:7925"})),
    )
    import app.mini_browser as package

    monkeypatch.setattr(
        package, "bridge", sys.modules["app.mini_browser.bridge"], raising=False
    )

    asyncio.run(
        actions_api.run_action("navigate", {"url": "cheap flights", "_session_id": "s"})
    )
    assert core.calls[0][2]["url"].startswith("https://find.example/?q=cheap")

    blocked = asyncio.run(
        actions_api.run_action("navigate", {"url": "http://localhost:7925/x"})
    )
    assert blocked["error_code"] == "MINI_BROWSER_BLOCKED_URL"
    assert len(core.calls) == 1
