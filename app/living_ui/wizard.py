"""Living UI creation wizard — pre-task requirement gathering.

The Add Living UI modal's Create Custom tab runs a three-step wizard:

  1. CONFIGURE — name, description, layout silhouette, icon, structured
     options (access, style, density, ...), reference attachments.
  2. INTERVIEW — this module turns the configuration into targeted
     questions (each with selectable options + free text) via a direct
     LLM call; question count scales with the app's complexity and how
     much the configuration leaves open.
  3. SYNTHESIS — this module rewrites description + configuration +
     attachments + interview answers into ONE comprehensive requirements
     document (Features / Data / Design / Operations / Quality of Life).
     The document becomes the build task's binding specification and is
     saved to <project>/reference/requirements.md.

Everything here runs BEFORE the build task exists — no project is created
until the wizard finalizes, so a cancelled wizard leaves nothing behind
except its staging folder (cleaned opportunistically).

Attachments upload to a staging area (workspace/tmp/living_ui_wizard/<id>)
and move into <project>/reference/ at finalize time.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def staging_root(workspace_root: Path) -> Path:
    return Path(workspace_root) / "tmp" / "living_ui_wizard"


def staging_dir(workspace_root: Path, wizard_id: str) -> Path:
    """Validated per-wizard staging folder (created on demand)."""
    if not _WIZARD_ID_RE.match(wizard_id or ""):
        raise ValueError(f"Invalid wizard id: {wizard_id!r}")
    d = staging_root(workspace_root) / wizard_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_staged(workspace_root: Path, wizard_id: str) -> List[Path]:
    d = staging_root(workspace_root) / wizard_id
    if not d.is_dir():
        return []
    return sorted(f for f in d.iterdir() if f.is_file())


def sweep_stale_staging(workspace_root: Path) -> None:
    """Remove abandoned wizard staging folders. Best-effort."""
    root = staging_root(workspace_root)
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
    """Point the app's index.html at the uploaded favicon (Vite serves
    public/ at the site root). Best-effort — a favicon must never break
    creation."""
    try:
        index_html = Path(project_path) / "index.html"
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
        logger.debug(f"[LIVING_UI:WIZARD] favicon injection skipped: {exc}")


def move_staging_into_project(
    workspace_root: Path, wizard_id: str, project_path: Path
) -> Dict[str, Any]:
    """Move staged files into the project: the uploaded icon (icon.*)
    becomes public/favicon.<ext> — both the project's display icon AND the
    app's real browser-tab favicon (index.html link injected); everything
    else goes to <project>/reference/. Returns
    {"icon": "file:<relpath>"|None, "references": [names]}. The staging
    folder is removed afterwards."""
    icon_value: Optional[str] = None
    references: List[str] = []
    d = staging_root(workspace_root) / wizard_id
    if not d.is_dir():
        return {"icon": None, "references": []}
    reference_dir = Path(project_path) / "reference"
    for f in sorted(d.iterdir()):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if f.stem == "icon" and suffix in ICON_EXTS:
            public_dir = Path(project_path) / "public"
            public_dir.mkdir(parents=True, exist_ok=True)
            favicon_name = f"favicon{suffix}"
            shutil.move(str(f), str(public_dir / favicon_name))
            icon_value = f"file:public/{favicon_name}"
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


async def describe_staged_images(workspace_root: Path, wizard_id: str) -> List[str]:
    """VLM descriptions of staged reference images (best-effort; skipped
    entirely when no VLM is configured)."""
    import asyncio

    from app.internal_action_interface import InternalActionInterface as IAI

    if IAI.vlm_interface is None:
        return []
    notes: List[str] = []
    for f in list_staged(workspace_root, wizard_id):
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
            logger.debug(f"[LIVING_UI:WIZARD] VLM unavailable: {exc}")
            break
        except Exception as exc:
            logger.debug(f"[LIVING_UI:WIZARD] image description skipped: {exc}")
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
    options = config.get("options") or {}
    option_labels = {
        "access": "Access / accounts",
        "style": "Design style",
        "colorMode": "Color mode",
        "accent": "Accent color",
        "fontSize": "Font size",
        "density": "Element density",
        "corners": "Corner style",
        "motion": "Motion / animation",
        "device": "Target device",
    }
    for key, label in option_labels.items():
        value = options.get(key)
        if value and value != "agent":
            lines.append(f"{label}: {value}")
    attachments = config.get("attachments") or []
    if attachments:
        names = ", ".join(str(a.get("name", "?")) for a in attachments)
        lines.append(f"User-provided reference files: {names}")
    if image_notes:
        lines.append("")
        lines.append("Reference image contents (described by a vision model):")
        for note in image_notes:
            lines.append(f"- {note}")
    return "\n".join(lines)


# ── interview ───────────────────────────────────────────────────────────────

INTERVIEW_SYSTEM_PROMPT = """You are a requirements interviewer for a web-app builder. \
The user described an app and picked configuration options; your questions close the \
gaps between that input and a complete, buildable specification.

