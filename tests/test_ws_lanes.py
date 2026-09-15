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
    assert message_lane({"type": "agent_app_launch", "projectId": "p1"}) == "agent_app:p1"
    assert message_lane({"type": "agent_app_stop", "projectId": "p1"}) == "agent_app:p1"
    assert message_lane({"type": "agent_app_launch", "projectId": "p2"}) == "agent_app:p2"
    assert message_lane({"type": "agent_app_list"}) == "agent_app"


def test_settings_domains_are_independent_but_internally_serialized():
    assert message_lane({"type": "mcp_enable"}) == message_lane({"type": "mcp_remove"})
    assert message_lane({"type": "model_connection_test"}) == "model"
    assert message_lane({"type": "ollama_models_get"}) == "model"
    assert message_lane({"type": "skill_install"}) == "skills"
    assert message_lane({"type": "skill_meta_get"}) == "skills"
    assert message_lane({"type": "command_list"}) == "skills"
    assert message_lane({"type": "model_connection_test"}) != message_lane({"type": "mcp_enable"})


def test_unknown_types_keep_one_at_a_time_behaviour():
    assert message_lane({"type": "something_new"}) == GENERAL_LANE
    assert message_lane({}) == GENERAL_LANE
