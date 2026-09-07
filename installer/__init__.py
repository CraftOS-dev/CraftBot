"""Installer-only modules used by craftbot.py.

Split out of the root namespace so the project root only contains the
user-facing entry points (`craftbot.py`, `run.py`, `main.py`). Everything
in here is implementation detail of the install flow, and all of it is
pure stdlib — it ships inside the source payload and runs under the
launcher's interpreter (launcher/), which replaced the old Tk wizard:

  - helpers:  detached-Popen flag soup + per-platform dispatcher
  - metadata: JSON read/write for install.json
  - payload:  agent source payload download + extract
"""
