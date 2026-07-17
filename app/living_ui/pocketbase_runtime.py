# -*- coding: utf-8 -*-
"""PocketBase as the Living UI backend — "shadcn for the data layer".

PocketBase (MIT, single Go binary, embedded SQLite) replaces the
platform-maintained declared engine (schema.json → SQLAlchemy+FastAPI
CRUD): the agent declares collections in PB's native
JSON format and PocketBase itself provides CRUD/filters/pagination,
auth, file storage, realtime subscriptions, and an admin UI. Custom
logic is JavaScript in pb_hooks/ (routerAdd). One idiom everywhere —
fields keep the exact names the agent declares (the camelCase/snake_case
boundary no longer exists).

This module owns the PB lifecycle pieces the manager drives:

- ensure_binary(): version-pinned download to ~/.craftbot/bin (once per
  machine, like the shadcn component install — network on first use,
  fail-loud with the URL).
- serve_command(): the platform-owned serve invocation.
- bootstrap_superuser(): local-only superuser via CLI (idempotent).
- import_collections(): agent's config/schema.json → PUT
  /api/collections/import (authenticated).

The superuser credentials are LOCAL-ONLY (127.0.0.1 apps on the user's
machine); they exist so the platform can import schemas and reset data.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

POCKETBASE_VERSION = "0.39.6"
_DOWNLOAD_URL = (
    "https://github.com/pocketbase/pocketbase/releases/download/"
    "v{ver}/pocketbase_{ver}_{osname}_{arch}.zip"
)

SUPERUSER_EMAIL = "admin@craftbot.local"
SUPERUSER_PASSWORD = "craftbot-local-admin"

# Platform-owned binaries/launchers live OUTSIDE the agent-writable
# workspace so no workspace reset/cleanup can ever delete them (the
# livingui CLI launchers install here too — see browser_adapter).
PLATFORM_BIN_DIR = Path.home() / ".craftbot" / "bin"
_BIN_DIR = PLATFORM_BIN_DIR


def _asset_platform() -> tuple:
    osname = {"darwin": "darwin", "linux": "linux", "windows": "windows"}[
        platform.system().lower()
    ]
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    return osname, arch


def binary_path() -> Path:
    exe = ".exe" if os.name == "nt" else ""
    return _BIN_DIR / f"pocketbase-{POCKETBASE_VERSION}{exe}"


def ensure_binary() -> Path:
    """Return the pinned PocketBase binary, downloading it once if absent.

    Raises RuntimeError with the download URL on failure — backend setup
    cannot proceed without it, and the error must say why."""
    target = binary_path()
    if target.is_file():
        return target
    osname, arch = _asset_platform()
    url = _DOWNLOAD_URL.format(ver=POCKETBASE_VERSION, osname=osname, arch=arch)
    logger.info(f"[LIVING_UI:PB] downloading PocketBase {POCKETBASE_VERSION} ({url})")
    _BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = _BIN_DIR / f".pb-{POCKETBASE_VERSION}.zip"
    try:
        urllib.request.urlretrieve(url, tmp_zip)  # nosec - pinned release URL
        with zipfile.ZipFile(tmp_zip) as zf:
            member = "pocketbase.exe" if os.name == "nt" else "pocketbase"
            zf.extract(member, _BIN_DIR)
        extracted = _BIN_DIR / ("pocketbase.exe" if os.name == "nt" else "pocketbase")
        shutil.move(str(extracted), str(target))
        target.chmod(0o755)
        return target
    except Exception as e:
        raise RuntimeError(
            f"PocketBase download failed ({e}). The Living UI backend needs "
            f"the PocketBase binary; fetch it manually from {url} and place "
            f"it at {target}."
        ) from e
    finally:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            pass


def serve_command(project_path: Path, port: int) -> str:
    """Shell command that serves this project's backend (run via the
    manager's _start_process for unified logging)."""
    binary = ensure_binary()
    pb_data = Path(project_path) / "pb_data"
    pb_hooks = Path(project_path) / "pb_hooks"
    pb_data.mkdir(parents=True, exist_ok=True)
    pb_hooks.mkdir(parents=True, exist_ok=True)
    return (
        f'"{binary}" serve --http=127.0.0.1:{port} '
        f'--dir="{pb_data}" --hooksDir="{pb_hooks}"'
    )


