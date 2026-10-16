"""Host-derived request review. No credential or generated session disclosure."""

import hashlib
import json
from urllib.parse import urlsplit

from .broker import canonical_request
from .helpers import HttpsJsonOperation
from .route_policy import target
from .use_errors import CredentialUseError, UseCode


def review_request(specification, payload, *, repeat=False):
    _, digest = canonical_request(payload)
    body = payload["body"]
    destination = specification.endpoint
    if type(specification) is HttpsJsonOperation and specification.envelope:
        if type(body) is not dict:
            raise CredentialUseError(UseCode.DENIED)
        parsed = urlsplit(destination)
        destination = f"{parsed.scheme}://{parsed.netloc}" + target(
            destination, specification.path_fields, body.get("path")
        )

    def visible(value, depth=0):
        if depth > 24:
            raise CredentialUseError(UseCode.LIMIT)
        if type(value) is dict:
            # Authentication/session material stays at its existing owner. It
            # is bound by the request hash, but never displayed or persisted.
            return {
                k: "[authentication value hidden]"
                if k.lower()
                in {
                    "session",
                    "authorization",
                    "access_token",
                    "access_token_secret",
                    "refresh_token",
                    "session_string",
                    "password",
                    "api_hash",
                    "app_secret",
                }
                else visible(v, depth + 1)
                for k, v in value.items()
            }
        if type(value) is list:
            return [visible(v, depth + 1) for v in value]
        if isinstance(value, str) and len(value) > 8192:
            return {
                "content_omitted": True,
                "characters": len(value),
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }
        return value

    details = {
        "Destination": destination,
        "Method": getattr(specification, "method", "POST"),
        "Request SHA256": digest.hex(),
        "Scope": "Repeated GET; resource/query parameters may change within this installed route until lease expiry, lock or revocation."
        if repeat
        else "ONE attempt of this exact request. Changing any parameter requires new approval.",
        "Parameters": json.dumps(
            visible(body), ensure_ascii=True, sort_keys=True, indent=2
        ),
        "Content notice": "Large values over 8192 characters are represented by length and SHA256; approving includes that exact content. Authentication values are hidden.",
    }
    # Do not truncate destinations, recipients or parameter lists. A request too
    # large for complete meaningful review fails closed before owner approval.
    if len(json.dumps(details, ensure_ascii=True).encode("utf-8")) > 1_900_000:
        raise CredentialUseError(UseCode.LIMIT)
    return details
