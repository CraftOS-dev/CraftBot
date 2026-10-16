"""Entrypoint copied into the administrator-protected install, never a checkout."""

import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
# -I -S already excluded environment, cwd, user site and .pth execution.
sys.path[:0] = [
    str(root),
    str(root / "deps"),
    str(root / "deps" / "win32"),
    str(root / "deps" / "win32" / "lib"),
    str(root / "deps" / "pywin32_system32"),
]
_dlls = [os.add_dll_directory(str(root / "deps" / "pywin32_system32"))]
from app.credentials.host_service import main  # noqa: E402 -- protected import roots first

main(root)
