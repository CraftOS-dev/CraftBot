"""Built-in ad / tracker blocking and the request-blocking patterns.

Blocking runs inside Chromium through CDP ``Network.setBlockedURLs`` on each
page (never ``context.route``: request interception turns the HTTP cache
off). CraftBot's own UI origins are blocked the same way, and additionally
with browser-wide ``Fetch`` interception (see :func:`ui_fetch_patterns`),
because ``setBlockedURLs`` does not stop main-frame navigations or a
popup's first load.

``AD_DOMAINS`` is deliberately conservative: only well-known advertising and
tracking networks. Domains that logins, CAPTCHAs or CDNs depend on (google.com,
gstatic.com, googleapis.com, recaptcha.net, hcaptcha.com, cloudflare.com,
facebook.com / facebook.net, apple.com, microsoft.com, amazon.com, tag
managers, ...) are never listed.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Iterable, List

from app.mini_browser.urls import split_origin

AD_DOMAINS: FrozenSet[str] = frozenset(
    {
        # Google advertising
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "googletagservices.com",
        "adservice.google.com",
        "2mdn.net",
        "google-analytics.com",
        # Programmatic exchanges, SSPs and DSPs
        "adnxs.com",
        "adnxs-simple.com",
        "adsrvr.org",
        "amazon-adsystem.com",
        "criteo.com",
        "criteo.net",
        "pubmatic.com",
        "rubiconproject.com",
        "openx.net",
        "casalemedia.com",
        "indexww.com",
        "smartadserver.com",
        "adform.net",
        "bidswitch.net",
        "3lift.com",
        "sharethrough.com",
        "gumgum.com",
        "teads.tv",
        "yieldmo.com",
        "contextweb.com",
        "districtm.io",
        "emxdgt.com",
        "conversantmedia.com",
        "dotomi.com",
        "mathtag.com",
        "bidr.io",
        "adition.com",
        "yieldlab.net",
        "lijit.com",
        "sonobi.com",
        "33across.com",
        "onetag-sys.com",
        "adhigh.net",
        "admixer.net",
        "adkernel.com",
        "adscale.de",
        "adtelligent.com",
        "smartclip.net",
        "stickyadstv.com",
        "springserve.com",
        "spotxchange.com",
        "spotx.tv",
        "tremorhub.com",
        "lkqd.net",
        "serving-sys.com",
        "flashtalking.com",
        "everesttech.net",
        "advertising.com",
        "atdmt.com",
        "turn.com",
        "w55c.net",
        "media.net",
        "zedo.com",
        "adroll.com",
        "adcolony.com",
        "applovin.com",
        "inmobi.com",
        "smaato.net",
        # Verification / measurement
        "moatads.com",
        "doubleverify.com",
        "adsafeprotected.com",
        "betrad.com",
        "scorecardresearch.com",
        "imrworldwide.com",
        "quantserve.com",
        "quantcount.com",
        # Data brokers / identity graphs
        "rlcdn.com",
        "tapad.com",
        "bluekai.com",
        "krxd.net",
        "exelator.com",
        "agkn.com",
        "crwdcntrl.net",
        "eyeota.net",
        "liadm.com",
        "adsymptotic.com",
        "ipredictive.com",
        "semasio.net",
        "owneriq.net",
        "rfihub.com",
        "nexac.com",
        "mookie1.com",
        # Native / content recommendation ads
        "taboola.com",
        "taboolasyndication.com",
        "outbrain.com",
        "outbrainimg.com",
        "mgid.com",
        "revcontent.com",
        "zergnet.com",
        "zemanta.com",
        "adblade.com",
        # Pop-under / aggressive networks
        "adsterra.com",
        "propellerads.com",
        "popads.net",
        "popcash.net",
        "exoclick.com",
        "juicyads.com",
        "trafficjunky.net",
        "adcash.com",
        "hilltopads.net",
        "clickadu.com",
        # Social / search ad pixels (their own sites stay reachable)
        "ads-twitter.com",
        "ads.linkedin.com",
        "analytics.tiktok.com",
        "ct.pinterest.com",
        "bat.bing.com",
        "mc.yandex.ru",
        "an.yandex.ru",
        "hm.baidu.com",
        "pos.baidu.com",
        # Session recording / heatmaps / share-widget trackers
        "hotjar.com",
        "mouseflow.com",
        "crazyegg.com",
        "clarity.ms",
        "addthis.com",
        "sharethis.com",
    }
)

_DOMAIN_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def is_ad_host(host: str) -> bool:
    """True if ``host`` is an AD_DOMAINS entry or a subdomain of one.

    Matches on label boundaries only: ``ads.doubleclick.net`` matches,
    ``notdoubleclick.net`` does not.
    """
    labels = (host or "").strip().lower().rstrip(".").split(".")
    return any(".".join(labels[i:]) in AD_DOMAINS for i in range(len(labels) - 1))


def blocked_url_patterns(
    adblock: bool, ui_origins: Iterable[str], extra_domains: Iterable[str] = ()
) -> List[str]:
    """Wildcard patterns for CDP ``Network.setBlockedURLs`` (its ``urls`` field).

    Chromium matches each ``*``-separated piece in order anywhere in the URL,
    so ``*://*.doubleclick.net/*`` blocks the domain's subdomains and
    ``*://doubleclick.net/*`` the domain itself; the ``:*`` variants cover an
    explicit port. ``ui_origins`` are normalised ``host:port`` entries (a bare
    host stands for every port). Ad domains are included only when
    ``adblock``; UI origins always are.
    """
    patterns: List[str] = []
    for origin in sorted({o for o in ui_origins or () if o}):
        patterns.extend(_origin_block_patterns(origin))
    if adblock:
        domains = set(AD_DOMAINS)
        domains.update(_clean_domain(d) for d in extra_domains or ())
        domains.discard("")
        for domain in sorted(domains):
            patterns.extend(
                (
                    f"*://*.{domain}/*",
                    f"*://{domain}/*",
                    f"*://*.{domain}:*",
                    f"*://{domain}:*",
                )
            )
    return list(dict.fromkeys(patterns))


def ui_fetch_patterns(ui_origins: Iterable[str]) -> List[str]:
    """Browser-wide CDP ``Fetch.enable`` url patterns for the UI origins.

    Fetch patterns must match the WHOLE url (``*`` and ``?`` are wildcards),
    so each one starts with its scheme: a URL that merely mentions the UI
    origin (say in a query string) does not match. URLs carry no port when it
    is the scheme's default.
    """
    patterns: List[str] = []
    for origin in sorted({o for o in ui_origins or () if o}):
        host, port = split_origin(origin)
        if not host:
            continue
        for name in _host_spellings(host):
            for scheme, default_port in (("http", 80), ("https", 443)):
                if port is None:
                    patterns.extend((f"{scheme}://{name}/*", f"{scheme}://{name}:*/*"))
                elif port == default_port:
                    patterns.extend(
                        (f"{scheme}://{name}/*", f"{scheme}://{name}:{port}/*")
                    )
                else:
                    patterns.append(f"{scheme}://{name}:{port}/*")
    return list(dict.fromkeys(patterns))


def _origin_block_patterns(origin: str) -> List[str]:
    host, port = split_origin(origin)
    patterns: List[str] = []
    for name in _host_spellings(host):
        if port is None:
            patterns.extend((f"*://{name}/*", f"*://{name}:*"))
        elif port == 80:
            patterns.extend((f"http://{name}/*", f"*://{name}:80/*"))
        elif port == 443:
            patterns.extend((f"https://{name}/*", f"*://{name}:443/*"))
        else:
            patterns.append(f"*://{name}:{port}/*")
    return patterns


def _host_spellings(host: str) -> List[str]:
    """The host, plus its trailing-dot spelling for names (``localhost.``)."""
    if host.startswith("[") or host.replace(".", "").isdigit():
        return [host]
    return [host, f"{host}."]


def _clean_domain(domain: str) -> str:
    text = (domain or "").strip().lower().strip(".")
    return text if _DOMAIN_RE.match(text) or text == "localhost" else ""
