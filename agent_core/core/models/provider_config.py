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
    "minimax": ProviderConfig(
        api_key_env="MINIMAX_API_KEY",
        default_base_url="https://api.minimax.chat/v1",
    ),
    "deepseek": ProviderConfig(
        api_key_env="DEEPSEEK_API_KEY",
        default_base_url="https://api.deepseek.com",
    ),
    "moonshot": ProviderConfig(
        api_key_env="MOONSHOT_API_KEY",
        default_base_url="https://api.moonshot.cn/v1",
    ),
    "grok": ProviderConfig(
        api_key_env="XAI_API_KEY",
        default_base_url="https://api.x.ai/v1",
    ),
    "glm": ProviderConfig(
        # Z.ai (Zhipu AI) GLM models -- OpenAI-compatible API.
        api_key_env="ZAI_API_KEY",
        default_base_url="https://api.z.ai/api/paas/v4",
    ),
    "fugu": ProviderConfig(
        # Sakana AI Fugu -- OpenAI-compatible API.
        api_key_env="SAKANA_API_KEY",
        default_base_url="https://api.sakana.ai/v1",
    ),
    "openrouter": ProviderConfig(
        api_key_env="OPENROUTER_API_KEY",
        base_url_env="OPENROUTER_BASE_URL",
        default_base_url="https://openrouter.ai/api/v1",
    ),
    "bedrock": ProviderConfig(
        # Bedrock uses the boto3 credential chain (access_key / secret_key /
        # session_token) read from settings.json by the factory. There is no
        # single API key, so api_key_env is left None. base_url_env carries
        # the AWS region (e.g. "us-east-1") through the factory plumbing.
        base_url_env="AWS_REGION",
        default_base_url="us-east-1",
    ),
}
