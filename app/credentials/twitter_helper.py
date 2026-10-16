"""Host-only OAuth 1.0a signing for sealed Twitter REST operations.

App key/secret remain in the vault. The generated user token pair is supplied
per operation by its existing account owner; no signer or header is exposed.
"""

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qsl, quote

from .secrets import Secret
from .use_errors import CredentialUseError, UseCode


def authorization(url, method, query, fields, session):
    if type(session) is not dict or set(session) != {
        "access_token",
        "access_token_secret",
    }:
        raise CredentialUseError(UseCode.DENIED)
    private = Secret({**fields.reveal(), **session})
    if set(fields.reveal()) != {"api_key", "api_secret"} or any(
        not isinstance(v, str)
        or not 1 <= len(v) <= 4096
        or any(ord(c) < 33 or ord(c) > 126 for c in v)
        for v in private.reveal().values()
    ):
        raise CredentialUseError(UseCode.DENIED)
    oauth = Secret(
        {
            "oauth_consumer_key": private.reveal()["api_key"],
            "oauth_token": private.reveal()["access_token"],
            "oauth_nonce": secrets.token_hex(16),
            "oauth_timestamp": str(int(time.time())),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_version": "1.0",
        }
    )
    pairs = parse_qsl(query, keep_blank_values=True)
    if any(k.startswith("oauth_") for k, _ in pairs):
        raise CredentialUseError(UseCode.DENIED)
    normalized = Secret(
        "&".join(
            k + "=" + v
            for k, v in sorted(
                (quote(k, safe=""), quote(v, safe=""))
                for k, v in [*pairs, *oauth.reveal().items()]
            )
        )
    )
    base = Secret(
        "&".join(quote(v, safe="") for v in (method, url, normalized.reveal()))
    )
    key = Secret(
        quote(private.reveal()["api_secret"], safe="")
        + "&"
        + quote(private.reveal()["access_token_secret"], safe="")
    )
    signature = Secret(
        base64.b64encode(
            hmac.new(
                key.reveal().encode(), base.reveal().encode(), hashlib.sha1
            ).digest()
        ).decode()
    )
    oauth.reveal()["oauth_signature"] = signature.reveal()
    header = Secret(
        "OAuth "
        + ", ".join(
            quote(k, safe="") + '="' + quote(v, safe="") + '"'
            for k, v in sorted(oauth.reveal().items())
        )
    )
    return header, Secret(
        {
            **private.reveal(),
            "signature": signature.reveal(),
            "signing_key": key.reveal(),
        }
    )
