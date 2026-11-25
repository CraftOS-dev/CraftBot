"""Mask secret-shaped text in tool results before the model sees them.

Settings > Security > "Hide secrets in results" (``redact_tool_output``).

app/security/redact.py hides the exact secret values CraftBot itself holds,
in log lines. This module is the other half, ported from Hermes Agent's
``agent/redact.py`` (MIT, Nous Research): a command's output or a file the
agent reads can carry anyone's credentials (a ``.env``, ``env`` output, a
``curl -v`` dump, a kubeconfig), and Hermes masks them by shape before they
reach the model (``security.redact_secrets``, on by default there; applied
to terminal output in tools/terminal_tool_result.py and to file reads in
tools/file_tools.py).

The passes, in Hermes' order:

- whole private-key blocks (PEM, base64 PEM, PGP, PuTTY, age) and the body
  of a partial key print;
- known vendor key prefixes (``sk-``, ``ghp_``, ``AKIA``, ``xoxb-`` ...);
- Zhipu ``id.secret`` keys and Discord bot tokens (validated by decoding);
- credentials passed as command-line flags (``--password=``, ``--token``,
  ``docker login -p``) and Azure connection-string keys;
- ``Authorization:`` headers, API-key headers and cookies;
- Telegram bot tokens;
- passwords in database URLs and ``user:pass@`` URL userinfo, bare-token
  URL userinfo and incoming-webhook URLs;
- JWTs;
- whole ``NAME=value`` lines (``env`` output, ``.env`` files) whose name is
  credential-like and whose value is not a reference or a literal
  (Hermes' ``redact_code_output`` env-dump pass).

Like Hermes' terminal and file-read surfaces, source-code assignments such
as ``MAX_TOKENS = 100`` or ``"apiKey": "test"`` fixtures are left alone,
and URL query strings pass through (OAuth callbacks and magic links must
still work). Hermes' phone-number masking is not ported: a phone number is
personal data, not a credential.

Each pass sits behind a substring gate its pattern requires, so ordinary
output skips almost all of the regex work. Masks are non-reusable markers
(``[REDACTED]``, ``[REDACTED:ghp_]``), never a head/tail fragment the agent
could write back into a config file as a dead key (Hermes issue #35519).

Python 3.10 has no possessive quantifiers or atomic groups, so the patterns
that use them in Hermes are rewritten with single-character alternations
that stay linear on input that fails to match.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import List

from app.security.redact import MASK

PRIVATE_KEY_MASK = "[REDACTED PRIVATE KEY]"


def _is_marker(value: str) -> bool:
    """A value an earlier pass already masked: masking it again is a no-op."""
    return value.startswith("[REDACTED")


# ── private keys ────────────────────────────────────────────────────────────

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"
)
# Base64 of a PEM private key (kubeconfig ``client-key-data``): kept only
# when it really decodes to a ``BEGIN ... PRIVATE KEY`` header.
_B64_PEM_RE = re.compile(r"LS0tLS1CRUdJTi[A-Za-z0-9+/=]{60,}")
_PGP_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN PGP PRIVATE KEY BLOCK-----[\s\S]*?-----END PGP PRIVATE KEY BLOCK-----"
)
_PPK_EOL = r"(?:\r?\n|\\r\\n|\\n)"
_PPK_BODY_GUTTER = r"[ \t]*(?:[0-9]+(?:[|:]|\t)[ \t]*)?"
# Each body line must end in a line break (or the end of text), so the run
# cannot be split between repetitions in more than one way.
_PUTTY_PRIVATE_LINES_RE = re.compile(
    rf"(?<![\w-])(Private-Lines:[ \t]*[0-9]+[ \t]*(?P<eol>{_PPK_EOL}))"
    rf"(?:{_PPK_BODY_GUTTER}[A-Za-z0-9+/=]{{16,}}[ \t]*(?:{_PPK_EOL}|\Z))+"
)
_AGE_SECRET_KEY_RE = re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{20,}")

# A ``head``/``tail`` of a key file keeps only one armor line.
_PRIVATE_KEY_ARMOR_RE = re.compile(r"-----(BEGIN|END)[A-Z ]*PRIVATE KEY-----")
_PEM_BODY_LINE_RE = re.compile(r"[ \t]*(?![0-9A-Fa-f]+[ \t]*$)[A-Za-z0-9+/=]{16,}[ \t]*")
_PEM_TRAILER_RE = re.compile(r"[ \t]*(?:[A-Za-z0-9+/]{1,15}={0,2}|==?)[ \t]*")


def _is_b64_pem_key(blob: str) -> bool:
    padded = blob + "=" * (-len(blob) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False)
    except (binascii.Error, ValueError):
        return False
    head = decoded[:64]
    return head.startswith(b"-----BEGIN") and b"PRIVATE KEY" in head


def _redact_partial_private_keys(text: str) -> str:
    """Mask the base64 run next to a lone BEGIN (forward) or END (backward)
    armor line. Walks lines, so a large blob stays linear."""
    lines = text.split("\n")
    drop = set()
    for i, line in enumerate(lines):
        m = _PRIVATE_KEY_ARMOR_RE.search(line)
        if not m:
            continue
        step = 1 if m.group(1) == "BEGIN" else -1
        j = i + step
        if (
            step < 0
            and j > 0
            and _PEM_TRAILER_RE.fullmatch(lines[j].rstrip("\r"))
            and _PEM_BODY_LINE_RE.fullmatch(lines[j - 1].rstrip("\r"))
        ):
            drop.add(j)
            j -= 1
        while 0 <= j < len(lines) and j not in drop and _PEM_BODY_LINE_RE.fullmatch(
            lines[j].rstrip("\r")
        ):
            drop.add(j)
            j += step
        if (
            step > 0
            and i + 1 < j < len(lines)
            and _PEM_TRAILER_RE.fullmatch(lines[j].rstrip("\r"))
            and lines[j].rstrip().endswith("=")
        ):
            drop.add(j)
        if j != i + step:
            lines[i] = PRIVATE_KEY_MASK
    if not drop:
        return text
    return "\n".join(line for k, line in enumerate(lines) if k not in drop)


def _redact_private_key_blocks(text: str) -> str:
    if "-----BEGIN" in text and "-----END" in text:
        text = _PRIVATE_KEY_RE.sub(PRIVATE_KEY_MASK, text)
    if "PRIVATE KEY-----" in text:
        text = _redact_partial_private_keys(text)
    if "LS0tLS1CRUdJTi" in text:
        text = _B64_PEM_RE.sub(
            lambda m: PRIVATE_KEY_MASK if _is_b64_pem_key(m.group(0)) else m.group(0),
            text,
        )
    if "END PGP PRIVATE KEY BLOCK" in text:
        text = _PGP_PRIVATE_KEY_RE.sub(PRIVATE_KEY_MASK, text)
    if "Private-Lines:" in text:
        text = _PUTTY_PRIVATE_LINES_RE.sub(
            lambda m: m.group(1) + PRIVATE_KEY_MASK + m.group("eol"), text
        )
    if "AGE-SECRET-KEY-1" in text:
        text = _AGE_SECRET_KEY_RE.sub(PRIVATE_KEY_MASK, text)
    return text


# ── vendor key prefixes ─────────────────────────────────────────────────────

# Every pattern starts with a literal prefix: the cheap substring gate is
# derived from those literals and must stay free of false negatives.
_PREFIX_PATTERNS = [
    r"sk-[A-Za-z0-9_-](?:\.?[A-Za-z0-9_-]){9,}",  # OpenAI, Anthropic, ... (incl. dotted bodies)
    r"ctx7sk-[A-Za-z0-9_-]{10,}",  # Context7
    r"ghp_[A-Za-z0-9]{10,}",  # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",  # GitHub PAT (fine-grained)
    r"gho_[A-Za-z0-9]{10,}",  # GitHub OAuth access token
    r"ghu_[A-Za-z0-9]{10,}",  # GitHub user-to-server token
    r"ghs_[A-Za-z0-9]{10,}",  # GitHub server-to-server token
    r"ghr_[A-Za-z0-9]{10,}",  # GitHub refresh token
    r"xapp-\d+-[A-Za-z0-9-]{10,}",  # Slack app-level token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",  # Slack bot/app/user tokens
    r"AIza[A-Za-z0-9_-]{30,}",  # Google API keys
    r"GOCSPX-[A-Za-z0-9_-]{8,}",  # Google OAuth client secret
    r"ya29\.(?:[a-z]\.)?[A-Za-z0-9_-]{20,}",  # Google OAuth access token
    r"AQ\.[A-Za-z0-9_-]{40,}",  # Google Gemini authorization keys
    r"1//0[A-Za-z0-9_-]{20,}",  # Google OAuth refresh token
    r"pplx-[A-Za-z0-9]{10,}",  # Perplexity
    r"fal_[A-Za-z0-9_-]{10,}",  # Fal.ai
    r"fc-[A-Za-z0-9]{10,}",  # Firecrawl
    r"bb_live_[A-Za-z0-9_-]{10,}",  # BrowserBase
    r"gAAAA[A-Za-z0-9_=-]{20,}",  # Fernet / Codex encrypted tokens
    r"AKIA[A-Z0-9]{16}",  # AWS access key id
    r"sk_live_[A-Za-z0-9]{10,}",  # Stripe secret key (live)
    r"sk_test_[A-Za-z0-9]{10,}",  # Stripe secret key (test)
    r"rk_live_[A-Za-z0-9]{10,}",  # Stripe restricted key
    r"SG\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{10,})?",  # SendGrid
    r"hf_[A-Za-z0-9]{10,}",  # Hugging Face
    r"r8_[A-Za-z0-9]{10,}",  # Replicate
    r"npm_[A-Za-z0-9]{10,}",  # npm
    r"pypi-[A-Za-z0-9_-]{10,}",  # PyPI
    r"dop_v1_[A-Za-z0-9]{10,}",  # DigitalOcean PAT
    r"doo_v1_[A-Za-z0-9]{10,}",  # DigitalOcean OAuth
    r"am_(?:org_)?[A-Za-z0-9]{20,}",  # AgentMail
    r"sk_[A-Za-z0-9_]{10,}",  # ElevenLabs
    r"tvly-(?:(?:dev|prod)-)?[A-Za-z0-9]{10,}",  # Tavily
    r"exa_[A-Za-z0-9]{10,}",  # Exa
    r"gsk_[A-Za-z0-9]{10,}",  # Groq
    r"syt_[A-Za-z0-9]{10,}",  # Matrix
    r"retaindb_[A-Za-z0-9]{10,}",  # RetainDB
    r"hsk-[A-Za-z0-9]{10,}",  # Hindsight
    r"mem0_[A-Za-z0-9]{10,}",  # Mem0
    r"brv_[A-Za-z0-9]{10,}",  # ByteRover
    r"xai-[A-Za-z0-9]{30,}",  # xAI
    r"ntn_[A-Za-z0-9]{10,}",  # Notion
    r"fw-[A-Za-z0-9]{30,}",  # Fireworks
    r"fw_[A-Za-z0-9]{30,}",  # Fireworks
    r"fpk_[A-Za-z0-9]{30,}",  # Fireworks project key
    r"glpat-[A-Za-z0-9_\-]{10,}",  # GitLab personal access token
    r"gloas-[A-Za-z0-9_\-]{10,}",  # GitLab OAuth application secret
    r"gldt-[A-Za-z0-9_\-]{10,}",  # GitLab deploy token
    r"glrt-[A-Za-z0-9_.\-]{10,}",  # GitLab runner token
    r"glrtr-[A-Za-z0-9_.\-]{10,}",  # GitLab runner registration token
    r"glcbt-[A-Za-z0-9_\-]{10,}",  # GitLab CI/CD job token
    r"glptt-[A-Za-z0-9_\-]{10,}",  # GitLab pipeline trigger token
    r"glft-[A-Za-z0-9_\-]{10,}",  # GitLab feed token
    r"glimt-[A-Za-z0-9_\-]{10,}",  # GitLab incoming mail token
    r"glagent-[A-Za-z0-9_\-]{10,}",  # GitLab agent token
    r"glsoat-[A-Za-z0-9_\-]{10,}",  # GitLab service-account token
    r"glffct-[A-Za-z0-9_\-]{10,}",  # GitLab feature-flags client token
    r"glwt-[A-Za-z0-9_\-]{10,}",  # GitLab workspace token
    r"GR1348941[A-Za-z0-9_\-]{10,}",  # GitLab legacy runner registration token
    r"glsa_[A-Za-z0-9]{10,}(?:_[A-Fa-f0-9]{8})?",  # Grafana service-account token
    r"glc_eyJ[A-Za-z0-9+/]{29,}={0,3}",  # Grafana Cloud token
    r"pk-lf-[A-Za-z0-9\-]{8,}",  # Langfuse public key
]


def _literal_prefix(pattern: str) -> str:
    for i, ch in enumerate(pattern):
        if ch in "[(\\.?*+|{^$":
            return pattern[:i]
    return pattern


_PREFIX_LITERALS = tuple(_literal_prefix(p) for p in _PREFIX_PATTERNS)


def _last_char_class(pattern: str):
    last = None
    i = 0
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] == "[":
            j = i + 1
            if pattern[j : j + 1] == "^":
                j += 1
            if pattern[j : j + 1] == "]":
                j += 1
            while j < len(pattern) and pattern[j] != "]":
                j += 2 if pattern[j] == "\\" else 1
            last = pattern[i : j + 1]
            i = j + 1
            continue
        i += 1
    return last


def _trailing_guard(pattern: str) -> str:
    """Reject a following alphanumeric, and ``_``/``-`` only when the body
    class admits them (Hermes #142852)."""
    body_class = _last_char_class(pattern)
    seps = "".join(c for c in "_-" if re.fullmatch(body_class, c)) if body_class else None
    return r"(?![A-Za-z0-9_-])" if seps is None else f"(?![A-Za-z0-9{seps}])"


def _compile_prefix_matcher(patterns: List[str]) -> "re.Pattern[str]":
    # Branches grouped by their literal first character; a key glued to an
    # identifier by ``-``/``_`` is admitted here and judged by _is_glued.
    by_first: dict = {}
    for pattern in patterns:
        by_first.setdefault(pattern[0], []).append(
            f"(?:{pattern[1:]}){_trailing_guard(pattern)}"
        )
    body = "|".join(
        f"{re.escape(c)}(?:{'|'.join(rest)})" for c, rest in by_first.items()
    )
    return re.compile(r"(?<![A-Za-z0-9])(" + body + r")")


_PREFIX_RE = _compile_prefix_matcher(_PREFIX_PATTERNS)
_LONG_ALNUM_RUN_RE = re.compile(r"[A-Za-z0-9]{16,}")


def _is_opaque_prefixed_token(token: str) -> bool:
    """A real key body has a 16+ character run mixing case or digits;
    ``sk-prod-deployment-01`` and ``fc-feature-flags-v2`` do not."""
    for m in _LONG_ALNUM_RUN_RE.finditer(token):
        run = m.group(0)
        if (run.isalpha() and (run.islower() or run.isupper())) or run.isdigit():
            continue
        return True
    return False


def _is_glued(m: "re.Match[str]") -> bool:
    """A match glued to an identifier (``scikit-learn``, ``backup-sk-learn``)
    whose body is not opaque is a word, not a key."""
    token = m.group(1)
    return (
        m.start() > 0
        and m.string[m.start() - 1] in "-_"
        and not token.startswith(("GOCSPX-", "ya29.", "1//0"))
        and not _is_opaque_prefixed_token(token)
    )


def _prefix_label(token: str) -> str:
    return next((p for p in _PREFIX_LITERALS if token.startswith(p)), "")


def _mask_prefixed(token: str) -> str:
    label = _prefix_label(token)
    return f"[REDACTED:{label}]" if label else MASK


def _redact_prefixed_keys(text: str) -> str:
    if not any(p in text for p in _PREFIX_LITERALS):
        return text
    return _PREFIX_RE.sub(
        lambda m: m.group(0) if _is_glued(m) else _mask_prefixed(m.group(1)), text
    )


# ── Zhipu and Discord (shape plus validation) ───────────────────────────────

_ZHIPU_API_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])([0-9a-f]{32}\.[A-Za-z0-9]{16,})(?![A-Za-z0-9_.-])"
)
# Gates that start with a literal character, so the regex engine can skip
# ahead to it: the full patterns start with a class or a lookbehind and are
# tried at every position.
_ZHIPU_GATE = re.compile(r"\.[A-Za-z0-9]{16}")

