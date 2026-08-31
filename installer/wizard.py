"""CraftBot installer wizard — a native window, drawn with CustomTkinter.

The UI lives in installer/ui/ (see that package's docstring for the split).
This module is only the entry point: it builds a WizardAPI, hands it to the
window, and decides what to do when no window can be opened at all.

## Why a native window rather than a browser or an embedded webview

Two earlier designs failed on the same point, and it is worth recording so a
third does not repeat it.

  * **pywebview** rendered the UI in an OS-native webview, which required an
    embedded browser engine to already be present: WebView2 on Windows —
    absent in Windows Sandbox, on LTSC and on some managed enterprise images;
    apt-installed libwebkit2gtk on Linux. Where it was missing, double-
    clicking the installer did nothing whatsoever, because the EXE is built
    console=False and the error had nowhere to go.

  * **A local HTTP server plus the user's own browser** removed that
    dependency but replaced it with a worse experience: the installer had to
    find and launch a browser, needed a registered `http` handler to exist,
    and the "app" was a tab with an address bar pointing at 127.0.0.1.

CustomTkinter draws its own widgets on Tk, which ships with CPython on every
platform we target and is bundled into the EXE. Nothing needs to be present
on the user's machine, and the result is a real application window.

## The one thing that can still be missing

Tk itself. A Python built without it (`python3-tk` unpackaged, which some
minimal Linux images do) cannot open any window. That is caught below and
turned into a console install rather than a silent failure — an installer
that cannot draw must still install.

Architecture:
  craftbot.py main()
    └─ launch_wizard()
         ├─ WizardAPI       lifecycle actions, shared with the CLI path
         └─ installer.ui.run(api)   opens the window, blocks until closed
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback

import craftbot
from installer.api import WizardAPI

#: Colour-code attributes on craftbot.py. The wizard captures stdout to show
#: it in the log panel, and Tk has no notion of ANSI escapes, so they are
#: blanked rather than rendered as mojibake.
_COLOR_ATTRS = ("ORANGE", "WHITE", "BOLD", "DIM", "GREEN", "RED", "RESET")

#: Overridable so a support request can ask for the trace somewhere specific.
_LOG_ENV = "CRAFTBOT_INSTALLER_LOG"


def _log_path() -> str:
    """Where the startup trace goes."""
    override = os.environ.get(_LOG_ENV, "").strip()
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_STATE_HOME") or ""
    directory = os.path.join(base, "CraftBot") if base else tempfile.gettempdir()
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        directory = tempfile.gettempdir()
    return os.path.join(directory, "installer-startup.log")


def _log(message: str) -> None:
    """Append one line to the startup trace. Never raises.

    This exists because the installer is built console=False: before the
    window is up there is no stdout, no stderr and no UI, so anything that
    goes wrong is completely invisible — the EXE just vanishes a moment after
    being double-clicked, which is the least diagnosable failure a program
    can have. A file is the only channel that survives that.

    It also distinguishes the three ways the window can disappear, which
    otherwise look identical from the outside: a crash (traceback logged), a
    normal close ("window closed normally"), and being killed from outside
    (the log simply stops at "entering mainloop").
    """
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_log_path(), "a", encoding="utf-8") as fh:
            fh.write(stamp + "  " + message + "\n")
    except Exception:
        pass


def _fatal(message: str) -> None:
    """Report a startup failure the user can actually see, then exit.

    The installer is built console=False, so stderr goes nowhere: a failure
    here otherwise looks exactly like double-clicking the EXE and nothing
    happening, which is the least debuggable outcome possible. On Windows we
    raise a native message box; elsewhere stderr is still visible.
    """
    sys.stderr.write("\nERROR: " + message + "\n\n")
    if sys.platform == "win32":
        try:
            import ctypes

            # MB_ICONERROR | MB_OK, owner=None so it shows without a window.
            ctypes.windll.user32.MessageBoxW(None, message, "CraftBot Installer", 0x10)
        except Exception:
            pass
    sys.exit(1)


def _headless_fallback(reason: str) -> None:
    """No window could be opened, so offer to install without one.

    The window's job is choosing a location and pressing a button. If the
    user cannot be shown it, refusing to install would be the worst outcome
    available: they double-clicked an installer and got nothing, on a machine
    that by definition offers them no other route. Offer the default-location
    install instead, which is what almost everyone picks anyway.
    """
    message = (
        "CraftBot could not open its setup window.\n\n"
        f"({reason})\n\n"
        "Install now with the default settings instead?"
    )
    proceed = False

    if sys.platform == "win32":
        try:
            import ctypes

            # MB_YESNO | MB_ICONQUESTION; IDYES == 6.
            answer = ctypes.windll.user32.MessageBoxW(
                None, message, "CraftBot Installer", 0x24
            )
            proceed = answer == 6
        except Exception:
            proceed = False
    else:
        # No dialog to ask with. On Linux the usual cause is a missing
        # python3-tk, and the user is most likely at a terminal watching
        # this — say what happened, then get on with it.
        sys.stdout.write("\n" + message + "\n")
        proceed = True

    if not proceed:
        sys.stdout.write(
            "\nInstall from a command prompt with:\n"
            "   CraftBotInstaller install\n"
        )
        return

    sys.stdout.write("\nInstalling with default settings...\n")
    if not craftbot.cmd_install([]):
        _fatal(
            "The installation did not complete.\n\n"
            "Run it from a Command Prompt to see the full output:\n"
            "   CraftBotInstaller.exe install"
        )


def launch_wizard() -> None:
    """Open the setup window and block until the user closes it."""
    _log("=" * 60)
    _log(
        f"launch_wizard: frozen={getattr(sys, 'frozen', False)} "
        f"exe={sys.executable} cwd={os.getcwd()} argv={sys.argv[1:]}"
    )

    for name in _COLOR_ATTRS:
        if hasattr(craftbot, name):
            setattr(craftbot, name, "")

    try:
        from installer.ui import run
    except ImportError as e:
        # Tk (or CustomTkinter) is unavailable. This is the only failure mode
        # worth degrading for rather than reporting: everything needed to
        # actually install is still present.
        _log(f"UI import FAILED: {type(e).__name__}: {e}")
        _headless_fallback(f"{type(e).__name__}: {e}")
        return
    _log("UI imported")

    api = WizardAPI()
    try:
        _log("entering mainloop")
        run(api, version=craftbot._read_bundled_version())
        _log("window closed normally")
    except Exception as e:  # noqa: BLE001 - last line before a silent exit
        _log("window RAISED:\n" + traceback.format_exc())
        _fatal(
            "The setup window stopped unexpectedly.\n\n"
            f"{type(e).__name__}: {str(e)[:300]}\n\n"
            f"Details were written to:\n   {_log_path()}"
        )


if __name__ == "__main__":
    launch_wizard()
