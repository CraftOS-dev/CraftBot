# -*- coding: utf-8 -*-
"""
Flexible function-level logging:
- logs start
- logs success (with result)
- logs failure (with exception)
Allows custom message templates:
  {id}, {name}, {args}, {kwargs}, {result}, {exception}, {duration_ms}
"""

import logging
import time
import uuid
from functools import wraps

try:
    from agent_core.utils.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def log_events(
    name: str | None = None,
    *,
    on_start: str | None = None,
    on_success: str | None = None,
    on_failure: str | None = None,
):
    """
    Decorator to log function start, success, failure.
    Adds a unique ID per call for tracing.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            entry_id = uuid.uuid4().hex[:8]  # unique ID per call
            entry = name or fn.__name__

            # START LOG
            try:
                msg = (
                    on_start.format(id=entry_id, name=entry, args=args, kwargs=kwargs)
                    if on_start
                    else f"[{entry}] START id={entry_id} args={args} kwargs={kwargs}"
                )
            except Exception:
                msg = f"[{entry}] START id={entry_id} args={args} kwargs={kwargs}"
            logger.debug(msg)

            start = time.time()

            try:
                result = fn(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000

                # SUCCESS LOG (always include result)
                try:
                    msg = (
                        on_success.format(
                            id=entry_id,
                            name=entry,
                            args=args,
                            kwargs=kwargs,
                            result=result,
                            duration_ms=f"{duration_ms:.2f}",
                        )
                        if on_success
                        else f"[{entry}] END (success) id={entry_id} duration={duration_ms:.2f}ms result={result}"
                    )
                except Exception:
                    msg = f"[{entry}] END (success) id={entry_id} duration={duration_ms:.2f}ms result={result}"

                logger.debug(msg)
                return result

            except Exception as exc:
                duration_ms = (time.time() - start) * 1000

                # FAILURE LOG
                try:
                    msg = (
                        on_failure.format(
                            id=entry_id,
                            name=entry,
                            args=args,
                            kwargs=kwargs,
                            exception=exc,
                            duration_ms=f"{duration_ms:.2f}",
                        )
                        if on_failure
                        else (
                            f"[{entry}] END (FAILED) id={entry_id} duration={duration_ms:.2f}ms "
                            f"error={type(exc).__name__}: {exc}"
                        )
                    )
                except Exception:
                    msg = (
                        f"[{entry}] END (FAILED) id={entry_id} duration={duration_ms:.2f}ms "
                        f"error={type(exc).__name__}: {exc}"
                    )

                logger.error(msg)
                raise

        return wrapper
    return decorator
