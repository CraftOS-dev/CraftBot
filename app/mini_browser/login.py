"""Saved-login autofill for the Mini Browser (origin-checked, never leaks).

``autofill(core, tab, username=None, submit=True)`` signs the agent's tab in
with a login from the password vault. Guarantees:

- The site is always the page's own origin (``page.main_frame.url`` at fill
  time). The vault decides which saved logins may be used there
  (``candidates_for_url``); ``username`` only picks among those.
- The origin is checked again right before every fill, and the fields are
  tagged with a fresh random nonce: a fill can only land in the document the
  form was found in, never in a page the tab navigated to meanwhile.
- The username field is looked for inside the password field's form (never
  a header search box). Two-step sign-ins (identifier first) are supported.
- The password never appears in a return value, event, log line or
  exception: it lives in a redacting holder, fill failures become fixed
  messages raised outside any ``except`` block (Playwright's error text
  contains the filled value), and it is added to ``tab.filled_secrets`` so
  everything the tab sends out is scrubbed.
- Results and notices name the page's real host (where the login was
  typed), not just the saved site.
- The reported outcome is conservative: ``signed_in`` needs positive
  evidence (a sign-out control appeared, or the sign-in address was left);
  failure pages, verification / push-approval steps and CAPTCHAs are told
  apart, and anything else is ``unknown`` ("check the page").
- Filling stops (MINI_BROWSER_USER_IN_CONTROL) once the user takes control
  of the tab.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from app.logger import logger
from app.mini_browser import human, ops
from app.mini_browser.errors import MiniBrowserError, action_error, scrub
from app.mini_browser.observe import is_context_destroyed
from app.mini_browser.types import EVENT_NOTICE

FILL_TIMEOUT_MS = 3000
PROBE_TIMEOUT_S = 10.0
STEP_WAIT_S = 10.0  # two-step: how long to wait for the password field
PROBE_POLL_S = 0.3
SUBMIT_REACTION_MS = 1500

MSG_NOT_WEB = (
    "This tab is not showing a web page. Open the site's sign-in page first, "
    "then call mini_browser_login."
)
MSG_NO_FORM = (
    "There is no sign-in form on this page. Open the site's sign-in page "
    "first, then call mini_browser_login."
)
MSG_SIGNUP_FORM = (
    "This looks like a sign-up or change-password form, not a sign-in form, "
    "so nothing was filled."
)
MSG_FILL_FAILED = (
    "Could not fill the sign-in form: the page changed or the field could not "
    "be used. Call mini_browser_read, then try mini_browser_login again."
)
MSG_ORIGIN_CHANGED = (
    "The page moved to a different site before the sign-in form was filled, "
    "so nothing more was filled. If the new page is the site's real sign-in "
    "page, call mini_browser_login again."
)
MSG_SUBMIT_FAILED = (
    "The sign-in form was filled but could not be submitted. Click the sign-in button."
)
MSG_NO_PASSWORD_STEP = (
    "Entered the username and continued, but no password field appeared "
    "within 10 s (the site may want a code, a CAPTCHA or another step). Check "
    "the page."
)
MSG_NO_USERNAME = "The saved login has no username for this two-step sign-in."
MSG_NO_PASSWORD = "The saved login has no password."
MSG_VAULT_UNAVAILABLE = (
    "The password vault is not available right now. Try again in a moment."
)

# Finds the sign-in fields in one frame and tags them
# data-mb-login="<nonce>-pw|user|submit". Returns what it found.
FIND_LOGIN_JS = r"""
(nonce) => {
  const ATTR = 'data-mb-login';
  const parentOf = (n) => n.parentElement
    || (n.parentNode && n.parentNode.host ? n.parentNode.host : null);
  const contains = (anc, el) => { for (let n = el; n; n = parentOf(n)) if (n === anc) return true; return false; };
  const elements = [];
  const walk = (root) => {
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      elements.push(n);
      if (n.hasAttribute(ATTR)) n.removeAttribute(ATTR);
      if (n.shadowRoot) walk(n.shadowRoot);
    }
  };
  walk(document);
  const order = new Map(elements.map((e, i) => [e, i]));
  const opts = {checkOpacity: true, checkVisibilityCSS: true, opacityProperty: true, visibilityProperty: true};
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2 && (!el.checkVisibility || el.checkVisibility(opts));
  };
  const usable = (el) => visible(el) && !el.disabled && !el.readOnly;
  const ac = (el) => (el.getAttribute('autocomplete') || '').toLowerCase();
  const type = (el) => String(el.type || 'text').toLowerCase();
  const inputs = elements.filter((e) => e.tagName === 'INPUT');
  // Marked for observe.py: stays secret even if a "show password" toggle
  // turns it into a text field later.
  inputs.forEach((e) => { if (type(e) === 'password') e.setAttribute('data-mb-pw', ''); });

  const passwords = inputs.filter((e) => type(e) === 'password' && usable(e));
  let pw = passwords.find((e) => /(^|\s)current-password(\s|$)/.test(ac(e)))
    || passwords.find((e) => !/(^|\s)new-password(\s|$)/.test(ac(e)))
    || (passwords.length === 1 ? passwords[0] : null);

  const words = (el) => [el.getAttribute('name'), el.id, el.getAttribute('aria-label'),
    el.getAttribute('placeholder'), el.getAttribute('title')].join(' ');
  const formWords = (el) => {
    const f = el.form || (el.closest ? el.closest('form') : null);
    return f ? [f.getAttribute('action'), f.id, f.getAttribute('name'), f.getAttribute('class'),
                f.getAttribute('role'), f.getAttribute('aria-label')].join(' ') : '';
  };
  const isSearch = (el) => {
    if (type(el) === 'search') return true;
    if ((el.getAttribute('role') || '').toLowerCase() === 'searchbox') return true;
    if (/(^|[^a-z])(search|query|keywords?|q)([^a-z]|$)/i.test(words(el))) return true;
    if (/search/i.test(formWords(el))) return true;
    for (let n = el; n; n = parentOf(n)) {
      if (n.tagName === 'SEARCH' || (n.getAttribute && (n.getAttribute('role') || '').toLowerCase() === 'search')) return true;
    }
    return false;
  };
  const textish = (el) => ['text', 'email', 'tel'].includes(type(el));
  const candidates = (scope) => inputs.filter((e) => e !== pw && textish(e) && usable(e)
    && !isSearch(e) && (!scope || e.form === scope || contains(scope, e)));
  const userTests = [
    (e) => /(^|\s)username(\s|$)/.test(ac(e)),
    (e) => type(e) === 'email' || /(^|\s)email(\s|$)/.test(ac(e)),
    (e) => /user|e-?mail|login|account|identifier|signin/i.test((e.getAttribute('name') || '') + ' ' + (e.id || '')),
  ];
  const pick = (list) => {
    for (const test of userTests) { const hit = list.find(test); if (hit) return hit; }
    return null;
  };

  let scope = null;
  let user = null;
  if (pw) {
    scope = pw.form || null;
    if (!scope) {
      let depth = 0;
      for (let n = parentOf(pw); n && depth < 8; n = parentOf(n), depth++) {
        if (n === document.body || n === document.documentElement) break;
        if (candidates(n).length) { scope = n; break; }
      }
    }
    if (scope) {
      const list = candidates(scope);
      user = pick(list);
      if (!user) {
        const before = list.filter((e) => order.get(e) < order.get(pw));
        if (before.length) user = before[before.length - 1];
      }
    }
  } else if (!passwords.length) {
    // Two-step sign-in: an account field on its own (no password field at
    // all; sign-up pages show "new-password" fields). Score it strictly so a
    // newsletter or contact box is never taken for a sign-in field.
    const signin = /log ?-?in|sign ?-?in|auth|session|account|identif|passw/i;
    const other = /newsletter|subscri|sign ?-?up|regist|contact|comment|feedback|coupon|promo/i;
    const pageHint = signin.test(location.pathname + ' ' + document.title) ? 2 : 0;
    let best = null;
    let bestScore = 0;
    for (const e of candidates(null)) {
      let score = 0;
      if (userTests[0](e)) score += 3;
      if (userTests[1](e)) score += 1;
      if (userTests[2](e)) score += 1;
      if (!score) continue;
      const context = formWords(e);
      if (signin.test(context)) score += 2;
      if (other.test(context) || other.test(words(e))) score -= 5;
      score += pageHint;
      if (score > bestScore) { best = e; bestScore = score; }
    }
    if (best && bestScore >= 3) {
      user = best;
      scope = best.form || null;
    }
  }

  // The button that submits this form (used when Enter does nothing).
  let submit = null;
  const field = pw || user;
  if (field) {
    const root = scope || field.getRootNode();
    const buttons = Array.from(root.querySelectorAll
      ? root.querySelectorAll('button, input[type="submit"], input[type="image"], [role="button"]') : []);
    const enabled = buttons.filter((b) => visible(b) && !b.disabled && b.getAttribute('aria-disabled') !== 'true');
    const label = (b) => String(b.innerText || b.value || b.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    const named = /^(log ?-?in|sign ?-?in|continue|next|submit|go|ok|enter|ログイン|サインイン|次へ|続行|続ける)$/i;
    submit = enabled.find((b) => named.test(label(b)))
      || enabled.find((b) => (b.tagName === 'BUTTON' && (!b.getAttribute('type') || b.type === 'submit'))
        || (b.tagName === 'INPUT' && (b.type === 'submit' || b.type === 'image')))
      || null;
  }

  if (pw) pw.setAttribute(ATTR, nonce + '-pw');
  if (user) user.setAttribute(ATTR, nonce + '-user');
  if (submit) submit.setAttribute(ATTR, nonce + '-submit');
  return {
    pw: !!pw,
    user: !!user,
    submit: !!submit,
    signup: !pw && passwords.length > 1,
  };
}
"""

# What the page looks like after a sign-in attempt.
OUTCOME_JS = r"""
() => {
  const parentOf = (n) => n.parentElement
    || (n.parentNode && n.parentNode.host ? n.parentNode.host : null);
  const elements = [];
  const walk = (root) => {
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      elements.push(n);
      if (n.shadowRoot) walk(n.shadowRoot);
    }
  };
  walk(document);
  const opts = {checkOpacity: true, checkVisibilityCSS: true, opacityProperty: true, visibilityProperty: true};
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1 && (!el.checkVisibility || el.checkVisibility(opts));
  };
  const pwVisible = elements.some((e) => e.tagName === 'INPUT'
    && String(e.type || '').toLowerCase() === 'password' && visible(e));
  const errorish = /(^|[\s_-])(error|errors|alert|invalid|danger|warning|failure|failed)([\s_-]|$)/i;
  const messages = [];
  for (const el of elements) {
    if (messages.length >= 5) break;
    const role = (el.getAttribute('role') || '').toLowerCase();
    const live = (el.getAttribute('aria-live') || '').toLowerCase();
    const named = errorish.test(String(el.getAttribute('class') || '') + ' ' + (el.id || ''));
    if (!(role === 'alert' || live === 'assertive' || named)) continue;
    if (!visible(el) || el.querySelector('input, select, textarea')) continue;
    const text = String(el.innerText || '').replace(/\s+/g, ' ').trim();
    if (text.length < 3 || text.length > 300) continue;
    if (!messages.some((m) => m.includes(text) || text.includes(m))) messages.push(text);
  }
  const body = String((document.body && document.body.innerText) || '').slice(0, 20000);
  // A verification step needs a field for the code, not just words on the
  // page (dashboards advertise "two-factor authentication" too).
  const inputs = elements.filter((e) => e.tagName === 'INPUT' && visible(e) && !e.disabled);
  const otpField = inputs.some((e) => /one-time-code/i.test(e.getAttribute('autocomplete') || ''));
  const codeField = inputs.some((e) =>
    /(^|[^a-z])(otp|totp|2fa|mfa|code|pin|passcode|verif|token)/i.test(
      (e.getAttribute('name') || '') + ' ' + (e.id || ''))
    || (e.getAttribute('inputmode') === 'numeric'
        && +(e.getAttribute('maxlength') || 0) > 0 && +(e.getAttribute('maxlength') || 0) <= 8));
  const codeWords = /verification code|security code|2-step|two-step|two-factor|2fa|authenticator app|one-time (pass)?code|確認コード|認証コード|ワンタイム/i.test(body);
  const code = otpField || (codeField && codeWords);
  // A visible challenge widget (not the invisible reCAPTCHA v3 badge).
  const captcha = Array.from(document.querySelectorAll(
      'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], '
      + 'iframe[src*="challenges.cloudflare.com"], iframe[title*="captcha" i]'))
    .some((f) => {
      if (/size=invisible/.test(f.getAttribute('src') || '')) return false;
      const r = f.getBoundingClientRect();
      return r.width >= 100 && r.height >= 50 && visible(f);
    });
  const oneLine = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const headings = [];
  for (const el of elements) {
    if (headings.length >= 6) break;
    if (!/^H[1-3]$/.test(el.tagName) && (el.getAttribute('role') || '').toLowerCase() !== 'heading') continue;
    if (!visible(el)) continue;
    const t = oneLine(el.innerText);
    if (t && t.length <= 200) headings.push(t);
  }
  // Positive evidence of a signed-in page: a sign-out control.
  const signOutWords = /(^|[^a-z])(sign|log)\s?-?\s?(out|off)([^a-z]|$)|ログアウト|サインアウト/i;
  const signOut = elements.some((e) => {
    if (e.tagName === 'A' && /(sign|log)[-_]?(out|off)/i.test(String(e.getAttribute('href') || ''))) return true;
    const role = (e.getAttribute('role') || '').toLowerCase();
    if (!(e.tagName === 'A' || e.tagName === 'BUTTON' || role === 'menuitem' || role === 'button' || role === 'link')) return false;
    const t = oneLine(e.innerText || e.getAttribute('aria-label') || e.getAttribute('title'));
    return t.length > 0 && t.length <= 40 && signOutWords.test(t) && visible(e);
  });
  return {pwVisible, messages, code, captcha, headings, signOut,
          title: oneLine(document.title).slice(0, 200), bodyHead: body.slice(0, 3000),
          path: location.pathname};
}
"""

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


class _Hidden:
    """Holds a password. Never shows it in a repr, str() or traceback."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "<hidden>"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("hidden values cannot be pickled")


