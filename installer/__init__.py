"""Installer-only modules used by craftbot.py.

Split out of the root namespace so the project root only contains the
user-facing entry points (`craftbot.py`, `run.py`, `main.py`). Everything
in here is implementation detail of the installer/wizard flow:

  - helpers:  detached-Popen flag soup + per-platform dispatcher
  - metadata: JSON read/write for install.json
  - payload:  agent source payload download + extract
  - api:      the lifecycle actions, with no UI attached
  - wizard:   entry point; opens the window, or installs headless if it cannot
  - ui/:      the window itself (CustomTkinter). The only package here that
              imports Tk, so everything else stays testable without a display.
"""
