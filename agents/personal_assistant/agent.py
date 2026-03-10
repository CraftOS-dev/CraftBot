# -*- coding: utf-8 -*-
"""
PersonalAssistantAgent
======================

A general “executive assistant” role: meeting scheduling, travel
research, summarising documents, etc.
"""

from __future__ import annotations

import yaml
from importlib import import_module
from pathlib import Path

from app.agent_base import AgentBase
from app.logger import logger


class PersonalAssistantAgent(AgentBase):
    # Factory for Docker entrypoint / tests
    @classmethod
    def from_bundle(cls, bundle_dir: str | Path) -> "PersonalAssistantAgent":
        bundle_path = Path(bundle_dir).resolve()
        cfg = yaml.safe_load((bundle_path / "config.yaml").read_text())
        return cls(cfg, bundle_path)

    def __init__(self, cfg: dict, bundle_path: Path):
        self._bundle_path = bundle_path
        self._cfg = cfg
        super().__init__(
            data_dir=cfg.get("data_dir", "app/data"),
            chroma_path=str(bundle_path / cfg.get("rag_dir", "rag_docs")),
        )

    # -------- AgentBase hooks ----------------------------------------- #

    def _generate_role_info_prompt(self) -> str:
        base_prompt = (
            "You are an intelligent personal assistant for professionals and executives.\n"
            "Your role includes:\n"
            "- Scheduling meetings and reminders.\n"
            "- Summarising documents and extracting key action points.\n"
            "- Researching travel, events, or logistics.\n"
            "- Assisting in task prioritisation and time management.\n\n"
            "Respond clearly, concisely, and respectfully, adapting your tone to the user's communication style."
        )
        # Append interface-specific capabilities (e.g., file attachment in browser mode)
        return base_prompt + self._get_interface_capabilities_prompt()

    def _register_extra_actions(self) -> None:
        actions_pkg = "agents.personal_assistant.actions"
        try:
            import_module(actions_pkg)
        except ModuleNotFoundError as exc:
            logger.debug("PersonalAssistantAgent: no extra actions found (%s)", exc)
            return

        from pkgutil import iter_modules

        package_path = self._bundle_path / "actions"
        for mod_info in iter_modules([str(package_path)]):
            mod = import_module(f"{actions_pkg}.{mod_info.name}")
            if hasattr(mod, "register"):
                mod.register(self.action_library)


if __name__ == "__main__":  # python -m agents.personal_assistant.agent
    import asyncio
    import pathlib

    bundle_dir = pathlib.Path(__file__).parent  # .../agents/personal_assistant
    agent = PersonalAssistantAgent.from_bundle(bundle_dir)
    asyncio.run(agent.run())
