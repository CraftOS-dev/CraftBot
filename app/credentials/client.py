"""Secret-free Windows client, also copied into isolated code snapshots.

No vault imports, key resolver, HTTP transport or configurable server address.
The pipe must be owned by SYSTEM; unprivileged squatters cannot forge that
kernel owner. No SCM privileges or session/bridge tokens are needed in a sandbox.
"""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import json
import os
import struct
import time

PIPE = r"\\.\pipe\LOCAL\CraftBot.Credentials.v1"
SERVICE = "CraftBotCredentialHost"


class CredentialHostUnavailable(RuntimeError):
    pass


def _dlls():
    if os.name != "nt":
        raise CredentialHostUnavailable("credential_host_unavailable")
    kernel = C.WinDLL("kernel32", use_last_error=True)
    advapi = C.WinDLL("advapi32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        W.LPCWSTR,
        W.DWORD,
        W.DWORD,
        C.c_void_p,
        W.DWORD,
        W.DWORD,
        W.HANDLE,
    ]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.GetNamedPipeServerProcessId.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    kernel.ReadFile.argtypes = [
        W.HANDLE,
        C.c_void_p,
        W.DWORD,
        C.POINTER(W.DWORD),
        C.c_void_p,
    ]
    kernel.WriteFile.argtypes = kernel.ReadFile.argtypes
    kernel.CloseHandle.argtypes = [W.HANDLE]
    advapi.GetSecurityInfo.argtypes = [
        W.HANDLE,
        C.c_int,
        W.DWORD,
        C.POINTER(C.c_void_p),
        C.c_void_p,
        C.c_void_p,
        C.c_void_p,
        C.POINTER(C.c_void_p),
    ]
    advapi.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    kernel.LocalFree.argtypes = [C.c_void_p]
    return kernel, advapi


def _require_system_pipe(kernel, advapi, handle):
    owner, descriptor = C.c_void_p(), C.c_void_p()
    text = W.LPWSTR()
    try:
        if (
            advapi.GetSecurityInfo(
                handle, 6, 1, C.byref(owner), None, None, None, C.byref(descriptor)
            )
            != 0
            or not advapi.ConvertSidToStringSidW(owner, C.byref(text))
            or text.value != "S-1-5-18"
        ):
            raise CredentialHostUnavailable("credential_host_identity_mismatch")
    finally:
        if text:
            kernel.LocalFree(text)
        if descriptor:
            kernel.LocalFree(descriptor)


def _request(operation: str, **parameters):
    """Only metadata/references/capabilities. Context comes from the kernel peer."""
    handle = None
    try:
        data = json.dumps({"op": operation, **parameters}, ensure_ascii=True).encode(
            "utf-8"
        )
        if len(data) > 65536 or "op" in parameters:
            raise CredentialHostUnavailable("credential_request_invalid")
        kernel, advapi = _dlls()
        # Exact data rights, not GENERIC_WRITE/FILE_CREATE_PIPE_INSTANCE.
        # Identification SQOS prevents impersonation by a squatting server.
        deadline = time.monotonic() + 305
        while True:
            handle = kernel.CreateFileW(
                PIPE, 3 | 0x120000, 0, None, 3, 0x100000 | 0x10000, None
            )
            if handle != W.HANDLE(-1).value:
                break
            handle = None
            # A missing service fails immediately. A busy protected host may be
            # running an owner prompt or HTTPS operation (bounded by its 120s
            # watchdog); polling controllers must not fail after five seconds.
            if C.get_last_error() != 231 or time.monotonic() >= deadline:
                raise CredentialHostUnavailable("credential_host_unavailable")
            time.sleep(0.05)
        server = W.DWORD()
        if (
            not kernel.GetNamedPipeServerProcessId(handle, C.byref(server))
            or not server.value
        ):
            raise CredentialHostUnavailable("credential_host_identity_mismatch")
        _require_system_pipe(kernel, advapi, handle)
        transferred = W.DWORD()
        frame = struct.pack("<I", len(data)) + data
        if not kernel.WriteFile(
            handle, frame, len(frame), C.byref(transferred), None
        ) or transferred.value != len(frame):
            raise CredentialHostUnavailable("credential_host_unavailable")

        def read(size):
            result = bytearray()
            while len(result) < size:
                buffer = C.create_string_buffer(size - len(result))
                count = W.DWORD()
                if (
                    not kernel.ReadFile(
                        handle, buffer, len(buffer), C.byref(count), None
                    )
                    or not count.value
                ):
                    raise CredentialHostUnavailable("credential_host_unavailable")
                result.extend(buffer.raw[: count.value])
            return bytes(result)

        size = struct.unpack("<I", read(4))[0]
        if not 2 <= size <= 65536:
            raise CredentialHostUnavailable("credential_response_invalid")
        value = json.loads(read(size))
        if value.get("ok") is not True:
            code = value.get("error", "credential_use_denied")
            if code not in {
                "credential_use_denied",
                "credential_grant_expired",
                "credential_capability_invalid",
                "credential_isolation_unavailable",
                "owner_verification_required",
                "vault_locked",
                "credential_changed",
                "credential_unavailable",
                "credential_helper_failed",
                "credential_use_limit",
                "credential_use_interrupted",
                "credential_busy",
            }:
                code = "credential_use_denied"
            raise CredentialHostUnavailable(code)
        return value["result"]
    except CredentialHostUnavailable as error:
        code = str(error)
    except Exception:
        code = "credential_host_unavailable"
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
    raise CredentialHostUnavailable(code) from None


