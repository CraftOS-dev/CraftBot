"""Agent App creation wizard — pre-build requirement gathering.

The Add Agent App modal's Create Custom tab runs a three-step wizard:

  1. CONFIGURE — name, description, layout silhouette, theme, icon,
     access mode, reference attachments.
  2. INTERVIEW — this module turns the configuration into targeted
     questions (each with selectable options + free text) via a direct
     LLM call; question count scales with the app's complexity and how
     much the configuration leaves open.
  3. SYNTHESIS — this module rewrites description + configuration +
     attachments + interview answers into ONE comprehensive requirements
     document (Features / Data / Design / Operations / Quality of Life).
     The document becomes the build run's binding specification and is
     saved to <project>/reference/requirements.md.

Everything here runs BEFORE the project or its session exists — no
project is created until the wizard finalizes, so a cancelled wizard
leaves nothing behind except its staging folder (swept opportunistically).

Attachments upload to a staging area (agent_app/_staging/wizard/<id>)
and move into the project at finalize time.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import marketplace_source

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
ICON_EXTS = {".png", ".svg", ".ico", ".jpg", ".jpeg", ".webp"}
STAGING_MAX_AGE_S = 24 * 3600  # abandoned wizard staging is swept after a day

_WIZARD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")

LAYOUT_LABELS = {
    "sidebar-body": "Sidebar navigation + main body",
    "topnav-body": "Top navigation bar + body",
    "hero-cards": "Hero section + card grid",
    "split-view": "Split view (list + detail panel)",
    "dashboard": "Dashboard grid (stat cards + panels)",
    "columns-board": "Columns board (kanban-style lanes)",
    "one-page": "Single-page tool (one focused screen)",
    "free": "Free layout — the agent decides what fits best",
}


# ── staging ─────────────────────────────────────────────────────────────────


def staging_root(agent_app_dir: Path) -> Path:
    return Path(agent_app_dir) / "_staging" / "wizard"


def staging_dir(agent_app_dir: Path, wizard_id: str) -> Path:
    """Validated per-wizard staging folder (created on demand)."""
    if not _WIZARD_ID_RE.match(wizard_id or ""):
        raise ValueError(f"Invalid wizard id: {wizard_id!r}")
    d = staging_root(agent_app_dir) / wizard_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_staged(agent_app_dir: Path, wizard_id: str) -> List[Path]:
    d = staging_root(agent_app_dir) / wizard_id
    if not d.is_dir():
        return []
    return sorted(f for f in d.iterdir() if f.is_file())


def sweep_stale_staging(agent_app_dir: Path) -> None:
    """Remove abandoned wizard staging folders. Best-effort."""
    root = staging_root(agent_app_dir)
    try:
        if not root.is_dir():
            return
        cutoff = time.time() - STAGING_MAX_AGE_S
        for d in root.iterdir():
            try:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                continue
    except Exception:
        pass


_FAVICON_MIME = {
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _inject_favicon(project_path: Path, favicon_name: str, suffix: str) -> None:
    """Point the app's frontend/index.html at the uploaded favicon (Vite
    serves frontend/public/ at the site root). index.html is a SYSTEM file —
    the caller must re-canonize hashes (kit-sync) after this. Best-effort:
    a favicon must never break creation."""
    try:
        index_html = Path(project_path) / "frontend" / "index.html"
        text = index_html.read_text(encoding="utf-8", errors="replace")
        link = (
            f'    <link rel="icon" type="{_FAVICON_MIME.get(suffix, "image/png")}" '
            f'href="/{favicon_name}" />'
        )
        if '<link rel="icon"' in text:
            text = re.sub(
                r'^\s*<link rel="icon"[^\n]*$', link, text, flags=re.MULTILINE
            )
        else:
            marker = "</title>"
            text = text.replace(marker, marker + "\n" + link, 1)
        index_html.write_text(text, encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[AGENT_APP:WIZARD] favicon injection skipped: {exc}")


def move_staging_into_project(
    agent_app_dir: Path, wizard_id: str, project_path: Path
) -> Dict[str, Any]:
    """Move staged files into the project: the uploaded icon (icon.*)
    becomes frontend/public/favicon.<ext> — both the project's display icon
    AND the app's real browser-tab favicon (index.html link injected);
    everything else goes to <project>/reference/. Returns
    {"icon": "file:<relpath>"|None, "references": [names]}. When "icon" is
    set the caller MUST re-canonize system hashes (index.html changed).
    The staging folder is removed afterwards."""
    icon_value: Optional[str] = None
    references: List[str] = []
    d = staging_root(agent_app_dir) / wizard_id
    if not d.is_dir():
        return {"icon": None, "references": []}
    reference_dir = Path(project_path) / "reference"
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if f.stem == "icon" and suffix in ICON_EXTS:
            public_dir = Path(project_path) / "frontend" / "public"
            public_dir.mkdir(parents=True, exist_ok=True)
            favicon_name = f"favicon{suffix}"
            shutil.move(str(f), str(public_dir / favicon_name))
            icon_value = f"file:frontend/public/{favicon_name}"
            _inject_favicon(Path(project_path), favicon_name, suffix)
        else:
            reference_dir.mkdir(parents=True, exist_ok=True)
            target = reference_dir / f.name
            shutil.move(str(f), str(target))
            references.append(f.name)
    shutil.rmtree(d, ignore_errors=True)
    return {"icon": icon_value, "references": references}


# ── LLM plumbing ────────────────────────────────────────────────────────────


async def _llm(system_prompt: str, user_prompt: str, prompt_name: str) -> str:
    from app.internal_action_interface import InternalActionInterface as IAI

    if IAI.llm_interface is None:
        raise RuntimeError("LLM interface not initialized")
    return await IAI.llm_interface.generate_response_async(
        system_prompt, user_prompt, prompt_name=prompt_name
    )


def _parse_json(text: str) -> Any:
    """Parse LLM output as JSON, tolerating a ```json fence."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        t = t[start : end + 1]
    return json.loads(t)


async def describe_staged_images(agent_app_dir: Path, wizard_id: str) -> List[str]:
    """VLM descriptions of staged reference images (best-effort; skipped
    entirely when no VLM is configured)."""
    import asyncio

    from app.internal_action_interface import InternalActionInterface as IAI

    if IAI.vlm_interface is None:
        return []
    notes: List[str] = []
    for f in list_staged(agent_app_dir, wizard_id):
        if f.suffix.lower() not in IMAGE_EXTS or f.stem == "icon":
            continue
        try:
            # describe_image is a blocking classmethod — keep it off the loop.
            desc = await asyncio.to_thread(
                IAI.describe_image,
                str(f),
                "Describe this reference image for a web-app design brief: "
                "layout, regions, components, colors, typography, and any "
                "annotations or labels. Be concrete and complete.",
            )
            if desc:
                notes.append(f"{f.name}: {desc}")
        except RuntimeError as exc:
            # VLM unavailable — no point trying the remaining images.
            logger.debug(f"[AGENT_APP:WIZARD] VLM unavailable: {exc}")
            break
        except Exception as exc:
            logger.debug(f"[AGENT_APP:WIZARD] image description skipped: {exc}")
    return notes


# ── config rendering ────────────────────────────────────────────────────────


def _render_config(config: Dict[str, Any], image_notes: List[str]) -> str:
    """Human-readable summary of the wizard configuration for prompts."""
    lines = [
        f"App name: {config.get('name', '')}",
        f"User's description of the app:\n{config.get('description', '')}",
        "",
        f"Layout choice: {LAYOUT_LABELS.get(config.get('layout') or 'free', 'Free layout — the agent decides')}",
    ]
    ui_theme = str(config.get("uiTheme") or "").strip()
    if ui_theme and ui_theme != "craftbot":
        lines.append(
            f"UI theme (user-picked): {ui_theme} — the host applies this "
            "theme's palette/style to the app automatically. Harmonize your "
            "design accents, imagery, and emphasis colors with it; NEVER "
            "hardcode palette overrides that would fight the theme."
        )
    auth_mode = str(config.get("authMode") or "none")
    if auth_mode == "multi-user":
        lines.append(
            "Access: multi-user — email+password accounts (the platform "
            "provides login/registration; data is per-account where sensible)."
        )
    attachments = config.get("attachments") or []
    if attachments:
        names = ", ".join(str(a.get("name", "?")) for a in attachments)
        lines.append(f"User-provided reference files: {names}")
    # Chat-path extra context (features + the user's verbatim words) — prompt
    # material only, never stored as the project description.
    context = str(config.get("context") or "").strip()
    if context:
        lines.append("")
        lines.append(context)
    if image_notes:
        lines.append("")
        lines.append("Reference image contents (described by a vision model):")
        for note in image_notes:
            lines.append(f"- {note}")
    return "\n".join(lines)


# ── prompts ─────────────────────────────────────────────────────────────────

# One platform-truth block shared by interview + synthesis so the two can
# never drift apart. Describes the (PocketBase) platform.
_PLATFORM_REALITY = """PLATFORM REALITY (questions, options, and the final spec MUST fit it):
- The app runs LOCALLY on the user's machine (localhost) as a single \
PocketBase process. External services CANNOT reach it: never propose inbound \
webhooks, callback URLs, or "install a GitHub App" style mechanisms for \
getting data in.
- CraftBot already has the user's connected accounts (GitHub, Google, Slack, \
Discord, Notion, ...) reachable through a built-in ZERO-KEY bridge the app's \
backend routes can call. External data is PULLED through that bridge — on \
load, on refresh, or on a schedule. The bridge also offers in-app AI \
(summarize/classify/generate text). NEVER propose OAuth flows, personal \
access tokens, API-key entry, or any credential handling; the platform \
forbids asking users for keys.
- Available building blocks: a declared database (PocketBase collections \
with typed fields and relations), file upload fields, LIVE in-app updates of \
the app's OWN data (realtime subscriptions are native — lists update \
instantly when records change), custom backend operations (an agent-callable \
verb surface), scheduled operations ("every 15m" / "daily HH:MM"), in-app AI \
via the bridge, CSV/JSON export, and an optional email+password multi-user \
mode (no third-party login).
- "Real-time" for EXTERNAL data still means periodic refresh or scheduled \
bridge sync — offer/write THAT, never webhooks. Only the app's own records \
update live.
- Browser permission prompts (location, notifications, camera) are \
unreliable in the embedded tab: location comes from a keyless backend IP \
lookup or a user-entered setting — never design a feature that depends on \
the user granting a browser permission. Public data (weather, news, \
prices) is fetched by the BACKEND from keyless public APIs, cached, \
degrading gracefully offline."""


_MARKETPLACE_CACHE: Dict[str, Any] = {}
_MARKETPLACE_TTL_SECONDS = 3600


def _marketplace_catalogue() -> List[Dict[str, Any]]:
    """[{id, name, description, tags}] of ready-made marketplace apps, or [].

    Local checkout first (developer machines), GitHub raw as fallback,
    fail-open always — a missing catalogue must never block a build. Cached
    an hour; the catalogue changes rarely.
    """
    import time as _time

    cached = _MARKETPLACE_CACHE.get("apps")
    if cached is not None and _time.time() - cached[0] < _MARKETPLACE_TTL_SECONDS:
        return cached[1]

    apps: List[Dict[str, Any]] = []
    raw = None
    local = marketplace_source.local_catalogue()
    if local is not None:
        try:
            raw = json.loads(local.read_text(encoding="utf-8"))
        except Exception:
            raw = None
    if raw is None:
        try:
            import urllib.request

            url = marketplace_source.catalogue_url()
            with urllib.request.urlopen(url, timeout=4) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"[WIZARD] marketplace catalogue unavailable: {e}")
            raw = None
    if isinstance(raw, dict):
        entries = raw.get("apps") or []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") and entry.get("description"):
                apps.append(
                    {
                        "id": entry["id"],
                        "name": entry.get("name") or entry["id"],
                        "description": str(entry["description"])[:200],
                        "tags": entry.get("tags") or [],
                    }
                )

    _MARKETPLACE_CACHE["apps"] = (_time.time(), apps)
    return apps


def _tokens(text: str) -> set:
    """Crude match tokens: lowercase alnum words, 3+ chars, plural-stripped."""
    return {
        w[:-1] if w.endswith("s") else w
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) >= 3
    }


def _rank_marketplace(
    apps: List[Dict[str, Any]], query: str, k: int = 6
) -> List[Dict[str, Any]]:
    """Top-k catalogue candidates for the user's description, scored by
    lexical overlap (tags > name > description). The interview prompt only
    ever sees these k — the LLM makes the final same-core-purpose judgment
    among them, but it must never be handed the whole catalogue: matching
    degrades and tokens explode as the marketplace grows (fine at 18 apps,
    unworkable at thousands). Deterministic and in-process; swap for an
    embedding index if lexical overlap ever proves too blunt."""
    q = _tokens(query)
    if not q:
        return apps[:k]

    def _score(app: Dict[str, Any]) -> int:
        tag_tokens = _tokens(" ".join(app.get("tags") or []))
        name_tokens = _tokens(str(app.get("name", "")) + " " + str(app.get("id", "")))
        desc_tokens = _tokens(str(app.get("description", "")))
        return 3 * len(q & tag_tokens) + 2 * len(q & name_tokens) + len(q & desc_tokens)

    scored = sorted(
        ((_score(a), i, a) for i, a in enumerate(apps)),
        key=lambda t: (-t[0], t[1]),
    )
    hits = [a for s, _, a in scored if s > 0][:k]
    # Nothing overlaps at all → offer nothing; the MARKETPLACE CHECK rule
    # already says never to force the question without a genuine match.
    return hits


def _render_marketplace(apps: List[Dict[str, Any]]) -> str:
    if not apps:
        return ""
    lines = [
        "\nMARKETPLACE — ready-made apps that can be installed instead of building:"
    ]
    for a in apps:
        tags = (" [" + ", ".join(a["tags"][:4]) + "]") if a["tags"] else ""
        lines.append(f"- {a['id']}: {a['name']} — {a['description']}{tags}")
    return "\n".join(lines) + "\n"


INTERVIEW_SYSTEM_PROMPT = f"""You are a requirements interviewer for a web-app builder. \
The user described an app and picked configuration options; your questions close the \
gaps between that input and a complete, buildable specification.

{_PLATFORM_REALITY}

Rules:
- Ask ONLY what the description and configuration leave genuinely open. Never ask \
something the input already answers.
- Scale the question count to the app: a simple single-purpose tool needs ~3-5 \
questions; a rich multi-entity app needs more. Ask for exactly what a builder \
would still need — no filler, no padding to a quota.
- Cover the aspects that matter for building: what the app manages (entities and \
their fields), core workflows, prioritization of features, edge behaviors, and any \
design intent the configuration left open. Skip design aspects the configuration \
already fixed.
- Every question offers 4-6 CONCRETE, specific options (never "Yes"/"No"/"Maybe" \
padding; each option is a real, distinct choice a user could want). The user can \
always type a free answer instead, so options should capture the most likely \
answers.
- DATA-SOURCE OPTIONS MUST BE REAL: an option describing where data comes from \
must name a mechanism that actually exists on this platform — user forms, \
CSV/file import, a NAMED connected-integration action, or a NAMED keyless \
public API (e.g. Open-Meteo). NEVER offer "the backend pulls/finds/verifies X" \
when no such source exists here: there is no web scraping, no lead database, \
no email-verification service, no business-directory search. An impossible \
option the user picks becomes a spec the builder cannot implement (observed \
live: "scheduled daily pull of 20-30 verified business emails" shipped as a \
button wired to nothing).
- Mark a question multiSelect when several options can genuinely combine.
- MARKETPLACE CHECK: when the input includes a MARKETPLACE list and one app \
on it clearly matches what the user described (same core purpose, not merely \
a shared word), your FIRST question must present it BY NAME and offer exactly: \
"Install <name> as-is (ready now)", "Install <name> and adapt it to my needs", \
"Build a fresh app from scratch". Reusing a finished app is the user's \
decision — never silently rebuild what exists, and never force the question \
when nothing genuinely matches. When you DO ask it, it may be your only \
question in this batch — the system runs a follow-up round with the detail \
questions once the user's choice is known, so don't pad this batch with \
questions that assume one branch.

Respond with STRICT JSON only (no prose, no markdown fence):
{{"questions": [{{"id": "q1", "question": "...", "why": "one short sentence on why this matters", "multiSelect": false, "options": ["...", "...", "...", "..."]}}]}}"""


# The MARKETPLACE CHECK option wordings are mandated by
# INTERVIEW_SYSTEM_PROMPT, so both choices are detectable verbatim in the
# answers.
_ADAPT_MARKER = "adapt it to my needs"
_FRESH_MARKER = "fresh app from scratch"


def adapt_chosen(answers: List[Dict[str, Any]]) -> bool:
    """True when the user answered the marketplace question with the
    'Install <name> and adapt it to my needs' option."""
    for a in answers or []:
        if _ADAPT_MARKER in str(a.get("answer", "")).lower():
            return True
    return False


def fresh_build_chosen(answers: List[Dict[str, Any]]) -> bool:
    """True when the user answered the marketplace question with
    'Build a fresh app from scratch'."""
    for a in answers or []:
        if _FRESH_MARKER in str(a.get("answer", "")).lower():
            return True
    return False


FOLLOWUP_SYSTEM_PROMPT = """You are a requirements interviewer for a web-app \
builder. The user chose to install an existing marketplace app but ADAPT it to \
their needs — and has not yet said what those needs are. Generate 2-4 \
follow-up questions that pin down EXACTLY what should be different from the \
marketplace version.

THE ONE RULE: every option must be a CONCRETE ADAPTATION the spec writer \
could paste in verbatim — a statement of the change itself, never a category \
of change. BANNED: "Change the board columns", "Modify fields on cards", \
"Update look and feel" — picking one of those teaches the builder NOTHING. \
GOOD: "Rename the columns to Backlog / In Progress / Done", "Remove the \
checklists and due dates from cards", "Add an assignee field to each card", \
"Keep it exactly as described". Never ask a single "what kind of change do \
you want?" question — ask one question PER dimension the app's description \
exposes (its stages/entities, its card/record fields, its extra features, \
its look), each with concrete candidate changes for THAT dimension drawn \
from the app's own described features. The user can always type a free \
answer, so options are the most likely concrete choices — and every \
question includes a "Keep this as the marketplace version has it" option.

Ground everything in the app's description and the user's words; never \
invent capabilities neither of them mentions.

Respond with STRICT JSON only (no prose, no markdown fence):
{"questions": [{"id": "f1", "question": "...", "why": "one short sentence", "multiSelect": false, "options": ["...", "..."]}]}"""


def _adapt_target(answers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The catalogue entry of the app the user chose to adapt, parsed from
    the mandated option wording. None when unresolvable (fail-open)."""
    chosen = ""
    for a in answers or []:
        m = re.search(
            r"install\s+(.+?)\s+and adapt it to my needs",
            str(a.get("answer", "")),
            re.IGNORECASE,
        )
        if m:
            chosen = m.group(1).strip().lower()
            break
    if not chosen:
        return None
    try:
        for app in _marketplace_catalogue():
            if chosen in (
                str(app.get("id", "")).lower(),
                str(app.get("name", "")).lower(),
            ):
                return app
    except Exception:
        return None
    return None


async def generate_followup_questions(
    config: Dict[str, Any],
    answers: List[Dict[str, Any]],
    image_notes: List[str],
) -> List[Dict[str, Any]]:
    """Second interview round, run only when the user picked the marketplace
    ADAPT option: ask what should actually be different. Observed live
    (2026-08-05, kanban board): without this round the synthesis had no
    material and fabricated the adaptation list. Returns [] on any failure —
    the caller falls through to synthesis rather than blocking the wizard."""
    answer_lines = [
        f"Q: {str(a.get('question', '')).strip()}\nA: {str(a.get('answer', '')).strip()}"
        for a in answers or []
        if str(a.get("question", "")).strip() and str(a.get("answer", "")).strip()
    ]
    # The model can only propose CONCRETE deltas if it knows what the app
    # HAS — without the catalogue entry it retreats to category options
    # ("change the columns") that teach the spec writer nothing (observed
    # live 2026-08-05, kanban-board adapt).
    target = _adapt_target(answers)
    target_part = (
        (
            f"\n\nThe marketplace app being adapted:\n"
            f"{target['id']}: {target['name']} — {target['description']}"
            + (
                (" [" + ", ".join(target["tags"][:6]) + "]")
                if target.get("tags")
                else ""
            )
        )
        if target
        else ""
    )
    user_prompt = (
        _render_config(config, image_notes)
        + target_part
        + "\n\nAnswers so far:\n"
        + ("\n\n".join(answer_lines) if answer_lines else "(none)")
        + "\n\nGenerate the follow-up questions now (STRICT JSON)."
    )
    try:
        raw = await _llm(
            FOLLOWUP_SYSTEM_PROMPT,
            user_prompt,
            prompt_name="AGENT_APP_WIZARD_FOLLOWUP",
        )
        data = _parse_json(raw)
        cleaned: List[Dict[str, Any]] = []
        for i, q in enumerate(data.get("questions") or []):
            text = str(q.get("question", "")).strip()
            options = [
                str(o).strip() for o in (q.get("options") or []) if str(o).strip()
            ]
            if not text or len(options) < 2:
                continue
            cleaned.append(
                {
                    "id": str(q.get("id") or f"f{i + 1}"),
                    "question": text,
                    "why": str(q.get("why", "")).strip(),
                    "multiSelect": bool(q.get("multiSelect", False)),
                    "options": options[:6],
                }
            )
        return cleaned[:3]
    except Exception as e:
        logger.warning(f"[AGENT_APP:WIZARD] follow-up generation failed: {e}")
        return []


async def generate_interview(
    config: Dict[str, Any],
    image_notes: List[str],
    include_marketplace: bool = True,
    allow_empty: bool = False,
) -> List[Dict[str, Any]]:
    """Generate interview questions from the wizard configuration.

    include_marketplace=False runs the SECOND round after the user chose
    'Build a fresh app from scratch': with a marketplace match, models make
    the marketplace question the ONLY round-1 question (observed live
    2026-08-05, kanban board — the fresh build then synthesized from a
    one-line description with zero requirement questions asked), so the real
    interview happens now, with the catalogue withheld so it cannot re-ask.

    allow_empty=True is the CHAT path: the description was distilled from a
    conversation that may already answer everything, so "no questions" is a
    valid outcome (build proceeds without a user round-trip). The modal
    wizard keeps allow_empty=False — there the user typed one description
    line and an empty interview means generation failed, not completeness.
    """
    marketplace_part = (
        _render_marketplace(
            _rank_marketplace(
                _marketplace_catalogue(),
                f"{config.get('name', '')} {config.get('description', '')}",
            )
        )
        if include_marketplace
        else (
            "\n\nThe user already chose to BUILD FRESH FROM SCRATCH (the "
            "marketplace was offered and declined) — ask the normal "
            "requirement questions; never ask about installing existing apps."
        )
    )
    empty_part = (
        (
            "\n\nThe description above was distilled from a chat conversation "
            "and may already be complete. If it (plus the marketplace check) "
            'leaves NOTHING genuinely open, respond {"questions": []} — do '
            "not invent questions the input already answers."
        )
        if allow_empty
        else ""
    )
    user_prompt = (
        _render_config(config, image_notes)
        + marketplace_part
        + empty_part
        + "\n\nGenerate the interview questions now (STRICT JSON)."
    )
    raw = await _llm(
        INTERVIEW_SYSTEM_PROMPT, user_prompt, prompt_name="AGENT_APP_WIZARD_INTERVIEW"
    )
    try:
        data = _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        # One reformat retry: feed the broken output back for correction.
        raw = await _llm(
            INTERVIEW_SYSTEM_PROMPT,
            "Your previous response was not valid JSON. Reply with ONLY the "
            "corrected strict-JSON object.\n\nPrevious response:\n" + raw,
            prompt_name="AGENT_APP_WIZARD_INTERVIEW_RETRY",
        )
        data = _parse_json(raw)
    questions = data.get("questions") or []
    cleaned: List[Dict[str, Any]] = []
    for i, q in enumerate(questions):
        text = str(q.get("question", "")).strip()
        options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        if not text or len(options) < 2:
            continue
        cleaned.append(
            {
                "id": str(q.get("id") or f"q{i + 1}"),
                "question": text,
                "why": str(q.get("why", "")).strip(),
                "multiSelect": bool(q.get("multiSelect", False)),
                "options": options[:6],
            }
        )
    if not cleaned and not allow_empty:
        raise ValueError("interview generation returned no usable questions")
    return cleaned


# ── synthesis ───────────────────────────────────────────────────────────────

# The document template + rules shared by BOTH synthesis prompts (interview
# and source-derived) — one definition so they can never drift apart, same
# reasoning as _PLATFORM_REALITY.
_REQUIREMENTS_TEMPLATE = """The document is markdown with EXACTLY these sections:

# <App name> — Requirements

## Overview
What the app is, who uses it, and the core experience — a few tight paragraphs.

## Features
Every user-facing capability, each as a concrete "the user can ..." statement with \
enough detail to build from (controls involved, expected outcome). Cover the full \
scope the user asked for — nothing vague, nothing invented beyond their intent.

## Data
Every entity the app manages: collections with fields (and types), relations, and \
lifecycle (how records are created/updated/deleted through the UI). For EVERY \
entity, state its INGRESS — how records actually enter the app: user forms, pull \
from a named connected service via the bridge (on load/refresh and/or a scheduled \
sync), file import, or computed from other entities. An app whose purpose is \
displaying external data MUST specify the bridge pull and a scheduled sync \
operation — a spec with no working ingress is unimplementable.

## Design
The binding visual contract: the chosen layout translated into concrete regions, \
the theme/color choices made binding, iconography, empty states, and how the \
reference images' ideas are incorporated. Where the user chose "agent decides", \
make a concrete choice HERE and state it.

## Operations
What the app's operations surface must support so an agent can operate it \
(reading and writing the app's data programmatically, the key custom verbs to \
declare beyond plain collection CRUD).

## Quality of Life
Power-user touches appropriate to THIS app (shortcuts, drag & drop, bulk actions, \
context menus, responsiveness) — concrete and scoped, not a generic checklist.

Rules:
- Every statement must be concrete and checkable; ban filler like "user-friendly", \
"modern", "polished".
- Where input is silent, decide — the builder must never need to ask.
- Respond with the markdown document ONLY (no fence, no preamble)."""


SYNTHESIS_SYSTEM_PROMPT = f"""You write the requirements document for a web-app build. \
You receive the user's app description, their configuration choices, descriptions of \
their reference files, and their interview answers. Rewrite ALL of it into ONE \
comprehensive, binding specification the builder agent will implement exactly.

{_PLATFORM_REALITY}

The spec is BINDING and the builder cannot question it, so it must be \
implementable exactly as written. If an interview answer implies a mechanism \
the platform cannot execute (inbound webhooks, OAuth, token entry), translate \
the INTENT into the platform's equivalent (bridge pull on load/refresh plus a \
scheduled sync operation) and write THAT. If an answer promises DATA the \
platform has no source for (found/verified/scraped business contacts, any \
"the backend pulls X" with no named connected integration or keyless public \
API behind it), do NOT write the impossible ingress: specify the nearest \
real one (user entry, CSV import, records the user's agent adds via the \
operations surface) and state the limitation plainly in the Overview. A spec \
whose ingress cannot run ships as a dead button and fails verification.

If an interview answer chose to INSTALL a marketplace app (as-is or adapted), \
the document is SHORT and different from the template below. Its FIRST line \
must be exactly: `MARKETPLACE DECISION: install <app-id>; adapt: <yes|no>`, \
then a `## Adaptations` list, then a `## User request` section quoting the \
user's own description — and NOTHING else. Do NOT generate the Features/Data/\
Design/Operations/Quality-of-Life sections for a marketplace install: the \
installed app already IS the specification, and an invented spec misleads \
verification. Adaptation bullets may ONLY restate changes the user explicitly \
asked for (in their description or interview answers), phrased as checkable \
"the user can ..." statements. If the user chose to adapt but stated no \
concrete changes anywhere, write `adapt: yes` with the single bullet \
`- none specified — ask the user before changing anything`; never invent \
adaptations. The builder installs that app via agent_app_marketplace_install \
and applies only the adaptations — it must NOT build from scratch.

