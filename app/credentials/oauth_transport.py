"""Execute confidential-client exchanges without releasing client secrets.

Generated access/refresh tokens return to the existing provider and persistence
callback. The vault holds only the manually configured client secret.
"""

import json
import httpx

from .client import CredentialHostUnavailable
from .invocation import invoke
from .model_transport import installed_model_helpers
from .references import parse


def request(method, url, *, reference, body, basic=False, json_body=False):
    parse(reference)
    protocol = "oauth_basic" if basic else "oauth_json" if json_body else "oauth_form"
    route = next(
        (
            r
            for r in installed_model_helpers()
            if r["helper"].startswith("oauth_")
            and r["endpoint"] == url
            and r["method"] == method.upper()
            and r.get("protocol") == protocol
        ),
        None,
    )
    if route is None:
        raise CredentialHostUnavailable("credential_destination_denied")
    public_body = {k: v for k, v in body.items() if k != "client_secret"}
    response = invoke(
        reference,
        route["helper"],
        route["operation"],
        {"path": {}, "query": {}, "data": public_body},
        subject="OAuth exchange: " + route["helper"],
    )
    # Only sanitized JSON; no cookie, redirect or provider headers.
    json.loads(response["body"])
    return httpx.Response(
        response["status"],
        content=response["body"].encode(),
        headers={"Content-Type": "application/json"},
    )
