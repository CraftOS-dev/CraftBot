"""Discord owner authority under Settings > Security strict channel identity."""

from __future__ import annotations

import asyncio

import pytest

import craftos_integrations.providers.discord.client as discord_client
from craftos_integrations import ConfigStore


@pytest.fixture
def client(monkeypatch):
    cfg = discord_client.DiscordConfig(self_usernames=["owner"])
    monkeypatch.setattr(discord_client, "load_config", lambda *a, **k: cfg)
    c = discord_client.DiscordClient()
    c._bot_user_id = "bot"
    c._catchup_done = True
    seen = []

    async def capture(message):
        seen.append(message)

    c._message_callback = capture

    async def label(*a, **k):
        return "general"

    monkeypatch.setattr(c, "_channel_label", label)
    return c, seen


def _message(username, global_name, mentioned=False, guild="g1"):
    return {
        "author": {"id": "u1", "username": username, "global_name": global_name},
        "content": "run something",
        "channel_id": "c1",
        "guild_id": guild,
        "mentions": [{"id": "bot"}] if mentioned else [],
        "timestamp": "2026-11-24T00:00:00+00:00",
    }


def _run(client, data, strict, monkeypatch):
    monkeypatch.setitem(ConfigStore.extras, "strict_channel_identity", lambda: strict)
    asyncio.run(client._handle_message_create(data))


def test_display_name_grants_owner_only_without_strict_identity(client, monkeypatch):
    c, seen = client
    _run(c, _message("attacker", "owner"), False, monkeypatch)
    assert seen and seen[-1].raw["is_self_message"] is True  # today's behaviour


def test_strict_identity_ignores_display_names_and_needs_a_mention(client, monkeypatch):
    c, seen = client
    _run(c, _message("attacker", "owner", mentioned=True), True, monkeypatch)
    assert not seen  # a look-alike display name is not the owner
    _run(c, _message("owner", "Owner", mentioned=False), True, monkeypatch)
    assert not seen  # in a server, the bot must be mentioned
    _run(c, _message("owner", "Owner", mentioned=True), True, monkeypatch)
    assert seen and seen[-1].raw["is_self_message"] is True
