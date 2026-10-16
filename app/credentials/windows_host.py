"""Windows kernel boundary. Imported only by the installed SYSTEM worker.

No attestation in a client message is used here. Handles, tokens and job
membership are queried by the host and retained for the lifetime of a launch.
"""

from __future__ import annotations

import ctypes as C
from contextlib import closing
from ctypes import wintypes as W
import os
from pathlib import Path
import stat
import subprocess
from threading import RLock
from uuid import uuid4

from .contracts import IsolationUnavailable

SYSTEM = "S-1-5-18"
ADMIN = "S-1-5-32-544"
WRITE = 0x500D0116  # generic write/all, delete, write DACL/owner, file mutations


def api():
    if os.name != "nt":
        raise IsolationUnavailable()
    import win32api
    import win32con
    import win32job
    import win32process
    import win32security
    import win32ts
    import win32event

    return (
        win32api,
        win32con,
        win32job,
        win32process,
        win32security,
        win32ts,
        win32event,
    )


def native_sid(pointer):
    dll = C.WinDLL("advapi32", use_last_error=True)
    dll.GetLengthSid.argtypes = [C.c_void_p]
    dll.GetLengthSid.restype = W.DWORD
    security = api()[4]
    return security.ConvertSidToStringSid(
        security.SID(C.string_at(pointer, dll.GetLengthSid(pointer)))
    )


def token_value(token, information, *, pointer=False):
    dll = C.WinDLL("advapi32", use_last_error=True)
    dll.GetTokenInformation.argtypes = [
        W.HANDLE,
        C.c_int,
        C.c_void_p,
        W.DWORD,
        C.POINTER(W.DWORD),
    ]
    size = W.DWORD()
    dll.GetTokenInformation(int(token), information, None, 0, C.byref(size))
    if not 4 <= size.value <= 4096:
        raise IsolationUnavailable()
    buffer = C.create_string_buffer(size.value)
    if not dll.GetTokenInformation(
        int(token), information, buffer, len(buffer), C.byref(size)
    ):
        raise IsolationUnavailable()
    value = (C.c_void_p if pointer else W.DWORD).from_buffer(buffer)
    return native_sid(value) if pointer and value.value else value.value


def private_acl(path: Path, sid: str | None = None, *, writable=False):
    security = api()[4]
    extra = f"(A;OICI;{'0x1301bf' if writable else 'GRGX'};;;{sid})" if sid else ""
    descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        "O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        + extra
        + ("S:(ML;OICI;NW;;;LW)" if writable else ""),
        1,
    )
    security.SetFileSecurity(
        str(path),
        security.DACL_SECURITY_INFORMATION
        | security.PROTECTED_DACL_SECURITY_INFORMATION
        | security.OWNER_SECURITY_INFORMATION
        | (0x10 if writable else 0),  # LABEL_SECURITY_INFORMATION, scratch only.
        descriptor,
    )


def check_install(root: Path, state: Path):
    """SYSTEM only; reject writable code/dependencies, links and foreign owners."""
    security = api()[4]
    with closing(security.OpenProcessToken(api()[0].GetCurrentProcess(), 8)) as token:
        if (
            security.ConvertSidToStringSid(security.GetTokenInformation(token, 1)[0])
            != SYSTEM
        ):
            raise IsolationUnavailable()
    for base in (root, state):
        for path in (base, *base.parents):
            info = path.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise IsolationUnavailable()
        # All files loaded by the worker/runtime must be protected, not only
        # the executable. The installer sets these ACLs before registering SCM.
        paths = [base, *base.rglob("*")] if base == root else [base]
        for path in paths:
            info = path.lstat()
            if getattr(info, "st_file_attributes", 0) & 0x400:
                raise IsolationUnavailable()
            sd = security.GetFileSecurity(str(path), 1 | 4)
            if security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()) not in (
                SYSTEM,
                ADMIN,
            ):
                raise IsolationUnavailable()
            dacl = sd.GetSecurityDescriptorDacl()
            if dacl is None:
                raise IsolationUnavailable()
            for index in range(dacl.GetAceCount()):
                ace = dacl.GetAce(index)
                if ace[0][0] != 0:  # no ambiguous object/callback/deny ACLs
                    raise IsolationUnavailable()
                if (
                    security.ConvertSidToStringSid(ace[-1]) not in (SYSTEM, ADMIN)
                    and ace[1] & WRITE
                ):
                    raise IsolationUnavailable()


class Peer:
    def __init__(self, pid: int):
        winapi, _, _, _, security, _, _ = api()
        self.pid = pid
        self.handle = winapi.OpenProcess(0x1000 | 0x100000, False, pid)
        dll = C.WinDLL("kernel32", use_last_error=True)
        dll.GetProcessTimes.argtypes = [W.HANDLE, *([C.POINTER(C.c_ulonglong)] * 4)]
        created, exited, system, user = (C.c_ulonglong() for _ in range(4))
        if not dll.GetProcessTimes(
            int(self.handle),
            C.byref(created),
            C.byref(exited),
            C.byref(system),
            C.byref(user),
        ):
            self.handle.Close()
            raise IsolationUnavailable()
        self.created = created.value
        with closing(security.OpenProcessToken(self.handle, 8)) as token:
            self.sid = security.ConvertSidToStringSid(
                security.GetTokenInformation(token, 1)[0]
            )
            self.session = security.GetTokenInformation(token, 12)
            self.container = bool(token_value(token, 29))
            self.elevated = bool(token_value(token, 20))
            self.app_sid = (
                token_value(token, 31, pointer=True) if self.container else None
            )

    def alive(self):
        return api()[6].WaitForSingleObject(self.handle, 0) == 258

    def close(self):
        self.handle.Close()


