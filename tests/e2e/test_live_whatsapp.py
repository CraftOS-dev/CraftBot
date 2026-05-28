"""LIVE end-to-end scenarios for WhatsApp.

One file per integration so test files stay scoped and easy to grow.
Generic infrastructure lives in [_harness/](tests/e2e/_harness/);
WhatsApp-specific verification lives in
[_integrations/whatsapp.py](tests/e2e/_integrations/whatsapp.py).

Each test:

1. Builds the real agent (skips if whatsapp_web isn't connected).
2. Sends a chat message through the same entry point the CraftBot UI uses.
3. After the agent's full lifecycle finishes, verifies the outcome
   black-box:
     - send tests: ``whatsapp.recent_messages_in_self_chat(...)``
     - read tests: ``assert_action_called(agent, <expected action>)``
4. Writes a per-test log file under ``tests/e2e/logs/`` with the agent
   trace + full LLM transcript.

**Opt-in.** Default ``pytest`` runs skip these. Run with::

    python -m pytest tests/e2e/test_live_whatsapp.py -v -m live -s

They spend LLM tokens and send REAL WhatsApp messages to the linked
account's own number.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.e2e._harness import (
    actions_called,
    assert_action_called,
    build_agent,
    format_agent_trace,
    run_scenario,
    save_trace_log,
)
from tests.e2e._integrations import whatsapp


pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Send-side scenarios — verified by querying the wwebjs chat history for an
# outgoing message in the owner's own chat, written during the test window.
# ---------------------------------------------------------------------------


def test_live_whatsapp_send_ping_to_me():
    """User asks the agent to whatsapp themselves. After the agent settles,
    we ask whatsapp directly: 'do you have a recent outgoing message from
    me to me?'. Passes regardless of which code path the agent took.

    Manual verification: a message arrives on your phone.
    """
    agent = build_agent(require=["whatsapp_web"])

    # Round down a couple of seconds for clock-skew safety between Python's
    # time.time() and whatsapp-web.js's message timestamps.
    test_start_ts = time.time() - 2

    async def _run() -> list[dict]:
        await run_scenario(
            agent,
            user_message="send me a whatsapp message saying 'ping from test'",
            wait_for=["whatsapp_web"],
        )
        # Bridge flush before query.
        await asyncio.sleep(2.0)
        return await whatsapp.recent_messages_in_self_chat(since_ts=test_start_ts)

    recent = asyncio.run(_run())
    log_path = save_trace_log(
        agent,
        extra={"recent_messages_in_self_chat": len(recent)},
    )
    print(f"\nagent trace: {log_path}")

    assert recent, (
        f"no outgoing whatsapp message landed in your self-chat after "
        f"the test window. trace: {log_path}\n\n" + format_agent_trace(agent)
    )


def test_live_whatsapp_threads_user_content_through():
    """Verifies the agent threads a quoted phrase verbatim instead of
    paraphrasing. The sentinel is unique per run so re-runs don't
    false-positive on prior runs' messages.
    """
    sentinel = f"craftbot-e2e-{int(time.time())}"
    agent = build_agent(require=["whatsapp_web"])
    test_start_ts = time.time() - 2

    async def _run() -> list[dict]:
        await run_scenario(
            agent,
            user_message=f"send me a whatsapp with this exact text: '{sentinel}'",
            wait_for=["whatsapp_web"],
        )
        await asyncio.sleep(2.0)
        return await whatsapp.recent_messages_in_self_chat(
            since_ts=test_start_ts,
            contains=sentinel,
        )

    recent = asyncio.run(_run())
    log_path = save_trace_log(
        agent,
        extra={"sentinel": sentinel, "matched_messages": len(recent)},
    )
    print(f"\nagent trace: {log_path}")

    assert recent, (
        f"no whatsapp message containing the sentinel arrived. The agent "
        f"may have paraphrased instead of threading the exact phrase. "
        f"sentinel={sentinel!r}. trace: {log_path}\n\n" + format_agent_trace(agent)
    )


def test_live_whatsapp_sends_unicode_body():
    """Emoji + non-Latin scripts must survive Python → wwebjs subprocess
    JSON → WhatsApp's API → the bridge's chat history readback. Catches
    encoding bugs anywhere in that chain.
    """
    sentinel = f"héllo 你好 🚀 {int(time.time())}"
    rocket = "🚀"
    agent = build_agent(require=["whatsapp_web"])
    test_start_ts = time.time() - 2

    async def _run() -> list[dict]:
        await run_scenario(
            agent,
            user_message=f"send me a whatsapp with this exact text: '{sentinel}'",
            wait_for=["whatsapp_web"],
        )
        await asyncio.sleep(2.0)
        return await whatsapp.recent_messages_in_self_chat(
            since_ts=test_start_ts,
            contains=rocket,
        )

    recent = asyncio.run(_run())
    # Log file is UTF-8; keep console print pure ASCII for Windows cp1252.
    log_path = save_trace_log(
        agent,
        extra={"sentinel": sentinel, "matched_with_rocket": len(recent)},
    )
    print(f"\nagent trace: {log_path}")

    assert recent, (
        f"no whatsapp message containing the rocket emoji arrived. The "
        f"wwebjs bridge may be mangling unicode. trace: {log_path}"
    )


# ---------------------------------------------------------------------------
# Read-side scenarios — verified by asserting on which action(s) the agent
# invoked, via the ``execute_action`` spy recorded in
# ``agent._test_actions_called``. No outgoing messages expected.
# ---------------------------------------------------------------------------


def test_live_whatsapp_query_session_status_for_my_number():
    """Asking for one's own whatsapp number should make the agent look it
    up via ``get_whatsapp_web_session_status`` (per the integration's
    ## Essentials block — "Never ask the user for it"). Regression check
    that the essentials reach task-mode prompts.
    """
    agent = build_agent(require=["whatsapp_web"])

    async def _run():
        await run_scenario(
            agent,
            user_message=(
                "what is my own whatsapp phone number? look it up — don't ask me."
            ),
            wait_for=["whatsapp_web"],
        )

    asyncio.run(_run())
    assert_action_called(agent, "get_whatsapp_web_session_status")


def test_live_whatsapp_checks_unread_chats():
    """Asking about unread whatsapp messages should fire
    ``get_whatsapp_unread_chats``. Result (0 vs N) doesn't matter; only
    that the agent reached for the right action.
    """
    agent = build_agent(require=["whatsapp_web"])

    async def _run():
        await run_scenario(
            agent,
            user_message="do i have any unread whatsapp messages? list them.",
            wait_for=["whatsapp_web"],
        )

    asyncio.run(_run())
    assert_action_called(agent, "get_whatsapp_unread_chats")


def test_live_whatsapp_searches_contact_by_name():
    """Asking the agent to find a contact by name should fire
    ``search_whatsapp_contact``. We don't assert the search FOUND the
    contact — only that the agent reasoned to search instead of asking
    the user for a phone number.
    """
    agent = build_agent(require=["whatsapp_web"])

    async def _run():
        await run_scenario(
            agent,
            user_message=(
                "search my whatsapp contacts for someone named 'craftbot test'. "
                "tell me what you find."
            ),
            wait_for=["whatsapp_web"],
        )

    asyncio.run(_run())
    assert_action_called(agent, "search_whatsapp_contact")


# ---------------------------------------------------------------------------
# Incoming-message scenarios — feed the agent a message that LOOKS like it
# came from the wwebjs bridge's on-message callback, via the same
# ``_handle_external_event`` entry the integration manager uses in
# production. We do NOT actually receive a message from outside — we
# synthesize the payload and inject it.
# ---------------------------------------------------------------------------


def test_live_whatsapp_self_message_from_phone_triggers_reply():
    """REAL bridge flow: you send a WhatsApp from your phone to yourself.
    The wwebjs bridge picks it up and emits an on-message event with
    ``is_self_message=True``. The agent wraps it as a user instruction
    (per [agent_base.py:2358](app/agent_base.py#L2358)) and replies.

    The bridge SUPPRESSES its own bridge-initiated sends from the
    on-message callback (see ownSentIds tracking in bridge.js) — so we
    can't automate this. You have to send from your phone within 30s.
    """
    agent = build_agent(require=["whatsapp_web"])

    async def _run():
        await run_scenario(
            agent,
            wait_for_incoming=True,
            wait_for=["whatsapp_web"],
            incoming_prompt=(
                ">>> SEND A WHATSAPP TO YOURSELF FROM YOUR PHONE NOW (30s).\n"
                ">>> Any message body works — the agent will reply to it."
            ),
            incoming_filter=lambda p: bool(p.get("is_self_message")),
            incoming_timeout=30.0,
        )

    # Explicit "default" config: self_messages_only=False. The user's
    # production config may have this set to True (which is fine for daily
    # use — it'd just drop third-party messages), so we force False here
    # so the test is independent of host state. The context manager
    # snapshots the current value and restores it on exit.
    with whatsapp.self_messages_only(False):
        asyncio.run(_run())
    assert_action_called(agent, "send_whatsapp_web_text_message")


def test_live_whatsapp_third_party_message_is_notification_only():
    """REAL bridge flow: someone else WhatsApps you. The bridge picks it
    up, on-message fires with ``is_self_message=False``, and per the
    hardcoded routing rule at [agent_base.py:2213-2217](app/agent_base.py#L2213)
    the chat handler short-circuits to ``_post_third_party_notification``
    BEFORE any LLM call. The agent must NOT reply on the sender's
    behalf.

    Verifications:
      - no LLM calls were made (third-party branch short-circuited),
      - no actions were invoked (no react() ran),
      - no outgoing whatsapp message landed in the owner's chat.
    """
    agent = build_agent(require=["whatsapp_web"])
    test_start_ts = time.time() - 2

    async def _run():
        await run_scenario(
            agent,
            wait_for_incoming=True,
            wait_for=["whatsapp_web"],
            incoming_prompt=(
                ">>> HAVE SOMEONE ELSE SEND YOU A WHATSAPP NOW (30s).\n"
                ">>> Must be from a different account/contact. Any body works."
            ),
            incoming_filter=lambda p: p.get("is_self_message") is False,
            incoming_timeout=30.0,
        )
        # Give the bridge a moment in case anything (wrongly) tried to send.
        await asyncio.sleep(2.0)
        return await whatsapp.recent_messages_in_self_chat(since_ts=test_start_ts)

    # Force self_messages_only=False so third-party messages reach the
    # agent. Without this, the user's production config (which may have
    # self_messages_only=True) would drop the message at the integration
    # layer and the test would time out waiting forever.
    with whatsapp.self_messages_only(False):
        sent_to_self = asyncio.run(_run())
    invoked = actions_called(agent)
    llm_calls = getattr(agent, "_test_llm_calls", []) or []

    log_path = save_trace_log(
        agent,
        extra={
            "llm_calls": len(llm_calls),
            "actions_called": invoked,
            "self_chat_sends_during_test": len(sent_to_self),
        },
    )
    print(f"\nagent trace: {log_path}")

    assert not llm_calls, (
        f"agent invoked the LLM ({len(llm_calls)} call(s)) for a third-"
        f"party whatsapp message. The notification-only branch should have "
        f"short-circuited. trace: {log_path}\n\n" + format_agent_trace(agent)
    )
    assert not invoked, (
        f"agent invoked actions {invoked} for a third-party whatsapp "
        f"message. Should be empty. trace: {log_path}"
    )
    assert not sent_to_self, (
        f"agent sent {len(sent_to_self)} whatsapp message(s) in response "
        f"to a third-party message. The notification-only rule was "
        f"violated. trace: {log_path}"
    )


# ---------------------------------------------------------------------------
# Incoming-message scenarios with ``self_messages_only=True`` config —
# the integration-level filter at
# [whatsapp_web/__init__.py:_handle_incoming_message](craftos_integrations/integrations/whatsapp_web/__init__.py)
# drops non-self messages BEFORE the on-message callback. Self-messages
# go through ``_handle_sent_message`` and aren't affected.
# ---------------------------------------------------------------------------


def test_live_whatsapp_self_only_config_still_processes_self_message():
    """With ``self_messages_only=True`` the integration must still forward
    self-messages to the agent — only third-party messages are dropped.
    You send a whatsapp to yourself from your phone within 30s; agent
    should still reply via ``send_whatsapp_web_text_message``.
    """
    agent = build_agent(require=["whatsapp_web"])

    async def _run():
        await run_scenario(
            agent,
            wait_for_incoming=True,
            wait_for=["whatsapp_web"],
            incoming_prompt=(
                ">>> [self_messages_only=True] SEND A WHATSAPP TO YOURSELF "
                "FROM YOUR PHONE NOW (30s). Agent should still reply."
            ),
            incoming_filter=lambda p: bool(p.get("is_self_message")),
            incoming_timeout=30.0,
        )

    with whatsapp.self_messages_only(True):
        asyncio.run(_run())

    assert_action_called(agent, "send_whatsapp_web_text_message")


def test_live_whatsapp_self_only_config_drops_third_party():
    """With ``self_messages_only=True`` a third-party message must be
    DROPPED at the integration layer — ``_handle_external_event`` is
    never invoked, so the agent doesn't even see it. Differs from the
    notification-only third-party test (which verifies the agent's
    ROUTING when the event does reach it).

    You ask someone else to whatsapp you within 30s. Test passes by
    timing out (no matching event ever reaches the agent).
    """
    agent = build_agent(require=["whatsapp_web"])

    async def _run():
        await run_scenario(
            agent,
            expect_no_incoming=True,
            wait_for=["whatsapp_web"],
            incoming_prompt=(
                ">>> [self_messages_only=True] HAVE SOMEONE ELSE WHATSAPP "
                "YOU IN THE NEXT 30s. The integration must DROP it before "
                "the agent sees it. Test passes by timing out silently."
            ),
            # We only care about third-party arrivals reaching the agent;
            # ignore any self-messages that might also arrive in the window.
            incoming_filter=lambda p: p.get("is_self_message") is False,
            incoming_timeout=30.0,
        )

    with whatsapp.self_messages_only(True):
        asyncio.run(_run())

    # Belt-and-suspenders: no actions, no LLM, no outgoing message.
    llm_calls = getattr(agent, "_test_llm_calls", []) or []
    invoked = actions_called(agent)
    log_path = save_trace_log(
        agent,
        extra={"llm_calls": len(llm_calls), "actions_called": invoked},
    )
    print(f"\nagent trace: {log_path}")
    assert not llm_calls and not invoked, (
        f"agent reacted to a message that should have been dropped at the "
        f"integration layer. llm_calls={len(llm_calls)}, actions={invoked}. "
        f"trace: {log_path}"
    )


def test_live_whatsapp_reads_self_chat_history():
    """Asking for the last whatsapp message in self-chat should fire
    ``get_whatsapp_chat_history``. The agent will likely call
    ``get_whatsapp_web_session_status`` first to find the owner's phone,
    then ``get_whatsapp_chat_history`` against it.
    """
    agent = build_agent(require=["whatsapp_web"])

    async def _run():
        await run_scenario(
            agent,
            user_message=(
                "look up the last whatsapp message i sent to myself. "
                "use my own number for the chat."
            ),
            wait_for=["whatsapp_web"],
        )

    asyncio.run(_run())
    assert_action_called(agent, "get_whatsapp_chat_history")
