"""Host-only cancellable execution and sanitized stream output."""

from threading import Event, Lock, Thread
from .helpers import JsonResult
from .use_errors import CredentialUseError, UseCode
from .wire import MAX_OUTPUT


class OperationJob:
    def __init__(self, operation, *, budget=None, grant_id=None):
        self.cancelled, self.done = Event(), Event()
        self.dispatched = Event()
        self.lock = Lock()
        self.status, self.content_type, self.body, self.error = None, None, "", None
        self.result = None
        self.budget, self.grant_id, self.charged = budget, grant_id, 0
        self.thread = Thread(target=self._run, args=(operation,), daemon=True)

    def start(self, status, content_type):
        with self.lock:
            self.status, self.content_type = status, content_type

    def emit(self, text):
        if self.cancelled.is_set():
            raise CredentialUseError(UseCode.INTERRUPTED)
        with self.lock:
            if len(self.body) + len(text) > MAX_OUTPUT:
                raise CredentialUseError(UseCode.LIMIT)
            self._charge(len(text))
            self.body += text

    def _charge(self, size):
        if self.cancelled.is_set():
            raise CredentialUseError(UseCode.INTERRUPTED)
        if self.budget is not None:
            self.budget.change(size)
        self.charged += size

    def close(self):
        self.cancelled.set()
        with self.lock:
            if self.budget is not None:
                self.budget.change(-self.charged)
            self.charged, self.body, self.result = 0, "", None

    def _run(self, operation):
        try:
            self.result = operation(self)
            if type(self.result) is JsonResult:
                with self.lock:
                    if self.status is None:
                        self._charge(len(self.result.body))
                        self.status, self.content_type, self.body = (
                            self.result.status,
                            self.result.content_type,
                            self.result.body,
                        )
        except CredentialUseError as error:
            self.error = (
                UseCode.INTERRUPTED if self.cancelled.is_set() else error.code
            ).value
        except BaseException:
            self.error = (
                UseCode.INTERRUPTED if self.cancelled.is_set() else UseCode.HELPER
            ).value
        finally:
            self.done.set()

    def snapshot(self, offset=0):
        with self.lock:
            if type(offset) is not int or not 0 <= offset <= len(self.body):
                raise CredentialUseError(UseCode.DENIED)
            return {
                "status": self.status,
                "content_type": self.content_type,
                "length": len(self.body),
                "chunk": self.body[offset : offset + 4000],
                "done": self.done.is_set(),
                "error": self.error,
            }


class OutputBudget:
    """Aggregate retained output across all isolated workers, in characters."""

    def __init__(self, maximum=192_000_000):
        self.maximum, self.used, self.lock = maximum, 0, Lock()

    def change(self, delta):
        with self.lock:
            if self.used + delta > self.maximum:
                raise CredentialUseError(UseCode.LIMIT)
            self.used = max(0, self.used + delta)
