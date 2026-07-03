# -*- coding: utf-8 -*-
from pathlib import Path

from startup_constants import CRAFTBOT_READY_MARKER


def test_ready_marker_literal_is_centralized():
    repo = Path(__file__).resolve().parents[1]
    offenders = []
    for relative in ("craftbot.py", "run.py", "installer/api.py"):
        text = (repo / relative).read_text(encoding="utf-8")
        if f'"{CRAFTBOT_READY_MARKER}"' in text or f"'{CRAFTBOT_READY_MARKER}'" in text:
            offenders.append(relative)

    assert offenders == []
