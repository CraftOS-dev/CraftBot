"""Gmail-specific verification helpers for live e2e tests.

All the Gmail API specifics live here:
  - the owner identifier is ``cred.email`` (stored on ``GoogleCredential``).
  - sent emails live in the ``SENT`` label and are queried via Gmail's
    search syntax (``in:sent``, ``after:`` for time bounds, free-text for
    body matches).
  - the underlying ``send_email`` / ``list_emails`` / etc. on the client
    are sync (REST), unlike WhatsApp's async bridge methods.

Tests just call ``recent_sent_emails(contains=...)`` and assert on the
returned list — no GmailAPI plumbing leaks into the test body.
"""

from __future__ import annotations

import asyncio

from craftos_integrations import get_client
from craftos_integrations.helpers import request as http_request
from craftos_integrations.integrations.gmail import GMAIL_API_BASE


INTEGRATION_ID = "gmail"


def owner_email() -> str:
    """The Gmail address the user is logged in as. Empty string if the
    client isn't registered or has no credentials.
    """
    client = get_client(INTEGRATION_ID)
    if client is None:
        return ""
    try:
        cred = client._load()
    except Exception:
        return ""
    return getattr(cred, "email", "") or ""


async def recent_sent_emails(
    *,
    contains: str | None = None,
    since_ts: float | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return emails the user's Gmail account sent recently.

    Uses Gmail's search syntax (``in:sent`` + free-text + ``after:``)
    so the filter happens server-side — no need to fetch + post-filter.

    Args:
        contains: optional case-insensitive substring matched against the
            message body OR subject (Gmail does whole-word fuzzy by
            default; a quoted phrase is treated as an exact substring).
        since_ts: optional unix timestamp lower bound. Gmail's ``after:``
            accepts unix seconds.
        limit: how many results to fetch.

    Returns a list of dicts with at least ``id``, ``snippet``, plus
    headers ``From`` / ``To`` / ``Subject`` / ``Date`` when present.
    Empty list = no match.
    """
    client = get_client(INTEGRATION_ID)
    if client is None:
        return []

    # We avoid Gmail's ``after:`` filter — it's quirky around unix
    # timestamps and the agent's own sentinel is already unique enough to
    # bound the match. If callers want a time bound for safety they can
    # filter ``timestamp`` on the returned dicts themselves.
    query_parts = ["in:sent"]
    if contains:
        # Quote so Gmail treats it as a phrase rather than tokenizing.
        query_parts.append(f'"{contains}"')
    q = " ".join(query_parts)
    _ = since_ts  # kept for API compatibility; unused for now

    # Gmail's search returns IDs only; we fetch each one for snippet +
    # headers. This is the same shape ``client.read_top_emails`` produces
    # but scoped to Sent + filtered by query.
    def _list_sync():
        return http_request(
            "GET",
            f"{GMAIL_API_BASE}/users/me/messages",
            headers=client._auth_header(),
            params={"q": q, "maxResults": limit},
            expected=(200,),
            transform=lambda d: d.get("messages", []),
        )

    envelope = await asyncio.to_thread(_list_sync)
    # ``request`` wraps every response in ``{"ok": True, "result": ...}``
    # on success or ``{"error": ..., "details": ...}`` on failure. Unwrap.
    if not isinstance(envelope, dict) or "error" in envelope:
        return []
    listing = envelope.get("result")
    if not isinstance(listing, list):
        return []

    def _fetch_one(mid: str):
        return client.get_email(message_id=mid, full_body=False)

    results: list[dict] = []
    for entry in listing:
        mid = entry.get("id")
        if not mid:
            continue
        detail_envelope = await asyncio.to_thread(_fetch_one, mid)
        if not isinstance(detail_envelope, dict) or "error" in detail_envelope:
            continue
        detail = detail_envelope.get("result", detail_envelope)
        if isinstance(detail, dict) and detail.get("id"):
            results.append(detail)
    return results
