"""LIVE end-to-end scenarios for Gmail.

Same black-box shape as the whatsapp suite: build the real agent, send
it a chat message via the production entry point, let it do its full
lifecycle, then ask Gmail itself "is there a matching email in my Sent
folder?" or assert which read-action the agent invoked.

Generic infrastructure lives in [_harness/](tests/e2e/_harness/);
Gmail-specific verification lives in
[_integrations/gmail.py](tests/e2e/_integrations/gmail.py).

**Opt-in.** Default ``pytest`` runs skip these. Run with::

    python -m pytest tests/e2e/test_live_gmail.py -v -m live -s

They spend LLM tokens and send REAL emails to your own inbox.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.e2e._harness import (
    build_agent,
    format_agent_trace,
    run_scenario,
    save_trace_log,
)
from tests.e2e._integrations import gmail


pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Send-side scenarios — verified by querying Gmail's Sent folder for an
# outgoing message written during the test window.
# ---------------------------------------------------------------------------


def test_live_gmail_send_to_me():
    """Agent emails the user themselves. After the lifecycle finishes,
    we ask Gmail directly whether a sent email matches the body sentinel.
    Passes regardless of which path the agent took (``send_gmail`` vs
    ``send_google_workspace_email``).

    The user's own email is threaded into the prompt explicitly (via
    ``gmail.owner_email()``) so the test doesn't depend on the agent
    inferring "me" from the integration_essentials block — Gemini
    sometimes asks for clarification even when the essentials forbid it.

    Manual verification: a 'gmail e2e test ping' message arrives in your
    inbox.
    """
    agent = build_agent(require=["gmail"])
    test_start_ts = time.time() - 5
    sentinel = f"gmail e2e test {int(time.time())}"
    to_addr = gmail.owner_email()
    assert to_addr, "couldn't determine the user's gmail address from credentials"

    async def _run() -> list[dict]:
        await run_scenario(
            agent,
            user_message=(
                f"send a Gmail email (use the send_gmail action, not outlook) "
                f"to {to_addr} with subject 'craftbot e2e' and body '{sentinel}'."
            ),
            max_iterations=30,
        )
        # Gmail's API has a small propagation delay between send and
        # appearing in the Sent folder via search.
        # Gmail can take 10–20s to index a new sent message for search.
        await asyncio.sleep(15.0)
        return await gmail.recent_sent_emails(
            contains=sentinel,
            since_ts=test_start_ts,
        )

    recent = asyncio.run(_run())
    log_path = save_trace_log(
        agent,
        extra={"sentinel": sentinel, "matched_sent_emails": len(recent)},
    )
    print(f"\nagent trace: {log_path}")

    assert recent, (
        f"no sent email containing the sentinel arrived in your Gmail "
        f"Sent folder. sentinel={sentinel!r}. trace: {log_path}\n\n"
        + format_agent_trace(agent)
    )


def test_live_gmail_threads_user_content_through():
    """Quoted phrase verbatim — verifies the agent doesn't paraphrase
    when threading body content. Unique sentinel per run.
    """
    agent = build_agent(require=["gmail"])
    test_start_ts = time.time() - 5
    sentinel = f"craftbot-gmail-{int(time.time())}"
    to_addr = gmail.owner_email()
    assert to_addr, "couldn't determine the user's gmail address from credentials"

    async def _run() -> list[dict]:
        await run_scenario(
            agent,
            user_message=(
                f"send a Gmail email (use the send_gmail action) to {to_addr} "
                f"with this exact body text: '{sentinel}'. "
                f"subject: 'craftbot e2e threading'."
            ),
            max_iterations=30,
        )
        # Gmail can take 10–20s to index a new sent message for search.
        await asyncio.sleep(15.0)
        return await gmail.recent_sent_emails(
            contains=sentinel,
            since_ts=test_start_ts,
        )

    recent = asyncio.run(_run())
    log_path = save_trace_log(
        agent,
        extra={"sentinel": sentinel, "matched_sent_emails": len(recent)},
    )
    print(f"\nagent trace: {log_path}")

    assert recent, (
        f"no sent email containing the sentinel arrived. The agent may "
        f"have paraphrased the body instead of threading verbatim. "
        f"sentinel={sentinel!r}. trace: {log_path}\n\n" + format_agent_trace(agent)
    )


def test_live_gmail_sends_unicode_body():
    """Emoji + non-Latin scripts must survive the MIME-encoded send path
    in [gmail.py](craftos_integrations/integrations/gmail.py) and round-
    trip back through Gmail's search.
    """
    agent = build_agent(require=["gmail"])
    test_start_ts = time.time() - 5
    rocket = "🚀"
    body = f"héllo 你好 {rocket} {int(time.time())}"
    to_addr = gmail.owner_email()
    assert to_addr, "couldn't determine the user's gmail address from credentials"

    async def _run() -> list[dict]:
        await run_scenario(
            agent,
            user_message=(
                f"send a Gmail email (use the send_gmail action) to {to_addr} "
                f"with this exact body text: '{body}'. "
                f"subject: 'craftbot e2e unicode'."
            ),
            max_iterations=30,
        )
        # Gmail can take 10–20s to index a new sent message for search.
        await asyncio.sleep(15.0)
        # Search for the rocket — if Gmail or the MIME encoder mangled
        # it to '?' or a numeric reference, this finds nothing.
        return await gmail.recent_sent_emails(
            contains=rocket,
            since_ts=test_start_ts,
        )

    recent = asyncio.run(_run())
    log_path = save_trace_log(
        agent,
        extra={"body_sentinel": body, "matched_with_rocket": len(recent)},
    )
    print(f"\nagent trace: {log_path}")

    assert recent, (
        f"no sent email containing the rocket emoji landed in your Sent "
        f"folder. The MIME encoder or Gmail may be mangling unicode. "
        f"trace: {log_path}"
    )


# ---------------------------------------------------------------------------
# Read-side scenarios — verified by which action the agent invoked.
# No outgoing emails expected.
# ---------------------------------------------------------------------------


def test_live_gmail_lists_unread_emails():
    """Asking for unread emails should fire ``list_gmail`` (or its
    google_workspace alias). We don't assert the count of unread — only
    that the agent reached for a read action instead of asking the user.
    """
    agent = build_agent(require=["gmail"])

    async def _run():
        await run_scenario(
            agent,
            user_message=(
                "use the list_gmail action to fetch my unread Gmail emails. "
                "list the senders and subjects. don't ask me anything — "
                "use Gmail (not outlook) and act now."
            ),
            max_iterations=30,
        )

    asyncio.run(_run())
    # Either action_set is acceptable — they both pull from the same
    # Gmail API. Assert at least one fired.
    from tests.e2e._harness import actions_called

    called = actions_called(agent)
    log_path = save_trace_log(
        agent,
        extra={
            "actions_called": called,
            "expecting_any_of": [
                "list_gmail",
                "read_top_emails",
                "read_recent_google_workspace_emails",
            ],
        },
    )
    print(f"\nagent trace: {log_path}")
    acceptable = {
        "list_gmail",
        "read_top_emails",
        "read_recent_google_workspace_emails",
    }
    assert acceptable.intersection(called), (
        f"agent didn't call any gmail read action. Called: {called}. "
        f"trace: {log_path}\n\n" + format_agent_trace(agent)
    )


def test_live_gmail_reads_top_emails_with_details():
    """Asking to summarise recent emails should fire ``read_top_emails``
    (or the equivalent google_workspace action) — it's the only Gmail
    action that returns body content in one call.
    """
    agent = build_agent(require=["gmail"])

    async def _run():
        await run_scenario(
            agent,
            user_message=(
                "summarise the last 3 emails in my Gmail inbox using the "
                "read_top_emails action. include who sent them and what each "
                "one is about. don't ask me anything — use Gmail (not "
                "outlook) and act now."
            ),
            max_iterations=30,
        )

    asyncio.run(_run())
    from tests.e2e._harness import actions_called

    called = actions_called(agent)
    log_path = save_trace_log(
        agent,
        extra={
            "actions_called": called,
            "expecting_any_of": [
                "read_top_emails",
                "read_recent_google_workspace_emails",
            ],
        },
    )
    print(f"\nagent trace: {log_path}")
    acceptable = {
        "read_top_emails",
        "read_recent_google_workspace_emails",
    }
    assert acceptable.intersection(called), (
        f"agent didn't call a read-with-body gmail action. Called: {called}. "
        f"trace: {log_path}\n\n" + format_agent_trace(agent)
    )