_DISCORD_TAIL = r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9_-])"
_DISCORD_TOKEN_RE = re.compile(
    rf"(?=(mfa\.[A-Za-z0-9_-]{{84}}){_DISCORD_TAIL})"
    rf"|(?=([MNO][A-Za-z0-9_-]{{22,27}}\.[A-Za-z0-9_-]{{6,7}}\.[A-Za-z0-9_-]{{27,}}){_DISCORD_TAIL})"
)
_DISCORD_GATE = re.compile(r"\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27}")
_ESCAPE_TAIL_RE = re.compile(
    r"(?:\\[nrtbf]|\\x[0-9A-Fa-f]{2}|%[0-9A-Fa-f]{2}|\\u[0-9A-Fa-f]{4}|(?:\x1b|\\x1b|\\033|\\e)\[[0-9;]*m)\Z"
)
_TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
)


def _mfa_left_ok(text: str, start: int) -> bool:
    if start == 0 or text[start - 1] not in _TOKEN_CHARS:
        return True
    return bool(_ESCAPE_TAIL_RE.search(text, max(0, start - 12), start))


def _is_discord_token(candidate: str) -> bool:
    """The first segment of a real token decodes to a Discord user id."""
    head = candidate.split(".", 1)[0]
    try:
        decoded = base64.urlsafe_b64decode(head + "=" * (-len(head) % 4))
    except ValueError:
        return False
    return decoded.isdigit() and 17 <= len(decoded) <= 20


