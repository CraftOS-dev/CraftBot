"""Agent Profile Bundle — export and import the current agent as a portable file.

A profile bundle is a zip-with-extension (`.craftbot`) containing the parts of
the agent that define its identity and capabilities — personality MD files, the
enabled skills (with their source folders), the MCP server configs, and the
Agent App app source. It deliberately does NOT include the user's API keys,
OAuth secrets, memory, conversation history, or personal data files.

Bundles are designed for one-click sharing: a recipient picks the bundle in
General Settings and chooses Replace or Merge. Agent name is shown in the
preview for context but is never applied on import.
"""

from __future__ import annotations

import json
import asyncio
import shutil
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    APP_CONFIG_PATH,
    PROJECT_ROOT,
    get_app_version,
)
from app.logger import logger


BUNDLE_FORMAT_VERSION = "1.0"

# Agent identity MD files that travel in the bundle.
# USER.md, MEMORY.md, EVENT*.md, CONVERSATION_HISTORY.md, TASK_HISTORY.md are
# user-personal or runtime state and are intentionally excluded.
PROFILE_MD_FILES = ("SOUL.md", "AGENT.md", "PROACTIVE.md", "GLOBAL_AGENT_APP.md")

# Substrings in MCP env-var NAMES that indicate a secret value. The names are
# kept (so the importer knows what to fill in) but the VALUES are stripped.
SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "CREDENTIAL")

# Files/directories to skip when copying skill folders or Agent App projects.
SKIP_DIR_NAMES = {
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".cache",
    ".turbo",
    ".vite",
    ".git",
    "__pycache__",
}
SKIP_FILE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db-journal", ".pyc")


SKILLS_CONFIG_PATH = APP_CONFIG_PATH / "skills_config.json"
MCP_CONFIG_PATH = APP_CONFIG_PATH / "mcp_config.json"
SKILLS_DIR = PROJECT_ROOT / "skills"


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _should_skip_path(path: Path) -> bool:
    """Skip transient/generated/private files when copying user content."""
    if path.name in SKIP_DIR_NAMES:
        return True
    if path.is_file() and any(
        path.name.lower().endswith(suffix) for suffix in SKIP_FILE_SUFFIXES
    ):
        return True
    return False


def _validate_skill_md(skill_md: Path) -> Optional[str]:
    """Mirror agent_core.core.impl.skill.loader.SkillLoader.parse_skill_file.

    Returns None if the file would load cleanly at runtime, else a short
    reason explaining why the SkillManager would silently drop it. Catches
    the malformed-frontmatter case where YAML parses junk like
    `description: Foo: bar` as a nested mapping.
    """
    import re as _re
    import yaml as _yaml

    if not skill_md.is_file():
        return "SKILL.md missing"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return f"read failed: {exc}"
    if len(text.strip()) < 1:
        return "file is empty"
    fm = _re.match(r"^---\s*\n(.*?)\n---\s*\n", text, _re.DOTALL)
    if not fm:
        # Bodied style (HTML comment / heading only) — loader derives metadata.
        return None
    try:
        data = _yaml.safe_load(fm.group(1))
    except _yaml.YAMLError as exc:
        return f"YAML frontmatter: {str(exc).splitlines()[0]}"
    if not isinstance(data, dict):
        return "frontmatter is not a YAML dict"
    return None


def _validate_mcp_entry(server: Dict[str, Any]) -> Optional[str]:
    """Mirror agent_core.core.impl.mcp.config.MCPConfig.from_dict validation.

    Returns None if the entry would be accepted by the runtime, else a short
    reason. This is the same shape check applied by the bundler — the
    importer enforces it again so corrupt bundles (or polluted upstream
    catalogs) can never silently bloat the recipient's mcp_config.json.
    """
    if not server.get("name"):
        return "missing name"
    transport = server.get("transport", "stdio")
    if transport == "stdio":
        if not server.get("command"):
            return "transport=stdio without command"
    elif transport in ("sse", "http", "streamable_http"):
        if not server.get("url"):
            return f"transport={transport} without url"
    else:
        return f"unknown transport {transport!r}"
    return None


