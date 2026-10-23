#!/usr/bin/env python3
"""Generate agent_core/core/models/model_catalog.json, the model catalog.

Per model: its context window, its input limit when the provider caps input
below the window, and how long the provider keeps its prompt cache. Per
surface: whether responses report cached input. agent_core/core/models/
catalog.py reads it, with defaults for whatever it does not list.

Every fact comes from scripts/model_catalog_sources.json (see its "about"):
the sources to read, facts per surface, facts per model. This script only
knows how to parse each source format; it names no model, provider or URL.
The output is deterministic (sorted, one row per line, no timestamps), so a
regeneration diff shows exactly what changed. Run it by hand when providers
change.

Usage:
    python scripts/gen_model_catalog.py
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent_core.core.models.catalog import (  # noqa: E402
    CATALOG_PATH,
    CacheLifetimeKind,
)

SOURCES_PATH = Path(__file__).with_name("model_catalog_sources.json")

#: Fields a model row carries; any other key in the sources file is a note.
ROW_FIELDS = ("context_window", "max_input_tokens", "cache_lifetime")

Row = Dict[str, Any]


class CatalogError(ValueError):
    """model_catalog_sources.json or a source does not make a valid catalog."""


def _fetch_json(url: str) -> Any:
    import certifi

    # certifi's bundle, not the OS store: a broken certificate in the Windows
    # store fails the default context before any request is made.
    context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(
        url, headers={"User-Agent": "CraftBot gen_model_catalog.py"}
    )
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        return json.load(response)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _models_dev_rows(
    source: Dict[str, Any], data: Any, surfaces: Dict
) -> Dict[str, Row]:
    """models.dev: limit.context / limit.input per model. A surface's cache
    lifetime goes to the models models.dev prices cache reads for."""
    rows: Dict[str, Row] = {}
    for surface, provider_id in source["providers"].items():
        lifetime = surfaces.get(surface, {}).get("cache_lifetime")
        for model_id, model in data[provider_id]["models"].items():
            limit = model.get("limit") or {}
            context = limit.get("context")
            if not _positive_int(context):
                continue
            row: Row = {"context_window": context}
            if _positive_int(limit.get("input")) and limit["input"] < context:
                row["max_input_tokens"] = limit["input"]
            if lifetime and (model.get("cost") or {}).get("cache_read") is not None:
                row["cache_lifetime"] = lifetime
            rows[f"{surface}/{model_id}"] = row
    return rows


def _codex_rows(source: Dict[str, Any], data: Any, surfaces: Dict) -> Dict[str, Row]:
    """The Codex model catalogue: context_window per model slug."""
    surface = source["surface"]
    return {
        f"{surface}/{model['slug']}": {"context_window": model["context_window"]}
        for model in data["models"]
        if _positive_int(model.get("context_window"))
    }


#: Source formats this script can read, by the "format" a source names.
PARSERS: Dict[str, Callable[[Dict[str, Any], Any, Dict], Dict[str, Row]]] = {
    "models.dev": _models_dev_rows,
    "codex": _codex_rows,
}


def _check_row(key: str, row: Row) -> None:
    if not _positive_int(row.get("context_window")):
        raise CatalogError(f"{key}: no source lists it and it gives no context_window")
    if "max_input_tokens" in row and not _positive_int(row["max_input_tokens"]):
        raise CatalogError(f"{key}: invalid max_input_tokens")
    lifetime = row.get("cache_lifetime")
    if lifetime is not None:
        if lifetime.get("kind") not in {kind.value for kind in CacheLifetimeKind}:
            raise CatalogError(
                f"{key}: unknown cache_lifetime kind {lifetime.get('kind')!r}"
            )
        if not _positive_int(lifetime.get("seconds")):
            raise CatalogError(f"{key}: invalid cache_lifetime seconds")


def _model_rows(sourced: Dict[str, Row], models: Dict[str, Dict]) -> Dict[str, Row]:
    """The sources file's per-model facts merged over the sourced rows."""
    rows: Dict[str, Row] = {}
    for key, facts in models.items():
        same_as = facts.get("same_as")
        if same_as is not None and same_as not in sourced:
            raise CatalogError(f"{key}: same_as {same_as}, which no source lists")
        base = sourced[same_as] if same_as is not None else sourced.get(key, {})
        rows[key] = {**base, **{f: facts[f] for f in ROW_FIELDS if f in facts}}
    return rows


def build_catalog(
    config: Dict[str, Any], fetch: Callable[[str], Any]
) -> Dict[str, Any]:
    """The catalog from the sources file's ``config``, reading each source's
    URL with ``fetch``."""
    surfaces: Dict[str, Dict[str, Any]] = config.get("surfaces", {})
    sourced: Dict[str, Row] = {}
    for source in config["sources"]:
        parse = PARSERS.get(source["format"])
        if parse is None:
            raise CatalogError(f"unknown source format {source['format']!r}")
        sourced.update(parse(source, fetch(source["url"]), surfaces))
    models = {**sourced, **_model_rows(sourced, config.get("models", {}))}
    for key, row in models.items():
        _check_row(key, row)
    return {
        "surfaces": {
            surface: {"reports_cached_tokens": facts["reports_cached_tokens"]}
            for surface, facts in surfaces.items()
            if "reports_cached_tokens" in facts
        },
        "models": models,
    }


def _render(catalog: Dict[str, Any]) -> str:
    def section(name: str, rows: Dict[str, Any], last: bool) -> list:
        items = sorted(rows.items())
        lines = [f'  "{name}": {{']
        for index, (key, row) in enumerate(items):
            comma = "," if index < len(items) - 1 else ""
            lines.append(
                f"    {json.dumps(key)}: {json.dumps(row, sort_keys=True)}{comma}"
            )
        lines.append("  }" if last else "  },")
        return lines

    lines = [
        "{",
        '  "generator": "scripts/gen_model_catalog.py from scripts/model_catalog_sources.json",',
        *section("surfaces", catalog["surfaces"], last=False),
        *section("models", catalog["models"], last=True),
        "}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    config = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    catalog = build_catalog(config, _fetch_json)
    text = _render(catalog)
    json.loads(text)  # the hand-rendered layout must stay valid JSON
    CATALOG_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"wrote {len(catalog['models'])} models to {CATALOG_PATH.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
