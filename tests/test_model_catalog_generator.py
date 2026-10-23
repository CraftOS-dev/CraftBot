# -*- coding: utf-8 -*-
"""scripts/gen_model_catalog.py builds the model catalog from data only.

Every model, provider and URL lives in scripts/model_catalog_sources.json;
the generator only parses source formats. These tests feed it made-up
sources (no network) and pin how facts combine: a surface's cache lifetime
goes to the models the source prices cache reads for, per-model facts merge
over sourced rows, same_as copies a row first, and anything that cannot make
a valid row is an error rather than a guess.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _generator():
    spec = importlib.util.spec_from_file_location(
        "gen_model_catalog", ROOT / "scripts" / "gen_model_catalog.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _generator()

TIMED = {"kind": "typical", "seconds": 300}
SOURCES = {
    "https://source.test/models.json": {
        "alpha-upstream": {
            "models": {
                "priced": {
                    "limit": {"context": 400_000, "input": 272_000},
                    "cost": {"cache_read": 0.1},
                },
                "unpriced": {"limit": {"context": 128_000}},
                "no-limit": {"limit": {}},
            }
        }
    },
    "https://source.test/codex.json": {
        "models": [
            {"slug": "sub-model", "context_window": 272_000},
            {"slug": "no-window"},
        ]
    },
}


def _config(models=None, surfaces=None):
    return {
        "sources": [
            {
                "format": "models.dev",
                "url": "https://source.test/models.json",
                "providers": {"alpha": "alpha-upstream"},
            },
            {
                "format": "codex",
                "url": "https://source.test/codex.json",
                "surface": "alpha_subscription",
            },
        ],
        "surfaces": surfaces
        if surfaces is not None
        else {
            "alpha": {"cache_lifetime": TIMED},
            "beta": {"reports_cached_tokens": False},
        },
        "models": models or {},
    }


def _build(config):
    return gen.build_catalog(config, SOURCES.__getitem__)


def test_rows_come_from_the_sources_as_configured():
    models = _build(_config())["models"]
    assert models["alpha/priced"] == {
        "context_window": 400_000,
        "max_input_tokens": 272_000,
        "cache_lifetime": TIMED,  # the source prices its cache reads
    }
    assert models["alpha/unpriced"] == {"context_window": 128_000}
    assert models["alpha_subscription/sub-model"] == {"context_window": 272_000}
    assert (
        "alpha/no-limit" not in models and "alpha_subscription/no-window" not in models
    )


def test_model_facts_merge_over_the_sourced_row():
    exact = {"kind": "exact", "seconds": 1800}
    models = _build(
        _config(models={"alpha/priced": {"cache_lifetime": exact, "note": "why"}})
    )["models"]
    assert models["alpha/priced"] == {
        "context_window": 400_000,
        "max_input_tokens": 272_000,
        "cache_lifetime": exact,
    }


def test_same_as_copies_a_sourced_row():
    models = _build(_config(models={"alpha/priced-2026": {"same_as": "alpha/priced"}}))[
        "models"
    ]
    assert models["alpha/priced-2026"] == models["alpha/priced"]


def test_only_surface_facts_the_runtime_reads_are_carried():
    assert _build(_config())["surfaces"] == {"beta": {"reports_cached_tokens": False}}


@pytest.mark.parametrize(
    "config",
    [
        _config(models={"alpha/missing": {"cache_lifetime": TIMED}}),  # no window
        _config(models={"alpha/copy": {"same_as": "alpha/missing"}}),
        _config(
            surfaces={"alpha": {"cache_lifetime": {"kind": "forever", "seconds": 1}}}
        ),
        {**_config(), "sources": [{"format": "unknown", "url": "x"}]},
    ],
)
def test_what_cannot_make_a_valid_row_is_an_error(config):
    with pytest.raises(gen.CatalogError):
        _build(config)


def test_the_sources_file_names_only_known_formats_and_surfaces():
    from agent_core.core.models.provider_config import PROVIDER_CONFIG
    from agent_core.core.models.reasoning import (
        SUBSCRIPTION_AUTH_MODE,
        reasoning_surface,
    )

    config = json.loads(gen.SOURCES_PATH.read_text(encoding="utf-8"))
    known = {
        reasoning_surface(key, auth)
        for key in PROVIDER_CONFIG
        for auth in ("api_key", SUBSCRIPTION_AUTH_MODE)
    }
    for source in config["sources"]:
        assert source["format"] in gen.PARSERS
        assert set(source.get("providers", {})) <= known
        assert source.get("surface") is None or source["surface"] in known
    assert set(config["surfaces"]) <= known
    assert {key.partition("/")[0] for key in config["models"]} <= known
