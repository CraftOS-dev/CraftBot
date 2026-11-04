"""Streaming download with progress, shared by every runtime we fetch.

Both sidecar downloads used shutil.copyfileobj(), which is one blocking call
that reports nothing until it finishes. The Python runtime is ~30 MB and the
Node one 30-55 MB, so on an ordinary connection that is a minute or more of a
completely silent installer — indistinguishable, from the user's side, from a
hang. Someone watching an install sat through exactly that and reasonably
concluded it had died.

A progress line every couple of seconds is the difference between "this is
working" and "this is broken".

Stdlib-only: app/node_runtime.py imports this before dependencies exist, and
certifi is used only when it happens to be importable.
"""

from __future__ import annotations

import os
import hashlib
import shutil
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

LogFn = Callable[[str], None]

#: How often to emit a progress line. Frequent enough to look alive, rare
#: enough not to flood a log panel that also carries pip's output.
_PROGRESS_INTERVAL_SECONDS = 2.0

#: Also require this much movement before reporting again. Time alone is not
#: enough on a slow link: it yields a wall of near-identical lines.
_PROGRESS_STEP_PERCENT = 10

_CHUNK = 256 * 1024


def ssl_context() -> ssl.SSLContext:
    """A verified SSL context, using certifi's roots when available.

    Windows' own store has repeatedly failed to load under some OpenSSL
    builds (see the openssl pin in environment.yml), so prefer certifi and
    fall back rather than assuming either works.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def cache_dir() -> Optional[str]:
    """Directory of previously fetched runtime archives, if one is configured.

    Set CRAFTBOT_DOWNLOAD_CACHE to reuse downloads across installs. Every
    clean-machine test otherwise re-fetches the same ~100 MB — a Python
    runtime, Node, and the VC++ redistributable — which on a slow connection
    costs the better part of an hour per run and makes re-testing something
    people avoid. It also saves a repair or reinstall from downloading them
    again.
    """
    configured = os.environ.get("CRAFTBOT_DOWNLOAD_CACHE", "").strip()
    return configured if configured and os.path.isdir(configured) else None


def cache_name(url: str) -> str:
    """Filename to cache a URL under.

    The last path segment, percent-decoded — these names already carry
    version and platform (cpython-3.10.21+20260825-x86_64-pc-windows-msvc-
    install_only.tar.gz), so they identify content precisely enough without
    hashing the URL.
    """
    from urllib.parse import unquote, urlparse

    name = os.path.basename(urlparse(url).path)
    return unquote(name) or "download.bin"


def _download_once(
    url: str,
    dest: str,
    log: Optional[LogFn] = None,
    label: str = "",
    timeout: int = 600,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> str:
    """Stream url to dest, reporting progress. Returns dest.

    Streams to disk rather than holding the archive in memory: these are
    tens of megabytes and a low-memory machine should not need twice that
    just to unpack them.

    Cache lookup and atomic publication are handled by download().
    """
    say: LogFn = log or (lambda _m: None)
    what = label or os.path.basename(dest) or url

    req = urllib.request.Request(url, headers={"User-Agent": "CraftBot"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        header = resp.getheader("Content-Length")
        total = int(header) if header and header.isdigit() else None
        say(f"    downloading {what} ({_human(total) if total else 'size unknown'})")

        read = 0
        last_report = time.monotonic()
        last_pct = -_PROGRESS_STEP_PERCENT
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                read += len(chunk)

                if progress_cb:
                    try:
                        progress_cb(read, total)
                    except Exception:
                        pass

                now = time.monotonic()
                pct = (read * 100 // total) if total else None
                # Report on time AND on meaningful movement. Time alone
                # produced ~40 lines for one 38 MB file, most of them a
                # single percent apart, burying everything else in the panel.
                moved_enough = pct is None or pct - last_pct >= _PROGRESS_STEP_PERCENT
                if now - last_report >= _PROGRESS_INTERVAL_SECONDS and moved_enough:
                    last_report = now
                    if pct is not None:
                        last_pct = pct
                        say(f"      {pct:3d}%  {_human(read)} / {_human(total)}")
                    else:
                        say(f"      {_human(read)}")

    if total is not None and read != total:
        raise OSError(f"Download incomplete: {read} of {total} bytes")
    say(f"    downloaded {_human(read)}")
    return dest


def verify_checksum(path: str, expected: Optional[str]) -> bool:
    if not os.path.isfile(path):
        return False
    if expected is None:
        return os.path.getsize(path) > 0
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def download(
    url: str,
    dest: str,
    log: Optional[LogFn] = None,
    label: str = "",
    timeout: int = 600,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    expected_sha256: Optional[str] = None,
    offline: bool = False,
) -> str:
    """Publish only complete, verified downloads; bad caches never block repair."""
    say = log or (lambda _m: None)
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cache = cache_dir()
    cached = os.path.join(cache, cache_name(url)) if cache else None
    fd, part = tempfile.mkstemp(
        prefix=".download-", suffix=".part", dir=os.path.dirname(dest)
    )
    os.close(fd)
    try:
        if cached and verify_checksum(cached, expected_sha256):
            say(f"    using verified cache: {label or cache_name(url)}")
            shutil.copyfile(cached, part)
        else:
            if offline:
                raise OSError(
                    f"Offline: no verified cached download for {cache_name(url)}"
                )
            for attempt in range(3):
                try:
                    _download_once(
                        url, part, say, label or cache_name(url), timeout, progress_cb
                    )
                    if not verify_checksum(part, expected_sha256):
                        raise ValueError(
                            f"SHA-256 verification failed for {cache_name(url)}"
                        )
                    break
                except Exception as exc:
                    # A permanent HTTP error or bad checksum won't improve with retry.
                    permanent = isinstance(exc, ValueError) or (
                        isinstance(exc, urllib.error.HTTPError)
                        and exc.code < 500
                        and exc.code not in (408, 429)
                    )
                    if permanent or attempt == 2:
                        raise
                    say(f"    download interrupted; retrying ({attempt + 2}/3): {exc}")
                    time.sleep(attempt + 1)
        os.replace(part, dest)
        if cached and os.path.abspath(cached) != dest:
            cache_part = None
            try:
                fd, cache_part = tempfile.mkstemp(prefix=".cache-", dir=cache)
                os.close(fd)
                shutil.copyfile(dest, cache_part)
                os.replace(cache_part, cached)
            except OSError as exc:
                say(f"    could not cache download: {exc}")
            finally:
                if cache_part and os.path.exists(cache_part):
                    os.unlink(cache_part)
        return dest
    finally:
        if os.path.exists(part):
            os.unlink(part)
