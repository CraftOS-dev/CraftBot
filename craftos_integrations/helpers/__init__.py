"""Internal helpers for integration authors.

These are package-internal utilities used by integration files
(``craftos_integrations/providers/<name>.py``). They're not part of the
public consumer API — host applications interact with the package via the
top-level facade (``configure``, ``get_client``, ``list_metadata``, etc.).

Submodules:
    http: thin wrappers around httpx that handle the standard REST
          ``status_code → {ok, result} | {error, details}`` envelope shape.
    result: ``Result`` / ``Ok`` / ``Err`` TypedDict aliases for the envelope —
            use as return annotations for static type-checking benefits.
"""

from .http import arequest, request
from .result import Err, Ok, Result

__all__ = [
    "Err",
    "Ok",
    "Result",
    "arequest",
    "request",
]
