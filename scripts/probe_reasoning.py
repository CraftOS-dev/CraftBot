# -*- coding: utf-8 -*-
"""Live check that per-model reasoning settings are accepted by the providers.

The unit and golden tests prove what CraftBot SENDS; only the provider can
say whether it ACCEPTS it. This script sends one tiny JSON request per model
through the real LLMInterface (same transports, same output cap as the app)
from inside a probe chat session holding the chosen reasoning choice (the
same session binding a real chat uses), and reports, per model, what was
sent and whether the provider answered or rejected it.

Every probe is a real, billed API call (a few hundred tokens each, more for
models that think). Nothing is sent with --dry-run.

Usage (from the repository root):
    python scripts/probe_reasoning.py                 # the configured LLM model
    python scripts/probe_reasoning.py --model openai/gpt-5.2 --model anthropic/claude-sonnet-4-6
    python scripts/probe_reasoning.py --all-rows      # every table row with credentials
    python scripts/probe_reasoning.py --all-rows --choice off   # a session choice
    python scripts/probe_reasoning.py --all-rows --dry-run

Exit status is 1 when any probe was rejected, else 0.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Output cap of the app's LLMInterface (app/llm/interface.py), so probes
#: exercise the same reasoning output-cap logic production does.
APP_MAX_TOKENS = 8_000

PROBE_SYSTEM_PROMPT = (
    "You are a connectivity probe. Reply with a single JSON object and nothing else."
)
PROBE_USER_PROMPT = 'Return exactly this JSON object: {"ok": true}'

#: Table surface -> the provider whose interface serves it.
SUBSCRIPTION_SURFACE = "openai_subscription"

#: Id of the in-memory chat session the probes run in (never persisted).
PROBE_SESSION_ID = "reasoning-probe"


@dataclass
class ProbeResult:
    target: str
    route: str
    decision: str
    status: str
    detail: str


def _parse_target(value: str) -> Tuple[str, str]:
    provider, sep, model = value.partition("/")
    if not sep or not provider or not model:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not <provider>/<model> (for example openai/gpt-5.2)"
        )
    return provider, model


def _configured_target() -> Tuple[str, str]:
    from app.config import get_llm_model, get_llm_provider

    return get_llm_provider(), get_llm_model()


def _all_row_targets() -> List[Tuple[str, str, str]]:
    """(surface, provider, model) for every row of the reasoning table."""
    from agent_core.core.models.reasoning import REASONING_RULES

    targets = []
    for surface, rows in REASONING_RULES.items():
        provider = "openai" if surface == SUBSCRIPTION_SURFACE else surface
        for model in rows:
            targets.append((surface, provider, model))
    return targets


def _has_aws_credentials() -> bool:
    """Whether Bedrock would authenticate: settings keys or boto3's chain.

    boto3 builds a client without credentials and only fails on the first
    call, so a missing credential must be detected up front or it would be
    reported as the provider rejecting the reasoning parameters.
    """
    from app.config import get_aws_credentials

    creds = get_aws_credentials()
    if creds.get("access_key_id") and creds.get("secret_access_key"):
        return True
    import boto3

    return boto3.Session().get_credentials() is not None


def _build_interface(provider: str, model: str):
    """A standalone LLMInterface with the app's credentials.

    Returns ``(interface, None)``, or ``(None, reason)`` when the provider
    cannot be reached with the configured credentials.
    """
    from agent_core.core.impl.llm.interface import LLMInterface
    from agent_core.core.models.registry import get_registry
    from app.config import get_api_key, get_base_url

    profile = get_registry().get(provider)
    if profile is None:
        return None, f"unknown provider {provider!r}"
    if profile.aws_credential_block and not _has_aws_credentials():
        return None, "no AWS credentials configured"
    try:
        iface = LLMInterface(
            provider=provider,
            model=model,
            api_key=get_api_key(provider) or None,
            base_url=get_base_url(provider) or None,
            max_tokens=APP_MAX_TOKENS,
        )
    except Exception as exc:  # each provider signals missing setup its own way
        return None, f"not configured: {exc}"
    if not iface.is_initialized:
        return None, "not configured"
    return iface, None


def _probe(
    provider: str, model: str, surface: Optional[str], dry_run: bool
) -> Optional[ProbeResult]:
    target = f"{provider}/{model}"
    iface, unavailable = _build_interface(provider, model)
    if iface is None:
        return ProbeResult(target, "-", "-", "SKIPPED", unavailable[:200])

    from agent_core.core.models.reasoning import reasoning_surface

    route = iface._auth_mode
    if surface is not None and reasoning_surface(provider, route) != surface:
        # This row belongs to the other OpenAI route (API key vs ChatGPT
        # subscription), which the current login cannot reach.
        return None
    if iface.model != model:
        return ProbeResult(
            target,
            route,
            "-",
            "SKIPPED",
            f"provider substitutes {iface.model!r} for this model",
        )

    decision = iface.reasoning_decision()
    described = decision.describe() if decision is not None else "no rule (not sent)"
    if dry_run:
        return ProbeResult(target, route, described, "DRY-RUN", "nothing sent")

    started = time.perf_counter()
    try:
        reply = iface.generate_response(
            system_prompt=PROBE_SYSTEM_PROMPT,
            user_prompt=PROBE_USER_PROMPT,
            log_response=False,
            prompt_name="reasoning_probe",
        )
    except Exception as exc:  # the provider's rejection is the result
        return ProbeResult(target, route, described, "REJECTED", str(exc)[:300])
    elapsed = time.perf_counter() - started
    return ProbeResult(
        target, route, described, "OK", f"{elapsed:.1f}s: {reply.strip()[:80]}"
    )


def main(argv: Optional[List[str]] = None) -> int:
    from agent_core.core.models.reasoning import ReasoningChoice
    from agent_core.core.session.session import Session
    from agent_core.core.state.session import StateSession

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--model",
        dest="targets",
        action="append",
        type=_parse_target,
        default=[],
        metavar="PROVIDER/MODEL",
        help="probe this model (repeatable); default is the configured LLM model",
    )
    parser.add_argument(
        "--all-rows",
        action="store_true",
        help="probe every reasoning-table row whose provider has credentials",
    )
    parser.add_argument(
        "--choice",
        type=ReasoningChoice,
        default=None,
        choices=list(ReasoningChoice),
        metavar="CHOICE",
        help=(
            "the probe session's reasoning choice "
            f"({', '.join(choice.value for choice in ReasoningChoice)}); "
            "default: each model's default level"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what each model would be sent without calling any API",
    )
    args = parser.parse_args(argv)

    if args.all_rows:
        plan = [(s, p, m) for s, p, m in _all_row_targets()]
    elif args.targets:
        plan = [(None, p, m) for p, m in args.targets]
    else:
        provider, model = _configured_target()
        plan = [(None, provider, model)]

    results: List[ProbeResult] = []
    StateSession.start(
        PROBE_SESSION_ID,
        current_session=Session(
            id=PROBE_SESSION_ID,
            reasoning_effort=args.choice.value if args.choice else None,
        ),
    )
    try:
        with StateSession.bind(PROBE_SESSION_ID):
            for surface, provider, model in plan:
                result = _probe(provider, model, surface, args.dry_run)
                if result is None:
                    continue
                results.append(result)
                print(
                    f"{result.status:9s} {result.target:55s} [{result.route}] "
                    f"{result.decision} :: {result.detail}",
                    flush=True,
                )
    finally:
        StateSession.end(PROBE_SESSION_ID)

    rejected = [r for r in results if r.status == "REJECTED"]
    ok = sum(r.status == "OK" for r in results)
    skipped = sum(r.status == "SKIPPED" for r in results)
    print(f"\n{ok} ok, {len(rejected)} rejected, {skipped} skipped")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
