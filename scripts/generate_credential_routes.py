"""Regenerate reviewed REST route metadata from provider source, never live data.

This is a developer tool. Its output is checked in and sealed at installation;
no AST, provider code or mutable registry is evaluated by the protected host.
Review changes before packaging. Dynamic hosts and generic request paths fail.
"""

import ast
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

BASES = {
    "twitter": "https://api.twitter.com/2",
    "jira": "https://jira.example.invalid/rest/api/3",
    "github": "https://api.github.com",
    "figma": "https://api.figma.com",
    "slack": "https://slack.com/api",
    "discord": "https://discord.com/api/v10",
    "stripe": "https://api.stripe.com/v1",
    "notion": "https://api.notion.com/v1",
    "hubspot": "https://api.hubapi.com",
    "posthog": "https://us.posthog.com/api",
    "supabase": "https://api.supabase.com/v1",
    "line": "https://api.line.me/v2",
    "telegram_bot": "https://api.telegram.org",
    "whatsapp_business": "https://graph.facebook.com/v21.0",
}


def generate(repository):
    rows = []
    for provider, base in BASES.items():
        tree = ast.parse(
            (
                repository / "craftos_integrations/providers" / provider / "client.py"
            ).read_text(encoding="utf-8")
        )
        constants = {}

        def render(node, local, depth=0):
            if depth > 10:
                raise ValueError()
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                if node.id in constants:
                    return constants[node.id]
                if node.id in local:
                    try:
                        return render(local[node.id], {}, depth + 1)
                    except ValueError:
                        pass
                return ":" + node.id.lower()
            if isinstance(node, ast.JoinedStr):
                return "".join(
                    render(v.value, local, depth + 1)
                    if isinstance(v, ast.FormattedValue)
                    else render(v, local, depth + 1)
                    for v in node.values
                )
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                return render(node.left, local, depth + 1) + render(
                    node.right, local, depth + 1
                )
            if isinstance(node, ast.Attribute) and node.attr in (
                "phone_number_id",
                "project_id",
                "file_key",
                "folder_id",
                "team_id",
            ):
                return ":" + node.attr
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "file_key"
            ):
                return ":file_key"
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name == "_base_url" and provider == "jira":
                    return base
                if name == "_agile_base_url" and provider == "jira":
                    return "https://jira.example.invalid/rest/agile/1.0"
                if name == "_file_path":
                    return "/v1/files/:file_key" + (
                        render(node.args[1], local, depth + 1)
                        if len(node.args) > 1
                        else ""
                    )
                if name == "_proj" and provider == "posthog":
                    return (
                        base
                        + "/projects/:project_id/"
                        + render(node.args[0], local, depth + 1).lstrip("/")
                    )
                if name == "_api" and provider == "posthog":
                    return (
                        base + "/" + render(node.args[0], local, depth + 1).lstrip("/")
                    )
                if name == "_api_url" and provider == "telegram_bot":
                    return (
                        base + "/bot_TOKEN_/" + render(node.args[0], local, depth + 1)
                    )
                if name == "_messages_url" and provider == "whatsapp_business":
                    return base + "/:phone_number_id/messages"
                if (
                    name
                    in ("quote", "_segment", "_team", "_project", "_ref", "str", "int")
                    and node.args
                ):
                    return render(node.args[0], local, depth + 1)
            raise ValueError()

        for _ in range(3):
            for item in tree.body:
                if (
                    isinstance(item, ast.Assign)
                    and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)
                ):
                    try:
                        value = render(item.value, {})
                        if not value.startswith(":"):
                            constants[item.targets[0].id] = value
                    except ValueError:
                        pass
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            local = {
                item.targets[0].id: item.value
                for item in ast.walk(function)
                if isinstance(item, ast.Assign)
                and len(item.targets) == 1
                and isinstance(item.targets[0], ast.Name)
            }
            query = set()
            for item in ast.walk(function):
                if isinstance(item, ast.Dict):
                    query.update(
                        k.value
                        for k in item.keys
                        if isinstance(k, ast.Constant)
                        and isinstance(k.value, str)
                        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", k.value)
                    )
                if (
                    isinstance(item, ast.Subscript)
                    and isinstance(item.slice, ast.Constant)
                    and isinstance(item.slice.value, str)
                    and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", item.slice.value)
                ):
                    query.add(item.slice.value)
            for call in ast.walk(function):
                if not isinstance(call, ast.Call):
                    continue
                name = (
                    call.func.attr
                    if isinstance(call.func, ast.Attribute)
                    else call.func.id
                    if isinstance(call.func, ast.Name)
                    else ""
                )
                keywords = {kw.arg: kw.value for kw in call.keywords}
                implicit = {
                    "_get": "GET",
                    "_post": "POST",
                    "_put": "PUT",
                    "_patch": "PATCH",
                    "_delete": "DELETE",
                }
                try:
                    if name in implicit and call.args:
                        method = implicit[name]
                        url = render(call.args[0], local)
                    elif (
                        name in ("_telegram_acall", "_telegram_call_sync") and call.args
                    ):
                        method = "POST" if "json" in keywords else "GET"
                        url = render(call.args[0], local)
                    elif (
                        name
                        in (
                            "arequest",
                            "http_request",
                            "raw_request",
                            "raw_stream",
                            "_request",
                            "_slack_call",
                            "_slack_acall",
                            "_notion_call",
                            "_mgmt",
                        )
                        and len(call.args) >= 2
                        and isinstance(call.args[0], ast.Constant)
                    ):
                        method = call.args[0].value
                        url = render(call.args[1], local)
                    else:
                        continue
                    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                        continue
                    if not url.startswith("https://"):
                        selected = (
                            render(keywords["base"], local)
                            if "base" in keywords
                            else base
                        )
                        url = selected.rstrip("/") + "/" + url.lstrip("/")
                except (ValueError, KeyError):
                    continue
                parsed = urlsplit(url)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or ":" in parsed.netloc
                    or "?" in url
                    or "#" in url
                ):
                    continue
                params = re.findall(r"(?<=/):([a-z][a-z0-9_]*)", parsed.path)
                if (
                    len(set(params)) != len(params)
                    or any(
                        p
                        in (
                            "url",
                            "base",
                            "base_url",
                            "endpoint",
                            "resource",
                            "suffix",
                            "method",
                        )
                        for p in params
                    )
                    or parsed.path.startswith("/:")
                ):
                    continue
                fmt = (
                    "multipart"
                    if "files" in keywords
                    else "image"
                    if "content" in keywords
                    else "form"
                    if "data" in keywords
                    or provider == "stripe"
                    and method in ("POST", "PUT", "PATCH")
                    else "json"
                )
                auth_header, prefix = (
                    ("X-Figma-Token", "")
                    if provider == "figma"
                    else ("Authorization", "Bot ")
                    if provider == "discord"
                    else ("Authorization", "Bearer ")
                )
                row = {
                    "type": "json",
                    "helper": "integration_" + provider,
                    "operation": function.name.strip("_")[:40]
                    + "_"
                    + hashlib.sha256((method + url + fmt).encode()).hexdigest()[:8],
                    "kind": "api_key",
                    "endpoint": url,
                    "method": method,
                    "path_fields": params,
                    "query_fields": sorted(
                        query
                        | {"limit", "offset", "cursor", "page", "per_page", "expand"}
                    )[:128],
                    "envelope": True,
                    "request_format": fmt,
                    "auth_header": auth_header,
                    "auth_prefix": prefix,
                }
                if provider == "stripe":
                    row["header_fields"] = ["Idempotency-Key", "Stripe-Account"]
                if provider == "telegram_bot":
                    row["protocol"] = "telegram"
                if provider == "jira":
                    row.update(
                        kind="service_secret",
                        secret_field="api_token",
                        protocol="basic",
                    )
                if provider == "twitter":
                    if parsed.netloc != "api.twitter.com" or fmt != "json":
                        continue
                    row.update(
                        kind="service_secret",
                        secret_field="api_secret",
                        protocol="twitter_oauth1",
                    )
                    row["query_fields"] = sorted(
                        set(row["query_fields"])
                        | {"tweet.fields", "user.fields", "media.fields", "list.fields"}
                    )
                if not any(
                    r["helper"] == row["helper"]
                    and r["method"] == method
                    and r["endpoint"] == url
                    for r in rows
                ):
                    rows.append(row)

    # Finite resource families selected by existing client enum tables. Expand
    # them here; the host never accepts an arbitrary resource suffix.
    def extra(
        provider,
        method,
        suffix,
        *,
        query=(),
        response_format="json",
        request_format="json",
    ):
        import copy

        prototype = next(r for r in rows if r["helper"] == "integration_" + provider)
        row = copy.deepcopy(prototype)
        endpoint = suffix if suffix.startswith("https://") else BASES[provider] + suffix
        row.update(
            operation="reviewed_"
            + hashlib.sha256((method + endpoint + request_format).encode()).hexdigest()[
                :12
            ],
            endpoint=endpoint,
            method=method,
            path_fields=re.findall(r"(?<=/):([a-z][a-z0-9_]*)", endpoint),
            query_fields=list(query),
            request_format=request_format,
            response_format=response_format,
        )
        if response_format == "binary":
            row["max_response_bytes"] = 64_000_000
        if not any(
            r["helper"] == row["helper"]
            and r["method"] == method
            and r["endpoint"] == endpoint
            for r in rows
        ):
            rows.append(row)

    for resource in ("components", "component_sets", "styles"):
        extra(
            "figma",
            "GET",
            "/v1/teams/:team_id/" + resource,
            query=("page_size", "after", "before"),
        )
        extra("figma", "GET", "/v1/files/:file_key/" + resource)
    extra(
        "twitter",
        "POST",
        "https://upload.twitter.com/1.1/media/upload.json",
        request_format="multipart",
    )
    for path, method in (
        ("config/auth", "PATCH"),
        ("postgrest", "PATCH"),
        ("config/realtime", "PATCH"),
        ("config/storage", "PATCH"),
        ("config/database/postgres", "PUT"),
    ):
        for verb in ("GET", method):
            extra("supabase", verb, "/projects/:project_ref/" + path)
    extra("supabase", "GET", "/projects/:project_ref/types/typescript")
    extra(
        "whatsapp_business",
        "GET",
        "/:phone_number_id/whatsapp_business_profile",
        query=("fields",),
    )
    extra("whatsapp_business", "GET", "/:media_id")
    extra("whatsapp_business", "GET", "/:phone_number_id", query=("fields",))
    extra(
        "telegram_bot",
        "GET",
        "/bot_TOKEN_/getUpdates",
        query=("offset", "timeout", "allowed_updates", "limit"),
    )
    extra(
        "telegram_bot", "GET", "/file/bot_TOKEN_/:file_path", response_format="binary"
    )
    extra("slack", "POST", "/auth.test")
    extra(
        "slack",
        "GET",
        "https://files.slack.com/files-pri/:team_file_id/download/:file_name",
        response_format="binary",
    )
    for r in rows:
        if (
            r["endpoint"].startswith("https://api-data.line.me/")
            and r["method"] == "GET"
        ):
            r.update(response_format="binary", max_response_bytes=64_000_000)
    return rows


if __name__ == "__main__":
    repository = Path(__file__).resolve().parents[1]
    rows = generate(repository)
    (repository / "app/credentials/provider_routes.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                provider: sum(r["helper"] == "integration_" + provider for r in rows)
                for provider in BASES
            }
        )
    )
