#!/usr/bin/env python
"""Verify an integration against the house gates — one command.

Runs the offline checks from craftos_integrations/README.md
("Verification") so they are a gate rather than a suggestion:

  A. imports cleanly and registers (provider + client resolve)
  B. operation audit — count, tag distribution, umbrella size, and the
     mutation/destructive flags the runtime depends on
  C. conformance suite — tests/integrations/test_<name>_conformance.py

What it cannot check is whether the vendor's API accepts what we send.
That needs a real account; the live smoke test stays a human step.

Usage (with the CraftBot interpreter — see app/python_runtime.py):

    python scripts/verify_integration.py posthog
    python scripts/verify_integration.py --all
    python scripts/verify_integration.py posthog --no-tests

Exit code is 0 when every gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import collections
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Windows consoles default to cp1252 and raise UnicodeEncodeError on the
# arrows and dashes in provider messages. Force UTF-8 where we can.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
    pass


def _reexec_on_craftbot_interpreter() -> None:
    """Re-run under the interpreter that has CraftBot's dependencies.

    The user's `python` is usually a trampoline without httpx installed, so
    these scripts would fail on import. app/python_runtime.py resolves the
    real one; mirror what the launchers do rather than making the caller
    remember a path.
    """
    import os

    if os.environ.get("_CRAFTBOT_REEXEC") == "1":
        return
    try:
        from app.python_runtime import resolve
    except Exception:  # pragma: no cover - fall through to a normal import error
        return
    target = resolve()
    if not target or Path(target).resolve() == Path(sys.executable).resolve():
        return
    os.environ["_CRAFTBOT_REEXEC"] = "1"
    raise SystemExit(
        subprocess.call([target, str(Path(__file__).resolve()), *sys.argv[1:]])
    )


_reexec_on_craftbot_interpreter()

# House conventions, from the README. Tuned per the 23 shipped integrations.
MIN_OPERATIONS = 30
MAX_OPERATIONS = 75
MIN_UMBRELLA = 15
MAX_UMBRELLA = 25
MIN_SET_SIZE = 3

# Verb prefixes that mutate remote state. These must not be parallelizable —
# the runtime fans out parallel calls and would duplicate the write.
MUTATING_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "remove_",
    "set_",
    "add_",
    "send_",
    "reply_",
    "enable_",
    "disable_",
    "archive_",
    "unarchive_",
    "move_",
    "cancel_",
    "post_",
    "upload_",
    "merge_",
    "revoke_",
)

# Mirrors tests/integrations/conformance.py DESTRUCTIVE_HINTS.
DESTRUCTIVE_VERBS = ("delete", "clear", "remove", "revoke", "destroy", "cancel")


class Report:
    """Collects gate results so every failure is reported, not just the first."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.failures: List[str] = []
        self.notes: List[str] = []

    def check(self, ok: bool, message: str) -> bool:
        if ok:
            print(f"    ok    {message}")
        else:
            print(f"    FAIL  {message}")
            self.failures.append(message)
        return ok

    def note(self, message: str) -> None:
        print(f"    --    {message}")
        self.notes.append(message)

    @property
    def passed(self) -> bool:
        return not self.failures


def gate_imports(name: str, report: Report) -> Optional[Any]:
    """A. The autoloader finds the provider and the client decorator fired."""
    print("  [A] imports and registers")
    from craftos_integrations import autoload_integrations, get_client
    from craftos_integrations.providers import get_provider

    autoload_integrations(force=True)
    provider = get_provider(name)
    client = get_client(name)

    report.check(provider is not None, f"provider '{name}' resolves")
    report.check(
        client is not None,
        f"client '{name}' resolves (@register_client fired)",
    )
    return provider


