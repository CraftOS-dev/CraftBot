"""Opt-in Telegram transport/owner routing checks, without an LLM.

Set CRAFTBOT_TELEGRAM_TEST_TOKEN and CRAFTBOT_TELEGRAM_TEST_CHAT_ID, then
run pytest -m live tests/e2e/test_live_telegram_feedback.py. The bot must
have an incoming test message. This sends a test reply in that chat.
Credentials, owner configuration and app state are isolated in tmp_path.
"""

import asyncio
import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.live


def test_live_owner_routing_typing_and_delivery(tmp_path, monkeypatch):
    from agent_core.core.impl.action.context import (
        current_input_data,
        current_message_origin,
    )
    from app.agent_base import AgentBase
    from app.agent_app import (
        AgentAppManager,
        set_agent_app_manager,
        get_agent_app_manager,
    )
    from app.data.action.agent_app_actions import agent_app_list_projects
    from app.data.action.integrations import _helpers
    from app.data.action.integrations.telegram.telegram_actions import (
        send_telegram_bot_message,
    )
    from app.data.action.integrations.telegram.telegram_auto_reply_actions import (
        set_telegram_owner_control,
    )
    from app.telegram_feedback import start_typing
    from craftos_integrations.config import ConfigStore
    from craftos_integrations.core.storage import FileCredentialStore
    from craftos_integrations.core.system import IntegrationSystem
    from craftos_integrations.providers._shared import platform_message_payload
    from craftos_integrations.providers.telegram_bot.provider import TelegramBotProvider

    token = os.environ.get("CRAFTBOT_TELEGRAM_TEST_TOKEN")
    chat_id = os.environ.get("CRAFTBOT_TELEGRAM_TEST_CHAT_ID")
    if not token or not chat_id:
        pytest.skip("Set the Telegram test token and private chat ID")
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    provider = TelegramBotProvider()
    client = provider.build_client({"bot_token": token}, lambda c: None)

    async def scenario():
        info = await client.get_me()
        assert info.get("ok") is True
        account = str(info["result"]["id"])
        system = IntegrationSystem(
            store=FileCredentialStore(tmp_path / "accounts"), providers=[provider]
        )
        system.store_credential(
            "telegram_bot", account, {"bot_token": token, "bot_id": account}
        )
        monkeypatch.setattr(_helpers, "system_for", lambda integration: system)
        monkeypatch.setattr(_helpers, "record_outgoing_message", lambda *args: None)
        receiving_client = system.client_for("telegram_bot", account)
        original_chat_action = receiving_client.send_chat_action
        typing_results = []

        async def record_chat_action(*args):
            result = await original_chat_action(*args)
            typing_results.append(result)
            return result

        monkeypatch.setattr(receiving_client, "send_chat_action", record_chat_action)
        updates = await client.get_updates(timeout=0)
        assert updates.get("ok") is True
        messages = [
            u
            for u in updates["result"]
            if str(u.get("message", {}).get("chat", {}).get("id")) == chat_id
        ]
        assert messages, "Send a test message to the bot first"
        assert (
            set_telegram_owner_control({"contact_id": chat_id, "enabled": True})[
                "status"
            ]
            == "success"
        )
        captured = []

        async def receive(msg):
            async def capture_chat(payload):
                captured.append(payload)

            await AgentBase._handle_external_event(
                SimpleNamespace(_handle_chat_message=capture_chat),
                {**platform_message_payload(msg), "account": account},
            )

        client._message_callback = receive
        await client._process_update(messages[-1])
        chat = captured[0]
        assert chat["owner_authenticated"] is True
        assert chat["is_self_message"] is True
        assert "[AUTHENTICATED OWNER MESSAGE" in chat["text"]
        origin = {
            k: chat[k]
            for k in (
                "account",
                "channel_id",
                "contact_id",
                "integration_type",
                "owner_authenticated",
                "is_self_message",
            )
        }
        previous_manager = get_agent_app_manager()
        set_agent_app_manager(AgentAppManager(tmp_path / "apps"))
        origin_token = current_message_origin.set(origin)
        typing = start_typing(origin)
        try:
            apps = await agent_app_list_projects({})
            assert apps["status"] == "success"
            assert apps["projects"] == []
            await asyncio.sleep(
                6
            )  # Exercise expiry and refresh, not just one API call.
            assert len(typing_results) >= 2
            assert all(result.get("ok") is True for result in typing_results)
            quoted = bool(os.environ.get("CRAFTBOT_TELEGRAM_REPLY_CHECK"))
            if quoted:
                assert "Replied-to message (context only" in chat["text"]
                assert "Live Telegram test" in chat["text"]
                text = "Reply-context test passed: I received your reply and the original message you replied to."
            else:
                text = (
                    "Live Telegram test: your private message was authenticated as the owner. "
                    "The Agent Apps tool ran successfully; this isolated test workspace has no apps. "
                    "Typing was refreshed while it worked. Please reply to this message with ‘This’ to test reply context."
                )
            params = {
                "account": account,
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": int(chat["message_id"]),
            }
            input_token = current_input_data.set(params)
            try:
                result = await send_telegram_bot_message(params)
            finally:
                current_input_data.reset(input_token)
            assert result["status"] == "success"
        finally:
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)
            current_message_origin.reset(origin_token)
            set_agent_app_manager(previous_manager)

    asyncio.run(scenario())
