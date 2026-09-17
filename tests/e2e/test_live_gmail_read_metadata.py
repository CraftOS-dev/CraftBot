"""LIVE end-to-end: can the agent answer metadata questions from Gmail reads?

Regression for the V1.4.3 "read Gmail action can't read email metadata"
report. Before the fix, get_gmail / read_top_emails returned only
{id, snippet, From/To/Subject/Date}: no unread state, no labels, no thread
id, no Reply-To/Cc, and an EMPTY body for HTML-only mail.

Read-only by construction: a spy on the action manager refuses every Gmail
action that could change the mailbox before it runs. Ground truth is pulled
straight from the Gmail API at test time and written into the trace log so
the agent's answer can be checked against it.

Run::

    python -m pytest tests/e2e/test_live_gmail_read_metadata.py -v -m live -s

Spends LLM tokens. NOTE: the harness wipes sessions/triggers in
app/data/.usage/sessions.db — back it up first on a machine you care about.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from tests.e2e._harness import (
    actions_called,
    build_agent,
    format_agent_trace,
    run_scenario,
    save_trace_log,
)

pytestmark = pytest.mark.live

_READ_ONLY_GMAIL = {
    "list_gmail",
    "get_gmail",
    "read_top_emails",
    "search_gmail",
    "get_gmail_thread",
    "list_gmail_threads",
    "get_gmail_profile",
    "list_gmail_labels",
    "get_gmail_label",
}
_READ_ONLY_RULE = (
    "This is read-only: do not mark as read, label, archive, reply, forward, "
    "draft, or send anything. Use Gmail (not Outlook). Don't ask me anything — "
    "act now."
)


def _install_action_recorder(agent) -> list[dict[str, Any]]:
    """Record name/input/output of every action; block mailbox-mutating
    Gmail actions before they execute."""
    records: list[dict[str, Any]] = []
    orig = agent.action_manager.execute_action

    async def _spy(action, *args, **kwargs):
        name = getattr(action, "name", str(action))
        rec: dict[str, Any] = {"name": name, "input": kwargs.get("input_data")}
        records.append(rec)
        if "gmail" in name and name not in _READ_ONLY_GMAIL:
            rec["blocked"] = True
            return {"status": "error", "message": "blocked by read-only e2e test"}
        out = await orig(action, *args, **kwargs)
        rec["output"] = out
        return out

    agent.action_manager.execute_action = _spy
    return records


def _gmail_ground_truth(n: int = 8) -> list[dict[str, Any]]:
    from craftos_integrations.helpers import request as http_request
    from craftos_integrations.providers.gmail.client import GMAIL_API_BASE
    from app.integrations import get_system

    sysm = get_system()
    client = sysm.client_for("gmail", sysm.resolve("gmail", None))
    listing = client.list_emails(n=n, unread_only=False)
    truth = []
    for m in listing.get("result", []):
        raw = http_request(
            "GET",
            f"{GMAIL_API_BASE}/users/me/messages/{m['id']}",
            headers=client._auth_header(),
            params={"format": "full"},
            expected=(200,),
        )["result"]
        hdrs = {h["name"].lower(): h["value"] for h in raw["payload"]["headers"]}
        truth.append(
            {
                "id": raw["id"],
                "threadId": raw["threadId"],
                "unread": "UNREAD" in raw.get("labelIds", []),
                "from": hdrs.get("from"),
                "subject": hdrs.get("subject"),
                "reply_to": hdrs.get("reply-to"),
                "cc": hdrs.get("cc"),
                "top_mime": raw["payload"].get("mimeType"),
            }
        )
    return truth


def _gmail_outputs(records, names) -> list[Any]:
    return [
        r.get("output")
        for r in records
        if r["name"] in names and isinstance(r.get("output"), dict)
    ]


def _finish(agent, records, truth, extra=None):
    log_path = save_trace_log(
        agent,
        extra={
            "actions_called": actions_called(agent),
            "ground_truth": json.dumps(truth, ensure_ascii=False),
            "action_records": json.dumps(records, ensure_ascii=False, default=str)[:20000],
            **(extra or {}),
        },
    )
    print(f"\nagent trace: {log_path}")
    print("\n--- GROUND TRUTH ---\n" + json.dumps(truth, indent=1, ensure_ascii=False))
    print("\n--- ACTIONS ---")
    for r in records:
        print(f"  {r['name']} input={json.dumps(r['input'], default=str)[:200]}"
              f"{' BLOCKED' if r.get('blocked') else ''}")
    print("\n--- TRACE ---\n" + format_agent_trace(agent))
    return log_path


def test_live_gmail_answers_unread_reply_to_and_thread():
    agent = build_agent(require=["gmail"])
    truth = _gmail_ground_truth(3)
    records = _install_action_recorder(agent)

    asyncio.run(
        run_scenario(
            agent,
            user_message=(
                "For each of my 3 most recent Gmail inbox emails, tell me the "
                "sender, the subject, whether it is READ or UNREAD, its "
                "Reply-To address (or 'none'), and its thread id. "
                + _READ_ONLY_RULE
            ),
            max_iterations=30,
        )
    )
    log_path = _finish(agent, records, truth)

    assert not any(r.get("blocked") for r in records), f"mutating action attempted. trace: {log_path}"
    outs = _gmail_outputs(records, {"get_gmail", "read_top_emails", "get_gmail_thread"})
    assert outs, f"agent never read message details. trace: {log_path}"
    blob = json.dumps(outs, default=str)
    # The fix: read results now carry the metadata the question needs.
    assert '"unread"' in blob and '"threadId"' in blob, (
        f"read results lack unread/thread metadata. trace: {log_path}"
    )
    for t in truth:
        if t["reply_to"]:
            assert t["reply_to"].split("<")[-1].rstrip(">") in blob, (
                f"Reply-To {t['reply_to']!r} missing from read results. trace: {log_path}"
            )


def test_live_gmail_summarises_html_only_email():
    agent = build_agent(require=["gmail"])
    truth = _gmail_ground_truth(8)
    html_only = next((t for t in truth if t["top_mime"] == "text/html"), None)
    if html_only is None:
        pytest.skip("no HTML-only email among the 8 most recent inbox messages")
    records = _install_action_recorder(agent)

    asyncio.run(
        run_scenario(
            agent,
            user_message=(
                f"Open the Gmail email with subject \"{html_only['subject']}\" "
                f"from {html_only['from']} and summarise what its BODY says in "
                "3 bullet points (not just the preview snippet). "
                + _READ_ONLY_RULE
            ),
            max_iterations=30,
        )
    )
    log_path = _finish(agent, records, [html_only])

    assert not any(r.get("blocked") for r in records), f"mutating action attempted. trace: {log_path}"
    outs = _gmail_outputs(records, {"get_gmail", "read_top_emails"})
    bodies = [
        o.get("result") for o in outs
        if isinstance(o.get("result"), dict) and o["result"].get("id") == html_only["id"]
    ]
    assert bodies, f"agent never fetched the HTML-only message. trace: {log_path}"
    full = [b for b in bodies if "body_format" in b]
    assert full, f"agent didn't request full_body for the message. trace: {log_path}"
    assert full[-1]["body_format"] == "html_converted" and len(full[-1]["body"]) > 200, (
        f"HTML-only body not converted: {full[-1].get('body_format')}. trace: {log_path}"
    )
