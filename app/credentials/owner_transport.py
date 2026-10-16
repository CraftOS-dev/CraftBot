"""Protected native consent/entry. Never use the browser bridge as owner proof."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import struct
import subprocess
from uuid import uuid4

from .errors import VaultError, VaultErrorCode
from .secrets import Secret
from .windows_host import Peer, SYSTEM, api


class WindowsOwnerConsent:
    def __init__(self, executable: Path, owner_sid: str):
        self.executable = executable
        self.owner_sid = owner_sid
        self.session = None
        self.message = None
        self.review_request = None

    def verify(self, owner):
        if (
            owner.os_identity != self.owner_sid
            or self.session is None
            or not self.message
        ):
            raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
        review, self.review_request = self.review_request, None
        if review is None:
            self.prompt()
        else:
            self._exchange(tuple(review), display=Secret(review), review=True)

    def _launch(self, arguments):
        winapi, _, job, process, security, _, event = api()
        if not isinstance(self.message, str) or len(self.message) > 1000:
            raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
        text = base64.b64encode(self.message.encode("utf-8")).decode("ascii")
        current = security.OpenProcessToken(winapi.GetCurrentProcess(), 0xF01FF)
        token = security.DuplicateTokenEx(current, 2, 0xF01FF, 1)
        current.Close()
        group = job.CreateJobObject(None, "")
        info = job.QueryInformationJobObject(
            group, job.JobObjectExtendedLimitInformation
        )
        # Only the fixed entry guardian may break away. It restores the prior
        # desktop if this job/worker/service is killed while source entry runs.
        info["BasicLimitInformation"]["LimitFlags"] = 0x2000 | (
            0x800 if arguments[0] in ("--entry", "--view", "--review") else 0
        )
        job.SetInformationJobObject(group, job.JobObjectExtendedLimitInformation, info)
        try:
            security.SetTokenInformation(token, 12, self.session)
            startup = process.STARTUPINFO()
            startup.lpDesktop = "winsta0\\default"
            handle, thread, pid, _ = process.CreateProcessAsUser(
                token,
                str(self.executable),
                subprocess.list2cmdline(
                    [
                        str(self.executable),
                        arguments[0],
                        self.owner_sid,
                        text,
                        *arguments[1:],
                    ]
                ),
                None,
                None,
                False,
                4 | 0x08000000,
                {"SYSTEMROOT": winapi.GetWindowsDirectory()},
                str(self.executable.parent),
                startup,
            )
            try:
                job.AssignProcessToJobObject(group, handle)
                process.ResumeThread(thread)
            finally:
                thread.Close()
            return handle, group, pid
        except BaseException:
            group.Close()
            raise
        finally:
            token.Close()

    def prompt(self):
        handle, group, _ = self._launch(["--consent"])
        try:
            if (
                api()[6].WaitForSingleObject(handle, 90000) != 0
                or api()[3].GetExitCodeProcess(handle) != 0
            ):
                raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
        finally:
            group.Close()
            handle.Close()

    def entry(self, fields: tuple[str, ...]) -> Secret:
        """Native SYSTEM form -> private SYSTEM pipe -> vault; never caller JSON."""
        return self._exchange(fields)

    def view(self, fields: Secret) -> None:
        """Owner-only display on the private desktop, with no global clipboard."""
        self._exchange(tuple(fields.reveal()), display=fields)

    def _exchange(self, fields, display=None, *, review=False):
        import pywintypes
        import win32file
        import win32pipe
        import win32security

        name = "CraftBot.CredentialEntry." + uuid4().hex
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = (
            win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                "O:SYD:P(A;;GA;;;SY)", 1
            )
        )
        pipe = win32pipe.CreateNamedPipe(
            "\\\\.\\pipe\\" + name,
            3 | 0x80000 | 0x40000000,
            8,
            1,
            65536,
            65536,
            0,
            attributes,
        )
        handle = group = None
        pending = pywintypes.OVERLAPPED()
        pending.hEvent = api()[6].CreateEvent(None, True, False, None)
        try:
            try:
                win32pipe.ConnectNamedPipe(pipe, pending)
            except pywintypes.error as error:
                if error.winerror not in (997, 535):
                    raise
            handle, group, pid = self._launch(
                [
                    "--review"
                    if review
                    else "--entry"
                    if display is None
                    else "--view",
                    name,
                    ",".join(fields),
                ]
            )
            if (
                api()[6].WaitForMultipleObjects([pending.hEvent, handle], False, 180000)
                != 0
            ):
                raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
            # Kernel process ID, not the JSON body or a claimed SYSTEM flag.
            import ctypes

            connected = ctypes.c_ulong()
            dll = ctypes.WinDLL("kernel32", use_last_error=True)
            dll.GetNamedPipeClientProcessId.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_ulong),
            ]
            if (
                not dll.GetNamedPipeClientProcessId(int(pipe), ctypes.byref(connected))
                or connected.value != pid
            ):
                raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
            peer = Peer(pid)
            try:
                if peer.sid != SYSTEM:
                    raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
            finally:
                peer.close()

            if display is not None:
                data = Secret(
                    json.dumps(display.reveal(), ensure_ascii=False).encode("utf-8")
                )
                if len(data.reveal()) > 2_100_000:
                    raise VaultError(VaultErrorCode.INVALID)
                framed = Secret(struct.pack("<I", len(data.reveal())) + data.reveal())
                outgoing = pywintypes.OVERLAPPED()
                outgoing.hEvent = api()[6].CreateEvent(None, True, False, None)
                try:
                    win32file.WriteFile(pipe, framed.reveal(), outgoing)
                    if api()[6].WaitForSingleObject(outgoing.hEvent, 10000) != 0:
                        raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
                    if win32file.GetOverlappedResult(pipe, outgoing, False) != len(
                        framed.reveal()
                    ):
                        raise VaultError(VaultErrorCode.INVALID)
                finally:
                    finish_io(pipe, outgoing)
                    outgoing.hEvent.Close()
                if (
                    api()[6].WaitForSingleObject(handle, 90000) != 0
                    or api()[3].GetExitCodeProcess(handle) != 0
                ):
                    raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
                return None

            # Overlapped reads have bounded waits and no diagnostic/value output.
            def read(count):
                result = Secret(bytearray())
                while len(result.reveal()) < count:
                    operation = pywintypes.OVERLAPPED()
                    operation.hEvent = api()[6].CreateEvent(None, True, False, None)
                    try:
                        _, data = win32file.ReadFile(
                            pipe, count - len(result.reveal()), operation
                        )
                        if api()[6].WaitForSingleObject(operation.hEvent, 10000) != 0:
                            raise VaultError(VaultErrorCode.VERIFICATION_REQUIRED)
                        length = win32file.GetOverlappedResult(pipe, operation, False)
                        if not length:
                            raise VaultError(VaultErrorCode.INVALID)
                        result.reveal().extend(data[:length])
                    finally:
                        finish_io(pipe, operation)
                        operation.hEvent.Close()
                return Secret(bytes(result.reveal()))

            size = struct.unpack("<I", read(4).reveal())[0]
            if not 2 <= size <= 2_100_000:
                raise VaultError(VaultErrorCode.INVALID)
            value = Secret(json.loads(read(size).reveal()))
            if type(value.reveal()) is not dict or set(value.reveal()) != set(fields):
                raise VaultError(VaultErrorCode.INVALID)
            return value
        finally:
            finish_io(pipe, pending)
            pipe.Close()
            pending.hEvent.Close()
            if group is not None:
                group.Close()
            if handle is not None:
                handle.Close()


def cancel_io(handle):
    import ctypes

    dll = ctypes.WinDLL("kernel32", use_last_error=True)
    dll.CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    dll.CancelIoEx(int(handle), None)


def finish_io(handle, operation):
    import win32file

    cancel_io(handle)
    try:
        win32file.GetOverlappedResult(handle, operation, True)
    except Exception:
        pass  # Cancelled/unqueued operations have no payload to publish.