class STARTUPINFO(C.Structure):
    _fields_ = [
        ("cb", W.DWORD),
        ("reserved", W.LPWSTR),
        ("desktop", W.LPWSTR),
        ("title", W.LPWSTR),
        ("x", W.DWORD),
        ("y", W.DWORD),
        ("xs", W.DWORD),
        ("ys", W.DWORD),
        ("xc", W.DWORD),
        ("yc", W.DWORD),
        ("fill", W.DWORD),
        ("flags", W.DWORD),
        ("show", W.WORD),
        ("reserved2size", W.WORD),
        ("reserved2", C.c_void_p),
        ("stdin", W.HANDLE),
        ("stdout", W.HANDLE),
        ("stderr", W.HANDLE),
    ]


class STARTUPINFOEX(C.Structure):
    _fields_ = [("startup", STARTUPINFO), ("attributes", C.c_void_p)]


class PROCESSINFO(C.Structure):
    _fields_ = [
        ("process", W.HANDLE),
        ("thread", W.HANDLE),
        ("pid", W.DWORD),
        ("tid", W.DWORD),
    ]


class CAPS(C.Structure):
    _fields_ = [
        ("sid", C.c_void_p),
        ("caps", C.c_void_p),
        ("count", W.DWORD),
        ("reserved", W.DWORD),
    ]