def _redact_discord_tokens(text: str) -> str:
    parts, pos = [], 0
    for m in _DISCORD_TOKEN_RE.finditer(text):
        mfa = m.group(1) is not None
        token = m.group(1) if mfa else m.group(2)
        start = m.start(1) if mfa else m.start(2)
        if start < pos or not (
            _mfa_left_ok(text, start) if mfa else _is_discord_token(token)
        ):
            continue
        parts += (text[pos:start], MASK)
        pos = start + len(token)
    return "".join(parts) + text[pos:] if parts else text


# ── assignments: which NAME=value pairs hold a credential ───────────────────

_KEY_KEYWORD_RE = re.compile(
    r"(?:api|auth|access|refresh|session|secret)[ _.\\-]?(?:key|token)"
    r"|token|secret|passwd|password|pass|pw|credential|auth|key",
    re.IGNORECASE,
)
_STRONG_KEY_KEYWORD_RE = re.compile(
    r"(?:api|auth|access|refresh|session|id|bearer)[ _.\\-]?(?:key|token)"
    r"|key[ _.\\-]?material|secret|passwd|password|pass|pw|credential|auth|bearer",
    re.IGNORECASE,
)
_PASSWORD_KEY_RE = re.compile(r"passwd|password|pass|pw", re.IGNORECASE)
_PASSWORD_WORD_RE = re.compile(r"passwd|password", re.IGNORECASE)
_GLUED_CREDENTIAL_ENV_RE = re.compile(r"PGPASSWORD|MYSQL_PWD|SSHPASS", re.IGNORECASE)
_SHELL_VAR_REF = r"\$(?:\{[A-Za-z_]\w*[^}]*\}|[A-Za-z_]\w*)"
_PATH_OR_VAR_VALUE_RE = re.compile(
    rf"^(?:{_SHELL_VAR_REF}|\$\(|~|/)(?:[\w./:-]|{_SHELL_VAR_REF})*$"
)
_OPAQUE_PATH_SEGMENT_RE = re.compile(
    r"(?=[^.]*[a-z])(?=[^.]*[A-Z])(?=[^.]*[0-9])[^.]{16,}"
)
_ENV_LOOKUP_VALUE_RE = re.compile(r"^(?:os\.(?:getenv|environ)|process\.env|\$ENV\{)")
_CONFIG_LITERAL_VALUES = frozenset(
    {"true", "false", "yes", "no", "on", "off", "null", "none"}
)
_CONFIG_PLACEHOLDER_VALUE_RE = re.compile(
    r"<[a-z]+(?:[ _-][a-z]+)+>|<(?:key|token|secret|password|value)>|true|false|yes|no|null|none|default",
    re.IGNORECASE,
)
_KEY_SECRET_QUALIFIERS = frozenset(
    {"secret", "private", "signing", "encryption", "encrypt", "master", "hmac", "symmetric", "access"}
)


