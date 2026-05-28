"""CraftBot installer wizard — pywebview launcher.

The actual UI lives in installer/web/{index.html,style.css,app.js} so we
get real Win11 Fluent / macOS Aqua styling via the OS's native webview
(WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux). Python
exposes lifecycle methods as a JS-callable API — see installer/api.py.

Architecture:
  craftbot.py main()
    └─ launch_wizard()
         ├─ creates webview window pointed at installer/web/index.html
         ├─ exposes WizardAPI (install/start/stop/...) as window.pywebview.api
         └─ webview.start() blocks until the user closes the window
"""

from __future__ import annotations

import os
import sys

import craftbot
from installer.api import WizardAPI


def _web_dir() -> str:
    """Locate the bundled web/ assets — works in source mode and frozen mode.

    In source mode this returns <repo>/installer/web. In frozen mode the
    spec bundles `('installer', 'installer')` which extracts to
    sys._MEIPASS/installer/web — the same relative layout, so __file__
    works either way.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "web")


def launch_wizard() -> None:
    """Open the wizard window. Blocks until the user closes the window."""
    # Blank craftbot.py's ANSI colour-code constants so the strings it prints
    # to our captured stdout don't contain escape sequences.
    for _name in ("ORANGE", "WHITE", "BOLD", "DIM", "GREEN", "RED", "RESET"):
        if hasattr(craftbot, _name):
            setattr(craftbot, _name, "")

    # Lazy import — gives a clean error message if pywebview isn't installed
    # in source-mode dev builds, instead of crashing at module load.
    try:
        import webview
    except ImportError:
        sys.stderr.write(
            "\nERROR: pywebview is not installed.\n"
            "  Install it with: pip install pywebview\n"
            "  (On Linux you also need: sudo apt install libwebkit2gtk-4.0-37)\n\n"
        )
        sys.exit(1)

    api = WizardAPI()
    index_path = os.path.join(_web_dir(), "index.html")
    if not os.path.isfile(index_path):
        sys.stderr.write(f"\nERROR: wizard assets not found at {index_path}\n")
        sys.exit(1)

    # file:// URL — pywebview hands this to the OS webview directly. We use
    # forward slashes regardless of OS because that's what file:// expects.
    url = "file:///" + index_path.replace(os.sep, "/").lstrip("/")

    window = webview.create_window(
        title="CraftBot",
        url=url,
        js_api=api,
        width=760,
        height=620,
        min_size=(620, 520),
        background_color="#161620",
        # Native title bar — Win11 rounds it automatically; macOS gives us
        # traffic lights. Frameless mode is harder to get right cross-OS.
    )
    api.attach(window)
    webview.start(debug=False)


if __name__ == "__main__":
    launch_wizard()
