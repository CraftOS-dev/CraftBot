"""
File storage (SYSTEM-MANAGED — do not edit)

Upload/serve/list/delete files without writing any storage code:

    POST   /api/files            multipart upload (field name: "file")
    GET    /api/files            list files (metadata)
    GET    /api/files/{id}       download/serve the bytes
    DELETE /api/files/{id}       remove file + metadata

Frontend: use the <FileUpload>/<ImageInput> presets or
`uploadFile(file)` from services/data — never hand-roll multipart code.

Where the bytes live (metadata is always in the app database):
  1. FILES_DIR in backend/.env (absolute, or relative to the project)
  2. LIVING_UI_FILES_DIR from the environment — CraftBot points this at
     its workspace (living_ui_files/<project>), so uploaded files are
     directly visible to the agent's normal file tools
  3. <project>/uploads (standalone fallback)
"""

import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from system_models import StoredFile

router = APIRouter()

# Per-upload size cap in MB; override with MAX_UPLOAD_MB in backend/.env.
_DEFAULT_MAX_UPLOAD_MB = 50

_SAFE_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")


def _read_env(key: str) -> str:
    env_file = Path(__file__).parent / ".env"
    try:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, value = line.partition("=")
                if k.strip() == key:
                    return value.strip().strip("'\"")
    except OSError:
        pass
    return ""


def files_dir() -> Path:
    """Resolve the storage root (see module docstring for precedence)."""
    configured = _read_env("FILES_DIR")
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        return p
    injected = os.environ.get("LIVING_UI_FILES_DIR", "")
    if injected:
        return Path(injected)
    return Path(__file__).parent.parent / "uploads"


def _max_upload_bytes() -> int:
    raw = _read_env("MAX_UPLOAD_MB")
    try:
        mb = int(raw) if raw else _DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        mb = _DEFAULT_MAX_UPLOAD_MB
    return max(1, mb) * 1024 * 1024


@router.post("/files")
async def upload_file(
    file: UploadFile, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Store an uploaded file; returns its metadata (id, url, ...)."""
    original = Path(file.filename or "upload").name or "upload"
    ext = Path(original).suffix.lstrip(".")
    stored_name = uuid.uuid4().hex + (f".{ext}" if _SAFE_EXT_RE.match(ext) else "")

    root = files_dir()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / stored_name

    limit = _max_upload_bytes()
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {limit // (1024 * 1024)}MB upload limit",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except OSError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not store file: {e}")

    record = StoredFile(
        name=original,
        stored_name=stored_name,
        mime=file.content_type,
        size=size,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record.to_dict()


@router.get("/files")
def list_files(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """List stored files (metadata only, newest first)."""
    records = db.query(StoredFile).order_by(StoredFile.id.desc()).all()
    return [r.to_dict() for r in records]


@router.get("/files/{file_id}")
def serve_file(file_id: int, db: Session = Depends(get_db)):
    """Serve a stored file's bytes."""
    record = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")
    path = files_dir() / record.stored_name
    if not path.is_file():
        raise HTTPException(
            status_code=410, detail=f"File {file_id} is missing from storage"
        )
    return FileResponse(
        path, media_type=record.mime or "application/octet-stream", filename=record.name
    )


@router.delete("/files/{file_id}")
def delete_file(file_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Delete a stored file (bytes + metadata). Idempotent."""
    record = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    if not record:
        return {"status": "deleted", "deleted": 0}
    try:
        (files_dir() / record.stored_name).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(record)
    db.commit()
    return {"status": "deleted", "deleted": 1}
