"""SDK HTTP adapter containing only source references and safe provider data."""

import json

import httpx

from .client import CredentialHostUnavailable, request as host_request
from .invocation import invoke, open_response
from .references import parse


def installed_model_helpers():
    """Read sealed metadata; custom settings never install a destination policy."""
    helpers, offset = [], 0
    while offset <= 1024:
        result = host_request("catalog", offset=offset)
        helpers.extend(item for item in result["helpers"] if item["type"] == "json")
        if not result["more"]:
            return helpers
        offset = result.get("next_offset", offset + 8)
    raise CredentialHostUnavailable("credential_response_invalid")


class VaultModelTransport(httpx.BaseTransport):
    def __init__(self, provider, reference, resolve_reference=None):
        parse(reference)
        self.provider, self.reference = provider, reference
        self.resolve_reference = resolve_reference
        self.routes = [
            item
            for item in installed_model_helpers()
            if item["helper"] == f"model_{provider}"
        ]
        if not self.routes:
            raise CredentialHostUnavailable("credential_model_helper_unavailable")

    def handle_request(self, request):
        # Exact full URL: query changes, custom endpoints and redirects require
        # their own reviewed descriptor, never a client-selected destination.
        from .route_policy import match_route

        matched = match_route(self.routes, request.method, str(request.url))
        if matched is None:
            raise CredentialHostUnavailable("credential_destination_denied")
        route, path, query = matched
        reference = (
            self.resolve_reference() if self.resolve_reference else self.reference
        )
        parse(reference)
        try:
            raw = request.read()
            body = (
                multipart_data(raw, request.headers.get("Content-Type", ""))
                if route.get("request_format") == "multipart"
                else json.loads(raw)
                if raw
                else None
            )
        except Exception:
            raise CredentialHostUnavailable("credential_request_invalid") from None
        if route.get("envelope"):
            body = {"path": path, "query": query, "data": body}
        response = open_response(
            reference,
            route["helper"],
            route["operation"],
            body,
            subject=f"{self.provider} model: {route['operation']}",
        )
        if route.get("response_format") == "binary" and 200 <= response.status < 300:
            import base64

            try:
                media = json.loads("".join(response))
                return httpx.Response(
                    response.status,
                    content=base64.b64decode(media["data"], validate=True),
                    headers={"Content-Type": media["media_type"]},
                    request=request,
                )
            finally:
                response.close()
        return httpx.Response(
            response.status,
            headers={"Content-Type": response.content_type},
            stream=CredentialByteStream(response),
            request=request,
        )


class CredentialByteStream(httpx.SyncByteStream):
    def __init__(self, response):
        self.response = response

    def __iter__(self):
        for part in self.response:
            yield part.encode("utf-8")

    def close(self):
        self.response.close()


def multipart_data(raw, content_type):
    from email.parser import BytesParser
    from email.policy import default
    import base64

    if len(raw) > 32_000_000:
        raise ValueError("credential_use_limit")
    message = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        + raw
    )
    if not message.is_multipart():
        raise ValueError("credential_request_invalid")
    fields, files = {}, []
    for part in message.iter_parts():
        field = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True)
        if part.get_filename() is not None:
            files.append(
                {
                    "field": field,
                    "content_type": part.get_content_type(),
                    "data": base64.b64encode(data).decode("ascii"),
                    "filename": part.get_filename(),
                }
            )
        else:
            if field in fields:
                raise ValueError("credential_request_invalid")
            fields[field] = data.decode("utf-8")
    return {"fields": fields, "files": files}


def http_client(provider, reference, resolve_reference=None):
    return httpx.Client(
        transport=VaultModelTransport(provider, reference, resolve_reference),
        follow_redirects=False,
        trust_env=False,
        timeout=240,
    )


def openai_client(reference):
    """Host injection for an SDK client containing only a saved reference."""
    parse(reference)
    from openai import OpenAI

    return OpenAI(api_key="vault-managed", http_client=http_client("openai", reference))


def requests_response(provider, reference, method, url, body=None):
    """Adapt the existing REST consumers without handing them a source key.

    None means an unchanged legacy/generated-token path. Host errors propagate;
    a reference must never fall back to the ordinary network transport.
    """
    from .references import is_reference

    if not is_reference(reference):
        return None
    from .route_policy import match_route

    matched = match_route(
        [r for r in installed_model_helpers() if r["helper"] == f"model_{provider}"],
        method,
        url,
    )
    if matched is None:
        raise CredentialHostUnavailable("credential_destination_denied")
    route, path, query = matched
    if route.get("envelope"):
        body = {"path": path, "query": query, "data": body}
    result = invoke(
        reference,
        route["helper"],
        route["operation"],
        body,
        subject=f"{provider}: {route['operation']}",
    )
    import requests

    response = requests.Response()
    response.status_code, response.url = result["status"], url
    response.headers["Content-Type"] = result["content_type"]
    if route.get("response_format") == "binary" and 200 <= result["status"] < 300:
        import base64

        media = json.loads(result["body"])
        response._content = base64.b64decode(media["data"], validate=True)
        response.headers["Content-Type"] = media["media_type"]
    else:
        response._content = result["body"].encode("utf-8")
    response._content_consumed = True
    response.encoding = "utf-8"
    return response


class VaultBedrockClient:
    """Converse facade: only a reference and model/region data, no boto3 keys."""

    def __init__(self, reference, region):
        parse(reference)
        self.reference, self.region = reference, region

    def converse(self, **parameters):
        import base64
        import re

        model = parameters.get("modelId")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", model):
            raise CredentialHostUnavailable("credential_destination_denied")
        endpoint = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{model}/converse"
        route = next(
            (
                r
                for r in installed_model_helpers()
                if r["helper"] == "model_bedrock"
                and r["method"] == "POST"
                and r["endpoint"] == endpoint
            ),
            None,
        )
        if route is None:
            raise CredentialHostUnavailable("credential_destination_denied")

        def wire(value):
            if isinstance(value, bytes):
                return base64.b64encode(value).decode("ascii")
            if type(value) is dict:
                return {key: wire(child) for key, child in value.items()}
            if type(value) is list:
                return [wire(child) for child in value]
            return value

        response = invoke(
            self.reference,
            route["helper"],
            route["operation"],
            wire({key: value for key, value in parameters.items() if key != "modelId"}),
            subject="Bedrock Converse",
        )
        if not 200 <= response["status"] < 300:
            raise CredentialHostUnavailable("credential_operation_failed")
        result = json.loads(response["body"])
        if type(result) is not dict:
            raise CredentialHostUnavailable("credential_response_invalid")
        return result
