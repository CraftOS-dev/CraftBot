"""Connect shows an app's approval page inside CraftBot only when the app allows it.

CraftBot reads the approval page's framing policy before showing it: an app
that lets CraftBot's page frame it is approved in place, any other app in a
tab as before. A policy CraftBot cannot read is treated as a refusal.
"""

import pytest
from multidict import CIMultiDict

from app.agent_app.framework_connections import frame_ancestors_allow

APP = "http://127.0.0.1:8097"
CRAFTBOT = "http://localhost:7925"
# What every Agent App sends unless its operator sets A2APP_FRAME_ANCESTORS.
DEFAULT = "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*"


def allows(*headers, embedder=CRAFTBOT, page=APP):
    return frame_ancestors_allow(CIMultiDict(headers), page, embedder)


def test_an_app_with_the_default_policy_is_approved_in_craftbot():
    assert allows(("Content-Security-Policy", DEFAULT))
    assert allows(("Content-Security-Policy", DEFAULT), embedder="http://127.0.0.1:7925")


def test_an_app_that_names_other_embedders_is_approved_in_a_tab():
    assert not allows(("Content-Security-Policy", DEFAULT), embedder="https://craftbot.example.com")
    assert not allows(("Content-Security-Policy", "frame-ancestors 'none'"))
    assert not allows(("Content-Security-Policy", "frame-ancestors"))
    assert not allows(("Content-Security-Policy", "frame-ancestors 'self'"))
    assert allows(("Content-Security-Policy", "frame-ancestors 'self'"), embedder=APP)


@pytest.mark.parametrize("source, embedder, expected", [
    ("*", CRAFTBOT, True),
    ("http:", CRAFTBOT, True),
    ("https:", CRAFTBOT, False),
    ("http:", "https://ui.example.com", True),
    ("https://*.example.com", "https://ui.example.com", True),
    ("https://*.example.com", "https://example.com", False),
    ("https://*.example.com", "http://ui.example.com", False),
    ("http://localhost:7925", CRAFTBOT, True),
    ("http://localhost:7926", CRAFTBOT, False),
    ("http://localhost", CRAFTBOT, False),
    ("localhost:*", CRAFTBOT, True),
    ("https://ui.example.com", "https://ui.example.com", True),
    ("https://ui.example.com/path", "https://ui.example.com", False),
])
def test_source_expressions(source, embedder, expected):
    assert allows(("Content-Security-Policy", f"frame-ancestors {source}"), embedder=embedder) is expected


def test_every_policy_must_allow_it():
    assert not allows(
        ("Content-Security-Policy", DEFAULT),
        ("Content-Security-Policy", "frame-ancestors https://ui.example.com"),
    )
    assert not allows(("Content-Security-Policy", f"{DEFAULT}, frame-ancestors 'none'"))


def test_without_frame_ancestors_x_frame_options_decides():
    assert allows()
    assert allows(("Content-Security-Policy", "default-src 'self'"))
    assert not allows(("X-Frame-Options", "DENY"))
    assert not allows(("Content-Security-Policy", "default-src 'self'"), ("X-Frame-Options", "SAMEORIGIN"))
    # frame-ancestors overrides X-Frame-Options, as browsers do.
    assert allows(("Content-Security-Policy", DEFAULT), ("X-Frame-Options", "DENY"))
