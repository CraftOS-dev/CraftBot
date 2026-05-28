"""Logger access for the integrations package.

Returns a proxy that resolves to the logger configured via
``configure(logger=...)`` at *call time*, falling back to a stdlib logger
when none has been configured. Resolving lazily matters because most
modules call ``get_logger(__name__)`` at import time — before the host
has had a chance to call ``configure()`` — and we want the host's
logger (e.g. loguru) to be used for every message regardless of import
order.

    from .logger import get_logger
    logger = get_logger(__name__)
"""

from __future__ import annotations

import logging


class _LoggerProxy:
    """Forward attribute access to the live host logger or a stdlib fallback.

    Each call (``logger.info(...)``, etc.) re-checks ``ConfigStore.logger``
    so a host that calls ``configure(logger=...)`` AFTER modules have
    already imported their logger still sees its messages routed correctly.
    """

    __slots__ = ("_name", "_fallback")

    def __init__(self, name: str) -> None:
        self._name = name
        self._fallback: logging.Logger | None = None

    def _resolve(self):
        from .config import ConfigStore

        if ConfigStore.logger is not None:
            return ConfigStore.logger
        if self._fallback is None:
            lg = logging.getLogger(self._name)
            if not lg.handlers:
                logging.basicConfig(
                    level=logging.INFO, format="%(levelname)s: %(message)s"
                )
            self._fallback = lg
        return self._fallback

    def __getattr__(self, attr):
        return getattr(self._resolve(), attr)


def get_logger(name: str) -> "_LoggerProxy":
    return _LoggerProxy(name)
