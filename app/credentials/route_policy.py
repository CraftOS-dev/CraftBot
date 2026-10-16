"""Public, secret-free matching of sealed resource routes."""

import re
from urllib.parse import quote, unquote, urlsplit, parse_qsl


def path_names(endpoint):
    return tuple(re.findall(r"(?<=/):([a-z][a-z0-9_]*)", urlsplit(endpoint).path))


def parameter(value, name):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError("credential_path_invalid")
    # Repository references and explicitly declared tail fields can contain
    # bounded relative segments. There is never a host, URL, dot traversal,
    # encoded slash, query or fragment in a resource parameter.
    parts = value.split("/")
    maximum = (
        32
        if name in ("path", "file_path", "operation_name")
        else 2
        if name == "owner_repo"
        else 1
    )
    if len(parts) > maximum or any(
        not re.fullmatch(r"[A-Za-z0-9_@.-]+(?::[A-Za-z0-9_.-]+)*", p)
        or p in (".", "..")
        for p in parts
    ):
        raise ValueError("credential_path_invalid")
    return "/".join(quote(p, safe="@.:-_") for p in parts)


def target(endpoint, names, values):
    if type(values) is not dict or set(values) != set(names):
        raise ValueError("credential_path_invalid")
    path = urlsplit(endpoint).path
    for name in names:
        path = re.sub(
            r"/:(" + re.escape(name) + r")(?=/|$|:)",
            lambda _: "/" + parameter(values[name], name),
            path,
        )
    return path or "/"


def match_route(routes, method, url):
    parsed = urlsplit(url)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.scheme != "https"
    ):
        return None
    for route in routes:
        base = urlsplit(route["endpoint"])
        if (
            route["method"] != method
            or base.scheme != parsed.scheme
            or base.netloc != parsed.netloc
        ):
            continue
        names = tuple(route.get("path_fields", ()))
        pattern = re.escape(base.path)
        for name in names:
            pattern = pattern.replace(
                re.escape(":" + name),
                "(?P<"
                + name
                + ">"
                + (
                    ".+"
                    if name in ("owner_repo", "path", "file_path", "operation_name")
                    else "[^/]+"
                )
                + ")",
                1,
            )
        found = re.fullmatch(pattern, parsed.path)
        if not found:
            continue
        try:
            values = {k: unquote(v) for k, v in found.groupdict().items()}
            # Round-trip canonicalization closes encoded separators and aliases.
            if target(route["endpoint"], names, values) != parsed.path:
                continue
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            if len(dict(pairs)) != len(pairs) or any(
                k.split("[", 1)[0] not in route.get("query_fields", ())
                for k, v in pairs
            ):
                continue
        except ValueError:
            continue
        return route, values, dict(pairs)
    return None
