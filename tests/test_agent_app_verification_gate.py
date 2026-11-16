"""Promotion needs a walk-verify pass for the code upstream last validated."""

import json
from types import SimpleNamespace

import pytest

from app.agent_app import framework_host
from app.agent_app.framework_store import HostStore


@pytest.mark.parametrize(
    ("verified", "gate", "allowed"),
    [
        ({"verdict": "pass", "stamp": {"fingerprint": "abc", "at": "t1"}}, {"fingerprint": "abc", "at": "t1"}, True),
        # Re-validating unchanged code only rewrites the pass's timestamp.
        ({"verdict": "pass", "stamp": {"fingerprint": "abc", "at": "t1"}}, {"fingerprint": "abc", "at": "t2"}, True),
        ({"verdict": "pass", "stamp": {"fingerprint": "abc", "at": "t1"}}, {"fingerprint": "new", "at": "t2"}, False),
        ({"verdict": "defects", "stamp": {"fingerprint": "abc", "at": "t1"}}, {"fingerprint": "abc", "at": "t1"}, False),
        ({"verdict": "pass", "stamp": {"fingerprint": "abc", "at": "t1"}}, None, False),
    ],
)
def test_promote_requires_a_pass_for_the_validated_fingerprint(
    tmp_path, monkeypatch, verified, gate, allowed
):
    monkeypatch.setattr(framework_host, "_host", None)
    host = framework_host.FrameworkHost(
        SimpleNamespace(), store=HostStore(tmp_path / "host.sqlite3")
    )
    app = tmp_path / "app"
    (app / ".a2app").mkdir(parents=True)
    if gate is not None:
        (app / ".a2app" / "gate-pass.json").write_text(json.dumps(gate))
    host.store.put("verification", str(app.resolve()), verified)
    if allowed:
        host.require_verified(str(app))
    else:
        with pytest.raises(ValueError, match="Independent verification has not passed"):
            host.require_verified(str(app))