def _is_word_start(s: str, i: int) -> bool:
    if i == 0:
        return True
    prev, cur = s[i - 1], s[i]
    if not prev.isalpha() or (cur.isupper() and prev.islower()):
        return True
    return cur.isupper() and prev.isupper() and i + 1 < len(s) and s[i + 1].islower()


def _is_word_end(s: str, j: int, *, allow_plural: bool = True) -> bool:
    if j >= len(s):
        return True
    cur = s[j]
    if not cur.isalpha() or (cur.isupper() and s[j - 1].islower()):
        return True
    return allow_plural and cur in "sS" and _is_word_end(s, j + 1, allow_plural=False)


def _has_word_bounded_keyword(key: str, keyword_re: "re.Pattern[str]") -> bool:
    return any(
        _is_word_start(key, m.start()) and _is_word_end(key, m.end())
        for m in keyword_re.finditer(key)
    )


def _has_password_keyword(key: str) -> bool:
    return any(_is_word_end(key, m.end()) for m in _PASSWORD_WORD_RE.finditer(key))


def _is_glued_credential_env(key: str) -> bool:
    return _GLUED_CREDENTIAL_ENV_RE.fullmatch(key.strip("\"'")) is not None


def _key_has_secret_keyword(key: str) -> bool:
    """``API_KEY``/``DB_PW`` count; ``KEYBOARD``/``secretary`` do not."""
    return (
        _has_word_bounded_keyword(key, _KEY_KEYWORD_RE)
        or _has_password_keyword(key)
        or _is_glued_credential_env(key)
    )


