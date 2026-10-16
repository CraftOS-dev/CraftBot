"""Interactive post-install acceptance. Run as the configured, unelevated owner.

The native Windows prompt asks the human to authorize a synthetic isolated run.
No saved user passwords, tokens, sessions, or credential values are inspected.
"""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.credentials.client import CredentialHostUnavailable, request  # noqa: E402


PROBE = """import ctypes as C, os, subprocess, sys, socket
from ctypes import wintypes as W
import credential_client
checks = {}
try:
    scratch = os.path.join(os.environ['TEMP'], 'synthetic-acceptance.txt')
    with open(scratch, 'w', encoding='utf-8') as stream:
        stream.write('synthetic scratch probe')
    with open(scratch, encoding='utf-8') as stream:
        checks['scratch_read_write'] = stream.read() == 'synthetic scratch probe'
    os.remove(scratch)
    checks['scratch_delete'] = not os.path.exists(scratch)
except OSError:
    checks['scratch_read_write'] = checks['scratch_delete'] = False
try:
    with open(__file__, 'a', encoding='utf-8') as stream:
        stream.write('# forbidden snapshot write')
    checks['snapshot_write_denied'] = False
except PermissionError:
    checks['snapshot_write_denied'] = True

advapi = C.WinDLL('advapi32', use_last_error=True)
kernel = C.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.restype = W.HANDLE
advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
token = W.HANDLE()
isolated, size = W.DWORD(), W.DWORD()
if advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, C.byref(token)):
    checks['appcontainer_token'] = bool(advapi.GetTokenInformation(token, 29, C.byref(isolated), 4, C.byref(size)) and isolated.value == 1)
    advapi.GetTokenInformation(token, 30, None, 0, C.byref(size))
    capabilities = C.create_string_buffer(size.value)
    checks['no_network_capabilities'] = bool(advapi.GetTokenInformation(token, 30, capabilities, size.value, C.byref(size)) and C.cast(capabilities, C.POINTER(W.DWORD))[0] == 0)
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle(token)
else:
    checks['appcontainer_token'] = False
    checks['no_network_capabilities'] = False
kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel.OpenProcess.restype = W.HANDLE
protected = kernel.OpenProcess(0x1010, False, SERVICE_PID)
checks['system_process_memory_denied'] = not bool(protected)
if protected:
    kernel.CloseHandle(protected)
advapi.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.c_void_p)]
advapi.CredFree.argtypes = [C.c_void_p]
record = C.c_void_p()
found = advapi.CredReadW(KEY_TARGET, 1, 0, C.byref(record))
checks['system_vault_key_denied'] = not found and C.get_last_error() in (5, 1168, 1312)
if found:
    advapi.CredFree(record)
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as transport:
        transport.settimeout(2)
        transport.connect(('1.1.1.1', 443))
    checks['network_denied'] = False
except OSError as error:
    checks['network_denied'] = getattr(error, 'winerror', None) == 10013
try:
    os.listdir(STATE_ROOT)
    checks['vault_files_denied'] = False
except PermissionError:
    checks['vault_files_denied'] = True
try:
    subprocess.run([sys.executable, '-I', '-S', '-c', 'pass'], timeout=2)
    checks['child_process_denied'] = False
except (PermissionError, OSError):
    checks['child_process_denied'] = True
for operation in ('profiles', 'read_secret'):
    try:
        credential_client.request(operation)
        checks[operation + '_denied'] = False
    except credential_client.CredentialHostUnavailable:
        checks[operation + '_denied'] = True
checks['clean_environment'] = set(os.environ).issubset({'PATH','SYSTEMROOT','TEMP','TMP','USERPROFILE','LC_CTYPE'})
credential_client.complete(checks)
"""


def verify(profile_id: str, state_root: Path, owner_id: str):
    from uuid import UUID
    import win32service

    owner_id, profile_id = str(UUID(owner_id)), str(UUID(profile_id))
    profiles = request("profiles")
    profile = next((item for item in profiles if item["id"] == profile_id), None)
    if profile is None or profile["state"] != "ready":
        raise RuntimeError(
            "Initialize/unlock the selected profile before native acceptance"
        )
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    service = None
    try:
        service = win32service.OpenService(
            manager, "CraftBotCredentialHost", win32service.SERVICE_QUERY_STATUS
        )
        service_pid = win32service.QueryServiceStatusEx(service)["ProcessId"]
        if not service_pid:
            raise RuntimeError("Credential service is not running")
    finally:
        if service is not None:
            win32service.CloseServiceHandle(service)
        win32service.CloseServiceHandle(manager)
    try:
        request("status")
    except CredentialHostUnavailable as error:
        if str(error) != "credential_isolation_unavailable":
            raise
    else:
        raise RuntimeError("Unisolated host unexpectedly gained consumer authority")
    source = (
        "STATE_ROOT = "
        + repr(str(state_root))
        + "\nSERVICE_PID = "
        + repr(service_pid)
        + "\nKEY_TARGET = "
        + repr(f"CraftBot/Vault/v1/{owner_id}/{profile_id}")
        + "\n"
        + PROBE
    )
    launch = request(
        "launch",
        profile_id=profile_id,
        kind="agent_app",
        subject="CM-03 native acceptance",
        deployment="development",
        files={"probe.py": source},
        entry="probe.py",
    )
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            response = request("program_result", run_id=launch["run_id"])
            if "exited" in response:
                raise RuntimeError(
                    "Native consumer exited without a result: "
                    + str(response["exited"])
                )
            if "result" in response:
                checks = response["result"]
                print(json.dumps(checks, indent=2))
                if not checks or not all(value is True for value in checks.values()):
                    raise RuntimeError("Native acceptance failed")
                print(
                    "Native containment and transport checks passed; no token/session store changed."
                )
                return
            time.sleep(0.2)
        raise RuntimeError("Native consumer did not finish")
    finally:
        try:
            request("stop", run_id=launch["run_id"])
        except CredentialHostUnavailable:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile_id")
    parser.add_argument(
        "--owner-id",
        required=True,
        help="Enrollment owner_id from the reviewed package payload/host.json; metadata only",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path(r"C:\ProgramData\CraftBotCredentialHost"),
    )
    args = parser.parse_args()
    verify(args.profile_id, args.state_root, args.owner_id)
