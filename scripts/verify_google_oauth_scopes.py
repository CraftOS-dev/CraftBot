"""Compare Google connector scope requests with the review manifest.

Run from a configured CraftBot Python environment. No Google API calls are
made, no credentials are loaded, and supplied authorization URLs are never
printed. Optional files let a reviewer compare actual browser requests and
the Console's scope list with the reviewed source configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def compare(expected: set[str], actual: set[str]) -> dict:
    return {
        "passed": expected == actual,
        "missing": sorted(expected - actual),
        "unexpected": sorted(actual - expected),
    }


def audit(
    console_file: Path | None = None,
    auth_file: Path | None = None,
    provider_id: str | None = None,
) -> dict:
    from craftos_integrations.providers._google_common import make_google_oauth
    from craftos_integrations.providers.gmail import GmailProvider
    from craftos_integrations.providers.google_calendar import GoogleCalendarProvider
    from craftos_integrations.providers.google_docs import GoogleDocsProvider
    from craftos_integrations.providers.google_drive import GoogleDriveProvider
    from craftos_integrations.providers.google_youtube import GoogleYoutubeProvider

    manifest = json.loads(
        (ROOT / "craftos_integrations/google_oauth_scopes.json").read_text("utf-8")
    )
    providers = [
        GmailProvider(),
        GoogleCalendarProvider(),
        GoogleDocsProvider(),
        GoogleDriveProvider(),
        GoogleYoutubeProvider(),
    ]
    checks = {}
    actual_union: set[str] = set()
    identity = set(manifest["identity_scopes"])
    checks["providers"] = compare(set(manifest["services"]), {p.id for p in providers})
    for provider in providers:
        expected = identity | set(manifest["services"][provider.id])
        actual = set(provider.oauth_spec().scopes)
        actual_union.update(actual)
        checks[f"{provider.id}_oauth_spec"] = compare(expected, actual)
        checks[f"{provider.id}_login"] = compare(
            expected, set(make_google_oauth(provider.scopes).scopes.split())
        )
    checks["manifest_console_union"] = compare(
        set(manifest["console_scopes"]), actual_union
    )
    if console_file is not None:
        checks["observed_console"] = compare(
            actual_union, set(console_file.read_text("utf-8-sig").split())
        )
    if auth_file is not None:
        if provider_id not in manifest["services"]:
            raise ValueError("--provider must name one of the Google connectors")
        query = parse_qs(urlparse(auth_file.read_text("utf-8-sig").strip()).query)
        actual = set(" ".join(query.get("scope", [])).split())
        checks["observed_authorization_request"] = compare(
            identity | set(manifest["services"][provider_id]), actual
        )
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "target_console_scopes": sorted(actual_union),
        "live_google_access_tested": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--console-scopes",
        type=Path,
        help="UTF-8 file with exact scope URIs separated by whitespace",
    )
    parser.add_argument(
        "--authorization-url-file",
        type=Path,
        help="Local UTF-8 file containing a captured Google authorization URL",
    )
    parser.add_argument(
        "--provider",
        choices=[
            "gmail",
            "google_calendar",
            "google_docs",
            "google_drive",
            "google_youtube",
        ],
    )
    args = parser.parse_args()
    if args.authorization_url_file is not None and args.provider is None:
        parser.error("--authorization-url-file requires --provider")
    try:
        result = audit(args.console_scopes, args.authorization_url_file, args.provider)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Scope audit could not complete: {error}\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
