"""Private static-AWS signing for one installed Bedrock Converse endpoint."""

from datetime import datetime, timezone
import hashlib
import hmac
import re
from urllib.parse import quote, urlsplit

from .secrets import Secret
from .use_errors import CredentialUseError, UseCode


def endpoint_region(endpoint):
    parsed = urlsplit(endpoint)
    match = re.fullmatch(
        r"bedrock-runtime\.([a-z]{2}(?:-[a-z]+)+-\d)\.amazonaws\.com", parsed.netloc
    )
    if not match or not re.fullmatch(r"/model/[A-Za-z0-9_.:-]+/converse", parsed.path):
        raise ValueError("invalid_bedrock_helper")
    return match[1]


def signing_headers(endpoint, body: bytes, fields: Secret):
    """No session-token flow here: generated AWS credentials retain their owner.

    Canonical request/signing-key derivation follow AWS SigV4. The endpoint has
    no query, encoded aliases, consumer path parameters or alternate AWS service.
    """
    region = endpoint_region(endpoint)
    selected = Secret(
        {key: fields.reveal()[key] for key in ("access_key_id", "secret_access_key")}
    )
    if not re.fullmatch(
        r"[A-Z0-9]{16,128}", selected.reveal()["access_key_id"]
    ) or not re.fullmatch(
        r"[A-Za-z0-9/+=]{16,256}", selected.reveal()["secret_access_key"]
    ):
        raise CredentialUseError(UseCode.DENIED)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    parsed = urlsplit(endpoint)
    signed = "content-type;host;x-amz-content-sha256;x-amz-date"
    digest = hashlib.sha256(body).hexdigest()
    canonical = Secret(
        "\n".join(
            (
                "POST",
                quote(parsed.path, safe="/~"),
                "",
                f"content-type:application/json\nhost:{parsed.netloc}\nx-amz-content-sha256:{digest}\nx-amz-date:{stamp}\n",
                signed,
                digest,
            )
        )
    )
    scope = f"{date}/{region}/bedrock/aws4_request"
    message = Secret(
        f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n"
        + hashlib.sha256(canonical.reveal().encode()).hexdigest()
    )
    key = Secret(("AWS4" + selected.reveal()["secret_access_key"]).encode())
    for part in (date, region, "bedrock", "aws4_request"):
        key = Secret(hmac.digest(key.reveal(), part.encode(), "sha256"))
    signature = Secret(
        hmac.new(key.reveal(), message.reveal().encode(), "sha256").hexdigest()
    )
    return Secret(
        {
            "Authorization": f"AWS4-HMAC-SHA256 Credential={selected.reveal()['access_key_id']}/{scope}, SignedHeaders={signed}, Signature={signature.reveal()}",
            "x-amz-date": stamp,
            "x-amz-content-sha256": digest,
        }
    ), selected
