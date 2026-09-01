"""Native window-frame polish, where the OS offers it.

Everything here is optional and best-effort. The window is fully usable and
looks right without any of it — these calls only stop the OS-drawn title bar
from clashing with the dark window we draw underneath it.

Nothing in here is allowed to raise. This is an installer: it runs exactly
once, on machines we have never seen, and a cosmetic call failing on some
unusual Windows build must never be the reason someone cannot install
CraftBot. Every function swallows its own errors and reports success as a
bool for logging, not for control flow.
"""

from __future__ import annotations

import sys

__all__ = ["apply_native_chrome", "set_window_icon"]

# DwmSetWindowAttribute attributes.
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # Windows 10 builds before 19041
_DWMWA_WINDOW_CORNER_PREFERENCE = 33  # Windows 11 only; ignored on 10
_DWMWCP_ROUND = 2
# Windows 11 build 22000+. Older builds return an error code we ignore, and
# keep the plain dark title bar.
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36


def _colorref(hex_color: str) -> int:
    """'#14141f' -> 0x001F1414. DWM wants COLORREF, which is BGR, not RGB."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_native_chrome(
    window, caption: str = "", caption_text: str = ""
) -> bool:
    """Make the OS title bar match the window. Returns True if anything
    was applied.

    Windows draws the title bar itself, in light mode, regardless of what the
    application paints in its client area. Without this the window is a
    near-black panel wearing a white hat, which is the single most obvious
    tell that something is a Tk app.

    `caption` goes further: it paints the title bar and border the window's
    own colour, so the frame stops reading as a separate strip and the window
    becomes one surface. Windows 11 only —
    older builds reject the attribute and keep the plain dark bar, which
    still looks fine, just not seamless.

    The alternative is a frameless window with hand-drawn controls, which
    costs taskbar presence, snapping, and Alt-Tab behaviour. Not worth it for
    a cosmetic gain the OS will do for us.
    """
    if sys.platform != "win32":
        # macOS already tracks the system appearance for Tk windows, and on
        # Linux the title bar belongs to the window manager, which offers no
        # portable way to ask.
        return False

    try:
        import ctypes
        from ctypes import wintypes

        # The window must exist before it has a handle to configure.
        window.update_idletasks()

        # winfo_id() returns Tk's child window; the frame that owns the title
        # bar is its parent, and that is what DWM wants.
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            return False

        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1)

        applied = False
        for attribute in (
            _DWMWA_USE_IMMERSIVE_DARK_MODE,
            _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
        ):
            result = dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(attribute),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:  # S_OK
                applied = True
                break

        def _set(attribute: int, value: int) -> None:
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(attribute),
                ctypes.byref(v),
                ctypes.sizeof(v),
            )

        # Rounded window corners. Windows 11 only — 10 returns a failure code
        # we simply ignore, which is why this is not part of `applied`.
        _set(_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)

        # Merge the title bar into the window. Border gets the same colour as
        # the caption so there is no seam where the frame meets the content.
        if caption:
            _set(_DWMWA_CAPTION_COLOR, _colorref(caption))
            _set(_DWMWA_BORDER_COLOR, _colorref(caption))
        if caption_text:
            _set(_DWMWA_TEXT_COLOR, _colorref(caption_text))

        return applied
    except Exception:
        return False


def set_window_icon(window, ico_path: str, png_path: str = "") -> bool:
    """Give the window its icon, preferring the .ico on Windows.

    `iconbitmap` is the only call that reaches the Windows taskbar and Alt-Tab
    thumbnail, but it wants a real .ico and is unavailable on some Linux Tk
    builds; `iconphoto` works everywhere but not for the taskbar on Windows.
    Try both, keep whichever lands.
    """
    ok = False
    if ico_path and sys.platform == "win32":
        try:
            window.iconbitmap(ico_path)
            ok = True
        except Exception:
            pass
    if png_path:
        try:
            import tkinter as tk

            image = tk.PhotoImage(file=png_path)
            window.iconphoto(True, image)
            # Same PhotoImage lifetime trap as the backdrop: without a
            # reference the icon is collected and silently vanishes.
            window._icon_image = image  # noqa: SLF001 - deliberate keep-alive
            ok = True
        except Exception:
            pass
    return ok


def center(window, width: int, height: int) -> None:
    """Position the window centred on the screen, biased slightly upward.

    Dead-centre looks low because the eye reads the optical centre as higher
    than the geometric one — the same reason dialogs across every OS sit a
    little above the middle.
    """
    try:
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, int((screen_h - height) * 0.42))
        window.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        window.geometry(f"{width}x{height}")
