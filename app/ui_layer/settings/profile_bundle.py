"""Agent Profile Bundle — export and import the current agent as a portable file.

A profile bundle is a zip-with-extension (`.craftbot`) containing the parts of
the agent that define its identity and capabilities — personality MD files, the
enabled skills (with their source folders), the MCP server configs, and the
Living UI app source. It deliberately does NOT include the user's API keys,
OAuth secrets, memory, conversation history, or personal data files.

Bundles are designed for one-click sharing: a recipient picks the bundle in
General Settings and chooses Replace or Merge. Agent name is shown in the
preview for context but is never applied on import.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from app.living_ui.manager import LivingUIManager

from app.config import (
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    AGENT_WORKSPACE_ROOT,
    APP_CONFIG_PATH,
    PROJECT_ROOT,
    get_app_version,
)
from app.logger import logger


BUNDLE_FORMAT_VERSION = "1.0"

# Agent identity MD files that travel in the bundle.
# USER.md, MEMORY.md, EVENT*.md, CONVERSATION_HISTORY.md, TASK_HISTORY.md are
# user-personal or runtime state and are intentionally excluded.
PROFILE_MD_FILES = ("SOUL.md", "AGENT.md", "PROACTIVE.md", "GLOBAL_LIVING_UI.md")

# Substrings in MCP env-var NAMES that indicate a secret value. The names are
# kept (so the importer knows what to fill in) but the VALUES are stripped.
SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "CREDENTIAL")

# Files/directories to skip when copying skill folders or Living UI projects.
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
LIVING_UI_PROJECTS_FILE = AGENT_WORKSPACE_ROOT / "living_ui_projects.json"
LIVING_UI_DIR = AGENT_WORKSPACE_ROOT / "living_ui"


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
                logger.warning(f"[PROFILE_BUNDLE] Skipping unreadable file {entry}: {exc}")


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


def _strip_mcp_secrets(servers: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
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


def _load_living_ui_projects(path: Path) -> List[Dict[str, Any]]:
    """Read a Living UI registry, tolerating both the {"projects":[...]} envelope
    used by the LivingUIManager and a bare list (legacy / hand-written)."""
    data = _load_json(path, {"projects": []})
    if isinstance(data, dict):
        return data.get("projects", []) or []
    if isinstance(data, list):
        return data
    return []


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
        s
        for s in skills_config.get("enabled_skills", [])
        if (SKILLS_DIR / s).is_dir()
    ]

    mcp_config = _load_json(MCP_CONFIG_PATH, {"mcp_servers": []})
    # Only export enabled MCP servers — the recipient already has the ~157
    # disabled defaults bundled with CraftBot, and shipping all of them would
    # leak machine-specific command paths.
    mcp_servers = [
        s for s in mcp_config.get("mcp_servers", []) if s.get("enabled", False)
    ]

    md_present = [
        f for f in PROFILE_MD_FILES if (AGENT_FILE_SYSTEM_PATH / f).is_file()
    ]

    living_ui_projects = _load_living_ui_projects(LIVING_UI_PROJECTS_FILE)

    return {
        "agent_name": _agent_name(),
        "md_files": md_present,
        "skills": enabled_skills,
        "mcp_servers": [s.get("name", "") for s in mcp_servers],
        "living_ui_apps": [p.get("name", p.get("id", "")) for p in living_ui_projects],
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
    apps = "\n".join(f"- {s}" for s in c.get("living_ui_apps", [])) or "_(none)_"
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
        f"## Living UI apps\n{apps}\n\n"
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


def _write_living_ui_dir(staging: Path) -> None:
    """Copy Living UI project source folders + the registry file."""
    living_dir = staging / "living_ui"
    living_dir.mkdir()
    projects = _load_living_ui_projects(LIVING_UI_PROJECTS_FILE)
    # Match the envelope the LivingUIManager uses on disk
    # ({"projects": [...]}). Writing a flat list would make the manager's
    # _load_projects() fail silently — and its next startup cleanup pass
    # would then delete every Living UI folder as "orphaned".
    (living_dir / "projects.json").write_text(
        json.dumps({"projects": projects}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    for project in projects:
        project_path_str = project.get("path", "")
        if not project_path_str:
            continue
        project_path = Path(project_path_str)
        if not project_path.is_absolute():
            project_path = PROJECT_ROOT / project_path
        if not project_path.is_dir():
            continue
        _copy_dir_filtered(project_path, living_dir / project_path.name)


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
    deleting the temp file. Mirrors the Living UI export flow.
    """
    contents = _gather_export_contents()
    manifest = _build_manifest(contents, description=description)

    staging = Path(tempfile.mkdtemp(prefix="craftbot_profile_"))
    try:
        _write_meta(staging, manifest)
        _write_profile_dir(staging, contents["md_files"])
        _write_skills_dir(staging, contents["skills"])
        _write_mcp_dir(staging)
        _write_living_ui_dir(staging)
        out_path = _zip_staging(staging, contents["agent_name"])

        return {
            "success": True,
            "path": str(out_path),
            "filename": out_path.name,
            "summary": {
                "skills": len(contents["skills"]),
                "mcp_servers": len(contents["mcp_servers"]),
                "living_ui_apps": len(contents["living_ui_apps"]),
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
                    mcp_needs_env.append({"name": server.get("name", ""), "env_keys": missing})

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
    mcp_added: List[str]
    mcp_skipped: List[str]
    mcp_needs_env: List[Dict[str, Any]]
    md_applied: List[str]
    living_ui_added: List[str]
    living_ui_renamed: List[str]

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


def _apply_skills(
    src_skills_dir: Path, mode: str
) -> Tuple[List[str], List[str], List[str]]:
    """Install skill folders and update skills_config.json.

    ``replace`` — bundle overwrites local on name collision; new skills added.
    ``overwrite`` — every existing skill folder under SKILLS_DIR is deleted,
    then the bundle's skills are installed and become the entire skill set
    (no disabled defaults left over).

    Bundles produced by agent_bundle/build.py list every skill the agent uses
    in ``enabled.json`` but only ship folders for the "bundled" ones — the
    "default" skills are assumed to already exist on the recipient's install.
    We split bundle_enabled into three buckets accordingly:

    - ``added``: bundle shipped a folder; copied to disk and enabled.
    - ``already_present``: no folder in bundle, but recipient already has it
      locally; enabled (replace mode only — overwrite mode wipes local first
      so this bucket is always empty there).
    - ``missing``: bundle expected the recipient to already have it but they
      don't; NOT enabled (would leave a ghost entry pointing at no folder).
    """
    added: List[str] = []
    already_present: List[str] = []
    missing: List[str] = []
    enabled_list_path = src_skills_dir / "enabled.json"
    bundle_enabled = _load_json(enabled_list_path, {}).get("enabled_skills", [])

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    if mode == "overwrite":
        # Strict factory reset: wipe every skill folder, then install the
        # bundle's. The recipient's skill set ends up exactly = bundle's.
        for child in list(SKILLS_DIR.iterdir()):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    for skill_name in bundle_enabled:
        src = src_skills_dir / skill_name
        dst = SKILLS_DIR / skill_name
        if not src.is_dir():
            # Bundle didn't include a folder for this one — it's a "default"
            # skill the recipient is expected to have. Keep it enabled only if
            # the folder actually exists locally; otherwise drop it so the
            # enabled list never contains ghost entries.
            if dst.is_dir():
                already_present.append(skill_name)
            else:
                missing.append(skill_name)
                logger.warning(
                    f"[PROFILE_BUNDLE] Bundle expected default skill "
                    f"'{skill_name}' but no folder exists locally; skipping."
                )
            continue
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        _copy_dir_filtered(src, dst)
        added.append(skill_name)

    installed_now = added + already_present

    if mode == "overwrite":
        # Authoritative config: bundle's enabled list IS the skill state, but
        # filtered to entries that physically exist on disk after the copy.
        config = {
            "auto_load": True,
            "enabled_skills": installed_now,
            "disabled_skills": [],
        }
    else:
        # Additive: enable everything the bundle wanted that we can back with
        # a real folder, but never disable anything the user already had.
        config = _load_json(
            SKILLS_CONFIG_PATH,
            {"auto_load": True, "enabled_skills": [], "disabled_skills": []},
        )
        enabled_set = list(config.get("enabled_skills", []))
        disabled_set = list(config.get("disabled_skills", []))
        for skill_name in installed_now:
            if skill_name not in enabled_set:
                enabled_set.append(skill_name)
            if skill_name in disabled_set:
                disabled_set.remove(skill_name)
        config["enabled_skills"] = enabled_set
        config["disabled_skills"] = disabled_set

    SKILLS_CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return added, already_present, missing


def _apply_mcp(
    src_mcp_dir: Path, mode: str
) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
    """Install MCP server configs from the bundle.

    ``replace`` — bundle overwrites local on name collision (preserving any
    env tokens the user already filled in); new servers added.
    ``overwrite`` — local mcp_config.json is wiped and replaced entirely with
    the bundle's servers; no env values are preserved (the recipient's MCP
    state ends up exactly = bundle's).
    """
    added: List[str] = []
    skipped: List[str] = []
    needs_env: List[Dict[str, Any]] = []

    servers_path = src_mcp_dir / "servers.json"
    bundle_servers = _load_json(servers_path, {}).get("mcp_servers", [])

    if mode == "overwrite":
        cleaned: List[Dict[str, Any]] = []
        for server in bundle_servers:
            name = server.get("name", "")
            if not name:
                continue
            missing_env = [k for k, v in (server.get("env") or {}).items() if not v]
            if missing_env:
                needs_env.append({"name": name, "env_keys": missing_env})
            cleaned.append(server)
            added.append(name)
        MCP_CONFIG_PATH.write_text(
            json.dumps({"mcp_servers": cleaned}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return added, skipped, needs_env

    # replace mode — additive with overwrite-on-conflict + env preservation
    current = _load_json(MCP_CONFIG_PATH, {"mcp_servers": []})
    existing = current.get("mcp_servers", [])
    by_name = {s.get("name", ""): s for s in existing}

    for server in bundle_servers:
        name = server.get("name", "")
        if not name:
            continue
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
    return added, skipped, needs_env


def _plan_and_copy_living_ui_imports(
    src_living_dir: Path,
    bundle_projects: List[Dict[str, Any]],
    target_living_dir: Path,
    current_ids: set,
    current_folders: set,
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """Walk the bundle's projects, copy each folder into ``target_living_dir``
    (renaming on id/folder conflict), and return the new registry records.

    Returns ``(new_records, added_names, renamed_names)``. ``current_ids`` /
    ``current_folders`` are mutated as new entries land so per-loop conflict
    checks see them.
    """
    new_records: List[Dict[str, Any]] = []
    added: List[str] = []
    renamed: List[str] = []

    for project in bundle_projects:
        project_path_str = project.get("path", "")
        if not project_path_str:
            continue
        original_folder = Path(project_path_str).name
        src_folder = src_living_dir / original_folder
        if not src_folder.is_dir():
            continue

        new_project = dict(project)
        folder_name = original_folder
        if project.get("id") in current_ids or folder_name in current_folders:
            new_id = uuid.uuid4().hex[:8]
            base_name = project.get("name", "imported")
            new_project["id"] = new_id
            new_project["name"] = f"{base_name} (imported)"
            sanitized = _slugify(base_name).lower()
            folder_name = f"{sanitized}_{new_id}"
            new_project["path"] = str(target_living_dir / folder_name)
            renamed.append(new_project["name"])
        else:
            new_project["path"] = str(target_living_dir / folder_name)
            added.append(project.get("name", original_folder))

        # Reset transient runtime fields so the imported project starts clean.
        new_project["status"] = "stopped"
        new_project.pop("pid", None)
        new_project.pop("backendPid", None)

        _copy_dir_filtered(src_folder, target_living_dir / folder_name)
        new_records.append(new_project)
        current_ids.add(new_project["id"])
        current_folders.add(folder_name)

    return new_records, added, renamed


def _register_living_ui_via_manager(
    records: List[Dict[str, Any]],
    manager: "LivingUIManager",
) -> None:
    """Insert imported projects into the live manager and persist via its own
    save path so they survive subsequent in-memory-driven flushes.

    Without this, ``_apply_living_ui`` would write the registry file directly
    but the still-running ``LivingUIManager`` would hold a stale in-memory
    state; any later ``_save_projects()`` (status update, watchdog tick, port
    change, etc.) would flush that stale state back and silently erase every
    imported entry.
    """
    # Local import keeps the module's top-level surface light + dodges any
    # circular-import risk between the settings and living_ui packages.
    from app.living_ui.manager import LivingUIProject

    for record in records:
        try:
            created_at_ms = record.get("createdAt")
            if not isinstance(created_at_ms, (int, float)):
                created_at_ms = datetime.now().timestamp() * 1000
            project_obj = LivingUIProject(
                id=record["id"],
                name=record["name"],
                description=record.get("description", ""),
                path=record["path"],
                status="stopped",
                port=record.get("port"),
                backend_port=record.get("backendPort"),
                created_at=created_at_ms / 1000,
                features=record.get("features", []) or [],
                theme=record.get("theme", "system") or "system",
                auto_launch=bool(record.get("autoLaunch", False)),
                log_cleanup=bool(record.get("logCleanup", True)),
                project_type=record.get("projectType", "native") or "native",
                app_runtime=record.get("appRuntime"),
            )
        except Exception as exc:
            logger.warning(
                f"[PROFILE_BUNDLE] Skipping malformed imported project "
                f"{record.get('id', '?')}: {exc}"
            )
            continue
        manager.projects[project_obj.id] = project_obj
        if project_obj.port:
            manager._used_ports.add(project_obj.port)
        if project_obj.backend_port:
            manager._used_ports.add(project_obj.backend_port)
    manager._save_projects()


def _register_living_ui_via_file(records: List[Dict[str, Any]]) -> None:
    """Fallback persistence — append records to the on-disk registry file.

    Race-prone when an agent is running (see _register_living_ui_via_manager
    for why), so reserved for inspection / non-running callers.
    """
    current_records = _load_living_ui_projects(LIVING_UI_PROJECTS_FILE)
    current_records.extend(records)
    LIVING_UI_PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIVING_UI_PROJECTS_FILE.write_text(
        json.dumps({"projects": current_records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _wipe_living_ui_state(
    manager: Optional["LivingUIManager"],
    target_living_dir: Path,
) -> None:
    """Delete every existing Living UI folder + clear the registry.

    Used by overwrite mode so the bundle's projects are the only ones present.
    When a manager is provided, both its in-memory state and the registry file
    are cleared (via _save_projects). With no manager, the registry file is
    truncated to ``{"projects": []}`` directly.

    Best-effort on the folders: one held open by a running process may fail to
    delete on Windows; the on-startup orphan cleanup will sweep it later.
    """
    if manager is not None:
        manager.projects.clear()
        manager._used_ports.clear()
        manager._save_projects()
    else:
        LIVING_UI_PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVING_UI_PROJECTS_FILE.write_text(
            json.dumps({"projects": []}, indent=2), encoding="utf-8"
        )
    if target_living_dir.exists():
        for child in list(target_living_dir.iterdir()):
            if child.is_dir():
                try:
                    shutil.rmtree(child)
                except OSError as exc:
                    logger.warning(
                        f"[PROFILE_BUNDLE] Failed to delete {child.name}: {exc}"
                    )


def _apply_living_ui(
    src_living_dir: Path,
    mode: str,
    manager: Optional["LivingUIManager"] = None,
) -> Tuple[List[str], List[str]]:
    """Copy Living UI projects into the workspace and register them.

    ``replace`` — renames on folder/id conflict so existing user data is never
    destroyed; new projects added alongside.
    ``overwrite`` — every existing Living UI project (folders + registry) is
    deleted first, then the bundle's projects are installed under their
    original ids/folder names.

    When ``manager`` is provided, persistence goes through the live
    ``LivingUIManager`` (required from a running agent); otherwise it falls
    back to a direct file write.
    """
    bundle_projects = _load_living_ui_projects(src_living_dir / "projects.json")
    target_living_dir = (
        manager.living_ui_dir if manager is not None else LIVING_UI_DIR
    )
    target_living_dir.mkdir(parents=True, exist_ok=True)

    if mode == "overwrite":
        _wipe_living_ui_state(manager, target_living_dir)
        # Empty starting set, so no conflict-rename happens.
        current_ids: set = set()
        current_folders: set = set()
    elif manager is not None:
        current_ids = set(manager.projects.keys())
        current_folders = {
            Path(p.path).name for p in manager.projects.values() if p.path
        }
    else:
        current = _load_living_ui_projects(LIVING_UI_PROJECTS_FILE)
        current_ids = {p.get("id") for p in current}
        current_folders = {
            Path(p.get("path", "")).name for p in current if p.get("path")
        }

    if not bundle_projects:
        # In overwrite mode the empty state was already persisted in
        # _wipe_living_ui_state(); nothing more to do.
        return [], []

    new_records, added, renamed = _plan_and_copy_living_ui_imports(
        src_living_dir,
        bundle_projects,
        target_living_dir,
        current_ids,
        current_folders,
    )

    if not new_records:
        return added, renamed

    if manager is not None:
        _register_living_ui_via_manager(new_records, manager)
    else:
        _register_living_ui_via_file(new_records)

    return added, renamed


VALID_IMPORT_MODES = ("replace", "overwrite")


def import_profile(
    bundle_path: str,
    mode: str = "replace",
    living_ui_manager: Optional["LivingUIManager"] = None,
) -> Dict[str, Any]:
    """Apply a bundle to the current agent.

    Args:
        bundle_path: filesystem path to the .craftbot file (already uploaded)
        mode:
            ``"replace"`` (default) — additive; bundle wins on name/id conflict
            for skills, MCP servers, and personality files; Living UI apps are
            always copied alongside under a rename. Surfaced in the UI as
            "Merge and Replace".

            ``"overwrite"`` — strict adoption; wipes the local skills folder,
            MCP config, and Living UI state, then installs the bundle's
            content as the entire agent identity. Destructive; the recipient's
            agent ends up = the bundle's.
        living_ui_manager: live LivingUIManager from the adapter. Required for
            Living UI projects to survive — see _apply_living_ui() for why.

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

        md_applied = _apply_md_files(work_dir / "profile", mode)
        skills_added, skills_already_present, skills_missing = _apply_skills(
            work_dir / "skills", mode
        )
        mcp_added, mcp_skipped, mcp_needs_env = _apply_mcp(work_dir / "mcp", mode)
        living_added, living_renamed = _apply_living_ui(
            work_dir / "living_ui", mode, manager=living_ui_manager
        )

        # NOTE: agent_name is intentionally NOT applied — per product decision,
        # users keep their own agent name and just inherit the personality/skills.

        summary = ImportSummary(
            skills_added=skills_added,
            skills_skipped=skills_already_present,
            skills_missing=skills_missing,
            mcp_added=mcp_added,
            mcp_skipped=mcp_skipped,
            mcp_needs_env=mcp_needs_env,
            md_applied=md_applied,
            living_ui_added=living_added,
            living_ui_renamed=living_renamed,
        )
        return {
            "success": True,
            "mode": mode,
            "bundle_name": bundle_name,
            "summary": summary.to_dict(),
            "restart_required": False,
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