def _key_name_words(key: str) -> List[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w]


def _is_qualified_key_name(key: str) -> bool:
    words = _key_name_words(key)
    if len(words) < 2 or words[-1] != "key":
        return False
    return any(w in _KEY_SECRET_QUALIFIERS for w in words[:-1])


def _looks_like_opaque_credential(value: str) -> bool:
    if len(value) >= 16 and re.fullmatch(r"[A-Fa-f0-9]+", value):
        return True
    if len(value) >= 20 and re.fullmatch(r"[A-Za-z0-9_./+=-]+", value):
        return True
    if len(value) < 12:
        return False
    return sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]")) >= 2


def _should_redact_assignment(key: str, value: str) -> bool:
    """Hermes' gate for the assignment passes: a credential-like key, a value
    that is not an env lookup, a literal, a path or a variable reference, and
    either a credential-specific key or an opaque value."""
    if not value or _ENV_LOOKUP_VALUE_RE.match(value) or _is_marker(value):
        return False
    if value.lower() in _CONFIG_LITERAL_VALUES:
        return False
    if not _key_has_secret_keyword(key):
        return False
    password_key = _has_word_bounded_keyword(key, _PASSWORD_KEY_RE) or _has_password_keyword(key)
    if _PATH_OR_VAR_VALUE_RE.match(value) and not password_key:
        if value[0] == "$" or not any(
            _OPAQUE_PATH_SEGMENT_RE.fullmatch(seg) for seg in value.split("/")
        ):
            return False
    return (
        password_key
        or _has_word_bounded_keyword(key, _STRONG_KEY_KEYWORD_RE)
        or _is_glued_credential_env(key)
        or (_is_qualified_key_name(key) and not _CONFIG_PLACEHOLDER_VALUE_RE.fullmatch(value))
        or _looks_like_opaque_credential(value)
    )


# A whole line of ``NAME=value`` (optionally ``export``-prefixed, no space
# around ``=``) is the ``.env`` / ``env`` shape; source assignments
# (``MAX_TOKENS = 100``, indented code) do not match.
_ENV_DUMP_LINE_RE = re.compile(r"^((?:export[ \t]+)?)([A-Z][A-Z0-9_]*)=(\S.*)$", re.MULTILINE)


def _mask_env_dump_line(m: "re.Match[str]") -> str:
    prefix, key, value = m.groups()
    value = value.rstrip("\r")
    quote = value[0] if len(value) > 1 and value[0] in "'\"" and value[-1] == value[0] else ""
    inner = value[1:-1] if quote else value
    if inner.startswith(("$(", "`")):
        return m.group(0)  # a command substitution names where the value comes from
    if _should_redact_assignment(key, inner):
        tail = m.group(3)[len(value):]  # a CR that ended the line
        return f"{prefix}{key}={quote}{MASK}{quote}{tail}"
    return m.group(0)


def _redact_env_dump_lines(text: str) -> str:
    if "=" not in text:
        return text
    return _ENV_DUMP_LINE_RE.sub(_mask_env_dump_line, text)


# ── command-line flags and connection-string keys ───────────────────────────

_QUOTED_FLAG_VALUE = (
    r"\"(?:\\[\s\S]|[^\"\\]){1,512}\"|'(?:'\\''|[^']){1,512}'"
    r"|[\"'][^\n]*|\S+"
)
_CLI_SECRET_FLAG_RE = re.compile(
    r"(?P<flag>(?<![\w-])--?(?:password|passwd|passphrase|pass|token|api[-_]?key|apikey"
    r"|client[-_]?secret|access[-_]?key|account[-_]?key|auth[-_]?token|session[-_]?token|secret|bearer"
    r"|credential)s?)"
    r"(?P<sep>\s*=|\s+)"
    rf"(?P<value>{_QUOTED_FLAG_VALUE})",
    re.IGNORECASE,
)
_CLI_LOGIN_P_RE = re.compile(
    r"(?P<flag>\b(?:docker|podman|nerdctl)\s+login\b[^\n;|&]*?\s-p\s*)"
    rf"(?P<value>{_QUOTED_FLAG_VALUE})"
)
_CONNSTR_SECRET_KEY_RE = re.compile(
    r"(?P<flag>(?<![^;,?&'\"\s])(?:AccountKey|SharedAccessKey|(?P<sas>SharedAccessSignature))"
    r"(?:=|[ \t]*=[ \t]*(?=[A-Za-z+/]*[0-9])(?=[A-Za-z0-9+/]{16,}={0,2}(?![\w.(]))))"
    r"(?P<value>(?(sas)(?:(?!sig=)[^;\s'\"&),`|]+&)*(?:sig=)?[^;\s'\"&),`|]*|[^;\s'\"&]+))",
    re.IGNORECASE,
)
# Run on the lower-cased text. ``(?<![\w-]-)`` after the first ``-`` is the
# full pattern's ``(?<![\w-])`` before it, moved so the gate starts with a
# literal.
_CLI_SECRET_FLAG_GATE = re.compile(
    r"-(?<![\w-]-)-?(?:pass|token|api|client|access|account|auth|session|secret|bearer|credential)"
)
# A space-separated flag followed by a placeholder or a word (``--token
# TOKEN``, ``[--password PASSWORD]``, ``--token to pass``) is --help text.
_FLAG_PLACEHOLDER_RE = re.compile(
    r"(?:[A-Z][A-Z_]*|[a-z]{1,8}|[a-z]{1,8}_[a-z]{1,8}|[a-z]{1,8}[A-Z][a-z]{1,8})[\]).,:;]*"
    r"|[-\[(<].*|[a-z][\w-]*=.*"
    r"|\S*(?:xxx|XXX|\.\.\.)"
)


