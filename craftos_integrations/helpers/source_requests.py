"""Optional secret-free HTTP routing; this context is never vault authority."""

from contextvars import ContextVar
from contextlib import contextmanager

override = ContextVar("source_request_adapter", default=None)


@contextmanager
def using(adapter):
    token = override.set(adapter)
    try:
        yield
    finally:
        override.reset(token)
