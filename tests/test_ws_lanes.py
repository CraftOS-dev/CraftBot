"""Concurrency lanes for browser WebSocket messages."""

from app.ui_layer.adapters.ws_lanes import GENERAL_LANE, message_lane


def test_session_messages_share_a_lane_per_session():
    assert message_lane({"type": "message", "sessionId": "s1"}) == "session:s1"
    assert message_lane({"type": "session_rename", "sessionId": "s1"}) == "session:s1"
    assert message_lane({"type": "chat_history", "sessionId": "s2"}) == "session:s2"
    assert message_lane({"type": "message"}) == "session:main"


def test_stop_never_waits_behind_session_work():
    assert message_lane({"type": "session_stop", "sessionId": "s1"}) != message_lane(
        {"type": "message", "sessionId": "s1"}
    )


def test_agent_app_messages_are_serialized_per_project():
    assert (
        message_lane({"type": "agent_app_launch", "projectId": "p1"}) == "agent_app:p1"
    )
    assert message_lane({"type": "agent_app_stop", "projectId": "p1"}) == "agent_app:p1"
    assert (
        message_lane({"type": "agent_app_launch", "projectId": "p2"}) == "agent_app:p2"
    )
    assert message_lane({"type": "agent_app_list"}) == "agent_app"


def test_settings_domains_are_independent_but_internally_serialized():
    assert message_lane({"type": "mcp_enable"}) == message_lane({"type": "mcp_remove"})
    assert message_lane({"type": "model_connection_test"}) == "model"
    assert message_lane({"type": "ollama_models_get"}) == "model"
    assert message_lane({"type": "skill_install"}) == "skills"
    assert message_lane({"type": "skill_meta_get"}) == "skills"
    assert message_lane({"type": "command_list"}) == "skills"
    assert message_lane({"type": "model_connection_test"}) != message_lane(
        {"type": "mcp_enable"}
    )


def test_unknown_types_keep_one_at_a_time_behaviour():
    assert message_lane({"type": "something_new"}) == GENERAL_LANE
    assert message_lane({}) == GENERAL_LANE


def test_mini_browser_lanes():
    # Viewers and view settings share one lane.
    for msg_type in (
        "mini_browser_subscribe",
        "mini_browser_unsubscribe",
        "mini_browser_resize",
        "mini_browser_view",
        "mini_browser_start",
        "mini_browser_copy",
        "mini_browser_adblock",
    ):
        assert message_lane({"type": msg_type}) == "mini_browser", msg_type
    # Live input keeps its order in a lane of its own (LANE-1).
    assert message_lane({"type": "mini_browser_input"}) == "mini_browser_input"
    # Closing the browser and taking / handing back control never wait
    # behind input or each other.
    assert message_lane({"type": "mini_browser_control"}) == "mini_browser_control"
    assert message_lane({"type": "mini_browser_shutdown"}) == "mini_browser_shutdown"
    # The vault prefix is matched before the general Mini Browser prefix.
    for msg_type in (
        "mini_browser_vault_list",
        "mini_browser_vault_add",
        "mini_browser_vault_update",
        "mini_browser_vault_delete",
        "mini_browser_vault_reset",
    ):
        assert message_lane({"type": msg_type}) == "mini_browser_vault", msg_type
    for msg_type in (
        "mini_browser_navigate",
        "mini_browser_history",
        "mini_browser_tab",
    ):
        assert message_lane({"type": msg_type}) == "mini_browser_nav", msg_type
    assert message_lane({"type": "mini_browser_install"}) == "mini_browser_install"


def test_slow_mini_browser_work_never_blocks_input_or_the_vault():
    lanes = {
        message_lane({"type": t})
        for t in (
            "mini_browser_input",
            "mini_browser_navigate",
            "mini_browser_vault_list",
            "mini_browser_install",
        )
    }
    assert len(lanes) == 4
    assert GENERAL_LANE not in lanes


def test_mini_browser_controls_never_wait_behind_input():
    """LANE-1: a hung page backs up live input; Close browser and Take
    control / Hand back must not queue behind it (or behind each other)."""
    lanes = [
        message_lane({"type": t})
        for t in (
            "mini_browser_input",
            "mini_browser_control",
            "mini_browser_shutdown",
            "mini_browser_view",
        )
    ]
    assert len(set(lanes)) == len(lanes)