def _is_flag_placeholder(value: str) -> bool:
    return value[0] not in "'\"" and _FLAG_PLACEHOLDER_RE.fullmatch(value) is not None


def _is_flag_path_reference(flag: str, value: str) -> bool:
    if _PASSWORD_KEY_RE.search(flag) or not value.startswith(("/", "~", "./", "../")):
        return False
    return not any(_OPAQUE_PATH_SEGMENT_RE.fullmatch(seg) for seg in value.split("/"))


def _mask_flag_value(match: "re.Match[str]") -> str:
    value = match.group("value")
    stripped = value.strip("'\"")
    if not stripped or _is_marker(stripped.strip()):
        return match.group(0)
    if stripped[0] in "$<{%":
        return match.group(0)  # ``--password=$DB_PASS`` names a variable
    if stripped.isdigit():
        return match.group(0)  # ``--token 60`` is a number, not a credential
    if match.re is _CLI_SECRET_FLAG_RE:
        if "=" not in match.group("sep") and _is_flag_placeholder(value):
            return match.group(0)
        if _is_flag_path_reference(match.group("flag"), stripped):
            return match.group(0)
    quote = value[0] if value[0] in "'\"" else ""
    closing = quote if quote and value.endswith(quote) and len(value) > 1 else ""
    start = match.start("value") - match.start(0)
    end = match.end("value") - match.start(0)
    whole = match.group(0)
    return whole[:start] + f"{quote}{MASK}{closing}" + whole[end:]


def _redact_cli_secrets(text: str, lower: str) -> str:
    if "=" in text or " " in text:
        if _CLI_SECRET_FLAG_GATE.search(lower):
            text = _CLI_SECRET_FLAG_RE.sub(_mask_flag_value, text)
        if "login" in lower and "-p" in text:
            text = _CLI_LOGIN_P_RE.sub(_mask_flag_value, text)
    if "accountkey" in lower or "sharedaccess" in lower:
        text = _CONNSTR_SECRET_KEY_RE.sub(_mask_flag_value, text)
    return text


# ── HTTP headers ────────────────────────────────────────────────────────────

_AUTH_SCHEME_WORD = (
    r"(?:bearer|basic|bot|token|digest|negotiate|ntlm|oauth)(?=[`)\],.;:!?]*(?:[\s\"']|$))"
)
_AUTH_HEADER_RE = re.compile(
    rf"((?:Proxy-)?Authorization:\s*)([A-Za-z][\w.+-]*\s+)?(?!{_AUTH_SCHEME_WORD})([^\s\"']+)",
    re.IGNORECASE,
)

_SECRET_HEADER_NAMES = (
    r"(?:x-api-key|x-goog-api-key|api-key|apikey|x-api-token|x-auth-token|x-access-token)"
)
_SECRET_HEADER_LINE_RE = re.compile(
    rf"(^[ \t]*(?:[<>][ \t]+)?{_SECRET_HEADER_NAMES}[ \t]*:[ \t]*)([^\r\n]+)",
    re.IGNORECASE | re.MULTILINE,
)
_SECRET_HEADER_INLINE_RE = re.compile(
    rf"({_SECRET_HEADER_NAMES}[ \t]*:[ \t]*)"
    rf"((?:[<(&;|]+(?![\s;&|<>()]|$))?(?:[^\s\"';&|<>()`\\]|[;&|](?![\s;&|<>()]|$))+)",
    re.IGNORECASE,
)
_CURL_HEADER_FLAG = r"(?:^|[ \t])(?:-H(?:(?:[ \t]|\\\r?\n)*|=)|--header(?:(?:[ \t]|\\\r?\n)+|=))"
_SECRET_HEADER_DOUBLE_QUOTED_RE = re.compile(
    rf'({_CURL_HEADER_FLAG}")({_SECRET_HEADER_NAMES}:[ \t]*)'
    r'((?:\\\r?\n|\\.|[^"\\\r\n])+)(")',
    re.IGNORECASE,
)
_SECRET_HEADER_SINGLE_QUOTED_RE = re.compile(
    rf"({_CURL_HEADER_FLAG}')({_SECRET_HEADER_NAMES}:[ \t]*)([^'\r\n]+)(')",
    re.IGNORECASE,
)
_SECRET_HEADER_UNQUOTED_CURL_RE = re.compile(
    rf"({_CURL_HEADER_FLAG}{_SECRET_HEADER_NAMES}:)"
    r"((?:\\[^\r\n]|[^ \t\r\n;&|<>()$`\\])+)",
    re.IGNORECASE | re.MULTILINE,
)
_COOKIE_NAME = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_COOKIE_HEADER_LINE_RE = re.compile(
    rf"(^[ \t]*(?:[<>][ \t]+)?(?:Set-)?Cookie:[ \t]*)({_COOKIE_NAME}=[^\r\n]*)",
    re.IGNORECASE | re.MULTILINE,
)
_COOKIE_HEADER_DOUBLE_QUOTED_RE = re.compile(
    rf'({_CURL_HEADER_FLAG}")((?:Set-)?Cookie:[ \t]*)'
    rf'({_COOKIE_NAME}=(?:\\\r?\n|\\.|[^"\\\r\n])*)(")',
    re.IGNORECASE,
)
_COOKIE_HEADER_SINGLE_QUOTED_RE = re.compile(
    rf"({_CURL_HEADER_FLAG}')((?:Set-)?Cookie:[ \t]*)({_COOKIE_NAME}=[^'\r\n]*)(')",
    re.IGNORECASE,
)
_COOKIE_HEADER_UNQUOTED_CURL_RE = re.compile(
    rf"({_CURL_HEADER_FLAG}(?:Set-)?Cookie:[ \t]*)"
    rf"({_COOKIE_NAME}=(?:\\[^\r\n]|[^ \t\r\n;&|<>()$`\\])*)",
    re.IGNORECASE | re.MULTILINE,
)
_HEADER_GATES = ("api-key", "apikey", "-token", "cookie")
_MASKED_VALUE_RE = re.compile(r"\[REDACTED[^\]]*\](?:\s|$)")
_CURL_FLAG_BEFORE_RE = re.compile(r"(?:-H|--header)(?:[ \t]*|=)[\"']?$", re.IGNORECASE)
_CURL_CONTINUED_RE = re.compile(r"(?:^|[ \t])(?:-H|--header)(?:[ \t]+|=).*\\[ \t]*$", re.IGNORECASE)


