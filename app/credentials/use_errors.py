"""Public helper errors discard secret-bearing traceback frames and contexts."""

from enum import Enum
from functools import wraps

from .contracts import IsolationUnavailable
from .directory import IdentityError
from .errors import VaultError, VaultErrorCode


class UseCode(str, Enum):
    DENIED = "credential_use_denied"
    EXPIRED = "credential_grant_expired"
    CAPABILITY = "credential_capability_invalid"
    ISOLATION = "credential_isolation_unavailable"
    VERIFICATION = "owner_verification_required"
    LOCKED = "vault_locked"
    CHANGED = "credential_changed"
    UNAVAILABLE = "credential_unavailable"
    HELPER = "credential_helper_failed"
    LIMIT = "credential_use_limit"
    INTERRUPTED = "credential_use_interrupted"
    BUSY = "credential_busy"


class CredentialUseError(RuntimeError):
    def __init__(self, code: UseCode):
        self.code = code
        super().__init__(code.value)


def use_boundary(operation):
    @wraps(operation)
    def sanitized(*args, **kwargs):
        interrupted = None
        try:
            return operation(*args, **kwargs)
        except CredentialUseError as error:
            code = error.code
        except IsolationUnavailable:
            code = UseCode.ISOLATION
        except IdentityError:
            code = UseCode.DENIED
        except VaultError as error:
            code = {
                VaultErrorCode.LOCKED: UseCode.LOCKED,
                VaultErrorCode.CONFLICT: UseCode.CHANGED,
                VaultErrorCode.VERIFICATION_REQUIRED: UseCode.VERIFICATION,
                VaultErrorCode.SCOPE_DENIED: UseCode.DENIED,
            }.get(error.code, UseCode.UNAVAILABLE)
        except Exception:
            code = UseCode.HELPER
        except (KeyboardInterrupt, SystemExit, GeneratorExit) as error:
            interrupted = type(error)
        except BaseException:
            code = UseCode.INTERRUPTED
        # Outside the except block: diagnostic loggers must not see inner frames.
        if interrupted is SystemExit:
            raise SystemExit(1) from None
        if interrupted is not None:
            raise interrupted() from None
        raise CredentialUseError(code) from None

    return sanitized