def request(operation: str, **parameters):
    deadline = time.monotonic() + 800
    while True:
        try:
            return _request(operation, **parameters)
        except CredentialHostUnavailable as error:
            if (
                str(error) != "credential_busy"
                or operation
                not in ("launch", "request_use", "authorize_grant", "start_use_staged")
                or time.monotonic() >= deadline
            ):
                raise
        time.sleep(0.1)


def use(
    helper: str,
    operation: str,
    credential_id: str | None = None,
    *,
    credential_version=None,
    payload=None,
):
    staged = payload is None or type(payload) is dict and set(payload) == {"body"}
    try:
        if staged:
            serialized = json.dumps(
                payload["body"] if payload is not None else None,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
            )
            if len(serialized) > 32_000_000:
                raise CredentialHostUnavailable("credential_use_limit")
            for offset in range(0, len(serialized), 8000):
                chunk = serialized[offset : offset + 8000]
                request(
                    "upload_payload_part",
                    offset=offset,
                    data=chunk,
                    done=offset + len(chunk) == len(serialized),
                )
        return _use(
            helper, operation, credential_id, credential_version, payload, staged
        )
    except BaseException:
        if staged:
            try:
                request("discard_payload")
            except Exception:
                pass
        raise


def _use(helper, operation, credential_id, credential_version, payload, staged):
    capability = request(
        "request_use",
        helper=helper,
        operation=operation,
        credential_id=credential_id,
        **(
            {"credential_version": credential_version}
            if credential_version is not None
            else {}
        ),
    )
    if staged:
        request("start_use_staged", capability=capability["capability"])
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            status = request("operation_status")
            if status["done"]:
                if status.get("error"):
                    raise CredentialHostUnavailable(status["error"])
                return {"outcome": status.get("outcome", "completed")}
            time.sleep(0.05)
        raise CredentialHostUnavailable("credential_operation_timeout")
    raise CredentialHostUnavailable("credential_request_invalid")


def operations():
    """Page the public names without overflowing the bounded pipe frame."""
    result, offset = [], 0
    while offset <= 1024:
        page = request("operations", offset=offset)
        result.extend(page["operations"])
        if not page["more"]:
            return result
        offset += 32
    raise CredentialHostUnavailable("credential_response_invalid")


def find():
    result, offset = [], 0
    while offset <= 4096:
        page = request("find", offset=offset)
        result.extend(page["offers"])
        if not page["more"]:
            return result
        offset += 8
    raise CredentialHostUnavailable("credential_response_invalid")


def complete(result):
    return request("complete", result=result)


def action_profile():
    """Owner-selected service preference; never read from action/bundle input."""
    from uuid import UUID

    value = request("action_profile")["profile_id"]
    return str(UUID(value)) if value is not None else None


def request_entry(helper: str, operation: str, account: str):
    """Ask the owner for protected entry; returns a reference, never values."""
    return request("request_entry", helper=helper, operation=operation, account=account)


def use_json(helper, operation, credential_id, *, credential_version, body=None):
    """For isolated workers only. Releases bounded, host-sanitized output."""
    use(
        helper,
        operation,
        credential_id,
        credential_version=credential_version,
        payload={"body": body},
    )
    result = request("read_response", offset=0)
    chunks, offset = [], 0
    length = result["length"]
    if type(length) is not int or not 0 <= length <= 96_000_000:
        raise CredentialHostUnavailable("credential_response_invalid")
    while offset < length:
        chunk = result["chunk"]
        if not isinstance(chunk, str) or not chunk or len(chunk) > 8000:
            raise CredentialHostUnavailable("credential_response_invalid")
        chunks.append(chunk)
        offset += len(chunk)
        if offset < length:
            result = request("read_response", offset=offset)
    return {
        "status": result["status"],
        "content_type": result["content_type"],
        "body": "".join(chunks),
    }