class SA(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", C.c_void_p), ("inherit", W.BOOL)]


class IsolatedProcess:
    """Single-process Python consumer, no descendants, handles or inherited env."""

    def __init__(self, root: Path, runtime: Path, owner_sid: str, session: int):
        winapi, _, job, _, security, ts, _ = api()
        self.root = root
        self._closing = RLock()
        self.profile_name = "CraftBot.Credential." + uuid4().hex
        self.job = job.CreateJobObject(None, "")
        limits = job.QueryInformationJobObject(
            self.job, job.JobObjectExtendedLimitInformation
        )
        limits["BasicLimitInformation"]["LimitFlags"] = 0x2000 | 0x8 | 0x100
        limits["BasicLimitInformation"]["ActiveProcessLimit"] = 1
        limits["ProcessMemoryLimit"] = 512 * 1024 * 1024
        job.SetInformationJobObject(
            self.job, job.JobObjectExtendedLimitInformation, limits
        )
        job.SetInformationJobObject(
            self.job, job.JobObjectBasicUIRestrictions, {"UIRestrictionsClass": 0xFF}
        )
        self.handle = None
        self.pid = None
        self.runtime = runtime
        self._sid = C.c_void_p()
        userenv = C.WinDLL("userenv", use_last_error=True)
        userenv.CreateAppContainerProfile.argtypes = [
            W.LPCWSTR,
            W.LPCWSTR,
            W.LPCWSTR,
            C.c_void_p,
            W.DWORD,
            C.POINTER(C.c_void_p),
        ]
        userenv.CreateAppContainerProfile.restype = C.c_long
        with closing(ts.WTSQueryUserToken(session)) as token:
            if (
                security.ConvertSidToStringSid(
                    security.GetTokenInformation(token, 1)[0]
                )
                != owner_sid
            ):
                raise IsolationUnavailable()
            if token_value(token, 20):
                dll = C.WinDLL("advapi32", use_last_error=True)
                dll.GetTokenInformation.argtypes = [
                    W.HANDLE,
                    C.c_int,
                    C.c_void_p,
                    W.DWORD,
                    C.POINTER(W.DWORD),
                ]
                linked, size = W.HANDLE(), W.DWORD()
                if not dll.GetTokenInformation(
                    int(token), 19, C.byref(linked), C.sizeof(linked), C.byref(size)
                ):
                    raise IsolationUnavailable()
                self.token = linked.value
            else:
                self.token = winapi.DuplicateHandle(
                    winapi.GetCurrentProcess(),
                    token,
                    winapi.GetCurrentProcess(),
                    0,
                    False,
                    2,
                ).Detach()
            if token_value(self.token, 20):
                raise IsolationUnavailable()
            security.ImpersonateLoggedOnUser(self.token)
            try:
                code = userenv.CreateAppContainerProfile(
                    self.profile_name,
                    "CraftBot isolated credential consumer",
                    "",
                    None,
                    0,
                    C.byref(self._sid),
                )
            finally:
                security.RevertToSelf()
            if code != 0:
                raise IsolationUnavailable()
            self.app_sid = native_sid(self._sid)
        root.mkdir()
        private_acl(root, self.app_sid)
        (root / "scratch").mkdir()
        private_acl(root / "scratch", self.app_sid, writable=True)

    def start(self, entry: str):
        kernel = C.WinDLL("kernel32", use_last_error=True)
        advapi = C.WinDLL("advapi32", use_last_error=True)
        initialize = kernel.InitializeProcThreadAttributeList
        initialize.argtypes = [C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_size_t)]
        update = kernel.UpdateProcThreadAttribute
        update.argtypes = [
            C.c_void_p,
            W.DWORD,
            C.c_size_t,
            C.c_void_p,
            C.c_size_t,
            C.c_void_p,
            C.c_void_p,
        ]
        kernel.DeleteProcThreadAttributeList.argtypes = [C.c_void_p]
        size = C.c_size_t()
        initialize(None, 2, 0, C.byref(size))
        storage = C.create_string_buffer(size.value)
        if not initialize(storage, 2, 0, C.byref(size)):
            raise IsolationUnavailable()
        caps = CAPS(self._sid, None, 0, 0)  # No network or broad file capabilities.
        no_children = W.DWORD(1)
        si = STARTUPINFOEX()
        si.startup.cb = C.sizeof(si)
        si.attributes = C.cast(storage, C.c_void_p)
        pi = PROCESSINFO()
        # Process/thread objects cannot be opened/injected by the desktop owner.
        security = api()[4]
        descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            "O:SYD:P(A;;GA;;;SY)", 1
        )
        descriptor_bytes = bytes(descriptor)
        descriptor_buffer = C.create_string_buffer(descriptor_bytes)
        attributes = SA(C.sizeof(SA), C.cast(descriptor_buffer, C.c_void_p), False)
        command = C.create_unicode_buffer(
            subprocess.list2cmdline(
                [str(self.runtime), "-I", "-S", str(self.root / entry)]
            )
        )
        windows = api()[0].GetWindowsDirectory()
        environment = C.create_unicode_buffer(
            "\0".join(
                [
                    "PATH=" + str(self.runtime.parent),
                    "SYSTEMROOT=" + windows,
                    "TEMP=" + str(self.root / "scratch"),
                    "TMP=" + str(self.root / "scratch"),
                    "USERPROFILE=" + str(self.root / "scratch"),
                ]
            )
            + "\0\0"
        )
        create = advapi.CreateProcessAsUserW
        create.argtypes = [
            W.HANDLE,
            W.LPCWSTR,
            W.LPWSTR,
            C.POINTER(SA),
            C.POINTER(SA),
            W.BOOL,
            W.DWORD,
            C.c_void_p,
            W.LPCWSTR,
            C.POINTER(STARTUPINFOEX),
            C.POINTER(PROCESSINFO),
        ]
        try:
            if not update(
                storage, 0, 0x20009, C.byref(caps), C.sizeof(caps), None, None
            ) or not update(
                storage,
                0,
                0x2000E,
                C.byref(no_children),
                C.sizeof(no_children),
                None,
                None,
            ):
                raise IsolationUnavailable()
            if not create(
                self.token,
                str(self.runtime),
                command,
                C.byref(attributes),
                C.byref(attributes),
                False,
                0x80000 | 0x400 | 4 | 0x08000000,
                environment,
                str(self.root / "scratch"),
                C.byref(si),
                C.byref(pi),
            ):
                raise IsolationUnavailable()
            self.handle = pi.process
            self.pid = pi.pid
            try:
                api()[2].AssignProcessToJobObject(self.job, self.handle)
                api()[3].ResumeThread(pi.thread)
            except BaseException:
                api()[0].TerminateProcess(self.handle, 1)
                raise
            finally:
                api()[0].CloseHandle(pi.thread)
        finally:
            kernel.DeleteProcThreadAttributeList(storage)

    def matches(self, peer: Peer):
        return (
            self.handle is not None
            and self.pid == peer.pid
            and peer.alive()
            and peer.container
            and peer.app_sid == self.app_sid
            and not peer.elevated
            and api()[2].IsProcessInJob(peer.handle, self.job)
        )

    def close(self):
        with self._closing:
            self._close()

    def __del__(self):
        try:
            self.close()
        except BaseException:
            pass

    def _close(self):
        if self.handle is not None:
            try:
                api()[0].TerminateProcess(self.handle, 1)
            except Exception:
                pass
            api()[6].WaitForSingleObject(self.handle, 5000)
            api()[0].CloseHandle(self.handle)
            self.handle = None
        if self.job is not None:
            self.job.Close()  # Kill-on-close, including on worker termination.
            self.job = None
        if getattr(self, "token", None):
            try:
                security = api()[4]
                security.ImpersonateLoggedOnUser(self.token)
                try:
                    delete = C.WinDLL("userenv").DeleteAppContainerProfile
                    delete.argtypes = [W.LPCWSTR]
                    delete(self.profile_name)
                finally:
                    security.RevertToSelf()
            except Exception:
                pass
            api()[0].CloseHandle(self.token)
            self.token = None
        if self._sid:
            free = C.WinDLL("advapi32").FreeSid
            free.argtypes = [C.c_void_p]
            free(self._sid)
            self._sid = None
