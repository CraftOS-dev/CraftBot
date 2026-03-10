# -*- coding: utf-8 -*-
"""
DogAgent
========

A dog

"""

from __future__ import annotations

import importlib.util
from importlib import import_module
from pathlib import Path

import yaml

from app.agent_base import AgentBase
from app.logger import logger


class DogAgent(AgentBase):
    """A friendly, dog-themed specialist built on :class:`AgentBase`."""

    # Factory for Docker entrypoint / tests
    @classmethod
    def from_bundle(cls, bundle_dir: str | Path) -> "DogAgent":
        bundle_path = Path(bundle_dir).resolve()
        cfg = yaml.safe_load((bundle_path / "config.yaml").read_text())
        return cls(cfg, bundle_path)

    def __init__(self, cfg: dict, bundle_path: Path):
        self._bundle_path = Path(bundle_path)
        self._cfg = cfg
        
        super().__init__(
            data_dir=cfg.get("data_dir", "app/data"),
            chroma_path=str(self._bundle_path / cfg.get("rag_dir", "rag_docs")),
            llm_provider=cfg.get("llm_provider", "byteplus"),
        )

    # -------- AgentBase hooks ----------------------------------------- #

    def _generate_role_info_prompt(self) -> str:
        base_prompt = (
            "You are a custom agent named DOG, a loyal and upbeat canine-inspired assistant.\n"
            "You MUST NOT talk at all. You MUST replace all human language with\n"
            "something like: 'Woof wooof woof, wooof wooff woof woff'\n"
            "You MUST NOT talk in human language AT ALL AS THAT VIOLATES your agent POLICY.\n"
            "When using the 'send_message' action, you MUST NOT send message in human langauge.\n"
            "You must REPLACE all English and human language words with 'woof' of different style and length.\n"
            "You do, however, still execute task for human using actions "
            "and offering encouraging nudges to stay productive."
        )
        # Append interface-specific capabilities (e.g., file attachment in browser mode)
        return base_prompt + self._get_interface_capabilities_prompt()

if __name__ == "__main__":  
    import asyncio

    bundle_dir = Path(__file__).parent  
    agent = DogAgent.from_bundle(bundle_dir)
    asyncio.run(agent.run())