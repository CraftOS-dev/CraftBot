"""Host-blind hook for vault references in confidential OAuth exchanges."""

import base64
from ..config import ConfigStore


def exchange(method, url, *, headers=None, json=None, data=None):
    body = json if json is not None else data
    basic = False
    reference = body.get("client_secret") if type(body) is dict else None
    authorization = next(
        (v for k, v in (headers or {}).items() if k.lower() == "authorization"), ""
    )
    if authorization.startswith("Basic "):
        try:
            client_id, candidate = (
                base64.b64decode(authorization[6:], validate=True)
                .decode()
                .split(":", 1)
            )
        except (ValueError, UnicodeError):
            candidate = None
        if isinstance(candidate, str) and candidate.startswith("craftbot-vault:"):
            reference, basic = candidate, True
            if type(body) is not dict:
                raise ValueError("credential_request_invalid")
            body = {**body, "client_id": client_id}
    if not isinstance(reference, str) or not reference.startswith("craftbot-vault:"):
        return None
    hook = ConfigStore.extras.get("source_oauth_request")
    if hook is None or type(body) is not dict:
        raise ValueError("credential_oauth_helper_unavailable")
    return hook(
        method,
        url,
        reference=reference,
        body=body,
        basic=basic,
        json_body=json is not None,
    )
