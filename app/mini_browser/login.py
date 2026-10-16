"""Protected saved-login sessions and conservative page outcome classification.

Ordinary Playwright receives only approved generated cookies. Saved source
values, login form requests and provider responses stay inside the host helper.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

# Site messages that mean the sign-in itself failed.
_FAILURE_WORDS = re.compile(
    r"incorrect|invalid|wrong|fail|locked|try again|not recognized|"
    r"does ?n[o'’]t match|could ?n[o'’]?t|unable|denied|expired|too many|"
    r"正しくありません|間違|失敗|無効",
    re.IGNORECASE,
)
# A verification step after the password (codes, push approvals, "verify
# it's you"), in a title / heading.
_VERIFY_WORDS = re.compile(
    r"verif|2-step|two-step|two-factor|2fa|mfa|multi-factor|authenticator|"
    r"approve|confirm (?:it'?s|that it'?s|your identity)|it'?s you|"
    r"check your (?:phone|email|device|inbox)|security (?:check|code)|one-time|"
    r"本人確認|確認コード|認証",
    re.IGNORECASE,
)
# ... or in the address the sign-in moved to.
_VERIFY_PATH = re.compile(
    r"challenge|verif|mfa|2fa|two-?factor|otp|approv|confirm", re.IGNORECASE
)
# Addresses that still belong to signing in.
_LOGIN_PATH = re.compile(r"log-?in|sign-?in|signin|auth|sso", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")


def origin_of(url: Any) -> Optional[Tuple[str, str, int]]:
    """(scheme, host, port) of an http(s) URL, else None."""
    try:
        parts = urlsplit(str(url or ""))
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        if (
            scheme not in ("http", "https")
            or not host
            or not host.isascii()
            or parts.username is not None
            or parts.password is not None
            or parts.port == 0
        ):
            return None
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None
    return (scheme, host, port)


def site_label(origin: Tuple[str, str, int]) -> str:
    """``host`` (``host:port`` for a non-default port) of the page itself."""
    scheme, host, port = origin
    shown = f"[{host}]" if ":" in host else host
    default = 443 if scheme == "https" else 80
    return shown if port == default else f"{shown}:{port}"


def _fresh_lines(text: Any, before: Any, pattern: "re.Pattern[str]") -> str:
    """The first sentence of ``text`` matching ``pattern`` that ``before``
    did not already show (so a login page's standing hints never count)."""
    old = str(before or "")
    for line in _SENTENCE_SPLIT.split(str(text or "")):
        line = " ".join(line.split())
        if 3 <= len(line) <= 200 and pattern.search(line) and line not in old:
            return line
    return ""


def decide_outcome(
    before: Optional[Dict[str, Any]],
    after: Dict[str, Any],
    url_before: str,
    url_after: str,
) -> Tuple[str, str, str]:
    """``(outcome, site_message, kind)`` of a submitted sign-in.

    ``before`` / ``after`` are observed non-secret page states. Conservative: ``signed_in`` only with positive
    evidence (a sign-out control appeared, or the page left the sign-in
    address for one that is not about signing in or verifying); otherwise
    ``unknown``. ``kind``: "code" / "approve" for needs_verification,
    "form" / "gone" for unknown.
    """
    before = before or {}
    messages = [m for m in after.get("messages") or [] if isinstance(m, str)]
    fresh = [m for m in messages if m not in (before.get("messages") or [])]
    if after.get("captcha") and not before.get("captcha"):
        return "captcha", "", ""
    # A new alert-like message is a rejection while the form is still
    # there; once it is gone, only if it reads like one (a landing page may
    # well show an unrelated banner).
    rejection = next(
        (m for m in fresh if after.get("pwVisible") or _FAILURE_WORDS.search(m)), ""
    )
    if rejection:
        return "error", rejection, ""
    new_code = bool(after.get("code")) and not before.get("code")
    old_heads = set(before.get("headings") or []) | {str(before.get("title") or "")}
    heads = [str(after.get("title") or "")] + [
        str(h) for h in after.get("headings") or []
    ]
    fresh_heads = [h for h in heads if h and h not in old_heads]
    if after.get("pwVisible"):
        # The form is still (or again) there: a sign-in page, so failure
        # wording anywhere on it is about this attempt.
        said = _fresh_lines(
            after.get("bodyHead"), before.get("bodyHead"), _FAILURE_WORDS
        )
        if said:
            return "error", said, ""
        if new_code:
            return "needs_verification", "", "code"
        return "unknown", "", "form"
    failure = next((h for h in fresh_heads if _FAILURE_WORDS.search(h)), "")
    if failure:
        return "error", failure, ""
    if new_code:
        return "needs_verification", "", "code"
    path_before = urlsplit(str(url_before or "")).path
    path_after = urlsplit(str(url_after or "")).path
    moved = path_after != path_before
    if any(_VERIFY_WORDS.search(h) for h in fresh_heads) or (
        moved and _VERIFY_PATH.search(path_after)
    ):
        return "needs_verification", "", "approve"
    signed_out_control = bool(after.get("signOut")) and not before.get("signOut")
    left = moved and not _LOGIN_PATH.search(path_after)
    if signed_out_control or left:
        return "signed_in", "", ""
    return "unknown", "", "gone"


async def autofill(
    core: Any,
    tab: Any,
    *,
    username: Optional[str] = None,
    submit: bool = True,
    credential_reference: Optional[str] = None,
    helper: Optional[str] = None,
    operation: str = "login",
) -> Dict[str, Any]:
    """Only generated session cookies enter the ordinary browser context."""
    handoff = {
        "status": "error",
        "outcome": "owner_handoff_required",
        "message": "Select a saved reference and installed login helper, or take control to sign in and complete MFA/passkeys. Google system-browser OAuth remains available.",
    }
    if not credential_reference or not helper or not submit:
        return handoff
    page, start_url = tab.page, tab.page.main_frame.url
    origin = origin_of(start_url)
    if origin is None or origin[0] != "https" or tab.user_control:
        return handoff
    try:
        from app.credentials.client import request
        from app.credentials.invocation import invoke_async
        from app.credentials.references import parse
        import json

        parse(credential_reference)
        offset, route = 0, None
        while offset <= 1024:
            catalog = await asyncio.to_thread(request, "catalog", offset=offset)
            route = next(
                (
                    r
                    for r in catalog["helpers"]
                    if r["type"] == "form"
                    and r["helper"] == helper
                    and r["operation"] == operation
                ),
                None,
            )
            if route or not catalog["more"]:
                break
            offset = catalog.get("next_offset", offset + 8)
        if route is None or origin_of(route["endpoint"]) != origin:
            return handoff
        response = await invoke_async(
            credential_reference,
            helper,
            operation,
            subject="Mini Browser saved sign-in",
        )
        if response["status"] != 200:
            return handoff
        result = json.loads(response["body"])
        if (
            tab.user_control
            or page.main_frame.url != start_url
            or origin_of(result["continue_url"]) != origin
        ):
            return handoff
        # The trusted helper exports only its reviewed cookie names and exact
        # HTTPS origin. No source fields, form HTML, traces or screenshot buffers
        # cross this boundary. Existing profile/cookie ownership stays here.
        await page.context.add_cookies(result["cookies"])
        if not tab.user_control and page.main_frame.url == start_url:
            await page.goto(result["continue_url"], wait_until="domcontentloaded")
        return {
            "status": "success",
            "outcome": "unknown",
            "site": site_label(origin),
            "message": "An approved login session was installed. Check the page before assuming sign-in succeeded.",
        }
    except Exception:
        return handoff