PLATFORM REALITY (questions, options, and the final spec MUST fit it):
- The app runs LOCALLY on the user's machine (localhost). External services \
CANNOT reach it: never propose inbound webhooks, callback URLs, or "install \
a GitHub App" style mechanisms for getting data in.
- CraftBot already has the user's connected accounts (GitHub, Google, Slack, \
Discord, Notion, ...) reachable through a built-in ZERO-KEY bridge. External \
data is PULLED through that bridge — on load, on refresh, or on a schedule. \
NEVER propose OAuth flows, personal access tokens, API-key entry, or any \
credential handling; the platform forbids asking users for keys.
- Available building blocks: a declared database (local SQLite; optional \
user-provided Postgres/Supabase), file uploads, scheduled operations \
("every 15m" / "daily HH:MM"), in-app AI (summarize/classify), CSV/JSON \
export, a CLI operations surface, and an optional email+password multi-user \
module (no third-party login).
- "Real-time updates" translates to periodic refresh or scheduled bridge \
sync — offer/write THAT, never webhooks.
- Browser permission prompts (location, notifications, camera) are \
unreliable in the embedded tab: location comes from a keyless backend IP \
lookup or a user-entered setting — never design a feature that depends on \
the user granting a browser permission. Public data (weather, news, \
prices) is fetched by the BACKEND from keyless public APIs, cached, \
degrading gracefully offline.

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
- Mark a question multiSelect when several options can genuinely combine.

Respond with STRICT JSON only (no prose, no markdown fence):
{"questions": [{"id": "q1", "question": "...", "why": "one short sentence on why this matters", "multiSelect": false, "options": ["...", "...", "...", "..."]}]}"""


async def generate_interview(
    config: Dict[str, Any], image_notes: List[str]
) -> List[Dict[str, Any]]:
    """Generate interview questions from the wizard configuration."""
    user_prompt = (
        _render_config(config, image_notes)
        + "\n\nGenerate the interview questions now (STRICT JSON)."
    )
    raw = await _llm(
        INTERVIEW_SYSTEM_PROMPT, user_prompt, prompt_name="LIVING_UI_WIZARD_INTERVIEW"
    )
    try:
        data = _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        # One reformat retry: feed the broken output back for correction.
        raw = await _llm(
            INTERVIEW_SYSTEM_PROMPT,
            "Your previous response was not valid JSON. Reply with ONLY the "
            "corrected strict-JSON object.\n\nPrevious response:\n" + raw,
            prompt_name="LIVING_UI_WIZARD_INTERVIEW_RETRY",
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
    if not cleaned:
        raise ValueError("interview generation returned no usable questions")
    return cleaned


# ── synthesis ───────────────────────────────────────────────────────────────

SYNTHESIS_SYSTEM_PROMPT = """You write the requirements document for a web-app build. \
You receive the user's app description, their configuration choices, descriptions of \
their reference files, and their interview answers. Rewrite ALL of it into ONE \
comprehensive, binding specification the builder agent will implement exactly.