def bootstrap_superuser(project_path: Path) -> bool:
    """Create/refresh the local superuser (idempotent, offline CLI)."""
    try:
        binary = ensure_binary()
        pb_data = Path(project_path) / "pb_data"
        pb_data.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                str(binary),
                "superuser",
                "upsert",
                SUPERUSER_EMAIL,
                SUPERUSER_PASSWORD,
                f"--dir={pb_data}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            logger.warning(
                f"[LIVING_UI:PB] superuser upsert failed: {proc.stderr[-300:]}"
            )
            return False
        return True
    except Exception as e:
        logger.warning(f"[LIVING_UI:PB] superuser bootstrap failed: {e}")
        return False


def _request(
    method: str, url: str, body: Optional[dict] = None, token: Optional[str] = None
) -> Dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", token)
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec - localhost
        text = resp.read().decode("utf-8", errors="replace")
        return json.loads(text) if text.strip() else {}


def auth_token(port: int) -> str:
    """Superuser auth token for admin API calls (raises on failure).

    Retries with backoff: right after first boot PB may still be applying
    migrations for a CLI-upserted superuser, briefly answering 400."""
    last: Exception = RuntimeError("unreachable")
    for delay in (0.0, 0.7, 1.5, 3.0):
        if delay:
            time.sleep(delay)
        try:
            out = _request(
                "POST",
                f"http://127.0.0.1:{port}/api/collections/_superusers/auth-with-password",
                {"identity": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD},
            )
            return str(out["token"])
        except Exception as e:
            last = e
    raise last


def normalize_legacy_options(collections: List[Dict[str, Any]]) -> None:
    """Hoist the legacy ``"options": {...}`` field wrapper in place.

    PB ≤0.22 nested field config under ``options`` ({"type": "select",
    "options": {"values": [...]}}); PB 0.23+ wants those keys flat on the
    field. Models keep producing the old shape from training data, and the
    flat-format import then fails with 'values cannot be blank' — an error
    the agent cannot reconcile with the values it can SEE in its file
    (session 20260717122556: 19 identical rejections, dummy fields added
    in desperation). Same philosophy as _resolve_relations: the agent's
    idiom is unambiguous, so the platform makes it valid. Explicit flat
    keys win over hoisted ones."""
    for col in collections or []:
        if not isinstance(col, dict):
            continue
        for field in col.get("fields", []):
            if not isinstance(field, dict):
                continue
            options = field.get("options")
            if isinstance(options, dict):
                for k, v in options.items():
                    field.setdefault(k, v)
                del field["options"]


def load_schema(project_path: Path) -> List[Dict[str, Any]]:
    """The agent's collections declaration (PB native format, with the
    legacy ``options`` wrapper tolerated — see normalize_legacy_options).
    Accepts either a bare list or {"collections": [...]}."""
    raw = json.loads(
        (Path(project_path) / "config" / "schema.json").read_text(encoding="utf-8")
    )
    collections = raw["collections"] if isinstance(raw, dict) else raw
    normalize_legacy_options(collections)
    return collections


# Field keys the agent may use to name a relation target (all resolved to
# PB's required `collectionId`).
_RELATION_TARGET_KEYS = ("collectionName", "collection", "collectionRef")


def _deterministic_id(name: str) -> str:
    """A stable 15-char PB collection id derived from the collection name.

    PB's import references relations by collectionId, and PB auto-generates
    those ids — unknowable to the agent at authoring time. Deriving them
    from the name makes them (a) knowable so we can wire relations, and
    (b) STABLE across re-imports (idempotent updates instead of dupes)."""
    import hashlib

    return "pbc_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:11]


def _resolve_relations(
    collections: List[Dict[str, Any]], existing: Dict[str, str]
) -> Optional[str]:
    """Rewrite the agent's relation-by-NAME idiom into PB's required
    relation-by-collectionId, in place. `existing` maps already-created
    collection names → their live PB ids (for system refs like `users`).

    Returns an error string if a relation points at an unknown collection,
    else None. THE platform fix for Round-20's schema-import loop: the
    agent declares `{"type": "relation", "collectionName": "cards"}` (PB's
    import rejects that — collectionId cannot be blank); we make it valid.
    """
    # Assign every declared collection a stable id (reusing its live PB id
    # when it already exists), then build the full name → id map.
    name_to_id: Dict[str, str] = dict(existing)
    for col in collections:
        if not isinstance(col, dict) or not col.get("name"):
            continue
        cid = (
            col.get("id") or existing.get(col["name"]) or _deterministic_id(col["name"])
        )
        col["id"] = cid
        name_to_id[col["name"]] = cid

    for col in collections:
        if not isinstance(col, dict):
            continue
        for field in col.get("fields", []):
            if not isinstance(field, dict) or field.get("type") != "relation":
                continue
            if field.get("collectionId"):
                continue  # already wired
            target = None
            for key in _RELATION_TARGET_KEYS:
                if field.get(key):
                    target = field.pop(key)
                    break
            # strip any leftover alias keys so PB sees only collectionId
            for key in _RELATION_TARGET_KEYS:
                field.pop(key, None)
            if not target:
                return (
                    f"relation field '{field.get('name')}' in collection "
                    f"'{col.get('name')}' must name its target collection "
                    '(add "collectionName": "<name>")'
                )
            if target not in name_to_id:
                return (
                    f"relation field '{field.get('name')}' in collection "
                    f"'{col.get('name')}' references unknown collection "
                    f"'{target}' — declare it in config/schema.json"
                )
            field["collectionId"] = name_to_id[target]
            field.setdefault("maxSelect", 1)
    return None


