"""Bound DNS waits without passing secret-bearing contexts to resolver threads."""

import queue
import socket
from threading import BoundedSemaphore, Thread

_slots = BoundedSemaphore(4)


def _lookup(host, port, output):
    try:
        try:
            result = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except Exception:
            result = None
        output.put_nowait(result)
    finally:
        _slots.release()


def resolve(host, port):
    if not _slots.acquire(blocking=False):
        raise TimeoutError("credential_dns_busy")
    output = queue.Queue(maxsize=1)
    try:
        Thread(target=_lookup, args=(host, port, output), daemon=True).start()
    except BaseException:
        _slots.release()
        raise
    try:
        result = output.get(timeout=10)
    except queue.Empty:
        raise TimeoutError("credential_dns_timeout") from None
    if result is None:
        raise OSError("credential_dns_unavailable")
    return result