def gate_operations(provider: Any, report: Report) -> None:
    """B. The agent-facing surface matches the house shape."""
    print("  [B] operation audit")
    operations = provider.operations()

    if not operations:
        report.note(
            "provider declares no operations — auth-layer bridge port, its "
            "action surface lives in app/data/action/integrations/"
        )
        return

    total = len(operations)
    report.check(
        MIN_OPERATIONS <= total <= MAX_OPERATIONS,
        f"operation count {total} within {MIN_OPERATIONS}-{MAX_OPERATIONS}",
    )

    counts: Dict[str, int] = collections.Counter()
    for op in operations:
        for tag in op.tags:
            counts[tag] += 1

    umbrella = counts.get(provider.id, 0)
    report.check(
        MIN_UMBRELLA <= umbrella <= MAX_UMBRELLA,
        f"umbrella set '{provider.id}' has {umbrella} ops "
        f"(want {MIN_UMBRELLA}-{MAX_UMBRELLA})",
    )

    untagged = [op.name for op in operations if not op.tags]
    report.check(not untagged, f"every operation carries a tag ({len(untagged)} bare)")

    unprefixed = [
        t for t in counts if t != provider.id and not t.startswith(provider.id)
    ]
    report.check(
        not unprefixed,
        f"every tag is prefixed with '{provider.id}' (offenders: {unprefixed})",
    )

    thin = {
        tag: n for tag, n in counts.items() if tag != provider.id and n < MIN_SET_SIZE
    }
    report.check(
        not thin,
        f"no sub-set below {MIN_SET_SIZE} operations (thin: {thin})",
    )

    parallel_mutations = [
        op.name
        for op in operations
        if op.name.startswith(MUTATING_PREFIXES) and op.parallelizable
    ]
    report.check(
        not parallel_mutations,
        f"mutations set parallelizable=False ({parallel_mutations})",
    )

    unflagged = [
        op.name
        for op in operations
        if any(f"{v}_" in f"{op.name}_" for v in DESTRUCTIVE_VERBS)
        and not op.destructive
    ]
    report.check(
        not unflagged,
        f"destructive operations flagged destructive=True ({unflagged})",
    )

    # Lifecycle: if the umbrella can create a noun it must be able to delete
    # it. An agent that creates a dashboard and then cannot remove it falls
    # back to raw HTTP and fails — this is the #1 agent-failure mode the
    # README warns about, and trimming the umbrella to hit the size ceiling
    # is how it gets introduced.
    umbrella_names = {op.name for op in operations if provider.id in op.tags}
    all_names = {op.name for op in operations}
    orphan_creates = []
    for name in sorted(umbrella_names):
        if not name.startswith("create_"):
            continue
        noun = name[len("create_") :]
        delete_name = f"delete_{noun}"
        if delete_name in all_names and delete_name not in umbrella_names:
            orphan_creates.append(f"{name} without {delete_name}")
    report.check(
        not orphan_creates,
        f"umbrella creates have a matching delete ({orphan_creates})",
    )

    account_leaks = [op.name for op in operations if "account" in op.input_schema]
    report.check(
        not account_leaks,
        f"no operation declares an 'account' input ({account_leaks})",
    )

    print("        tag distribution:")
    for tag, n in sorted(counts.items()):
        marker = "  <- umbrella" if tag == provider.id else ""
        print(f"          {tag:34s} {n}{marker}")
    print(f"          {'TOTAL':34s} {total}")


def gate_conformance(name: str, report: Report) -> None:
    """C. The offline conformance suite for this provider."""
    print("  [C] conformance suite")
    test_file = REPO_ROOT / "tests" / "integrations" / f"test_{name}_conformance.py"
    if not test_file.exists():
        # Several older providers use a differently-named file.
        alternatives = sorted(
            (REPO_ROOT / "tests" / "integrations").glob(f"test_{name}_*.py")
        )
        if alternatives:
            test_file = alternatives[0]
        else:
            report.check(
                False,
                f"no conformance test found (expected {test_file.name}) — every "
                "provider needs one",
            )
            return

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    summary = (result.stdout or result.stderr).strip().splitlines()
    tail = summary[-1] if summary else "no output"
    report.check(result.returncode == 0, f"{test_file.name}: {tail}")
    if result.returncode != 0:
        print("\n".join(f"        {line}" for line in summary[-25:]))


def verify(name: str, *, run_tests: bool = True) -> Report:
    print(f"\n=== {name} ===")
    report = Report(name)
    provider = gate_imports(name, report)
    if provider is None:
        report.note("skipping remaining gates — provider did not resolve")
        return report
    gate_operations(provider, report)
    if run_tests:
        gate_conformance(name, report)
    else:
        report.note("conformance suite skipped (--no-tests)")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", nargs="?", help="integration id, e.g. posthog")
    parser.add_argument(
        "--all", action="store_true", help="verify every shipped integration"
    )
    parser.add_argument(
        "--no-tests",
        action="store_true",
        help="skip the conformance suite (gates A and B only)",
    )
    args = parser.parse_args()

    if not args.name and not args.all:
        parser.error("give an integration name, or --all")

    from craftos_integrations.providers import provider_ids

    names = provider_ids() if args.all else [args.name]
    reports = [verify(n, run_tests=not args.no_tests) for n in names]

    failed = [r for r in reports if not r.passed]
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {len(failed)}/{len(reports)} integrations")
        for r in failed:
            print(f"  {r.name}:")
            for failure in r.failures:
                print(f"    - {failure}")
        print(
            "\nNote: these gates are offline. A live smoke test against a real "
            "account is still required before calling an integration done."
        )
        return 1

    print(f"PASSED: {len(reports)}/{len(reports)} integrations")
    print(
        "\nOffline gates only — run the live smoke test against a real account "
        "before calling an integration done."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
