# -*- coding: utf-8 -*-
"""Provider configuration for model factories."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderConfig:
    api_key_env: Optional[str] = None
    base_url_env: Optional[str] = None
    default_base_url: Optional[str] = None


PROVIDER_CONFIG = {
    "openai": ProviderConfig(api_key_env="OPENAI_API_KEY"),
    "gemini": ProviderConfig(api_key_env="GOOGLE_API_KEY"),
    "anthropic": ProviderConfig(api_key_env="ANTHROPIC_API_KEY"),
    "byteplus": ProviderConfig(
        api_key_env="BYTEPLUS_API_KEY",
        base_url_env="BYTEPLUS_BASE_URL",
        default_base_url="https://ark.ap-southeast.bytepluses.com/api/v3",
    ),
    "remote": ProviderConfig(
        base_url_env="REMOTE_MODEL_URL",
        default_base_url="http://localhost:11434",
    ),
}
