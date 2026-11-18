"""The small window the desktop icon shows while CraftBot starts.

The icon runs `craftbot.py open` without a console (pythonw on Windows, a
.desktop entry on Linux), so a start that takes a minute would otherwise be
a minute of nothing. This shows what is happening, and when the start fails,
why and where the log is, instead of a browser tab that never loads.

Stdlib only. Without a usable Tk (some minimal Linux installs) the work runs
anyway and only the window is missing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Tuple

#: work(status) -> (ok, failure detail). status(text) updates the message.
Work = Callable[[Callable[[str], None]], Tuple[bool, Optional[str]]]


def run_with_window(work: Work, log_file: Optional[str] = None) -> bool:
    """Run `work` while a small status window is shown; True when it succeeded.

    The window closes by itself on success. On failure it stays open with the
    reason, an "Open log" button and a "Close" button.
    """
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
    except Exception:
        ok, _detail = work(lambda _text: None)
        return ok

    root.title("CraftBot")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=(20, 16, 20, 16))
    frame.grid(sticky="nsew")
    message = tk.StringVar(value="Opening CraftBot...")
    elapsed = tk.StringVar(value="")
    ttk.Label(frame, textvariable=message, wraplength=380, justify="left").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(
        frame,
        textvariable=elapsed,
        foreground="#666666",
        wraplength=480,
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(6, 0))
    buttons = ttk.Frame(frame)
    buttons.grid(row=3, column=0, sticky="e", pady=(12, 0))

    _center(root, 420, 120)

    result: dict = {}
    started = time.monotonic()

    def status(text: str) -> None:
        # Called from the worker thread, which must not touch Tk: leave the
        # text for poll(), which runs on Tk's own thread.
        result["status"] = text

    def runner() -> None:
        try:
            result["ok"], result["detail"] = work(status)
        except Exception as e:  # never leave the window spinning forever
            result["ok"], result["detail"] = False, f"{type(e).__name__}: {e}"

    def poll() -> None:
        if "ok" not in result:
            if result.get("status") and message.get() != result["status"]:
                message.set(result["status"])
            elapsed.set(f"{int(time.monotonic() - started)} s")
            root.after(500, poll)
            return
        if result["ok"]:
            root.destroy()
            return
        _show_failure(root, ttk, message, elapsed, buttons, result["detail"], log_file)

    threading.Thread(target=runner, daemon=True).start()
    root.after(500, poll)
    root.mainloop()
    return bool(result.get("ok"))


def _show_failure(root, ttk, message, elapsed, buttons, detail, log_file) -> None:
    message.set("CraftBot could not start.")
    elapsed.set(detail or "")
    if log_file and os.path.isfile(log_file):
        ttk.Button(buttons, text="Open log", command=lambda: _open_file(log_file)).grid(
            row=0, column=0, padx=(0, 8)
        )
    ttk.Button(buttons, text="Close", command=root.destroy).grid(row=0, column=1)
    root.attributes("-topmost", False)
    _center(root, 520, 220)


def _center(root, width: int, height: int) -> None:
    root.update_idletasks()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 3
    root.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")


def _open_file(path: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