def _copy_dir_filtered(src: Path, dst: Path) -> None:
    """Recursive copy honoring SKIP_DIR_NAMES / SKIP_FILE_SUFFIXES."""
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if _should_skip_path(entry):
            continue
        target = dst / entry.name
        if entry.is_dir():
            _copy_dir_filtered(entry, target)
        else:
            try:
                shutil.copy2(entry, target)
            except OSError as exc:
                logger.warning(
                    f"[PROFILE_BUNDLE] Skipping unreadable file {entry}: {exc}"
                )


def _agent_name() -> str:
    """Best-effort current agent name — used only for the manifest/preview."""
    try:
        from app.onboarding import onboarding_manager

        name = (onboarding_manager.state.agent_name or "").strip()
        if name:
            return name
    except Exception:
        pass
    return "CraftBot"


def _looks_like_secret(env_key: str) -> bool:
    upper = env_key.upper()
    return any(hint in upper for hint in SECRET_ENV_HINTS)


def _strip_mcp_secrets(
    servers: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Strip env-var values that look like secrets. Returns (cleaned, stripped_names)."""
    stripped: List[str] = []
    cleaned: List[Dict[str, Any]] = []
    for server in servers:
        s = dict(server)
        env = dict(s.get("env", {}) or {})
        for key in list(env.keys()):
            # Strip every value to be safe — the user will need to refill them
            # on the recipient machine anyway. Keep the keys so the importer
            # knows what placeholders to surface in the UI.
            if env[key]:
                if _looks_like_secret(key):
                    stripped.append(f"{s.get('name', '?')}::{key}")
                env[key] = ""
        s["env"] = env
        cleaned.append(s)
    return cleaned, stripped


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default




def _slugify(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe.strip("_") or "agent"


# ─────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────


def _gather_export_contents() -> Dict[str, Any]:
    """Pre-flight inventory used by manifest + README."""
    skills_config = _load_json(SKILLS_CONFIG_PATH, {"enabled_skills": []})
    enabled_skills = [
        s for s in skills_config.get("enabled_skills", []) if (SKILLS_DIR / s).is_dir()
    ]

    mcp_config = _load_json(MCP_CONFIG_PATH, {"mcp_servers": []})
    # Only export enabled MCP servers — the recipient already has the ~157
    # disabled defaults bundled with CraftBot, and shipping all of them would
    # leak machine-specific command paths.
    mcp_servers = [
        s for s in mcp_config.get("mcp_servers", []) if s.get("enabled", False)
    ]

    md_present = [f for f in PROFILE_MD_FILES if (AGENT_FILE_SYSTEM_PATH / f).is_file()]


    return {
        "agent_name": _agent_name(),
        "md_files": md_present,
        "skills": enabled_skills,
        "mcp_servers": [s.get("name", "") for s in mcp_servers],
        "agent_app_apps": [],
    }


def _build_manifest(contents: Dict[str, Any], description: str = "") -> Dict[str, Any]:
    return {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "name": contents["agent_name"],
        "description": description,
        "source_app_version": get_app_version(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contents": contents,
    }


def _build_readme(manifest: Dict[str, Any]) -> str:
    c = manifest["contents"]
    skills = "\n".join(f"- {s}" for s in c.get("skills", [])) or "_(none)_"
    mcps = "\n".join(f"- {s}" for s in c.get("mcp_servers", [])) or "_(none)_"
    apps = "\n".join(f"- {s}" for s in c.get("agent_app_apps", [])) or "_(none)_"
    mds = ", ".join(c.get("md_files", [])) or "_(none)_"
    return (
        f"# {manifest['name']} — CraftBot agent profile\n\n"
        f"{manifest['description'] or '_(no description)_'}\n\n"
        f"Bundle format: `{manifest['bundle_format_version']}`  "
        f"Source app: `{manifest['source_app_version']}`  "
        f"Created: `{manifest['created_at']}`\n\n"
        f"## Personality\n{mds}\n\n"
        f"## Skills\n{skills}\n\n"
        f"## MCP servers\n{mcps}\n\n"
        f"## Agent App apps\n{apps}\n\n"
        "API keys, OAuth secrets, personal memory, and conversation history\n"
        "are **not** included in this bundle.\n"
    )


def _write_meta(staging: Path, manifest: Dict[str, Any]) -> None:
    """Write top-level manifest.json + README.md."""
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (staging / "README.md").write_text(_build_readme(manifest), encoding="utf-8")


def _write_profile_dir(staging: Path, md_files: List[str]) -> None:
    """Copy personality MD files into profile/."""
    profile_dir = staging / "profile"
    profile_dir.mkdir()
    for fname in md_files:
        src = AGENT_FILE_SYSTEM_PATH / fname
        if src.is_file():
            shutil.copy2(src, profile_dir / fname)


def _write_skills_dir(staging: Path, skill_names: List[str]) -> None:
    """Copy each enabled skill folder and write the enabled-list manifest."""
    skills_dir = staging / "skills"
    skills_dir.mkdir()
    (skills_dir / "enabled.json").write_text(
        json.dumps({"enabled_skills": skill_names}, indent=2),
        encoding="utf-8",
    )
    for skill_name in skill_names:
        src = SKILLS_DIR / skill_name
        if src.is_dir():
            _copy_dir_filtered(src, skills_dir / skill_name)


def _write_mcp_dir(staging: Path) -> None:
    """Write mcp/servers.json with enabled servers only and secrets stripped."""
    mcp_dir = staging / "mcp"
    mcp_dir.mkdir()
    mcp_config = _load_json(MCP_CONFIG_PATH, {"mcp_servers": []})
    enabled_mcp = [
        s for s in mcp_config.get("mcp_servers", []) if s.get("enabled", False)
    ]
    cleaned_servers, _stripped = _strip_mcp_secrets(enabled_mcp)
    (mcp_dir / "servers.json").write_text(
        json.dumps({"mcp_servers": cleaned_servers}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )




def _zip_staging(staging: Path, agent_name: str) -> Path:
    """Zip the staging tree into a fresh temp file. Returns the .craftbot path."""
    slug = _slugify(agent_name).lower()
    ts = time.strftime("%Y%m%d")
    out_dir = Path(tempfile.mkdtemp(prefix="craftbot_profile_out_"))
    out_path = out_dir / f"craftbot-{slug}-{ts}.craftbot"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in staging.rglob("*"):
            if entry.is_file():
                zf.write(entry, entry.relative_to(staging))
    return out_path


def export_profile(description: str = "") -> Dict[str, Any]:
    """Build the bundle and return path + filename + summary for download.

    Caller is responsible for serving the file and (after the response is sent)
    deleting the temp file. Mirrors the Agent App export flow.
    """
    contents = _gather_export_contents()
    staging = Path(tempfile.mkdtemp(prefix="craftbot_profile_"))
    try:
        from app.agent_app.framework_profile import export_packages

        packages = asyncio.run(export_packages(staging))
        contents["framework_apps"] = [p["name"] for p in packages]
        contents["agent_app_apps"] = contents["framework_apps"]
        manifest = _build_manifest(contents, description=description)
        _write_meta(staging, manifest)
        _write_profile_dir(staging, contents["md_files"])
        _write_skills_dir(staging, contents["skills"])
        _write_mcp_dir(staging)
        out_path = _zip_staging(staging, contents["agent_name"])

        return {
            "success": True,
            "path": str(out_path),
            "filename": out_path.name,
            "summary": {
                "skills": len(contents["skills"]),
                "mcp_servers": len(contents["mcp_servers"]),
                "agent_app_apps": len(contents["agent_app_apps"]),
                "framework_apps": len(packages),
                "md_files": len(contents["md_files"]),
            },
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────
# Inspect (preview before import)
# ─────────────────────────────────────────────────────────────────────


def _open_bundle(bundle_path: Path) -> zipfile.ZipFile:
    if not bundle_path.exists():
        raise FileNotFoundError(f"Bundle not found: {bundle_path}")
    try:
        return zipfile.ZipFile(bundle_path, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid .craftbot bundle: {exc}") from exc


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract, refusing absolute paths or paths that escape `dest`."""
    dest = dest.resolve()
    for member in zf.infolist():
        # Refuse absolute or traversal paths — defends against zip-slip.
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError(f"Unsafe path in bundle: {member.filename}")
        out_path = (dest / name).resolve()
        try:
            out_path.relative_to(dest)
        except ValueError as exc:
            raise ValueError(f"Unsafe path in bundle: {member.filename}") from exc
    zf.extractall(dest)


def inspect_bundle(bundle_path: str) -> Dict[str, Any]:
    """Return the manifest + a preview of what will be applied on import."""
    path = Path(bundle_path)
    try:
        with _open_bundle(path) as zf:
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except KeyError:
                return {"success": False, "error": "Bundle is missing manifest.json"}
            except json.JSONDecodeError as exc:
                return {"success": False, "error": f"Invalid manifest.json: {exc}"}

            # Compute "already installed" hints so the UI can call them out.
            local_skills = (
                set(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())
                if SKILLS_DIR.exists()
                else set()
            )
            mcp_local = _load_json(MCP_CONFIG_PATH, {"mcp_servers": []}).get(
                "mcp_servers", []
            )
            local_mcp_names = {s.get("name", "") for s in mcp_local}

            # Detect MCP env vars the user will need to refill.
            try:
                mcp_servers_in_bundle = json.loads(
                    zf.read("mcp/servers.json").decode("utf-8")
                ).get("mcp_servers", [])
            except (KeyError, json.JSONDecodeError):
                mcp_servers_in_bundle = []
            mcp_needs_env: List[Dict[str, Any]] = []
            for server in mcp_servers_in_bundle:
                env = server.get("env") or {}
                missing = [k for k in env if not env.get(k)]
                if missing:
                    mcp_needs_env.append(
                        {"name": server.get("name", ""), "env_keys": missing}
                    )

            contents = manifest.get("contents", {})
            return {
                "success": True,
                "manifest": manifest,
                "preview": {
                    "skills_already_installed": sorted(
                        set(contents.get("skills", [])) & local_skills
                    ),
                    "mcp_already_installed": sorted(
                        set(contents.get("mcp_servers", [])) & local_mcp_names
                    ),
                    "mcp_needs_env": mcp_needs_env,
                },
            }
    except (ValueError, FileNotFoundError) as exc:
        return {"success": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────
# Import
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ImportSummary:
    skills_added: List[str]
    skills_skipped: List[str]
    skills_missing: List[str]
    # Skills whose folder is on disk but whose SKILL.md fails runtime
    # validation. Each entry: {name, reason, origin}. Folder is preserved on
    # disk — the importer NEVER deletes files for validation reasons.
    skills_invalid: List[Dict[str, str]]
    # CraftBot-essential skills (user-invocable: false in frontmatter) that
    # were force-enabled regardless of import mode. Typically overlaps with
    # skills_added when the bundle includes them (current build.py always
    # does).
    skills_system_enabled: List[str]
    mcp_added: List[str]
    mcp_skipped: List[str]
    mcp_needs_env: List[Dict[str, Any]]
    # MCP servers from the bundle whose config shape is invalid. Each entry:
    # {name, reason}. These never enter mcp_config.json.
    mcp_invalid: List[Dict[str, str]]
    md_applied: List[str]
    agent_app_added: List[str]
    agent_app_renamed: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _apply_md_files(src_profile: Path, mode: str) -> List[str]:
    """Write personality MD files from the bundle into the agent file system.

    Both ``replace`` and ``overwrite`` modes write the bundle's content verbatim
    over the local file. The only difference is what happens to MD files the
    bundle DIDN'T ship: in ``overwrite`` mode we reset them to their template
    (so the recipient's agent ends up strictly defined by the bundle); in
    ``replace`` mode we leave the user's existing file alone.
    """
    applied: List[str] = []
    AGENT_FILE_SYSTEM_PATH.mkdir(parents=True, exist_ok=True)
    for fname in PROFILE_MD_FILES:
        src = src_profile / fname
        target = AGENT_FILE_SYSTEM_PATH / fname
        try:
            if src.is_file():
                target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                applied.append(fname)
            elif mode == "overwrite":
                tmpl = AGENT_FILE_SYSTEM_TEMPLATE_PATH / fname
                if tmpl.is_file():
                    shutil.copy2(tmpl, target)
                    applied.append(fname)
        except OSError as exc:
            logger.error(f"[PROFILE_BUNDLE] Failed to apply {fname}: {exc}")
    return applied


def _is_system_skill_md(skill_md: Path) -> bool:
    """A SKILL.md belongs to the always-import set iff its YAML frontmatter
    declares ``user-invocable: false``. This is the same marker the runtime
    uses to identify system-spawned tasks ([browser_adapter.py]
    _INTERNAL_SKILL_NAMES). Auto-discovery via this marker means new system
    skills get the always-import treatment automatically — no hardcoded list
    to keep in sync.
    """
    import re as _re
    import yaml as _yaml

    if not skill_md.is_file():
        return False
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return False
    m = _re.match(r"^---\s*\n(.*?)\n---\s*\n", text, _re.DOTALL)
    if not m:
        return False
    try:
        data = _yaml.safe_load(m.group(1))
    except _yaml.YAMLError:
        return False
    return isinstance(data, dict) and data.get("user-invocable") is False


def _discover_system_skills_in(skills_dir: Path) -> List[str]:
    """Return names of folders under `skills_dir` whose SKILL.md is marked
    `user-invocable: false`. Used by the importer to identify which entries
    in the bundle (or already on disk) must be force-enabled regardless of
    import mode.
    """
    out: List[str] = []
    if not skills_dir.is_dir():
        return out
    for sk in skills_dir.iterdir():
        if sk.is_dir() and _is_system_skill_md(sk / "SKILL.md"):
            out.append(sk.name)
    return sorted(out)


def _apply_skills(
    src_skills_dir: Path, mode: str
) -> Tuple[List[str], List[str], List[str], List[Dict[str, str]], List[str]]:
    """Install skill folders from the bundle and update skills_config.json.

    Returns ``(added, skipped, missing, invalid, system_enabled)``.

    Bundle model (post-rebuild, no more "default" assumption):
      Every skill the agent uses ships physically inside the bundle's
      ``skills/`` folder. ``enabled.json`` lists exactly that set. One code
      path covers every skill — no two-bucket logic.

    Import modes:
      ``replace`` — bundle's skills are written into the recipient's skills
        dir, overwriting any folder of the same name. Skills the recipient
        had locally that the bundle doesn't ship are left untouched.
      ``overwrite`` — recipient's entire skills dir is wiped first, then the
        bundle's skills are installed. The recipient's skill set ends up
        exactly == bundle's.

    System skills (always-import):
      Skills with ``user-invocable: false`` in their SKILL.md frontmatter
      are CraftBot-essential. Build.py force-includes them in every bundle.
      The importer force-enables them in skills_config.json in every mode,
      so a profile import can never strip the agent of its core ability to
      spawn memory-processing / heartbeat / planner / Agent-App workflows.

    Buckets:
      ``added`` — folder copied from bundle, SKILL.md validates, name enabled.
      ``skipped`` — reserved/empty (preserved for API back-compat).
      ``missing`` — name in ``enabled.json`` but no folder shipped (bundle bug).
      ``invalid`` — folder copied but SKILL.md fails validation. The folder
        is LEFT ON DISK (never deleted) so the user can inspect/fix it. The
        name is NOT added to skills_config.json so the loader doesn't trip
        on it at runtime.
      ``system_enabled`` — system skills (user-invocable: false) that were
        force-enabled. Overlaps with ``added`` when the bundle includes them
        (the new build.py always does).
    """
    added: List[str] = []
    skipped: List[str] = []  # unused under the new model; kept for API shape
    missing: List[str] = []
    invalid: List[Dict[str, str]] = []
    enabled_list_path = src_skills_dir / "enabled.json"
    bundle_enabled = _load_json(enabled_list_path, {}).get("enabled_skills", [])

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    if mode == "overwrite":
        # Strict factory reset (this IS what the user picked when they chose
        # Overwrite mode). The validation-failure path below never deletes;
        # only the explicit Overwrite contract does.
        for child in list(SKILLS_DIR.iterdir()):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    for skill_name in bundle_enabled:
        src = src_skills_dir / skill_name
        dst = SKILLS_DIR / skill_name
        if not src.is_dir():
            # Bundle's enabled.json names a skill it didn't ship a folder
            # for. Under the new build.py this never happens; if it does it
            # means the bundle was built by an older toolchain. Skip cleanly.
            missing.append(skill_name)
            logger.warning(
                f"[PROFILE_BUNDLE] Bundle enabled.json names '{skill_name}' "
                f"but no folder was shipped — bundle is from an older build "
                f"toolchain. Skipping."
            )
            continue

        # Replace-on-collision is the documented behavior of both modes
        # (bundle's version wins for skills the bundle ships). This is NOT
        # the validation-failure path — that one never deletes.
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        _copy_dir_filtered(src, dst)

        # Validate AFTER copy. Failure → name is not enabled, but the folder
        # is left on disk untouched so the user can inspect/repair the file.
        copy_err = _validate_skill_md(dst / "SKILL.md")
        if copy_err:
            invalid.append({"name": skill_name, "reason": copy_err, "origin": "bundle"})
            logger.warning(
                f"[PROFILE_BUNDLE] Bundled skill '{skill_name}' fails "
                f"validation ({copy_err}); NOT enabling, folder left on "
                f"disk at {dst} for manual inspection."
            )
            continue
        added.append(skill_name)

    # Force-discover and force-enable system skills. We discover from the
    # RECIPIENT's skills dir (post-copy) so the always-import promise holds
    # for any system skill physically present — whether the bundle just
    # installed it, the recipient already had it, or it's been there since
    # initial CraftBot install. Mode is irrelevant: Overwrite wipes-then-
    # installs the bundle's copy; Replace adds it if the bundle had it.
    system_skills = _discover_system_skills_in(SKILLS_DIR)
    system_enabled: List[str] = list(system_skills)

    if mode == "overwrite":
        # Bundle's enabled list IS the skill state — but always union with
        # the system skills so they survive a "wipe and install bundle".
        config = {
            "auto_load": True,
            "enabled_skills": _dedup_preserve_order(added + system_enabled),
            "disabled_skills": [],
        }
    else:
        # Additive: enable everything the bundle installed + the system
        # skills; never disable anything the user already had. If a system
        # skill is currently in disabled_skills, un-disable it (always-on).
        config = _load_json(
            SKILLS_CONFIG_PATH,
            {"auto_load": True, "enabled_skills": [], "disabled_skills": []},
        )
        enabled_set = list(config.get("enabled_skills", []))
        disabled_set = list(config.get("disabled_skills", []))
        for skill_name in added + system_enabled:
            if skill_name not in enabled_set:
                enabled_set.append(skill_name)
            if skill_name in disabled_set:
                disabled_set.remove(skill_name)
        config["enabled_skills"] = _dedup_preserve_order(enabled_set)
        config["disabled_skills"] = disabled_set

    SKILLS_CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return added, skipped, missing, invalid, system_enabled


def _dedup_preserve_order(items: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _apply_mcp(
    src_mcp_dir: Path, mode: str
) -> Tuple[List[str], List[str], List[Dict[str, Any]], List[Dict[str, str]]]:
    """Install MCP server configs from the bundle.

    ``replace`` — bundle overwrites local on name collision (preserving any
    env tokens the user already filled in); new servers added.
    ``overwrite`` — local mcp_config.json is wiped and replaced entirely with
    the bundle's servers; no env values are preserved (the recipient's MCP
    state ends up exactly = bundle's).

    Each candidate entry is shape-validated BEFORE landing in the catalog —
    entries that would be rejected by the runtime (stdio without command,
    sse/http without url, unknown transport) go into the ``invalid`` bucket
    and never touch mcp_config.json. This guarantees a successful import
    means the runtime can actually load every named server.
    """
    added: List[str] = []
    skipped: List[str] = []
    needs_env: List[Dict[str, Any]] = []
    invalid: List[Dict[str, str]] = []

    servers_path = src_mcp_dir / "servers.json"
    bundle_servers = _load_json(servers_path, {}).get("mcp_servers", [])

    def _filter_valid(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        good: List[Dict[str, Any]] = []
        for s in servers:
            name = s.get("name", "")
            if not name:
                invalid.append({"name": "<unnamed>", "reason": "missing name"})
                continue
            err = _validate_mcp_entry(s)
            if err:
                invalid.append({"name": name, "reason": err})
                logger.warning(
                    f"[PROFILE_BUNDLE] MCP '{name}' fails shape validation "
                    f"({err}); not adding to catalog."
                )
                continue
            good.append(s)
        return good

    if mode == "overwrite":
        cleaned: List[Dict[str, Any]] = []
        for server in _filter_valid(bundle_servers):
            name = server["name"]
            missing_env = [k for k, v in (server.get("env") or {}).items() if not v]
            if missing_env:
                needs_env.append({"name": name, "env_keys": missing_env})
            cleaned.append(server)
            added.append(name)
        MCP_CONFIG_PATH.write_text(
            json.dumps({"mcp_servers": cleaned}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return added, skipped, needs_env, invalid

    # replace mode — additive with overwrite-on-conflict + env preservation
    current = _load_json(MCP_CONFIG_PATH, {"mcp_servers": []})
    existing = current.get("mcp_servers", [])
    by_name = {s.get("name", ""): s for s in existing}

    for server in _filter_valid(bundle_servers):
        name = server["name"]
        missing_env = [k for k, v in (server.get("env") or {}).items() if not v]
        if missing_env:
            needs_env.append({"name": name, "env_keys": missing_env})

        if name in by_name:
            # Keep ANY env values the user had set locally — don't blow
            # them away, since the user's filled-in tokens are more
            # valuable than the (empty) tokens from the bundle.
            preserved_env = by_name[name].get("env", {})
            merged_env = dict(server.get("env", {}))
            for k, v in preserved_env.items():
                if v and k in merged_env and not merged_env[k]:
                    merged_env[k] = v
            server["env"] = merged_env
            by_name[name] = server
            added.append(name)
        else:
            by_name[name] = server
            added.append(name)

    current["mcp_servers"] = list(by_name.values())
    MCP_CONFIG_PATH.write_text(
        json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return added, skipped, needs_env, invalid












VALID_IMPORT_MODES = ("replace", "overwrite")


def import_profile(
    bundle_path: str,
    mode: str = "replace",
) -> Dict[str, Any]:
    """Apply a bundle to the current agent.

    Args:
        bundle_path: filesystem path to the .craftbot file (already uploaded)
        mode:
            ``"replace"`` (default) — additive; bundle wins on name/id conflict
            for skills, MCP servers, and personality files; Agent App apps are
            always copied alongside under a rename. Surfaced in the UI as
            "Merge and Replace".

            ``"overwrite"`` — strict adoption; wipes the local skills folder,
            MCP config, and Agent App state, then installs the bundle's
            content as the entire agent identity. Destructive; the recipient's
            agent ends up = the bundle's.

    Returns:
        Dict with success flag and ImportSummary contents. The agent will need
        a manual restart for the changes to fully take effect; the caller
        surfaces that to the user.
    """
    if mode not in VALID_IMPORT_MODES:
        return {"success": False, "error": f"Unknown import mode: {mode}"}

    path = Path(bundle_path)
    if not path.exists():
        return {"success": False, "error": f"Bundle file not found: {bundle_path}"}

    work_dir = Path(tempfile.mkdtemp(prefix="craftbot_profile_import_"))
    try:
        with _open_bundle(path) as zf:
            _safe_extract(zf, work_dir)

        manifest_path = work_dir / "manifest.json"
        if not manifest_path.is_file():
            return {"success": False, "error": "Bundle is missing manifest.json"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bundle_version = manifest.get("bundle_format_version", "")
        if bundle_version.split(".")[0] != BUNDLE_FORMAT_VERSION.split(".")[0]:
            return {
                "success": False,
                "error": (
                    f"Bundle format {bundle_version} is not compatible with this "
                    f"app (expected {BUNDLE_FORMAT_VERSION}). Update CraftBot."
                ),
            }
        bundle_name = manifest.get("name") or "imported profile"

        from app.agent_app.framework_profile import stage_packages

        old_index = work_dir / "agent_app" / "projects.json"
        if old_index.exists():
            old_apps = json.loads(old_index.read_text(encoding="utf-8"))
            if isinstance(old_apps, dict):
                old_apps = old_apps.get("projects", [])
            if old_apps:
                raise ValueError("This profile contains legacy CraftBot apps. Import their source "
                                 "through Add Agent App to convert them with the framework first.")
        framework_packages = stage_packages(work_dir)

        md_applied = _apply_md_files(work_dir / "profile", mode)
        (
            skills_added,
            skills_skipped,
            skills_missing,
            skills_invalid,
            skills_system_enabled,
        ) = _apply_skills(work_dir / "skills", mode)
        mcp_added, mcp_skipped, mcp_needs_env, mcp_invalid = _apply_mcp(
            work_dir / "mcp", mode
        )


        # NOTE: agent_name is intentionally NOT applied — per product decision,
        # users keep their own agent name and just inherit the personality/skills.

        summary = ImportSummary(
            skills_added=skills_added,
            skills_skipped=skills_skipped,
            skills_missing=skills_missing,
            skills_invalid=skills_invalid,
            skills_system_enabled=skills_system_enabled,
            mcp_added=mcp_added,
            mcp_skipped=mcp_skipped,
            mcp_needs_env=mcp_needs_env,
            mcp_invalid=mcp_invalid,
            md_applied=md_applied,
            agent_app_added=[p["name"] for p in framework_packages],
            agent_app_renamed=[],
        )
        return {
            "success": True,
            "mode": mode,
            "bundle_name": bundle_name,
            "summary": summary.to_dict(),
            "restart_required": False,
            "framework_packages": framework_packages,
        }
    except (ValueError, json.JSONDecodeError) as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"[PROFILE_BUNDLE] Import failed: {exc}", exc_info=True)
        return {"success": False, "error": f"Import failed: {exc}"}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


__all__ = [
    "BUNDLE_FORMAT_VERSION",
    "export_profile",
    "inspect_bundle",
    "import_profile",
]
