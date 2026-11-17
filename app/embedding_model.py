"""The memory embedder's model files, provisioned like any other runtime.

BAAI/bge-small-en-v1.5 as an ONNX graph plus its tokenizer, pinned to one
Hugging Face revision and SHA-256 in app/provision/embedding_model.json.
Fetched at INSTALL time (app.provision's embedding-model stage), so the first
start never waits on huggingface.co, and a network that cannot reach it fails
the install with a clear message instead of killing the backend at every boot.

Stdlib-only: used by the installer before dependencies exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

from app import downloads, paths

LogFn = Callable[[str], None]

PINS_PATH = Path(__file__).parent / "provision" / "embedding_model.json"


def pins() -> Dict:
    """The pinned model files, each validated (HTTPS, a full SHA-256)."""
    data = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    for name, item in data["files"].items():
        digest = item.get("sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Invalid embedding model checksum for {name}")
        if urlparse(item["url"]).scheme != "https":
            raise ValueError("Embedding model downloads must use HTTPS")
    return data


def model_dir() -> Path:
    return paths.RUNTIME_DIR / "models" / pins()["dir"]


def missing() -> List[str]:
    """Files that are absent or the wrong size (a cheap check; the SHA-256 is
    verified when a file is downloaded)."""
    out = []
    for name, item in pins()["files"].items():
        path = model_dir() / name
        if not path.is_file() or (
            item.get("size") and path.stat().st_size != int(item["size"])
        ):
            out.append(name)
    return out


def ensure(log: Optional[LogFn] = None, offline: bool = False) -> Path:
    """Download whatever is missing; returns the model directory.

    Raises with an actionable message when a file cannot be fetched.
    """
    say = log or (lambda _m: None)
    files = pins()["files"]
    gone = missing()
    if gone and offline:
        raise RuntimeError(
            "Offline: the memory embedding model is not downloaded yet "
            f"({', '.join(gone)}). Run the install again with a connection."
        )
    for name in gone:
        item = files[name]
        dest = model_dir() / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            downloads.download(
                item["url"],
                str(dest),
                log=say,
                label=f"embedding model {name}",
                expected_sha256=item["sha256"],
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not download the memory embedding model ({name}): {exc}. "
                "If huggingface.co is blocked on this network, set HF_ENDPOINT "
                "(for example https://hf-mirror.com) or CRAFTBOT_MIRRORS, then "
                "run `python craftbot.py install` again (or Repair in the installer)."
            ) from exc
    return model_dir()
