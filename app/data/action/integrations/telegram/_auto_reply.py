"""Check scoped third-party reply permission immediately before dispatch."""

from __future__ import annotations


def reply_permission_error(input_data: dict) -> dict | None:
    from agent_core.core.impl.action.context import current_message_origin
    from craftos_integrations import load_config
    from craftos_integrations.providers.telegram_bot.client import (
        TelegramBotConfig,
        _telegram_bot_config_file,
    )

    origin = current_message_origin.get() or {}
    from app.telegram_feedback import owner_permission_error

    denied = owner_permission_error(origin)
    if denied:
        return denied
    if (
        not origin.get("contact_id") and not origin.get("integration_type")
    ) or origin.get("is_self_message") is True:
        return None  # Local owner input or a trusted self-message.
    if origin.get("integration_type") != "telegram_bot" or not origin.get(
        "auto_reply_allowed"
    ):
        return {
            "status": "error",
            "message": "This sender has no Telegram Bot auto-reply permission.",
        }
    config = (
        load_config(_telegram_bot_config_file(), TelegramBotConfig)
        or TelegramBotConfig()
    )
    if not config.allows_auto_reply(
        origin["contact_id"], origin.get("channel_id", ""), "private"
    ):
        return {
            "status": "error",
            "message": "Auto-reply permission was removed; do not send this queued reply.",
        }
    if input_data.get("chat_id") != origin.get("channel_id"):
        return {
            "status": "error",
            "message": "An auto-reply must target the incoming private chat ID.",
        }
    if input_data.get("account") != origin.get("account"):
        return {
            "status": "error",
            "message": "An auto-reply must use the receiving bot account.",
        }
    return None


def finish_reply(result: dict) -> dict:
    from agent_core.core.impl.action.context import current_message_origin

    origin = current_message_origin.get() or {}
    if (
        result.get("status") == "success"
        and origin.get("auto_reply_allowed")
        and origin.get("is_self_message") is not True
    ):
        return {**result, "end_turn": True}
    return result