def origin_of(url: Any) -> Optional[Tuple[str, str, int]]:
    """(scheme, host, port) of an http(s) URL, else None."""
    try:
        parts = urlsplit(str(url or ""))
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower().rstrip(".")
        if scheme not in ("http", "https") or not host:
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

    ``before`` / ``after``: OUTCOME_JS states before the password was filled
    and after submitting. Conservative: ``signed_in`` only with positive
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


def _failed(detail: str) -> MiniBrowserError:
    return MiniBrowserError("MINI_BROWSER_LOGIN_FAILED", detail=detail)


def _check_origin(page: Any, frame: Any, origin: Tuple[str, str, int]) -> None:
    """Abort unless the page AND the form's frame are still on ``origin``."""
    try:
        detached = frame.is_detached()
        same = (
            origin_of(page.main_frame.url) == origin and origin_of(frame.url) == origin
        )
    except Exception:
        detached, same = True, False
    if detached:
        raise _failed(MSG_FILL_FAILED)
    if not same:
        raise _failed(MSG_ORIGIN_CHANGED)


def _choose(
    entries: List[Dict[str, Any]], username: Optional[str]
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """The entry to use (vault order = best first) and the other usernames."""
    chosen: Optional[Dict[str, Any]] = None
    if not username:
        chosen = entries[0]
    else:
        wanted = username.strip().casefold()
        names = [str(e.get("username") or "").casefold() for e in entries]
        exact = [e for e, name in zip(entries, names) if name == wanted]
        if exact:
            chosen = exact[0]
        else:
            local = [
                e for e, name in zip(entries, names) if name.split("@")[0] == wanted
            ]
            chosen = local[0] if len(local) == 1 else None
    others = [str(e.get("username") or "") for e in entries if e is not chosen]
    return chosen, others


async def _no_login(vault: Any, host: str) -> MiniBrowserError:
    """The error for "no candidate": unreadable vault vs. nothing saved."""
    try:
        status = await asyncio.to_thread(vault.status)
    except Exception as exc:
        logger.debug(f"[MiniBrowser] vault status failed: {type(exc).__name__}")
        status = {}
    if isinstance(status, dict) and status.get("unreadable"):
        return MiniBrowserError("MINI_BROWSER_VAULT_UNREADABLE")
    if isinstance(status, dict) and status and not status.get("ok", True):
        return _failed(MSG_VAULT_UNAVAILABLE)
    return MiniBrowserError("MINI_BROWSER_NO_SAVED_LOGIN", site=host)


async def _probe(frame: Any, nonce: str) -> Optional[Dict[str, Any]]:
    try:
        info = await asyncio.wait_for(
            frame.evaluate(FIND_LOGIN_JS, nonce), PROBE_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None
    except Exception as exc:
        if not is_context_destroyed(exc):
            logger.debug(f"[MiniBrowser] login probe failed: {type(exc).__name__}")
        return None
    return info if isinstance(info, dict) else None


def _same_origin_frames(page: Any, origin: Tuple[str, str, int]) -> List[Any]:
    frames = [page.main_frame]
    try:
        for frame in page.frames:
            if frame is not page.main_frame and origin_of(frame.url) == origin:
                frames.append(frame)
    except Exception:
        pass
    return frames


async def find_form(
    page: Any, origin: Tuple[str, str, int], nonce: str
) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """(frame, info) of the sign-in form: a password form first (main frame,
    then same-origin frames), else a two-step account field, else a
    sign-up-only form (``info["signup"]``)."""
    fallback: Optional[Tuple[Any, Dict[str, Any]]] = None
    for frame in _same_origin_frames(page, origin):
        info = await _probe(frame, nonce)
        if not info:
            continue
        if info.get("pw"):
            return frame, info
        if info.get("user") and (fallback is None or not fallback[1].get("user")):
            fallback = (frame, info)
        elif info.get("signup") and fallback is None:
            fallback = (frame, info)
    return fallback


async def _point_at(core: Any, tab: Any, locator: Any) -> None:
    """Move the agent's pointer onto a field (purely visual, best effort;
    stops with MINI_BROWSER_USER_IN_CONTROL once the user takes control)."""
    if not ops.humanlike_enabled(core):
        return
    try:
        box = await locator.bounding_box(timeout=1000)
        if box and box["width"] > 0 and box["height"] > 0:
            await human.move_mouse(core, tab, *human.target_point(box))
    except (asyncio.CancelledError, MiniBrowserError):
        raise
    except Exception:
        pass


async def _fill(
    core: Any,
    tab: Any,
    frame: Any,
    nonce: str,
    role: str,
    value: Any,
    origin: Tuple[str, str, int],
) -> None:
    """Fill the tagged field; any failure becomes a fixed message.

    ``value`` is a plain username or a ``_Hidden`` password. The exception
    raised by a failed fill carries the value in its call log, so it is
    reduced to its type name inside the ``except`` and the fixed error is
    raised afterwards (no exception chaining).
    """
    page = tab.page
    human.ensure_control(tab)
    _check_origin(page, frame, origin)
    locator = frame.locator(f'[data-mb-login="{nonce}-{role}"]')
    await _point_at(core, tab, locator)
    human.ensure_control(tab)
    _check_origin(page, frame, origin)
    failure = ""
    try:
        if await asyncio.wait_for(locator.count(), 3.0) != 1:
            failure = "field gone"
        else:
            await locator.fill(
                value.reveal() if isinstance(value, _Hidden) else value,
                timeout=FILL_TIMEOUT_MS,
            )
    except Exception as exc:
        failure = type(exc).__name__
    if failure:
        logger.warning(
            f"[MiniBrowser] login: filling the {role} field failed ({failure})"
        )
        raise _failed(MSG_FILL_FAILED)


async def _mutations(page: Any, quiet_ms: int, max_ms: int) -> Tuple[bool, int]:
    """(navigated, DOM mutation count) while the page reacts."""
    try:
        result = await asyncio.wait_for(
            page.evaluate(ops.SETTLE_JS, {"quietMs": quiet_ms, "maxMs": max_ms}),
            max_ms / 1000.0 + 2.0,
        )
    except asyncio.TimeoutError:
        return False, 0
    except Exception as exc:
        return is_context_destroyed(exc), 0
    count = result.get("mutations") if isinstance(result, dict) else 0
    return False, int(count or 0)


async def _submit(
    core: Any, tab: Any, frame: Any, nonce: str, role: str, origin: Tuple[str, str, int]
) -> None:
    """Submit the form: Enter in the field; if nothing reacts, click its button.

    Leaves the page settled (following a navigation it caused).
    """
    page = tab.page
    human.ensure_control(tab)
    _check_origin(page, frame, origin)
    field = frame.locator(f'[data-mb-login="{nonce}-{role}"]')
    with ops.NavWatch(page) as watch:
        pressed = True
        try:
            await field.press("Enter", timeout=FILL_TIMEOUT_MS)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] login: Enter failed ({type(exc).__name__})")
            pressed = False
        navigated, mutations = (
            await _mutations(page, 300, SUBMIT_REACTION_MS) if pressed else (False, 0)
        )
        reacted = pressed and (
            navigated
            or watch.started
            or watch.commits > 0
            or watch.requests > 0
            or mutations > 0
        )
        if not reacted:
            button = frame.locator(f'[data-mb-login="{nonce}-submit"]')
            clicked = False
            try:
                if await asyncio.wait_for(button.count(), 3.0) == 1:
                    _check_origin(page, frame, origin)
                    await ops.pointer_click(core, tab, button, -1)
                    clicked = True
            except MiniBrowserError as exc:
                # The button could not be clicked: Enter may still have done
                # it. Anything else (the user took control, the page or the
                # browser went away, another site) ends the sign-in.
                if exc.code not in (
                    "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                    "MINI_BROWSER_ELEMENT_NOT_FOUND",
                ):
                    raise
            except Exception as exc:
                logger.debug(
                    f"[MiniBrowser] login: submit click failed ({type(exc).__name__})"
                )
            if not clicked and not pressed:
                raise _failed(MSG_SUBMIT_FAILED)
        await ops.after_action(page, watch, core=core)


async def _wait_for_password_step(
    page: Any, origin: Tuple[str, str, int]
) -> Optional[Tuple[Any, Dict[str, Any], str]]:
    """Two-step: wait for the password field; abort if the site changes."""
    deadline = time.monotonic() + STEP_WAIT_S
    while True:
        if origin_of(page.main_frame.url) != origin:
            raise _failed(MSG_ORIGIN_CHANGED)
        nonce = secrets.token_hex(8)
        found = await find_form(page, origin, nonce)
        if found is not None and found[1].get("pw"):
            return found[0], found[1], nonce
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(PROBE_POLL_S)


async def _page_state(page: Any, frame: Any) -> Dict[str, Any]:
    """Merged OUTCOME_JS of the main frame and the form's frame."""
    merged: Dict[str, Any] = {
        "pwVisible": False,
        "messages": [],
        "code": False,
        "captcha": False,
        "signOut": False,
        "title": "",
        "headings": [],
        "bodyHead": "",
    }
    frames = [page.main_frame]
    try:
        if frame is not page.main_frame and not frame.is_detached():
            frames.append(frame)
    except Exception:
        pass
    for target in frames:
        try:
            state = await asyncio.wait_for(target.evaluate(OUTCOME_JS), PROBE_TIMEOUT_S)
        except Exception as exc:
            logger.debug(
                f"[MiniBrowser] login outcome check failed: {type(exc).__name__}"
            )
            continue
        if not isinstance(state, dict):
            continue
        for flag in ("pwVisible", "code", "captcha", "signOut"):
            merged[flag] = merged[flag] or bool(state.get(flag))
        if not merged["title"] and isinstance(state.get("title"), str):
            merged["title"] = state["title"]
        for key in ("messages", "headings"):
            for item in state.get(key) or []:
                if isinstance(item, str) and item not in merged[key]:
                    merged[key].append(item)
        if isinstance(state.get("bodyHead"), str):
            merged["bodyHead"] = (merged["bodyHead"] + "\n" + state["bodyHead"]).strip()
    return merged


def _without_fragment(url: str) -> str:
    return str(url or "").split("#", 1)[0]


async def autofill(
    core: Any, tab: Any, *, username: Optional[str] = None, submit: bool = True
) -> Dict[str, Any]:
    """Fill (and by default submit) the page's sign-in form from the vault.

    Returns ``{status, message, username, site, outcome, page}`` (plus
    ``other_usernames`` when several logins match) — never the password.
    ``outcome``: filled | signed_in | needs_verification | captcha |
    unknown | error.
    """
    page = tab.page
    start_url = page.main_frame.url
    origin = origin_of(start_url)
    if origin is None:
        raise _failed(MSG_NOT_WEB)
    # Results and notices name the page's own host, where the login is
    # typed (a saved "example.com" says nothing about which page got it).
    site = site_label(origin)

    try:
        vault = core.vault()
    except MiniBrowserError:
        raise
    except Exception as exc:
        logger.warning(
            f"[MiniBrowser] password vault unavailable: {type(exc).__name__}"
        )
        raise _failed(MSG_VAULT_UNAVAILABLE) from None
    entries = await asyncio.to_thread(vault.candidates_for_url, start_url)
    if not entries:
        raise await _no_login(vault, site)
    entry, others = _choose(entries, username)
    if entry is None:
        raise MiniBrowserError(
            "MINI_BROWSER_NO_SAVED_LOGIN", site=f"{site} for username {username!r}"
        )
    secret = _Hidden(str(entry.get("password") or ""))
    entry_id = str(entry.get("id") or "")
    account = str(entry.get("username") or "")
    del entries, entry  # drop every reference to raw passwords but `secret`
    if not secret:
        raise _failed(MSG_NO_PASSWORD)

    nonce = secrets.token_hex(8)
    found = await find_form(page, origin, nonce)
    if found is None:
        raise _failed(MSG_NO_FORM)
    frame, info = found
    if not info.get("pw") and not info.get("user"):
        raise _failed(MSG_SIGNUP_FORM if info.get("signup") else MSG_NO_FORM)

    if info.get("pw"):
        if info.get("user") and account:
            await _fill(core, tab, frame, nonce, "user", account, origin)
    else:
        # Two-step sign-in: account first, then the password page.
        if not account:
            raise _failed(MSG_NO_USERNAME)
        await _fill(core, tab, frame, nonce, "user", account, origin)
        await _submit(core, tab, frame, nonce, "user", origin)
        step = await _wait_for_password_step(page, origin)
        if step is None:
            observation = await ops.page_observation(core, tab)
            return action_error(
                "MINI_BROWSER_LOGIN_FAILED",
                secrets=[secret.reveal()],
                extra={
                    "username": account,
                    "site": site,
                    "outcome": "unknown",
                    "page": observation,
                },
                detail=MSG_NO_PASSWORD_STEP,
            )
        frame, info, nonce = step

    if secret.reveal() not in tab.filled_secrets:
        tab.filled_secrets.append(secret.reveal())
    before = await _page_state(page, frame) if submit else None
    await _fill(core, tab, frame, nonce, "pw", secret, origin)
    try:
        await asyncio.to_thread(vault.mark_used, entry_id)
    except Exception as exc:  # bookkeeping only
        logger.debug(
            f"[MiniBrowser] could not mark the login used: {type(exc).__name__}"
        )
    who = f"{account} on {site}" if account else site
    try:
        core.add_event(tab, EVENT_NOTICE, f"Filled the saved login for {who}.")
    except Exception as exc:
        logger.debug(f"[MiniBrowser] login notice failed: {type(exc).__name__}")

    outcome, site_message, kind, title = "filled", "", "", ""
    if submit:
        url_before = _without_fragment(page.url)
        await _submit(core, tab, frame, nonce, "pw", origin)
        if ops.tab_gone(core, tab):
            raise ops.closed_error(core, tab)
        after = await _page_state(page, frame)
        outcome, site_message, kind = decide_outcome(
            before, after, url_before, _without_fragment(page.url)
        )
        title = scrub(
            " ".join(str(after.get("title") or "").split()), [secret.reveal()]
        )

    observation = await ops.page_observation(core, tab)
    extra: Dict[str, Any] = {"username": account, "site": site, "outcome": outcome}
    if others:
        extra["other_usernames"] = others
    if outcome == "error":
        said = scrub(site_message, [secret.reveal()])[:200]
        return action_error(
            "MINI_BROWSER_LOGIN_FAILED",
            secrets=[secret.reveal()],
            extra={**extra, "page": observation},
            detail=f'The site did not accept the sign-in: "{said}"',
        )
    message = _outcome_message(outcome, kind, who, title[:120])
    if others:
        message += (
            f" Other saved logins for this site: {', '.join(others)} (pass "
            "username to use one)."
        )
    result: Dict[str, Any] = {
        "status": "success",
        "message": scrub(message, [secret.reveal()]),
    }
    result.update(extra)
    result["page"] = observation
    return result


_WAIT_FOR_USER = (
    "then call mini_browser_wait with for_user=true: it waits until they take "
    "control of this tab and hand it back"
)


def _outcome_message(outcome: str, kind: str, who: str, title: str) -> str:
    """What the agent is told after a sign-in attempt (and what to do next)."""
    shows = f' "{title}"' if title else " a new page"
    if outcome == "filled":
        return f"Filled the saved login for {who} (not submitted)."
    if outcome == "signed_in":
        return f"Signed in as {who}."
    if outcome == "captcha":
        return (
            f"Submitted the saved login for {who}, but the site shows a CAPTCHA. "
            "Never try to solve it yourself: tell the user (send_message) to solve "
            "it in the Mini Browser page and press Hand back, "
            f"{_WAIT_FOR_USER}."
        )
    if outcome == "needs_verification" and kind == "code":
        return (
            f"Submitted the saved login for {who}; the site now asks for a "
            "verification code. Ask the user for it (never guess it) and type it "
            "in, or tell them to enter it in the Mini Browser page and press Hand "
            f"back, {_WAIT_FOR_USER}."
        )
    if outcome == "needs_verification":
        return (
            f"Submitted the saved login for {who}; the site now wants the user to "
            f"confirm the sign-in (the page shows{shows}; for example approving a "
            "prompt on their phone). Ask the user to do that. If they have to act "
            "in the Mini Browser page, tell them to press Hand back when done, "
            f"{_WAIT_FOR_USER}; otherwise check again with mini_browser_wait "
            "(text=...) or mini_browser_read."
        )
    if kind == "form":
        return (
            f"Submitted the saved login for {who}, but the sign-in form is still "
            f"showing (the page shows{shows}). Check the page: the site may show an "
            "error or want another step. Do not assume you are signed in."
        )
    return (
        f"Submitted the saved login for {who}; the sign-in form is gone and the "
        f"page now shows{shows}. Check it before assuming you are signed in."
    )