PLATFORM REALITY (questions, options, and the final spec MUST fit it):
- The app runs LOCALLY on the user's machine (localhost). External services \
CANNOT reach it: never propose inbound webhooks, callback URLs, or "install \
a GitHub App" style mechanisms for getting data in.
- CraftBot already has the user's connected accounts (GitHub, Google, Slack, \
Discord, Notion, ...) reachable through a built-in ZERO-KEY bridge. External \
data is PULLED through that bridge — on load, on refresh, or on a schedule. \
NEVER propose OAuth flows, personal access tokens, API-key entry, or any \
credential handling; the platform forbids asking users for keys.
- Available building blocks: a declared database (local SQLite; optional \
user-provided Postgres/Supabase), file uploads, scheduled operations \
("every 15m" / "daily HH:MM"), in-app AI (summarize/classify), CSV/JSON \
export, a CLI operations surface, and an optional email+password multi-user \
module (no third-party login).
- "Real-time updates" translates to periodic refresh or scheduled bridge \
sync — offer/write THAT, never webhooks.
- Browser permission prompts (location, notifications, camera) are \
unreliable in the embedded tab: location comes from a keyless backend IP \
lookup or a user-entered setting — never design a feature that depends on \
the user granting a browser permission. Public data (weather, news, \
prices) is fetched by the BACKEND from keyless public APIs, cached, \
degrading gracefully offline.

The spec is BINDING and the builder cannot question it, so it must be \
implementable exactly as written. If an interview answer implies a mechanism \
the platform cannot execute (inbound webhooks, OAuth, token entry), translate \
the INTENT into the platform's equivalent (bridge pull on load/refresh plus a \
scheduled sync operation) and write THAT.

The document is markdown with EXACTLY these sections:

# <App name> — Requirements

## Overview
What the app is, who uses it, and the core experience — a few tight paragraphs.

## Features
Every user-facing capability, each as a concrete "the user can ..." statement with \
enough detail to build from (controls involved, expected outcome). Cover the full \
scope the user asked for — nothing vague, nothing invented beyond their intent.

## Data
Every entity the app manages: fields (with types), relationships, and lifecycle \
(how records are created/updated/deleted through the UI). For EVERY entity, \
state its INGRESS — how records actually enter the app: user forms, pull from \
a named connected service via the bridge (on load/refresh and/or a scheduled \
sync), file import, or computed from other entities. An app whose purpose is \
displaying external data MUST specify the bridge pull and a scheduled sync \
operation — a spec with no working ingress is unimplementable.

## Design
The binding visual contract: the chosen layout translated into concrete regions, \
the style/color/typography/density/motion choices made binding, iconography, empty \
states, and how the reference images' ideas are incorporated. Where the user chose \
"agent decides", make a concrete choice HERE and state it.

## Operations
What the app's CLI/operations surface must support so an agent can operate it \
(reading and writing the app's data programmatically, the key operations to declare).

## Quality of Life
Power-user touches appropriate to THIS app (shortcuts, drag & drop, bulk actions, \
context menus, responsiveness) — concrete and scoped, not a generic checklist.

Rules:
- Every statement must be concrete and checkable; ban filler like "user-friendly", \
"modern", "polished".
- Preserve EVERY decision the user made in the configuration and interview — \
nothing they chose may be dropped or diluted.
- Where input is silent, decide — the builder must never need to ask.
- Respond with the markdown document ONLY (no fence, no preamble)."""


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
        SYNTHESIS_SYSTEM_PROMPT, user_prompt, prompt_name="LIVING_UI_WIZARD_SYNTHESIS"
    )
    doc = (doc or "").strip()
    if doc.startswith("```"):
        doc = re.sub(r"^```[a-zA-Z]*\s*", "", doc)
        doc = re.sub(r"\s*```$", "", doc)
    if len(doc) < 200:
        raise ValueError(
            "requirements synthesis returned an implausibly short document"
        )
    return doc
