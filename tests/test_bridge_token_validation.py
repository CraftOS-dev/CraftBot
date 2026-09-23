"""validate_bridge_token: the integration bridge's only authentication.

An Agent App backend presents this token to POST /api/integrations/proxy,
which then injects the user's real OAuth credentials into an outbound call.
The token therefore guards every connected integration, and it is compared
against a value an attacker supplies in an HTTP header -- so the comparison
has to be constant-time, and it has to survive whatever bytes arrive.
"""

import types

import pytest

from app.agent_app.manager import AgentAppManager

TOKEN = "kR3n-9bQwTf1xZa7LmPd0sVhYcE2gJu4"


@pytest.fixture
def manager():
    mgr = AgentAppManager.__new__(AgentAppManager)  # no filesystem, no ports
    mgr.projects = {
        "alpha": types.SimpleNamespace(bridge_token=TOKEN),
        "beta": types.SimpleNamespace(bridge_token="another-token-entirely"),
        "gamma": types.SimpleNamespace(bridge_token=""),  # never launched
    }
    return mgr


def test_the_right_token_resolves_to_its_project(manager):
    assert manager.validate_bridge_token(TOKEN) == "alpha"
    assert manager.validate_bridge_token("another-token-entirely") == "beta"


@pytest.mark.parametrize(
    "presented",
    [
        "",
        None,
        "wrong",
        TOKEN[:-1],  # prefix
        TOKEN + "x",  # extension
        TOKEN[:-1] + "X",  # last character differs
        TOKEN.upper(),  # case
        " " + TOKEN,  # leading space
        TOKEN + " ",  # trailing space
    ],
)
def test_anything_else_is_refused(manager, presented):
    assert manager.validate_bridge_token(presented) is None


def test_a_project_with_no_token_is_never_matched(manager):
    """An empty bridge_token means 'not launched'. Presenting '' must not
    match it -- that would hand out a project id for free."""
    assert manager.validate_bridge_token("") is None


@pytest.mark.parametrize(
    "presented",
    [
        "tökén-with-non-ascii",
        "\udcff\udcfe",  # lone surrogates, as a mangled header can carry
        "x" * 10000,  # absurd length
        "null\x00byte",
    ],
)
def test_hostile_input_is_refused_without_raising(manager, presented):
    """hmac.compare_digest rejects non-ASCII str outright, so the comparison
    works on bytes. A caller controls this value; it must not be able to turn
    a failed auth into a 500."""
    assert manager.validate_bridge_token(presented) is None


def test_no_project_at_all(manager):
    manager.projects = {}
    assert manager.validate_bridge_token(TOKEN) is None