NEVER weaken a user-stated deliverable when rewriting: "email me" means the \
user RECEIVES an email (via the bridge's send_gmail action) — not "queues", \
"logs", or "prepares" one. Preserve user-visible outcomes verbatim.

{_REQUIREMENTS_TEMPLATE}
- Preserve EVERY decision the user made in the configuration and interview — \
nothing they chose may be dropped or diluted."""


SOURCE_SYNTHESIS_SYSTEM_PROMPT = f"""You write the requirements document for \
REBUILDING an existing app on a new platform. You receive the app's source \
code (README, dependency manifests, routes, models, UI files — possibly \
truncated). The original runs on a DIFFERENT stack; only the BEHAVIOR is \
being carried over, never the code. Describe what the app DOES for its user \
— every capability you can actually evidence in the source — as a binding \
specification the builder agent will implement from scratch.

{_PLATFORM_REALITY}

Ground every statement in the source: a feature you cannot point to in the \
code does not go in the document. If the source integrates services this \
platform reaches differently (its own SMTP, OAuth, webhooks), translate the \
INTENT into the platform's equivalent (bridge actions, scheduled sync) — and \
if the source's purpose for it is unclear, OMIT it rather than guess. Never \
describe implementation details of the old stack (frameworks, file names, \
endpoints) — describe user-visible behavior.

{_REQUIREMENTS_TEMPLATE}"""


def _render_source(source_dir: Path) -> str:
    """Deterministic prompt rendering of a foreign app's source tree: the
    file listing plus the contents of the most informative files (README
    first, then dependency manifests, then route/model/schema/UI-looking
    files), truncated per-file and capped overall. Pure, read-only."""
    source_dir = Path(source_dir)
    per_file_cap = 3000
    total_cap = 24000
    listing: List[str] = []
    files: List[Path] = []
    for f in sorted(source_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(source_dir)
        if len(listing) < 200:
            listing.append(str(rel))
        files.append(f)

    def _score(f: Path) -> int:
        name = f.name.lower()
        rel = str(f.relative_to(source_dir)).lower()
        if name.startswith("readme"):
            return 0
        if name in ("package.json", "pyproject.toml", "go.mod", "cargo.toml"):
            return 1
        if re.search(r"(route|model|schema|api|urls|views|controller)", rel):
            return 2
        if name.endswith((".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rb")):
            return 3
        return 4

    parts = ["File tree:\n" + "\n".join(listing)]
    used = len(parts[0])
    for f in sorted(files, key=lambda f: (_score(f), str(f))):
        if _score(f) >= 4 or used >= total_cap:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:per_file_cap]
        except Exception:
            continue
        if not text.strip():
            continue
        chunk = f"\n\n--- {f.relative_to(source_dir)} ---\n{text}"
        if used + len(chunk) > total_cap:
            continue
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)


async def synthesize_requirements_from_source(
    source_dir: Path, app_name: str, user_hint: str = ""
) -> str:
    """Derive the requirements document from a foreign app's source code
    (LIFECYCLE-PLAN Phase 4: conversion = rebuild with the source as
    evidence). Same output contract as synthesize_requirements."""
    user_prompt = (
        f"App name: {app_name}\n"
        + (f"User's note on what matters: {user_hint}\n" if user_hint else "")
        + "\nThe app's source code:\n\n"
        + _render_source(Path(source_dir))
        + "\n\nWrite the requirements document now."
    )
    doc = await _llm(
        SOURCE_SYNTHESIS_SYSTEM_PROMPT,
        user_prompt,
        prompt_name="AGENT_APP_SOURCE_SYNTHESIS",
    )
    doc = _unwrap_document(doc or "")
    if len(doc) < 200:
        raise ValueError(
            "source-requirements synthesis returned an implausibly short document"
        )
    return doc


async def synthesize_requirements(
    config: Dict[str, Any],
    answers: List[Dict[str, Any]],
    image_notes: List[str],
) -> str:
    """Rewrite config + interview answers into the requirements document."""
    answer_lines = []
    for a in answers or []:
        q = str(a.get("question", "")).strip()
        ans = a.get("answer")
        if isinstance(ans, list):
            ans = ", ".join(map(str, ans))
        ans = str(ans or "").strip()
        if q and ans:
            answer_lines.append(f"Q: {q}\nA: {ans}")
    user_prompt = (
        _render_config(config, image_notes)
        + "\n\nInterview answers:\n"
        + ("\n\n".join(answer_lines) if answer_lines else "(none)")
        + "\n\nWrite the requirements document now."
    )
    doc = await _llm(
        SYNTHESIS_SYSTEM_PROMPT, user_prompt, prompt_name="AGENT_APP_WIZARD_SYNTHESIS"
    )
    doc = _unwrap_document(doc or "")
    # The short-document guard protects against a truncated/empty LLM
    # response becoming the binding spec — but marketplace-decision documents
    # are SHORT by mandate ("install X; adapt: no" + the user's one-liner is
    # complete and correct at well under 200 chars). Observed live
    # 2026-08-05: a valid as-is install doc tripped the guard and failed the
    # whole wizard finalize. Exempt them; require only the decision line.
    if doc.startswith("MARKETPLACE DECISION:"):
        if not re.match(
            r"^MARKETPLACE DECISION: install [A-Za-z0-9_-]+; adapt: (yes|no)\s*$",
            doc.splitlines()[0],
        ):
            raise ValueError("marketplace decision line is malformed")
        return doc
    if len(doc) < 200:
        raise ValueError(
            "requirements synthesis returned an implausibly short document"
        )
    return doc


def _unwrap_document(doc: str) -> str:
    """Strip a code fence and/or JSON envelope off an LLM-written document.

    Some providers return JSON even when told "markdown only". Observed live
    (kanban_board_1bb64990, 2026-08-04): grok wrapped the whole requirements
    document as {"document": "# kanban...\\n..."} — the file shipped as
    escaped JSON and the verifier, unable to read it as markdown, collapsed
    a 9-feature spec into "1 feature verified". And again 2026-08-05: a
    SHORT-by-mandate marketplace-decision doc arrived in the same envelope,
    slipped past the old ≥200-char unwrap heuristic, and tripped the
    short-document guard while still wrapped. Unwrap: a decision-prefixed
    value always wins; a dict with exactly one string value unwraps
    regardless of length; multiple strings fall back to the single-long-one
    rule; a bare JSON string unwraps. Everything else is untouched.
    """
    doc = doc.strip()
    if doc.startswith("```"):
        doc = re.sub(r"^```[a-zA-Z]*\s*", "", doc)
        doc = re.sub(r"\s*```$", "", doc)
        doc = doc.strip()
    if doc.startswith("{"):
        try:
            parsed = json.loads(doc)
            if isinstance(parsed, dict):
                strings = [
                    v.strip()
                    for v in parsed.values()
                    if isinstance(v, str) and v.strip()
                ]
                decision = [s for s in strings if s.startswith("MARKETPLACE DECISION:")]
                if decision:
                    return decision[0]
                if len(strings) == 1:
                    return strings[0]
                long_strings = [s for s in strings if len(s) >= 200]
                if len(long_strings) == 1:
                    return long_strings[0]
        except Exception:
            pass
    elif doc.startswith('"'):
        try:
            parsed = json.loads(doc)
            if isinstance(parsed, str):
                return parsed.strip()
        except Exception:
            pass
    return doc


# ── chat-path requirements phase ────────────────────────────────────────────
# A build started from chat (agent_app_scaffold) runs the SAME interview →
# synthesis → finalize pipeline as the modal wizard: with open questions the
# scaffold action creates NOTHING and summons the wizard UI instead
# (agent_app_wizard_open); the wizard's finalize creates the project exactly
# as the modal path does. Only the zero-questions shortcut below runs in the
# action itself. These helpers live here and not in the actions file because
# action handlers execute from registry-extracted source (no module globals).


async def synthesize_to_project(
    project_path: Path, config: Dict[str, Any], answers: List[Dict[str, Any]]
) -> str:
    """Synthesize the binding spec and write it where the build and
    walk-verify read it. Returns the document."""
    doc = await synthesize_requirements(config, answers, [])
    reference_dir = Path(project_path) / "reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    (reference_dir / "requirements.md").write_text(doc, encoding="utf-8")
    return doc
