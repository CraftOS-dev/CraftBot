"""PyInstaller runtime hook: suppress per-subprocess console windows on Windows.

The frozen agent and installer EXEs are built with `console=False` (Windows
GUI subsystem, no console attached). When a no-console Windows process spawns
a CLI child without `creationflags=CREATE_NO_WINDOW`, Windows allocates a
fresh console for that child — visible as a brief terminal flash.

Patching every subprocess call site individually doesn't scale (the agent has
spawns spread across MCP servers, action executor/registry, Agent App manager,
scheduler, GUI handler, npm bridge, etc.). Instead we patch the choke points
once here, before any user code runs:

  - subprocess.Popen.__init__   covers subprocess.run / call / check_output /
                                  asyncio.create_subprocess_exec / _shell
  - _winapi.CreateProcess        used by asyncio's ProactorEventLoop directly
  - os.system                    spawns cmd.exe with its own console; replace
                                  with subprocess.run which is now patched

`flags | CREATE_NO_WINDOW` is idempotent, so callers that already set the flag
explicitly keep working unchanged.

Linux/macOS: no-op.
"""

import sys

if sys.platform == "win32":
    import os
    import subprocess

    _CREATE_NO_WINDOW = 0x08000000

    # ── subprocess.Popen ─────────────────────────────────────────────────────
    _original_popen_init = subprocess.Popen.__init__

    def _patched_popen_init(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0) or 0
        kwargs["creationflags"] = flags | _CREATE_NO_WINDOW
        return _original_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_popen_init

    # ── _winapi.CreateProcess (asyncio Proactor path) ────────────────────────
    try:
        import _winapi

        _original_create_process = _winapi.CreateProcess

        def _patched_create_process(
            executable,
            command_line,
            proc_attrs,
            thread_attrs,
            inherit_handles,
            creation_flags,
            env,
            current_directory,
            startup_info,
        ):
            return _original_create_process(
                executable,
                command_line,
                proc_attrs,
                thread_attrs,
                inherit_handles,
                creation_flags | _CREATE_NO_WINDOW,
                env,
                current_directory,
                startup_info,
            )

        _winapi.CreateProcess = _patched_create_process
    except Exception:
        pass

    # ── os.system ────────────────────────────────────────────────────────────
    _original_os_system = os.system

    def _patched_os_system(command):
        try:
            return subprocess.run(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
        except Exception:
            return _original_os_system(command)

    os.system = _patched_os_system
