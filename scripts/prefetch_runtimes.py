#!/usr/bin/env python3
"""Fetch everything an install downloads, so test runs do not re-fetch it.

A clean-machine install pulls roughly 300 MB before it is usable:

    Python (python-build-standalone)   ~38 MB
    Node.js                            ~36 MB
    Visual C++ redistributable         ~24 MB
    npm packages (Baileys and friends) ~50 MB
    Playwright's Chromium             ~150 MB
    bge-small model weights           ~130 MB (downloaded on FIRST RUN,
                                               after the installer finishes)

plus ~2 GB of Python packages, which scripts/build_wheelhouse.py handles.

On a fast connection that is a few minutes. Inside Windows Sandbox, over
NAT, it was the better part of an hour PER RUN — and that cost is what stops
people re-testing, which is how install bugs survive.

This fetches everything on the machine with the good connection. The sandbox
script maps the results in automatically:

    downloads-cache/      CRAFTBOT_DOWNLOAD_CACHE   runtime archives
    npm-cache/            CRAFTBOT_NPM_CACHE        npm's package cache
    playwright-browsers/  PLAYWRIGHT_BROWSERS_PATH  Chromium
    hf-cache/             HF_HOME                   embedding model weights

Usage:
    python scripts/prefetch_runtimes.py
    python scripts/prefetch_runtimes.py --output D:\\craftbot-cache
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _fetch_archives(out: Path) -> int:
    """Runtime archives: Python, Node, and (on Windows) the VC++ runtime."""
    from app import downloads, node_runtime
    from app.provision import runtimes
    from app.provision.verify import _vcredist_url

    targets = []

    py_url = runtimes._pbs_download_url(print)
    if py_url:
        targets.append(("Python runtime", py_url))
    else:
        print("warning: could not resolve the Python runtime URL", file=sys.stderr)

    node_url = node_runtime.latest_download_url(log=print)
    if node_url:
        targets.append(("Node.js", node_url))
    else:
        print("warning: could not resolve the Node URL", file=sys.stderr)

    if sys.platform == "win32":
        targets.append(("Visual C++ runtime", _vcredist_url()))

    failures = 0
    for label, url in targets:
        dest = out / downloads.cache_name(url)
        if dest.is_file():
            print(f"\n{label}: cached already ({dest.stat().st_size / 1048576:.1f} MB)")
            continue
        print(f"\n{label}:")
        try:
            downloads.download(url, str(dest), log=print, label=label)
        except Exception as e:
            failures += 1
            print(f"  failed: {str(e)[:200]}", file=sys.stderr)
    return failures


def _warm_npm_cache(cache: Path) -> int:
    """Populate npm's cache with the WhatsApp bridge's dependency tree."""
    from app import node_runtime

    bridge = REPO_ROOT / "craftos_integrations" / "providers" / "whatsapp_web"
    if not bridge.is_dir():
        return 0

    npm = node_runtime.npm_cmd()
    if not npm:
        print("\nnpm cache: skipped, no npm found", file=sys.stderr)
        return 0

    print(f"\nnpm packages -> {cache}")
    cache.mkdir(parents=True, exist_ok=True)

    # Install into a THROWAWAY copy of the manifests, not the real tree.
    # Running it in place on a machine that already has node_modules is a
    # no-op: npm downloads nothing, so it caches nothing, and the cache ends
    # up empty exactly when you thought you had warmed it.
    import shutil
    import tempfile

    staging = Path(tempfile.mkdtemp(prefix="craftbot-npmwarm-"))
    try:
        copied = False
        for name in ("package.json", "package-lock.json"):
            src = bridge / name
            if src.is_file():
                shutil.copy2(src, staging / name)
                copied = copied or name == "package.json"
        if not copied:
            print("  no package.json to warm from", file=sys.stderr)
            return 0

        proc = subprocess.run(
            [
                npm,
                "install",
                "--no-audit",
                "--no-fund",
                # Only fetch and cache; the lifecycle scripts are what need a
                # real Node and they are irrelevant to warming a cache.
                "--ignore-scripts",
                "--cache",
                str(cache),
            ],
            cwd=str(staging),
            # Lifecycle scripts spawn bare `node`, which must resolve to the
            # sidecar rather than failing or picking up a different Node.
            env=node_runtime.child_env(),
        )
        if proc.returncode != 0:
            print("  npm cache warm-up failed", file=sys.stderr)
            return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return 0


def _fetch_playwright(browsers: Path) -> int:
    """Download Chromium into a relocatable directory.

    PLAYWRIGHT_BROWSERS_PATH is Playwright's own mechanism for this, so the
    directory can be mapped in read-only and found without a download.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("\nPlaywright: skipped, not installed in this environment")
        return 0

    print(f"\nPlaywright browser -> {browsers}")
    browsers.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    proc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"], env=env
    )
    if proc.returncode != 0:
        print("  playwright download failed", file=sys.stderr)
        return 1
    return 0


