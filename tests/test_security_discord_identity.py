"""Discord owner authority: by user ID, never by display name or role name."""

from __future__ import annotations

import asyncio

import pytest

import craftos_integrations.providers.discord.client as discord_client


@pytest.fixture
def client(monkeypatch):
    cfg = discord_client.DiscordConfig(self_usernames=["owner"])
    monkeypatch.setattr(discord_client, "load_config", lambda *a, **k: cfg)
    saved = []
    monkeypatch.setattr(discord_client, "save_config", lambda path, obj: saved.append(list(obj.self_user_ids)))
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


def _message(username, global_name, mentioned=False, guild="g1", user_id="u1"):
    return {
        "author": {"id": user_id, "username": username, "global_name": global_name},
        "content": "run something",
        "channel_id": "c1",
        "guild_id": guild,
        "mentions": [{"id": "bot"}] if mentioned else [],
        "timestamp": "2026-11-24T00:00:00+00:00",
    }


def _run(client, data):
    asyncio.run(client._handle_message_create(data))


def test_display_names_never_grant_owner(client):
    c, seen = client
    _run(c, _message("attacker", "owner"))
    assert not seen  # a look-alike display name is not the owner
    _run(c, _message("owner", "Owner"))
    assert seen and seen[-1].raw["is_self_message"] is True


def test_the_owner_id_is_pinned_on_first_match(client):
    c, seen = client
    _run(c, _message("owner", "Owner", user_id="111"))
    assert seen[-1].raw["is_self_message"] is True
    # The username is later taken by another account: the pinned ID decides.
    _run(c, _message("owner", "Owner", user_id="999"))
    assert len(seen) == 1
    _run(c, _message("renamed", "New name", user_id="111"))
    assert seen[-1].raw["is_self_message"] is True


def test_listed_ids_match(client):
    c, seen = client
    cfg = discord_client.load_config()
    cfg.self_user_ids = ["222"]
    _run(c, _message("someone", "Someone", user_id="222"))
    assert seen[-1].raw["is_self_message"] is True


def test_mention_is_required_only_when_mention_only_is_set(client):
    c, seen = client
    cfg = discord_client.load_config()
    cfg.mention_only = True
    _run(c, _message("owner", "Owner", mentioned=False))
    assert not seen
    _run(c, _message("owner", "Owner", mentioned=True))
    assert seen[-1].raw["is_self_message"] is True


def test_self_roles_from_older_configs_only_grant_third_party(client, monkeypatch):
    c, seen = client
    cfg = discord_client.load_config()
    cfg.self_usernames = []
    cfg.self_role_names = ["Admin"]

    async def roles(guild_id):
        return {"r1": "admin"}

    monkeypatch.setattr(c, "_resolve_guild_role_names", roles)
    data = _message("mod", "Mod")
    data["member"] = {"roles": ["r1"]}
    _run(c, data)
    assert seen and seen[-1].raw["is_self_message"] is False
    _run(c, _message("stranger", "Stranger"))
    assert len(seen) == 1  # without the role, still dropped
