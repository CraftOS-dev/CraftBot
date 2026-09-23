"""The pip that reads the locks is pinned.

A lock pins 239 packages by hash so every machine installs the same set. That
guarantee is only as strong as the tool reading it: pip 23.1 rejects the
committed lock outright (it treats `lxml[html_clean]>=4.4.2`, which jusText
declares, as a requirement separate from the pinned `lxml`, re-resolves it
against the index, and then refuses the unpinned result), while pip 23.3.2
and later install it. Same lock, same command, opposite outcomes.

Which pip a machine had used to be an accident — the sidecar ships whatever
python-build-standalone bundled the day it was downloaded, and PythonStage
may hand the install to an interpreter already on the machine. PipStage
removes that variable, so these tests guard the pin and its position in the
pipeline rather than any particular pip's behaviour.
"""

import re

from app import paths
from app.provision import default_stages
from app.provision.deps import (
    PipStage,
    _pinned_pip_version,
    find_pip_bootstrap,
)


def test_the_bootstrap_file_ships_with_the_code():
    assert find_pip_bootstrap(str(paths.CODE_ROOT)) is not None


def test_the_pin_is_exact_and_hashed():
    bootstrap = find_pip_bootstrap(str(paths.CODE_ROOT))
    body = bootstrap.read_text(encoding="utf-8")

    # --require-hashes is what makes the pin unforgeable rather than advisory.
    assert "--require-hashes" in body

    pins = re.findall(r"^pip==(\S+)", body, re.M)
    assert len(pins) == 1, f"expected exactly one pip pin, found {pins}"
    assert re.search(r"--hash=sha256:[0-9a-f]{64}", body), "the pin carries no sha256"


def test_the_stage_reads_the_version_from_the_file():
    # Read, never duplicated as a constant: two places to edit is how a pin
    # and the stage enforcing it drift apart.
    bootstrap = find_pip_bootstrap(str(paths.CODE_ROOT))
    version = _pinned_pip_version(bootstrap)
    assert version, "no pip== pin parsed"
    assert re.fullmatch(r"\d+(\.\d+)+", version), version
    assert f"pip=={version}" in bootstrap.read_text(encoding="utf-8")


def test_pip_is_pinned_before_any_lock_is_read():
    """Ordering is the whole point: pinning pip after the lock install would
    fix the next run and not this one."""
    names = [s.name for s in default_stages()]
    assert "pip" in names, names
    assert "python-deps" in names, names
    assert names.index("pip") < names.index("python-deps"), names
    # And after the interpreter is settled — it is that interpreter's pip
    # being pinned, not the installer's.
    assert names.index("python") < names.index("pip"), names


def test_a_wrong_pip_is_reported_as_degraded_not_satisfied():
    """check() must not wave through a pip that differs from the pin, or
    apply() never runs and the stage is decorative."""

    class _Ctx:
        code_root = str(paths.CODE_ROOT)

        def python(self):
            return ["definitely-not-a-real-interpreter"]

    result = PipStage().check(_Ctx())
    assert not result.ok, result
    assert result.data.get("want"), result.data