def _redact_inline_header(m: "re.Match[str]") -> str:
    """Leave an empty curl header's following argument alone."""
    before = m.string[max(0, m.start() - 32) : m.start()]
    if _CURL_FLAG_BEFORE_RE.search(before) or _is_marker(m.group(2)):
        return m.group(0)
    return m.group(1) + MASK


def _redact_header_line(m: "re.Match[str]") -> str:
    """Mask a header line unless it continues a ``curl -H`` argument or was
    already masked."""
    line_start = m.string.rfind("\n", 0, m.start()) + 1
    if line_start:
        previous_start = m.string.rfind("\n", 0, line_start - 1) + 1
        previous = m.string[previous_start : line_start - 1].rstrip("\r")
        if previous.rstrip().endswith("\\") and _CURL_CONTINUED_RE.search(previous):
            return m.group(0)
    if _MASKED_VALUE_RE.match(m.group(2)):
        return m.group(0)
    return m.group(1) + MASK


def _redact_headers(text: str, lower: str) -> str:
    if "authorization" in lower:
        text = _AUTH_HEADER_RE.sub(
            lambda m: m.group(1) + (m.group(2) or "") + MASK, text
        )
    if not any(gate in lower for gate in _HEADER_GATES):
        return text
    quoted = lambda m: m.group(1) + m.group(2) + MASK + m.group(4)  # noqa: E731
    text = _SECRET_HEADER_LINE_RE.sub(_redact_header_line, text)
    text = _SECRET_HEADER_DOUBLE_QUOTED_RE.sub(quoted, text)
    text = _SECRET_HEADER_SINGLE_QUOTED_RE.sub(quoted, text)
    text = _SECRET_HEADER_UNQUOTED_CURL_RE.sub(lambda m: m.group(1) + MASK, text)
    text = _SECRET_HEADER_INLINE_RE.sub(_redact_inline_header, text)
    text = _COOKIE_HEADER_LINE_RE.sub(_redact_header_line, text)
    text = _COOKIE_HEADER_DOUBLE_QUOTED_RE.sub(quoted, text)
    text = _COOKIE_HEADER_SINGLE_QUOTED_RE.sub(quoted, text)
    text = _COOKIE_HEADER_UNQUOTED_CURL_RE.sub(lambda m: m.group(1) + MASK, text)
    return text


# ── Telegram bot tokens ─────────────────────────────────────────────────────

_TELEGRAM_RE = re.compile(
    r"(?P<boundary>\\[nrtbfv]|\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|"
    r"\\U[0-9a-fA-F]{8}|%[0-9a-fA-F]{2}|(?P<csi>(?:\x1b|\\x1b|\\u001[bB]|\\033)\[[0-?]*[ -/]*[@-~])|(?<![A-Za-z_\d]))"
    r"(?P<bot>bot)?(?P<id>\d{8,}):(?P<body>[-A-Za-z0-9_]{30,})"
)


_TELEGRAM_GATE = re.compile(r":[-A-Za-z0-9_]{30}")


def _redact_telegram_token(match: "re.Match[str]") -> str:
    boundary = match.group("boundary")
    # An encoded identifier character is still an identifier, not a separator.
    if len(boundary) > 2 and not match.group("csi"):
        value = int(boundary[1:] if boundary[0] == "%" else boundary[2:], 16)
        if value > 0x10FFFF:
            return match.group(0)
        char = chr(value)
        if char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_" or char.isdecimal():
            return match.group(0)
    return f"{boundary}{match.group('bot') or ''}{match.group('id')}:{MASK}"


# ── URLs ────────────────────────────────────────────────────────────────────

