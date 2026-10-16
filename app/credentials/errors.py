"""Stable errors: never include paths, provider responses or secret values."""

from enum import Enum
from functools import wraps


class VaultErrorCode(str, Enum):
    LOCKED = "locked"
    VERIFICATION_REQUIRED = "owner_verification_required"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    UNREADABLE = "vault_unreadable"
    IO = "vault_io_error"
    INVALID = "credential_invalid"
    CONFLICT = "credential_conflict"
    NOT_FOUND = "credential_not_found"
    ALREADY_EXISTS = "vault_already_exists"
    SCOPE_DENIED = "scope_denied"


class VaultError(RuntimeError):
    def __init__(self, code: VaultErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def sanitized_errors(operation):
    """Drop inner frames as well as messages at the secret-bearing boundary.

    `raise ... from None` inside a context manager is insufficient: loguru's
    diagnose mode can print the original exception from contextlib.__exit__'s
    `value` local. Raise a fresh error OUTSIDE the except block, so no such
    frames or exception contexts reach callers' diagnostic logs.
    """

    @wraps(operation)
    def sanitized(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except VaultError as error:
            code = error.code
        except Exception:
            code = VaultErrorCode.IO
        raise VaultError(code) from None

    return sanitized
