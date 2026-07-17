# -*- coding: utf-8 -*-
"""Package-local logger: loguru when available, stdlib otherwise.

The agentic package must stay importable from inside agent_core (see the
package docstring), so it cannot use app.logger (which pulls app.config);
every module here shares this fallback instead of repeating it.
"""

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger("app.agentic")

__all__ = ["logger"]
