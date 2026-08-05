"""App-layer error catalogue.

`app/errors/codebook.py` — curated codes and `make_error()`/`verbatim()`/
`error_from_exception()` for building a classified `ErrorInfo`.
`app/errors/envelope.py` — `error_fields()`, the snake_case wire-tag block
shared by every non-chat transport (action outputs, browser_adapter WS/REST,
slash-command events).
`app/errors/actions.py` — the exec-safe facade `@action` handler bodies
import from (function-local import required — see that module's docstring).
`app/errors/web.py` — `error_json_response()` for aiohttp REST handlers.

Naming rule (see envelope.py for the full rationale): new error envelopes
are snake_case; `ChatMessage.to_dict()`'s camelCase `errorCategory`/
`errorCode`/`errorSeverity` and `error_json_response`'s snake_case
`error_category`/`error_code` are both pre-existing, shipped wire contracts
and are never renamed to "harmonize" them.
"""

from app.errors.codebook import CatalogError, error_from_exception, make_error, verbatim

__all__ = ["CatalogError", "make_error", "verbatim", "error_from_exception"]
