"""The installer's window: a small, self-contained CustomTkinter UI.

Split three ways so the parts that need a display are separable from the
parts that do not:

    theme.py    design tokens and colour maths. No tkinter import, so it is
                testable without a display.
    glass.py    renders the lit backdrop and answers "what colour is behind
                this point", which every widget needs to tint itself.
    chrome.py   best-effort native window polish (dark title bar, rounded
                corners). Every call is optional and swallows its own errors.
    window.py   the window, and the only module that talks to WizardAPI.

`installer.wizard` is the entry point; import failures here (a Python built
without tkinter, most often on minimal Linux images) are caught there and
fall back to a console install.
"""

from installer.ui.window import InstallerWindow, run

__all__ = ["InstallerWindow", "run"]
