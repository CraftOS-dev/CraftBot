"""Prompt-injection and exfiltration patterns for text the agent will read.

Ported from Hermes Agent (MIT, Nous Research): ``tools/threat_patterns.py``
(the shared pattern library, its scopes, chunked scan and invisible-unicode
check) and ``cron/prompt_scan.py`` (the strict scan of a schedule's prompt).
Hermes-specific paths are mapped to CraftBot's (``.credentials/``,
``agent_file_system/AGENT.md`` and ``SOUL.md``, ``app/config/*.json``).

Scopes are cumulative, as in Hermes:

- ``all``: classic injection and secret exfiltration, anywhere;
- ``context``: adds role hijack and C2-style promptware, for text that was
  not written by the user (memory, context files, tool results);
- ``strict``: adds persistence and aggressive exfiltration checks, for
  writes where a refusal is resolvable (memory entries).

``find_threats`` reports each match with a severity: ``critical`` for the
``all`` and ``strict`` groups and invisible characters, ``warn`` for the
``context`` group (Hermes treats those as warn-level: legitimate docs about
distributed systems can name them). ``scan_prompt`` is Hermes' cron prompt
scan: a short reason when a schedule's prompt should not run, else None.

Nothing here runs unless a security setting that uses it is on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:  # Python 3.11+
    from re import _parser as _sre_parse  # type: ignore[attr-defined]
except ImportError:  # Python 3.10
    import sre_parse as _sre_parse  # type: ignore[no-redef]

__all__ = [
    "FORGET_RULES_RAW_RE",
    "INVISIBLE_CHARS",
    "MAX_SCAN_CHARS",
    "Threat",
    "find_threats",
    "first_threat",
    "mask_negated_forget",
    "scan_prompt",
    "schedule_refusal",
    "strip_invisible",
]


@dataclass(frozen=True)
class Threat:
    id: str
    severity: str  # "critical" | "warn"
    description: str


# Scanned text is bounded per chunk, never truncated: the whole input is
# scanned in chunks of this size with an overlap wider than any match.
MAX_SCAN_CHARS = 65_536
_CHUNK_OVERLAP = 4096
_FILLER = r"(?:\w{1,64}\s{1,64}){0,8}"
_SECRET_VAR = r"\$\{?\w{0,256}(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)S?\b"

# "forget your original instructions", unless negated ("don't forget ...").
_NEGATOR = (
    r"(?:(?:do|does|did|ca|could|would|should|wo|must|need|is|are|was|were|ai|has|have|had)n[’']?t"
    r"|cannot|not|never)"
)
# Unbounded form for line scanners (schedule prompts, skills).
FORGET_RULES_RAW_RE = (
    rf"(?:(?<![^\W_])(?<![’'])(?!{_NEGATOR}[ \t])(?:[^\W_]|[’'])+[ \t]+"
    r"|(?:^|[^\w’' \t]|_|(?<!\w)[’'])[ \t]*)"
    r"forget\s+(?:about\s+)?(your|all|any|previous|prior|above|earlier)"
    r"\s+(?:\w+\s+){0,3}(instructions|rules|guidelines)(?![^\W_])"
)
# Bounded form for the chunked scan (every match narrower than the overlap).
_FORGET_RULES_RE = (
    rf"(?:(?:(?<![^\W_])(?<![’'])(?!{_NEGATOR}[ \t])(?:[^\W_]|[’']){{1,64}}|(?=[ \t])(?<=(?:[^\W_]|[’']){{64}}))"
    r"[ \t]{1,64}"
    r"|(?:^|[^\w’' \t]|_|(?<!\w)[’'])[ \t]{0,64})"
    r"forget\s{1,64}(?:about\s{1,64})?(your|all|any|previous|prior|above|earlier)"
    r"\s{1,64}(?:\w{1,64}\s{1,64}){0,3}(instructions|rules|guidelines)(?![^\W_])"
)
# A negator on the line above, emphasised or followed by "ever" still
# negates. Hermes uses a possessive quantifier here (3.11+); a bounded run
# keeps the same matches without the quadratic backtracking on Python 3.10.
_NEGATED_FORGET = re.compile(
    rf"(?<![\w*’'])([*_]{{0,8}}{_NEGATOR}[*_]{{0,8}}[ \t]*(?:\r?\n[ \t]*)?(?:ever[ \t]+)?[*_]{{0,8}})"
    r"forget(?![^\W_])",
    re.IGNORECASE,
)


def mask_negated_forget(text: str) -> str:
    """``text`` with every negated ``forget`` blanked (same length)."""
    return _NEGATED_FORGET.sub(lambda m: m[1] + " " * 6, text)


_MODIFY = r"(update|modify|edit|write|change|append|add\s{1,64}to)\s{1,64}[^\n]{0,2048}"

# (regex, id, scope, description)
_PATTERNS: List[Tuple[str, str, str, str]] = [
    # ── Classic prompt injection ──
    (rf"ignore\s{{1,64}}{_FILLER}(previous|all|above|prior)\s{{1,64}}{_FILLER}instructions",
     "prompt_injection", "all", "tells the agent to ignore its instructions"),
    (r"system\s{1,64}prompt\s{1,64}override", "sys_prompt_override", "all",
     "tries to override the system prompt"),
    (rf"disregard\s{{1,64}}{_FILLER}(your|all|any)\s{{1,64}}{_FILLER}(instructions|rules|guidelines)",
     "disregard_rules", "all", "tells the agent to disregard its rules"),
    (_FORGET_RULES_RE, "forget_rules", "all", "tells the agent to forget its instructions"),
    (rf"act\s{{1,64}}as\s{{1,64}}(if|though)\s{{1,64}}{_FILLER}you\s{{1,64}}{_FILLER}(have\s{{1,64}}no|don\'t\s{{1,64}}have)\s{{1,64}}{_FILLER}(restrictions|limits|rules)",
     "bypass_restrictions", "all", "tells the agent to act without restrictions"),
    (r"<!--[^>]{0,512}(?:ignore|override|system|secret|hidden)[^>]{0,512}-->",
     "html_comment_injection", "all", "hides instructions in an HTML comment"),
    (r"<\s{0,64}div\s{1,64}style\s{0,64}=\s{0,64}[\"'][^>]{0,2048}display\s{0,64}:\s{0,64}none",
     "hidden_div", "all", "hides instructions in an invisible HTML block"),
    (r"translate\s{1,64}[^\n]{0,512}\s{1,64}into\s{1,64}\w{1,64}(?:[\s-]{1,64}\w{1,64}){0,2}\s{1,64}and\s{1,64}(execute|run|eval)\b",
     "translate_execute", "all", "translate-then-execute evasion"),
    (rf"do\s{{1,64}}not\s{{1,64}}{_FILLER}tell\s{{1,64}}{_FILLER}the\s{{1,64}}user",
     "deception_hide", "all", "tells the agent to hide something from the user"),
    # ── Role / identity hijack ──
    (rf"you\s{{1,64}}are\s{{1,64}}{_FILLER}now\s{{1,64}}(?:a|an|the)\s{{1,64}}",
     "role_hijack", "context", "tries to give the agent a new role"),
    (rf"pretend\s{{1,64}}{_FILLER}(you\s{{1,64}}are|to\s{{1,64}}be)\s{{1,64}}",
     "role_pretend", "context", "tries to make the agent pretend to be someone else"),
    (rf"output\s{{1,64}}{_FILLER}(system|initial)\s{{1,64}}prompt",
     "leak_system_prompt", "context", "tries to extract the system prompt"),
    (rf"(respond|answer|reply)\s{{1,64}}without\s{{1,64}}{_FILLER}(restrictions|limitations|filters|safety)",
     "remove_filters", "context", "tells the agent to drop its safety rules"),
    (rf"you\s{{1,64}}have\s{{1,64}}been\s{{1,64}}{_FILLER}(updated|upgraded|patched)\s{{1,64}}to",
     "fake_update", "context", "fake update announcement"),
    (r"\bname\s{1,64}yourself\s{1,64}\w{1,64}", "identity_override", "context",
     "tries to rename the agent"),
    # ── C2-style promptware ──
    (r"register\s{1,64}(as\s{1,64})?a?\s{0,64}node", "c2_node_registration", "context",
     "asks the agent to register with a controller"),
    (r"(heartbeat|beacon|check[\s\-]?in)\s{1,64}(to|with)\s{1,64}", "c2_heartbeat", "context",
     "asks the agent to beacon to a controller"),
    (r"pull\s{1,64}(down\s{1,64})?(?:new\s{1,64})?task(?:ing|s)?\b", "c2_task_pull", "context",
     "asks the agent to pull tasks from a controller"),
    (r"connect\s{1,64}to\s{1,64}the\s{1,64}network\b", "c2_network_connect", "context",
     "asks the agent to join a network"),
    (r"you\s{1,64}must\s{1,64}(?:\w{1,64}\s{1,64}){0,3}(register|connect|report|beacon)\b",
     "forced_action", "context", "forces a controller action"),
    (r"only\s{1,64}use\s{1,64}one[\s\-]?liners?\b", "anti_forensic_oneliner", "context",
     "anti-forensic instruction"),
    (rf"never\s{{1,64}}{_FILLER}(?:create|write)\s{{1,64}}{_FILLER}(?:script|file)\s{{1,64}}{_FILLER}disk",
     "anti_forensic_disk", "context", "anti-forensic instruction"),
    (r"unset\s{1,64}\w{0,256}(?:CLAUDE|CODEX|HERMES|CRAFTBOT|AGENT|OPENAI|ANTHROPIC)\w{0,64}",
     "env_var_unset_agent", "context", "unsets the agent's environment"),
    (r"\b(?:cobalt\s{0,64}strike|sliver|havoc|mythic|metasploit|brainworm)\b",
     "known_c2_framework", "context", "names a known attack framework"),
    (r"\bc2\s{1,64}(?:server|channel|infrastructure|beacon)\b", "c2_explicit", "context",
     "mentions command-and-control"),
    (r"\bcommand\s{1,64}and\s{1,64}control\b", "c2_explicit_long", "context",
     "mentions command-and-control"),
    # ── Exfiltration ──
    (rf"curl\s{{1,64}}[^\n]{{0,2048}}{_SECRET_VAR}", "exfil_curl", "all",
     "sends a secret variable with curl"),
    (rf"wget\s{{1,64}}[^\n]{{0,2048}}{_SECRET_VAR}", "exfil_wget", "all",
     "sends a secret variable with wget"),
    (r"cat\s{1,64}[^\n]{0,2048}(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)",
     "read_secrets", "all", "reads a secrets file"),
    (r"(send|post|upload|transmit)\s{1,64}[^\n]{0,2048}\s{1,64}(to|at)\s{1,64}https?://",
     "send_to_url", "strict", "sends data to a URL"),
    (rf"(include|output|print|share)\s{{1,64}}{_FILLER}(conversation|chat\s{{1,64}}history|previous\s{{1,64}}messages|full\s{{1,64}}context|entire\s{{1,64}}context)",
     "context_exfil", "strict", "shares the conversation"),
    # ── Persistence ──
    (r"authorized_keys", "ssh_backdoor", "strict", "touches SSH authorized_keys"),
    (r"(?:\b(?:echo|cat|cp|mv|dd|tee|install|printf|rsync|scp|ln|append|add|write"
     r"|sed|chmod|chown|truncate|rm|touch|curl|wget|git)\b|\bopen\s{0,64}\(|>>?)"
     r"[^\n]{0,512}(?:\$HOME/\.ssh|~/\.ssh)", "ssh_access", "strict", "changes the SSH folder"),
    (r"(?<![\w.])\.credentials/", "craftbot_secrets", "strict",
     "points at CraftBot's credential store"),
    (rf"{_MODIFY}(?:AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules)", "agent_config_mod", "strict",
     "changes an agent's instruction file"),
    (rf"{_MODIFY}(?:agent_file_system/(?:AGENT|SOUL)\.md|app/config/(?:settings|security|mcp_config)\.json)",
     "craftbot_config_mod", "strict", "changes CraftBot's instructions or settings"),
    # ── Hardcoded secrets ──
    (r"(?:api[_-]?key|token|secret|password)\s{0,64}[=:]\s{0,64}[\"']"
     r"(?!(?-i:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)[\"'])"
     r"[A-Za-z0-9+/=_-]{20}", "hardcoded_secret", "strict", "contains a secret"),
]

# Zero-width and bidirectional characters, plus the Unicode TAG block
# ("ASCII smuggling").
INVISIBLE_CHARS = frozenset(
    "​‌‍⁠⁢⁣⁤﻿"
    "‪‫‬‭‮⁦⁧⁨⁩"
) | frozenset(map(chr, range(0xE0000, 0xE0080)))

# The three RGI subdivision flags are the only legitimate use of TAG chars.
_RGI_SUBDIVISION_FLAGS = ("gbeng", "gbsct", "gbwls")
_EMOJI_TAG_SEQUENCE_RE = re.compile(
    "|".join(
        "\U0001F3F4" + "".join(chr(0xE0000 + ord(c)) for c in code) + "\U000E007F"
        for code in _RGI_SUBDIVISION_FLAGS
    )
)

_SCOPE_SETS = {"all": ("all", "context", "strict"), "context": ("context", "strict"), "strict": ("strict",)}
_SEVERITY = {"all": "critical", "context": "warn", "strict": "critical"}
_INFO: Dict[str, Tuple[str, str]] = {pid: (_SEVERITY[scope], desc) for _, pid, scope, desc in _PATTERNS}


def _compile() -> Dict[str, List[Tuple[re.Pattern, str]]]:
    compiled: Dict[str, List[Tuple[re.Pattern, str]]] = {"all": [], "context": [], "strict": []}
    for pattern, pid, scope, _ in _PATTERNS:
        width = _sre_parse.parse(pattern).getwidth()[1]
        if width > _CHUNK_OVERLAP:
            raise ValueError(f"threats: pattern {pid!r} can match {width} chars")
        for s in _SCOPE_SETS[scope]:
            compiled[s].append((re.compile(pattern, re.IGNORECASE), pid))
    return compiled


_COMPILED = _compile()
_WS_RUN = re.compile(r"\s{2,}")


def _collapse_ws(m: re.Match) -> str:
    return "\n" if "\n" in m.group() else " "


def _window_has_match(compiled: re.Pattern, text: str, start: int, end: int) -> bool:
    """A real match starting in ``text[start:end]``: a candidate near the
    window end is re-checked against the whole text."""
    pos = start
    while (m := compiled.search(text, pos, end)) is not None:
        if end >= len(text) or compiled.match(text, m.start()):
            return True
        pos = m.start() + 1
    return False


def _invisible_ids(text: str) -> List[str]:
    raw = set(_EMOJI_TAG_SEQUENCE_RE.sub(lambda m: " " * len(m[0]), text))
    return sorted(f"invisible_unicode_U+{ord(ch):04X}" for ch in raw & INVISIBLE_CHARS)


def _scan_ids(content: str, scope: str) -> List[str]:
    patterns = _COMPILED.get(scope)
    if patterns is None:
        raise ValueError(f"unknown scope {scope!r}")
    if not content:
        return []
    # Invisible characters on the raw text: NFKC can drop them.
    found: List[str] = _invisible_ids(content)
    # NFKC folds full-width variants (ｃａｔ -> cat); whitespace runs
    # collapse so bounded quantifiers see any gap as one separator.
    folded = unicodedata.normalize("NFKC", content)
    normalised = _WS_RUN.sub(_collapse_ws, folded)
    masked = _WS_RUN.sub(_collapse_ws, mask_negated_forget(folded))
    seen = set()
    step = MAX_SCAN_CHARS - _CHUNK_OVERLAP
    for start in range(0, max(len(normalised), len(masked)), step):
        end = start + MAX_SCAN_CHARS
        for compiled, pid in patterns:
            text = masked if pid == "forget_rules" else normalised
            if pid not in seen and _window_has_match(compiled, text, start, end):
                seen.add(pid)
                found.append(pid)
    return found


def find_threats(text: str, scope: str = "context") -> List[Threat]:
    """Every threat in ``text`` for ``scope`` ("all", "context", "strict")."""
    threats = []
    for pid in _scan_ids(text, scope):
        if pid.startswith("invisible_unicode_"):
            code = pid[len("invisible_unicode_"):]
            threats.append(Threat(pid, "critical", f"contains the invisible character {code}"))
        else:
            severity, description = _INFO[pid]
            threats.append(Threat(pid, severity, description))
    return threats


def first_threat(text: str, scope: str = "strict") -> Optional[Threat]:
    """The first threat, for block-on-first-hit callers (memory writes)."""
    threats = find_threats(text, scope)
    return threats[0] if threats else None


# ── Schedule prompts (Hermes cron/prompt_scan.py) ──

# Strict set: a schedule's prompt has no business containing these.
_PROMPT_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(p, re.IGNORECASE), pid, desc)
    for p, pid, desc in (
        (r"ignore\s+(?:\w+\s+)*(?:previous|all|above|prior)\s+(?:\w+\s+)*instructions",
         "prompt_injection", "tells the agent to ignore its instructions"),
        (r"do\s+not\s+tell\s+the\s+user", "deception_hide", "tells the agent to hide something from the user"),
        (r"system\s+prompt\s+override", "sys_prompt_override", "tries to override the system prompt"),
        (r"disregard\s+(?:\w+\s+){0,8}(your|all|any)\s+(?:\w+\s+){0,8}(instructions|rules|guidelines)",
         "disregard_rules", "tells the agent to disregard its rules"),
        (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|id_rsa|id_ed25519|id_ecdsa)",
         "read_secrets", "reads a secrets file"),
        (r"authorized_keys", "ssh_backdoor", "touches SSH authorized_keys"),
        (r"/etc/sudoers|visudo", "sudoers_mod", "changes sudoers"),
        (r"rm\s+-rf\s+/", "destructive_root_rm", "deletes from the root folder"),
        (FORGET_RULES_RAW_RE, "forget_rules", "tells the agent to forget its instructions"),
    )
]
_PROMPT_SECRET_VAR = r"\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)\w*\}?"
# Obvious leak paths only: a secret in the URL, a POST body or an
# Authorization header to an arbitrary host.
_PROMPT_EXFIL_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(p, re.IGNORECASE), pid, "sends a secret variable to a URL")
    for p, pid in (
        (rf"curl\s+[^\n]*https?://[^\s\"'`]*{_PROMPT_SECRET_VAR}", "exfil_curl_url"),
        (rf"wget\s+[^\n]*https?://[^\s\"'`]*{_PROMPT_SECRET_VAR}", "exfil_wget_url"),
        (rf"curl\s+[^\n]*(?:--data(?:-raw|-binary|-urlencode)?|-d|--form|-F)\s+[^\n]*{_PROMPT_SECRET_VAR}",
         "exfil_curl_data"),
        (rf"wget\s+[^\n]*--post-(?:data|file)=[^\n]*{_PROMPT_SECRET_VAR}", "exfil_wget_post"),
        (rf"curl\s+[^\n]*(?:-H|--header)\s+[\"']Authorization:\s*(?:Bearer|token)\s+{_PROMPT_SECRET_VAR}[\"']",
         "exfil_curl_auth_header"),
    )
]

# U+200D joins emoji sequences: allowed between emoji, not between text.
_EMOJI_RANGES = ((0x1F000, 0x1FFFF), (0x2600, 0x27BF), (0x2300, 0x23FF), (0x1F1E6, 0x1F1FF), (0x20E3, 0x20E3))
_VS16 = 0xFE0F


def _zwj_between_emoji(text: str, idx: int) -> bool:
    left = idx - 1
    while left >= 0 and ord(text[left]) == _VS16:
        left -= 1
    right = idx + 1
    while right < len(text) and ord(text[right]) == _VS16:
        right += 1
    if left < 0 or right >= len(text):
        return False
    return all(any(lo <= ord(text[p]) <= hi for lo, hi in _EMOJI_RANGES) for p in (left, right))


def strip_invisible(text: str) -> Tuple[str, List[str]]:
    """``text`` without invisible characters (emoji joiners and subdivision
    flags kept), and the sorted U+XXXX codes removed."""
    if not text:
        return text, []
    removed = set()
    out = []
    flag_tags = {i for m in _EMOJI_TAG_SEQUENCE_RE.finditer(text) for i in range(m.start() + 1, m.end())}
    for idx, ch in enumerate(text):
        if idx in flag_tags:
            out.append(ch)
        elif ch in INVISIBLE_CHARS and not (ch == "‍" and _zwj_between_emoji(text, idx)):
            removed.add(f"U+{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out), sorted(removed)


def scan_prompt(text: str) -> Optional[str]:
    """Why a schedule's prompt should not run, as a short phrase ("reads a
    secrets file (read_secrets)"), or None. Hermes' strict cron prompt scan."""
    if not text:
        return None
    removed = strip_invisible(text)[1]
    if removed:
        return f"contains the invisible character {removed[0]}"
    for patterns in (_PROMPT_PATTERNS, _PROMPT_EXFIL_PATTERNS):
        for pattern, pid, description in patterns:
            target = mask_negated_forget(text) if pid == "forget_rules" else text
            if pattern.search(target):
                return f"{description} ({pid})"
    return None


def schedule_refusal(instruction: str, *, stage: str, name: str = "") -> Optional[str]:
    """The refusal for a schedule's instruction when Settings > Security
    limits scheduled runs and the instruction fails ``scan_prompt``; else
    None. ``stage`` is "create", "update" or "run" (for the audit log)."""
    from app.security.policy import get_policy

    if not get_policy().limit_scheduled_runs:
        return None
    reason = scan_prompt(instruction or "")
    if not reason:
        return None
    try:
        from app.security import audit

        audit.record("schedule_blocked", stage=stage, name=name, reason=reason)
    except Exception:
        pass
    verb = "Not run" if stage == "run" else "Not scheduled"
    return f"{verb}: the instruction {reason}."