def _fetch_embedding_model(hf_home: Path) -> int:
    """Download the memory embedding model's weights.

    The last uncached download in an install, and the only one that happens
    AFTER the installer finishes: the agent fetches ~130 MB from HuggingFace
    the first time it builds its memory index, so a "finished" install still
    sits there downloading before it can answer anything.

    HF_HOME relocates the whole HuggingFace cache, so this can be mapped in
    the same way as everything else.
    """
    model = os.environ.get("MEMORY_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    if model == "default":
        print("\nEmbedding model: skipped (MEMORY_EMBEDDING_MODEL=default)")
        return 0

    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        print("\nEmbedding model: skipped, sentence-transformers not installed")
        return 0

    print(f"\nEmbedding model {model} -> {hf_home}")
    hf_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HF_HOME"] = str(hf_home)
    # A subprocess so HF_HOME is read at import time, which is when the
    # library decides where its cache lives.
    code = (
        "from sentence_transformers import SentenceTransformer;"
        f"SentenceTransformer({model!r});"
        "print('model cached')"
    )
    proc = subprocess.run([sys.executable, "-c", code], env=env)
    if proc.returncode != 0:
        print("  embedding model download failed", file=sys.stderr)
        return 1
    return 0


def _dir_size_mb(path: Path) -> float:
    if not path.is_dir():
        return 0.0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / (1024 * 1024)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "downloads-cache"),
        help="where to keep the runtime archives (default: <repo>/downloads-cache)",
    )
    ap.add_argument(
        "--skip-npm", action="store_true", help="don't warm npm's cache"
    )
    ap.add_argument(
        "--skip-playwright", action="store_true", help="don't fetch Chromium"
    )
    ap.add_argument(
        "--skip-model", action="store_true", help="don't fetch the embedding model"
    )
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    # download() reads this to decide where to cache.
    os.environ["CRAFTBOT_DOWNLOAD_CACHE"] = str(out)

    npm_cache = REPO_ROOT / "npm-cache"
    browsers = REPO_ROOT / "playwright-browsers"
    hf_home = REPO_ROOT / "hf-cache"

    failures = _fetch_archives(out)
    if not args.skip_npm:
        failures += _warm_npm_cache(npm_cache)
    if not args.skip_playwright:
        failures += _fetch_playwright(browsers)
    if not args.skip_model:
        failures += _fetch_embedding_model(hf_home)

    print("\n" + "=" * 58)
    print(f"  runtime archives   {_dir_size_mb(out):7.0f} MB   {out}")
    if npm_cache.is_dir():
        print(f"  npm cache          {_dir_size_mb(npm_cache):7.0f} MB   {npm_cache}")
    if browsers.is_dir():
        print(f"  playwright         {_dir_size_mb(browsers):7.0f} MB   {browsers}")
    if hf_home.is_dir():
        print(f"  embedding model    {_dir_size_mb(hf_home):7.0f} MB   {hf_home}")
    print("=" * 58)

    if failures:
        print(f"\n{failures} step(s) failed", file=sys.stderr)
        return 1

    print("\nThe sandbox script maps all of these automatically when present.")
    print("To use them elsewhere:")
    print(f"  set CRAFTBOT_DOWNLOAD_CACHE={out}")
    if npm_cache.is_dir():
        print(f"  set CRAFTBOT_NPM_CACHE={npm_cache}")
    if browsers.is_dir():
        print(f"  set PLAYWRIGHT_BROWSERS_PATH={browsers}")
    if hf_home.is_dir():
        print(f"  set HF_HOME={hf_home}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
