"""The test fixture must never inherit a developer's runtime or credentials."""

import json
import pytest
from tests.qa_runtime import seed_runtime


def test_runtime_seeds_assets_but_strips_credentials_and_databases(tmp_path):
    code, home = tmp_path / "code", tmp_path / "home"
    config = code / "app/config"
    config.mkdir(parents=True)
    secrets = {
        key: {"secret": "do-not-copy"}
        for key in (
            "api_keys",
            "oauth",
            "aws_credentials",
            "credentials",
            "model_pools",
        )
    }
    (config / "settings.json").write_text(json.dumps({"version": "1.4.4", **secrets}))
    actions = code / "app/data/action"
    actions.mkdir(parents=True)
    (actions / "tool.py").write_text("pass")
    (actions / "user.db").write_text("private data")
    seed_runtime(code, home)
    settings = json.loads((home / "app/config/settings.json").read_text())
    assert settings["version"] == "1.4.4"
    assert not secrets.keys() & settings.keys()
    assert (home / "app/data/action/tool.py").is_file()
    assert not list(home.rglob("*.db"))
    with pytest.raises(ValueError, match="empty"):
        seed_runtime(code, home)
