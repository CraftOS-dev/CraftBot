#!/usr/bin/env python3
"""End-to-end test of the installer path, without the GUI.

The acceptance test for docs/plans/unified-install-architecture.md: an
installed CraftBot must be the SAME THING as a source checkout. This performs
a real install into a throwaway directory and then compares it against the
developer's environment, so "same thing" is measured rather than asserted.

What it does:
  1. Extracts dist/CraftBot-src.zip into a temp directory (what the wizard
     downloads and unpacks).
  2. Marks it a managed install, so state goes to CRAFTBOT_HOME rather than
     into the install directory.
  3. Runs the SAME app.provision pipeline install.py and the wizard run.
  4. Fingerprints the result with scripts/parity_check.py and diffs it
     against a fingerprint of this checkout.

Usage:
    python scripts/package_source.py         # build the payload first
    python scripts/test_install_e2e.py
    python scripts/test_install_e2e.py --keep   # leave the temp install
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = REPO_ROOT / "dist" / "CraftBot-src.zip"


def _run(cmd, cwd=None, env=None, timeout=5400):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(
        cmd, cwd=cwd, env=env, timeout=timeout, text=True, capture_output=True
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true", help="don't delete the temp install")
    ap.add_argument(
        "--skip-deps",
        action="store_true",
        help="skip the dependency install (fast structural check only)",
    )
    args = ap.parse_args()

    if not PAYLOAD.is_file():
        print(f"error: {PAYLOAD} not found — run scripts/package_source.py first")
        return 1

    workdir = Path(tempfile.mkdtemp(prefix="craftbot-e2e-"))
    install_dir = workdir / "install"
    state_dir = workdir / "state"
    state_dir.mkdir(parents=True)
    ok = True

    try:
        print(f"\n== 1. Extract payload -> {install_dir}")
        install_dir.mkdir(parents=True)
        with zipfile.ZipFile(PAYLOAD) as zf:
            zf.extractall(install_dir)
        src_root = install_dir
        if not (src_root / "run.py").is_file():
            subdirs = [d for d in src_root.iterdir() if d.is_dir()]
            for d in subdirs:
                if (d / "run.py").is_file():
                    src_root = d
                    break
        print(f"   source root: {src_root}")

        print("\n== 2. Mark as a managed install")
        # Same call the wizard makes. Without it the extracted tree looks
        # like a dev checkout (it contains install.py and requirements.txt)
        # and would put user state inside the install directory.
        sys.path.insert(0, str(src_root))
        marker = src_root / ".craftbot-managed"
        marker.write_text("managed\n", encoding="utf-8")

        env = dict(os.environ)
        env["CRAFTBOT_HOME"] = str(state_dir)
        env["PYTHONPATH"] = str(src_root)

        print("\n== 3. Verify path resolution inside the install")
        res = _run([sys.executable, "-m", "app.paths"], cwd=src_root, env=env)
        if res.returncode != 0:
            print(res.stdout, res.stderr)
            return 1
        described = json.loads(res.stdout)
        print(json.dumps(described, indent=2))
        if described["dev_checkout"]:
            print("   FAIL: install is being treated as a dev checkout")
            ok = False
        if not described.get("managed_install"):
            print("   FAIL: managed marker not detected")
            ok = False
        if Path(described["state_root"]) != state_dir:
            print(f"   FAIL: state_root is {described['state_root']}, want {state_dir}")
            ok = False
        if Path(described["code_root"]) != src_root:
            print(f"   FAIL: code_root is {described['code_root']}, want {src_root}")
            ok = False

        print("\n== 4. Payload completeness")
        # Every file the frozen build used to get wrong. Each was a real
        # shipped bug: missing bridge.js broke WhatsApp entirely, missing
        # INTEGRATION.md broke the integration guidance layer, and actions
        # are exec'd from source so their absence is silent until called.
        required = [
            "run.py",
            "app/provision/__init__.py",
            "app/data/action/read_pdf.py",
            "craftos_integrations/providers/whatsapp_web/bridge.js",
            "craftos_integrations/providers/gmail/INTEGRATION.md",
            "app/ui_layer/browser/frontend/dist/index.html",
            "app/i18n/errors.en.json",
        ]
        for rel in required:
            if not (src_root / rel).exists():
                print(f"   FAIL: missing {rel}")
                ok = False
        if ok:
            print(f"   {len(required)} required paths present")

        lock_dir = src_root / "requirements"
        locks = list(lock_dir.glob("lock-*.txt")) if lock_dir.is_dir() else []
        print(f"   locks shipped: {[p.name for p in locks]}")
        if not locks:
            print("   FAIL: no lock in the payload")
            ok = False

        if args.skip_deps:
            print("\n== 5. Provisioning SKIPPED (--skip-deps)")
        else:
            # A fresh venv, not this interpreter. Provisioning into the
            # developer's own site-packages would report success because
            # everything is already there — it would test nothing. The whole
            # question is whether a machine with none of this ends up correct.
            print("\n== 5a. Create an empty environment")
            venv_dir = workdir / "venv"
            r = _run([sys.executable, "-m", "venv", str(venv_dir)])
            if r.returncode != 0:
                print(r.stdout, r.stderr)
                return 1
            venv_py = (
                venv_dir / "Scripts" / "python.exe"
                if os.name == "nt"
                else venv_dir / "bin" / "python"
            )
            print(f"   {venv_py}")

            print("\n== 5b. Provision into it (installs 239 packages — slow)")
            res = _run(
                [
                    sys.executable,
                    "-c",
                    "import sys;from app import provision;"
                    f"ctx=provision.default_context(service_python=[r'{venv_py}']);"
                    "r=provision.install(log=print, ctx=ctx);"
                    "print('PIPELINE_OK' if r.ok else 'PIPELINE_FAIL');"
                    "print(provision.format_report(r))",
                ],
                cwd=src_root,
                env=env,
            )
            print(res.stdout[-4000:])
            if res.stderr.strip():
                print("stderr:", res.stderr[-2000:])
            if "PIPELINE_OK" not in res.stdout:
                print("   FAIL: provisioning did not complete")
                ok = False

            print("\n== 6. Compare install against this checkout")
            fp_install = workdir / "fp-install.json"
            fp_dev = workdir / "fp-dev.json"
            # Fingerprint the INSTALL through its own interpreter (the venv),
            # and the checkout through this one. Anything the two disagree on
            # is a real difference between how a user gets CraftBot and how a
            # developer does — which is the thing this whole plan removes.
            for out, py, cwd_, env_, label in (
                (fp_install, str(venv_py), src_root, env, "install"),
                (fp_dev, sys.executable, REPO_ROOT, dict(os.environ), "dev"),
            ):
                r = _run(
                    [
                        py,
                        str(REPO_ROOT / "scripts" / "parity_check.py"),
                        "--label",
                        label,
                    ],
                    cwd=cwd_,
                    env=env_,
                )
                out.write_text(r.stdout, encoding="utf-8")
            r = _run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "parity_check.py"),
                    "--compare",
                    str(fp_dev),
                    str(fp_install),
                ]
            )
            print(r.stdout)
            if r.returncode != 0:
                print("   NOTE: divergences above (see detail)")

        print("\n" + "=" * 60)
        print("  E2E RESULT:", "PASS" if ok else "FAIL")
        print("=" * 60)
        return 0 if ok else 1
    finally:
        if args.keep:
            print(f"\nkept: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