# ``scheme://user:PASSWORD@host``. The password is a run of single characters
# (never a nested ``(x+)+``), so a URL with no ``@`` fails in linear time.
_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|rediss?|amqps?)://[^:\s]*:)((?:[^@\s:]|:(?!//))+)(@)",
    re.IGNORECASE,
)
_DSN_PW_PLACEHOLDER_RE = re.compile(
    r"<(?:[a-z][a-z_ -]*|[A-Z][A-Z_ -]*)>|\$\{?[A-Z_][A-Z0-9_]*\}?|%[A-Z_][A-Z0-9_]*%"
)
_USERINFO_PLACEHOLDER_WORDS = frozenset({"password", "passwd", "pass", "pw", "pwd", "secret", "token"})
# Bare-token userinfo (``https://TOKEN@github.com``): round-trip tokens live in
# the query string, never in userinfo, so masking it breaks no workflow.
_URL_BARE_TOKEN_RE = re.compile(
    r"((?:https?|wss?|git|ssh|ftp|ftps|sftp)://)([^\s:@/\"]{8,})(@[^\s]+)",
    re.IGNORECASE,
)
_URL_USERINFO_PAIR_RE = re.compile(r"(//)([^/\s?#@\"]+)@")
# Literal-led necessary conditions for the two patterns above (an ``@`` alone
# is in every e-mail address).
_URL_BARE_TOKEN_GATE = re.compile(r"://[^\s:@/\"]{8,}@")
_URL_USERINFO_GATE = re.compile(r"//[^/\s?#@\"]*:[^/\s?#@\"]*@")
# Incoming-webhook URLs: the URL itself is the credential.
_WEBHOOK_HOST_END = r"\.?(?::\d+)?/"
_WEBHOOK_URL_RE = re.compile(
    r"(https?://hooks\.slack(?:-gov)?\.com" + _WEBHOOK_HOST_END
    + r"workflows/[A-Z0-9]+/[A-Z0-9]+/\d+/)([A-Za-z0-9]{8,})"
    r"|(https?://hooks\.slack(?:-gov)?\.com" + _WEBHOOK_HOST_END
    + r"(?:services|workflows|triggers)/[A-Z0-9]+/[A-Z0-9]+/)(?!\d+/)([A-Za-z0-9]{8,})"
    r"|(https?://(?:canary\.|ptb\.|www\.)?discord(?:app)?\.com" + _WEBHOOK_HOST_END
    + r"api/(?:v\d+/)?webhooks/\d+/)([\w-]{8,})"
    r"|(https?://[A-Za-z0-9.-]*\.?(?:webhook\.office\.com" + _WEBHOOK_HOST_END
    + r"webhookb2|outlook\.office\.com" + _WEBHOOK_HOST_END + r"webhook)/)([\w@/%+=-]{8,})",
    re.IGNORECASE,
)


def _is_userinfo_placeholder(password: str) -> bool:
    return (
        (password.startswith("{") and password.endswith("}"))
        or _DSN_PW_PLACEHOLDER_RE.fullmatch(password) is not None
        or password.casefold() in _USERINFO_PLACEHOLDER_WORDS
        or _is_marker(password)
    )


def _redact_db(m: "re.Match[str]") -> str:
    password = m.group(2)
    # ``f"postgresql://{user}:{pw}@{host}"`` is a template, not a password.
    if password.startswith("{") and password.endswith("}"):
        return m.group(0)
    if m.group(1).endswith("://:") and _DSN_PW_PLACEHOLDER_RE.fullmatch(password):
        return m.group(0)
    if _is_marker(password):
        return m.group(0)
    return f"{m.group(1)}{MASK}{m.group(3)}"


def _redact_webhook(m: "re.Match[str]") -> str:
    groups = m.groups()
    for prefix, _secret in zip(groups[::2], groups[1::2]):
        if prefix:
            return f"{prefix}{MASK}"
    return m.group(0)


def _redact_userinfo(m: "re.Match[str]") -> str:
    user, sep, password = m.group(2).partition(":")
    if not sep or not password or _is_userinfo_placeholder(password):
        return m.group(0)
    return f"{m.group(1)}{user}:{MASK}@"


_DB_SCHEMES = ("postgres", "mysql", "mongodb", "redis", "amqp")
_WEBHOOK_HOSTS = ("hooks.slack", "discord", "webhook")


def _redact_url_credentials(text: str, lower: str) -> str:
    if any(scheme in lower for scheme in _DB_SCHEMES):
        text = _DB_CONNSTR_RE.sub(_redact_db, text)
    if any(host in lower for host in _WEBHOOK_HOSTS):
        text = _WEBHOOK_URL_RE.sub(_redact_webhook, text)
    if _URL_BARE_TOKEN_GATE.search(text):
        text = _URL_BARE_TOKEN_RE.sub(
            lambda m: m.group(0) if _is_marker(m.group(2)) else f"{m.group(1)}{MASK}{m.group(3)}",
            text,
        )
    if _URL_USERINFO_GATE.search(text):
        text = _URL_USERINFO_PAIR_RE.sub(_redact_userinfo, text)
    return text


# ── JWTs ────────────────────────────────────────────────────────────────────

_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_=-]{4,}){0,2}")


# ── entry point ─────────────────────────────────────────────────────────────


def redact_secrets(text: str) -> str:
    """``text`` with secret-shaped values replaced by ``[REDACTED]``.

    Safe on any string; idempotent (a second pass changes nothing). Ordinary
    output, with none of the gating substrings, is returned unchanged after
    a handful of substring checks.
    """
    if not text or not isinstance(text, str):
        return text
    # Key blocks first: a body line holding a token prefix would otherwise be
    # masked alone and end the run there, leaving the rest of the key visible.
    text = _redact_private_key_blocks(text)
    text = _redact_prefixed_keys(text)
    # Gates read the lower-cased text once. A pass only ever removes text,
    # so a gate that saw a substring before it can only run a pass for
    # nothing, never skip one that was needed.
    lower = text.lower()
    if "." in text:
        if _ZHIPU_GATE.search(text):
            text = _ZHIPU_API_KEY_RE.sub(lambda m: MASK, text)
        if "mfa." in text or _DISCORD_GATE.search(text):
            text = _redact_discord_tokens(text)
    text = _redact_cli_secrets(text, lower)
    text = _redact_headers(text, lower)
    if _TELEGRAM_GATE.search(text):
        text = _TELEGRAM_RE.sub(_redact_telegram_token, text)
    if "://" in text:
        text = _redact_url_credentials(text, lower)
    if "eyJ" in text:
        text = _JWT_RE.sub(lambda m: MASK, text)
    text = _redact_env_dump_lines(text)
    return text


__all__: List[str] = ["redact_secrets", "MASK", "PRIVATE_KEY_MASK"]