def import_collections(project_path: Path, port: int) -> Optional[str]:
    """Import config/schema.json into the running PB. Returns an error
    string (None = success). deleteMissing=False so PB system collections
    and previously-imported ones survive partial declarations."""
    try:
        collections = load_schema(project_path)
    except FileNotFoundError:
        return None  # no schema yet — nothing to import
    except Exception as e:
        return f"config/schema.json is not valid PocketBase collections JSON: {e}"
    if not collections:
        return None
    # PB v0.23+ makes created/updated OPT-IN autodate fields. The platform
    # guarantees them on every collection (like the old engine's automatic
    # timestamps) so `sort: '-created'` and the generated types always work.
    for col in collections:
        if not isinstance(col, dict):
            continue
        fields = col.setdefault("fields", [])
        names = {f.get("name") for f in fields if isinstance(f, dict)}
        if "created" not in names:
            fields.append({"name": "created", "type": "autodate", "onCreate": True})
        if "updated" not in names:
            fields.append(
                {
                    "name": "updated",
                    "type": "autodate",
                    "onCreate": True,
                    "onUpdate": True,
                }
            )
        # Force PUBLIC access rules where UNSET. PB defaults a missing rule
        # to null = superuser-only, which 403s every unauthenticated SDK
        # call from the frontend. These are local single-user apps — public
        # is correct, and the agent shouldn't have to remember 5 rule fields
        # per collection. An EXPLICIT rule (e.g. an auth-gated app setting
        # `@request.auth.id != ""`) is respected: only None/missing → "".
        for rule in ("listRule", "viewRule", "createRule", "updateRule", "deleteRule"):
            if col.get(rule) is None:
                col[rule] = ""
    try:
        token = auth_token(port)
        # Wire relations by collectionId (PB's import contract) from the
        # agent's collectionName idiom, reusing live ids for existing
        # collections so re-imports stay idempotent.
        existing: Dict[str, str] = {}
        try:
            listing = _request(
                "GET",
                f"http://127.0.0.1:{port}/api/collections?perPage=500",
                token=token,
            )
            for c in listing.get("items", []):
                if c.get("name") and c.get("id"):
                    existing[c["name"]] = c["id"]
        except Exception:
            pass  # fresh instance — deterministic ids cover it
        rel_err = _resolve_relations(collections, existing)
        if rel_err:
            return rel_err
        _request(
            "PUT",
            f"http://127.0.0.1:{port}/api/collections/import",
            {"collections": collections, "deleteMissing": False},
            token=token,
        )
        return None
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        detail = e.read().decode("utf-8", errors="replace")[:600]
        return (
            f"PocketBase rejected the collections import: {detail}"
            f"{_index_legend(detail, collections)}"
        )
    except Exception as e:
        return f"PocketBase collections import failed: {e}"


def _index_legend(detail: str, collections: List[Dict[str, Any]]) -> str:
    """PB reports field errors by numeric PAYLOAD INDEX ('fields "4":
    values cannot be blank') — a riddle that sent agents adding dummy
    fields at position 4 instead of fixing the real one (session
    20260717122556). Echo the failing collection's fields AS SENT, indexed,
    so the error names its culprit. Best effort; empty string on any
    surprise."""
    try:
        import re

        names = re.findall(r'failed for collection \\?"(\w+)\\?"', detail)
        legend = []
        for col in collections or []:
            if isinstance(col, dict) and col.get("name") in names:
                fields = ", ".join(
                    f"{i}={f.get('name', '?')}"
                    for i, f in enumerate(col.get("fields", []))
                    if isinstance(f, dict)
                )
                legend.append(f"{col['name']} fields as sent: {fields}")
        if not legend:
            return ""
        return (
            "\n(field numbers refer to these positions — fix the NAMED "
            "field, never add fields to change positions: "
            + "; ".join(legend)
            + ")"
        )
    except Exception:
        return ""
