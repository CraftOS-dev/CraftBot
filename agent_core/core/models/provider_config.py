# -*- coding: utf-8 -*-
"""Provider profiles: the single source of truth for provider identity.

Phase 1 of docs/PROVIDER_LAYER_CATCHUP.md (FR-1). A ProviderProfile declares
everything about a provider in one place: auth env vars, endpoints, display
names, settings.json mapping, subscription OAuth, default models, and the
OpenRouter proxy fallback. Structures that used to be hand-synced across six
files (PROVIDER_INFO, PROVIDER_TO_SETTINGS_KEY, the /provider CLI list,
MODEL_REGISTRY, the factory's OpenRouter maps, connection-test models) are
now DERIVED from these profiles — see agent_core/core/models/registry.py.

Profiles are declarative data. They do not own client construction, session
state, caching, or error handling; those stay on ModelFactory/LLMInterface.

``ProviderConfig`` is kept as an alias of ``ProviderProfile`` so every
existing import keeps working.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from agent_core.core.models.types import InterfaceType


# Sentinel for ProviderProfile.fixed_temperature meaning "do NOT send the
# temperature field at all" — the model manages it server-side. Adopted from
# Hermes Agent (providers/base.py); required by Moonshot/Kimi thinking models
# (kimi-k2.5+), whose API rejects an explicit temperature
# ("invalid temperature: only 1 is allowed for this model"). Verified against
# the Kimi API docs ("temperature is not modifiable and should not be passed")
# and Hermes' kimi-coding profile (fixed_temperature=OMIT_TEMPERATURE).
OMIT_TEMPERATURE = object()


@dataclass(frozen=True)
class ProviderProfile:
    # ── auth & endpoints (original ProviderConfig fields) ─────────────
    api_key_env: Optional[str] = None
    base_url_env: Optional[str] = None
    default_base_url: Optional[str] = None

    # ── identity / display ────────────────────────────────────────────
    key: str = ""
    display_name: str = ""  # settings-UI name (was PROVIDER_INFO["name"])
    # Short name used in factory error messages (was factory._PROVIDER_DISPLAY).
    # None -> callers fall back to the raw provider key, preserving the old
    # ``_PROVIDER_DISPLAY.get(provider, provider)`` behavior exactly.
    error_display_name: Optional[str] = None
    # Wire protocol / transport key (consumed by Phase 2 transports):
    # chat_completions | anthropic_messages | bedrock_converse |
    # gemini_native | byteplus_responses | ollama
    wire: str = "chat_completions"

    # ── settings.json / self-config mapping ───────────────────────────
    # api_keys key in settings.json (was PROVIDER_TO_SETTINGS_KEY).
    # None -> provider has no single API key (bedrock, remote).
    settings_key: Optional[str] = None
    requires_api_key: bool = True
    # True -> the settings UI renders the AWS credentials block
    # (was PROVIDER_INFO["is_bedrock"]).
    aws_credential_block: bool = False

    # ── subscription OAuth (was scattered across PROVIDER_INFO) ───────
    # Backend name in craftos_integrations/integrations/llm_oauth
    # ("chatgpt" flows live under provider key "openai"; the backend is
    # addressed by the provider key, so this field just marks support).
    oauth_backend: Optional[str] = None
    subscription_label: Optional[str] = None
    subscription_models: Tuple[str, ...] = ()
    subscription_default_model: Optional[str] = None

    # ── UI capabilities ───────────────────────────────────────────────
    # Frontend opts into the catalog-aware model picker (OpenRouter).
    supports_catalog_picker: bool = False

    # ── models ────────────────────────────────────────────────────────
    # {InterfaceType: default model id} (was MODEL_REGISTRY row).
    default_models: Mapping[InterfaceType, Optional[str]] = field(
        default_factory=dict
    )
    # Tiny known-good model for auth checks (was connection_test_models.json).
    connection_test_model: Optional[str] = None
    connection_test_max_tokens: Optional[int] = None

    # ── model discovery (Phase U2, docs/PROVIDER_SETTINGS_UX_FIX.md) ───
    # True when the provider exposes an OpenAI-standard GET {base_url}/models
    # that lists usable models, so the settings UI offers a live dropdown +
    # Refresh instead of a blind text box.
    supports_model_discovery: bool = False
    # Local-server flavor for richer native handling: "lmstudio" unlocks the
    # native list-all (/api/v1/models) + load (/api/v1/models/load) UI.
    local_kind: Optional[str] = None

    # ── caching / request quirks (consumed by Phase 2/3) ──────────────
    # Whether the endpoint documents ``prompt_cache_key``. True only for
    # providers that already receive it today (NFR-3: golden payloads
    # must not change).
    supports_prompt_cache_key: bool = False
    # Temperature policy for the chat_completions wire (Hermes-style):
    #   None            -> send the caller's temperature (default behavior)
    #   OMIT_TEMPERATURE -> do NOT send temperature (Kimi/Moonshot thinking
    #                       models reject it; the server manages it)
    #   a float          -> always send this fixed value
    fixed_temperature: Any = None
    # Whether the provider accepts response_format={"type":"json_object"} on
    # its chat endpoint. True by default (the major OpenAI-compatible
    # providers do). Set False for endpoints that only accept json_schema
    # (Perplexity hard-400s on json_object; LM Studio ignores/rejects it) —
    # those fall back to prompt-instructed JSON, exactly like Hermes (which
    # never sends response_format at all). Verified against provider docs.
    supports_json_object: bool = True
    # Output-token cap: many providers 400 (not clamp) when the requested
    # max_tokens exceeds the model's output limit. When set, the transport
    # sends min(caller_max_tokens, max_output_tokens). None = no cap.
    # Values are battle-tested (Hermes default_max_tokens) or from docs.
    max_output_tokens: Optional[int] = None
    # True -> always send the OpenAI `max_completion_tokens` field instead of
    # the legacy `max_tokens` (OpenAI deprecated max_tokens; Cerebras/MiniMax
    # require the new field; Groq deprecates max_tokens). False -> legacy
    # `max_tokens`.
    uses_max_completion_tokens: bool = False
    # Whether the chat_completions session path accumulates a growing
    # [user, assistant, ...] history for this provider (the
    # _openai_compat_session_messages buffer). False preserves the
    # historical behavior for minimax/moonshot, whose session turns fall
    # through to stateless generation. Only meaningful on the
    # chat_completions wire.
    session_accumulation: bool = False
    default_headers: Mapping[str, str] = field(default_factory=dict)

    # ── OpenRouter proxy fallback (was factory module maps) ───────────
    # True -> route through OpenRouter when no direct key is configured
    # (geo-restricted direct APIs; was _OPENROUTER_PROXIED membership).
    openrouter_proxy: bool = False
    openrouter_namespace: Optional[str] = None  # was _OR_NAMESPACE
    openrouter_slug_map: Mapping[str, str] = field(default_factory=dict)

    @property
    def settings_endpoint_key(self) -> str:
        """settings.json ``endpoints.<key>`` slot for this provider's base URL.

        Derived so every provider (built-in, local server, custom) has a
        persistence slot without hand-syncing a per-provider branch in the
        save/load/test paths. The derivation reproduces the legacy keys
        exactly: BYTEPLUS_BASE_URL -> byteplus_base_url, REMOTE_MODEL_URL ->
        remote_model_url, OPENROUTER_BASE_URL -> openrouter_base_url,
        AWS_REGION -> aws_region (Bedrock's "base URL" is the region).
        """
        if self.base_url_env:
            return self.base_url_env.lower()
        return f"{self.key}_base_url"


# Legacy alias — every existing `from ... import ProviderConfig` keeps working.
ProviderConfig = ProviderProfile


def resolve_temperature(profile: Optional[ProviderProfile], caller_temperature):
    """Temperature to send on a chat_completions request, per the provider's
    policy. Returns OMIT_TEMPERATURE when the field must be dropped entirely.

    - profile.fixed_temperature is OMIT_TEMPERATURE -> OMIT_TEMPERATURE
    - profile.fixed_temperature is a value          -> that value
    - otherwise                                     -> caller's temperature
    """
    fixed = profile.fixed_temperature if profile is not None else None
    if fixed is OMIT_TEMPERATURE:
        return OMIT_TEMPERATURE
    if fixed is not None:
        return fixed
    return caller_temperature


PROVIDER_CONFIG: Dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        key="openai",
        session_accumulation=True,
        api_key_env="OPENAI_API_KEY",
        display_name="OpenAI",
        error_display_name="OpenAI",
        settings_key="openai",
        oauth_backend="chatgpt",
        subscription_label="Sign in with ChatGPT",
        # Codex-accepted models for ChatGPT subscription auth.
        subscription_models=(
            "gpt-5.4",
            "gpt-5.5",
            "gpt-5.4-mini",
            "gpt-5.3-codex-spark",
        ),
        subscription_default_model="gpt-5.4",
        supports_prompt_cache_key=True,
        # OpenAI deprecated `max_tokens` in favor of `max_completion_tokens`;
        # every current chat model accepts the new field, and reasoning
        # models (o-series, gpt-5.x) reject the old one.
        uses_max_completion_tokens=True,
        # Reasoning models reject an explicit temperature ("'temperature'
        # does not support 0.0 with this model. Only the default (1) value
        # is supported."). Omitting the field is valid on every OpenAI
        # model (the server applies its default), so the profile drops it
        # unconditionally — same policy as Kimi/Moonshot.
        fixed_temperature=OMIT_TEMPERATURE,
        connection_test_model="gpt-4o-mini",
        default_models={
            InterfaceType.LLM: "gpt-5.2-2025-12-11",
            InterfaceType.VLM: "gpt-5.2-2025-12-11",
            InterfaceType.EMBEDDING: "text-embedding-3-small",
            InterfaceType.IMAGE_GEN: "gpt-image-2",
            InterfaceType.VIDEO_GEN: "sora-2",
        },
    ),
    "gemini": ProviderProfile(
        key="gemini",
        api_key_env="GOOGLE_API_KEY",
        display_name="Google Gemini",
        wire="gemini_native",
        settings_key="google",
        connection_test_model="gemini-2.0-flash",
        default_models={
            InterfaceType.LLM: "gemini-2.5-pro",
            InterfaceType.VLM: "gemini-2.5-pro",
            InterfaceType.EMBEDDING: "text-embedding-004",
            InterfaceType.IMAGE_GEN: "gemini-3-pro-image",
            InterfaceType.VIDEO_GEN: "veo-3.1-generate-preview",
        },
    ),
    "anthropic": ProviderProfile(
        key="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        wire="anthropic_messages",
        settings_key="anthropic",
        connection_test_model="claude-haiku-4-5-20251001",
        connection_test_max_tokens=1,
        default_models={
            InterfaceType.LLM: "claude-sonnet-4-6",
            InterfaceType.VLM: "claude-sonnet-4-6",
            # Anthropic does not provide native embedding models.
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "byteplus": ProviderProfile(
        key="byteplus",
        api_key_env="BYTEPLUS_API_KEY",
        base_url_env="BYTEPLUS_BASE_URL",
        default_base_url="https://ark.ap-southeast.bytepluses.com/api/v3",
        display_name="BytePlus",
        wire="byteplus_responses",
        settings_key="byteplus",
        connection_test_model="kimi-k2-250905",
        default_models={
            InterfaceType.LLM: "seed-2-0-pro-260328",
            InterfaceType.VLM: "seed-2-0-pro-260328",
            InterfaceType.EMBEDDING: "skylark-embedding-vision-250615",
            InterfaceType.IMAGE_GEN: None,
            # BytePlus international (ap-southeast.bytepluses.com) model IDs
            # use dated build suffixes, no dots, no `doubao-` prefix
            # (`doubao-*` is the Volcengine China naming). Verified from
            # BytePlus ModelArk docs.
            InterfaceType.VIDEO_GEN: "seedance-1-0-pro-fast-251015",
        },
    ),
    "remote": ProviderProfile(
        key="remote",
        base_url_env="REMOTE_MODEL_URL",
        default_base_url="http://localhost:11434",
        display_name="Local (Ollama)",
        wire="ollama",
        requires_api_key=False,
        connection_test_model="llama3",
        default_models={
            InterfaceType.LLM: "llama3.2:3b",
            InterfaceType.VLM: "llava:7b",
            InterfaceType.EMBEDDING: "nomic-embed-text",
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "minimax": ProviderProfile(
        key="minimax",
        api_key_env="MINIMAX_API_KEY",
        # International OpenAI-compatible endpoint (verified 2026-08-17:
        # platform.minimax.io). The old api.minimax.chat domain is RETIRED.
        base_url_env="MINIMAX_BASE_URL",
        default_base_url="https://api.minimax.io/v1",
        display_name="MiniMax",
        error_display_name="MiniMax",
        settings_key="minimax",
        # MiniMax caches passively (no request key) and reports hits in
        # usage.prompt_tokens_details.cached_tokens (which the reader counts).
        # Sending prompt_cache_key is undocumented for MiniMax -> don't.
        supports_prompt_cache_key=False,
        # MiniMax's OpenAI-compat /v1 endpoint uses max_completion_tokens
        # (not max_tokens); M2.x also inlines <think>...</think> reasoning in
        # content, which the transport strips.
        uses_max_completion_tokens=True,
        # MiniMax has no /v1/models endpoint — the connection tester must do
        # a real (tiny) chat call against this model.
        connection_test_model="MiniMax-M2.1",
        openrouter_proxy=True,
        openrouter_namespace="minimax",
        openrouter_slug_map={
            # Slugs follow OpenRouter's lowercase convention; verify against
            # openrouter.ai/models when bumping the MiniMax model family.
            "MiniMax-M3": "minimax/minimax-m3",
            "MiniMax-M2.1": "minimax/minimax-m2.1",
            "MiniMax-M2": "minimax/minimax-m2",
        },
        default_models={
            # MiniMax-Text-01 was retired upstream; M-series is current
            # (M3 flagship, M2.x cheap tier).
            InterfaceType.LLM: "MiniMax-M2.1",
            InterfaceType.VLM: None,
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "deepseek": ProviderProfile(
        key="deepseek",
        session_accumulation=True,
        api_key_env="DEEPSEEK_API_KEY",
        default_base_url="https://api.deepseek.com",
        display_name="DeepSeek",
        error_display_name="DeepSeek",
        settings_key="deepseek",
        supports_prompt_cache_key=True,
        connection_test_model="deepseek-chat",
        default_models={
            InterfaceType.LLM: "deepseek-chat",
            InterfaceType.VLM: None,
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "moonshot": ProviderProfile(
        key="moonshot",
        api_key_env="MOONSHOT_API_KEY",
        # International endpoint (verified 2026-08-17: platform.kimi.ai).
        base_url_env="MOONSHOT_BASE_URL",
        default_base_url="https://api.moonshot.ai/v1",
        display_name="Moonshot",
        error_display_name="Moonshot",
        settings_key="moonshot",
        # Kimi/Moonshot is a strict provider (rejects unknown request fields);
        # prompt_cache_key acceptance is undocumented, so don't send it. Kimi
        # caches context automatically; the reader counts cached_tokens.
        supports_prompt_cache_key=False,
        # Kimi thinking models (k2.5+) reject an explicit temperature — omit
        # it (verified: Kimi API docs + Hermes kimi-coding profile).
        fixed_temperature=OMIT_TEMPERATURE,
        connection_test_model="kimi-k2.5",
        openrouter_proxy=True,
        openrouter_namespace="moonshotai",
        openrouter_slug_map={
            "kimi-k2.5": "moonshotai/kimi-k2.5",
            "moonshot-v1-8k": "moonshotai/moonshot-v1-8k",
            "moonshot-v1-32k": "moonshotai/moonshot-v1-32k",
            "moonshot-v1-128k": "moonshotai/moonshot-v1-128k",
            "moonshot-v1-8k-vision-preview": (
                "moonshotai/moonshot-v1-8k-vision-preview"
            ),
        },
        default_models={
            InterfaceType.LLM: "kimi-k2.5",
            InterfaceType.VLM: "moonshot-v1-8k-vision-preview",
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "grok": ProviderProfile(
        key="grok",
        session_accumulation=True,
        api_key_env="XAI_API_KEY",
        default_base_url="https://api.x.ai/v1",
        display_name="Grok (xAI)",
        error_display_name="Grok",
        settings_key="grok",
        # Subscription OAuth (SuperGrok / X Premium+). xAI publicly endorsed
        # this path in May 2026.
        oauth_backend="grok",
        subscription_label="Sign in with Grok",
        subscription_models=("grok-4-0709", "grok-3"),
        supports_prompt_cache_key=True,
        default_models={
            InterfaceType.LLM: "grok-3",
            InterfaceType.VLM: "grok-4-0709",
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "glm": ProviderProfile(
        key="glm",
        session_accumulation=True,
        # Z.ai (Zhipu AI) GLM models -- OpenAI-compatible API.
        api_key_env="ZAI_API_KEY",
        default_base_url="https://api.z.ai/api/paas/v4",
        display_name="Z.ai (GLM)",
        settings_key="glm",
        supports_prompt_cache_key=True,
        connection_test_model="glm-5.2",
        default_models={
            # Z.ai (Zhipu AI) GLM-5.2 -- 1M-context, OpenAI-compatible,
            # multimodal.
            InterfaceType.LLM: "glm-5.2",
            InterfaceType.VLM: "glm-5.2",
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "fugu": ProviderProfile(
        key="fugu",
        session_accumulation=True,
        # Sakana AI Fugu -- OpenAI-compatible API.
        api_key_env="SAKANA_API_KEY",
        default_base_url="https://api.sakana.ai/v1",
        display_name="Sakana (Fugu)",
        settings_key="fugu",
        supports_prompt_cache_key=True,
        connection_test_model="fugu",
        default_models={
            # Sakana AI Fugu -- OpenAI-compatible orchestration model.
            # Text/LLM only; no native vision/embedding/image/video models.
            InterfaceType.LLM: "fugu",
            InterfaceType.VLM: None,
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "openrouter": ProviderProfile(
        key="openrouter",
        session_accumulation=True,
        api_key_env="OPENROUTER_API_KEY",
        base_url_env="OPENROUTER_BASE_URL",
        default_base_url="https://openrouter.ai/api/v1",
        display_name="OpenRouter",
        error_display_name="OpenRouter",
        settings_key="openrouter",
        supports_prompt_cache_key=True,
        supports_catalog_picker=True,
        default_models={
            # OpenRouter slugs follow `<provider>/<model>` format. Default to
            # a Claude model so KV caching exercises the cache_control path on
            # first use.
            InterfaceType.LLM: "anthropic/claude-sonnet-4.5",
            InterfaceType.VLM: "anthropic/claude-sonnet-4.5",
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "bedrock": ProviderProfile(
        key="bedrock",
        # Bedrock uses the boto3 credential chain (access_key / secret_key /
        # session_token) read from settings.json by the factory. There is no
        # single API key, so api_key_env stays None. base_url_env carries the
        # AWS region (e.g. "us-east-1") through the factory plumbing.
        base_url_env="AWS_REGION",
        default_base_url="us-east-1",
        display_name="AWS Bedrock",
        wire="bedrock_converse",
        requires_api_key=False,
        aws_credential_block=True,
        connection_test_model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        default_models={
            # Default to Claude Haiku 4.5 — best price/performance on Bedrock
            # with cachePoint support (5-min + 1-hour TTL). The `us.` prefix
            # is the cross-region inference profile, required because Claude
            # 4.x models reject on-demand invocations against the bare
            # `anthropic.*` ID. The `us.anthropic.` prefix still matches
            # `_BEDROCK_CACHE_PREFIXES`, so cachePoint is exercised. Users in
            # EU / APAC regions should change `us.` to `eu.` / `ap.`.
            # Haiku 4.5 also accepts image content blocks via Converse, so it
            # doubles as the VLM default. Embedding stays on Titan.
            InterfaceType.LLM: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            InterfaceType.VLM: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            InterfaceType.EMBEDDING: "amazon.titan-embed-text-v2:0",
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    # ── Phase 3 additions (endpoints verified 2026-08-17, see
    # docs/PROVIDER_LAYER_CATCHUP.md section 8.3/8.4) ──────────────────
    "groq": ProviderProfile(
        key="groq",
        session_accumulation=True,
        api_key_env="GROQ_API_KEY",
        base_url_env="GROQ_BASE_URL",
        default_base_url="https://api.groq.com/openai/v1",
        display_name="Groq",
        settings_key="groq",
        # The llama-3.x / llama-4-scout ids were decommissioned (Groq
        # deprecations page, Aug 2026); gpt-oss are Groq's current
        # general models. Groq deprecates `max_tokens` -> use
        # max_completion_tokens; cap output to the model's limit.
        connection_test_model="openai/gpt-oss-20b",
        supports_model_discovery=True,
        uses_max_completion_tokens=True,
        max_output_tokens=32768,
        default_models={
            InterfaceType.LLM: "openai/gpt-oss-120b",
            # Groq's vision lineup churned (llama-4-scout gone); its current
            # VLM id could not be confirmed against docs, so leave VLM off and
            # let the model dropdown (discovery) surface it. Better no default
            # than a dead/guessed id.
            InterfaceType.VLM: None,
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "mistral": ProviderProfile(
        key="mistral",
        session_accumulation=True,
        api_key_env="MISTRAL_API_KEY",
        base_url_env="MISTRAL_BASE_URL",
        default_base_url="https://api.mistral.ai/v1",
        display_name="Mistral",
        settings_key="mistral",
        # "-latest" aliases insulate against Mistral's dated concrete ids.
        connection_test_model="mistral-small-latest",
        supports_model_discovery=True,
        # Mistral La Plateforme has prompt caching and honors the
        # `prompt_cache_key` field (cached tokens billed at 10%, reported in
        # usage.prompt_tokens_details.cached_tokens — the field we read).
        # Without this we send no cache key and get 0% hits on repeated
        # prefixes (observed in a live session at slow_mode's TPM ceiling).
        supports_prompt_cache_key=True,
        default_models={
            InterfaceType.LLM: "mistral-large-latest",
            # pixtral-large-latest was retired (2026-05-31). mistral-small is
            # multimodal and current, so it doubles as the VLM default.
            InterfaceType.VLM: "mistral-small-latest",
            InterfaceType.EMBEDDING: "mistral-embed",
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "together": ProviderProfile(
        key="together",
        session_accumulation=True,
        api_key_env="TOGETHER_API_KEY",
        base_url_env="TOGETHER_BASE_URL",
        # api.together.ai is the current docs domain; the legacy
        # api.together.xyz still resolves.
        default_base_url="https://api.together.ai/v1",
        display_name="Together AI",
        settings_key="together",
        connection_test_model="meta-llama/Llama-3.1-8B-Instruct-Turbo",
        supports_model_discovery=True,
        # Together's serverless models cap output well below our default;
        # Llama-3.3-70B ~16k. Exceeding it 4xxes.
        max_output_tokens=16384,
        default_models={
            InterfaceType.LLM: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            InterfaceType.VLM: "meta-llama/Llama-4-Scout-17B-16E-Instruct",
            InterfaceType.EMBEDDING: "BAAI/bge-large-en-v1.5",
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "fireworks": ProviderProfile(
        key="fireworks",
        session_accumulation=True,
        api_key_env="FIREWORKS_API_KEY",
        base_url_env="FIREWORKS_BASE_URL",
        default_base_url="https://api.fireworks.ai/inference/v1",
        display_name="Fireworks",
        settings_key="fireworks",
        connection_test_model="accounts/fireworks/models/llama-v3p1-8b-instruct",
        supports_model_discovery=True,
        default_models={
            # `p`-for-dot version naming: v3p3 = 3.3, qwen2p5-vl = Qwen2.5-VL.
            # llama-v3p3-70b's serverless availability is ambiguous; glm-5p2 is
            # a Hermes-verified served Fireworks model (their aux default).
            InterfaceType.LLM: "accounts/fireworks/models/glm-5p2",
            InterfaceType.VLM: "accounts/fireworks/models/qwen2p5-vl-32b-instruct",
            InterfaceType.EMBEDDING: (
                "accounts/fireworks/models/nomic-embed-text-v1.5"
            ),
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "cerebras": ProviderProfile(
        key="cerebras",
        session_accumulation=True,
        api_key_env="CEREBRAS_API_KEY",
        base_url_env="CEREBRAS_BASE_URL",
        default_base_url="https://api.cerebras.ai/v1",
        display_name="Cerebras",
        settings_key="cerebras",
        # Cerebras' catalog is small and churns; gpt-oss-120b is their
        # long-lived production model (stable pick for the auth test too).
        connection_test_model="gpt-oss-120b",
        supports_model_discovery=True,
        # Cerebras' OpenAI-compat endpoint documents max_completion_tokens;
        # gpt-oss-120b output cap is 32k (free) — exceeding it errors.
        uses_max_completion_tokens=True,
        max_output_tokens=32000,
        # Cerebras documents prompt_cache_key as a routing hint (max 1024
        # chars) and reports hits in prompt_tokens_details.cached_tokens.
        supports_prompt_cache_key=True,
        default_models={
            InterfaceType.LLM: "gpt-oss-120b",
            # Cerebras is a speed-focused, text-only inference stack — no
            # vision model on the chat endpoint (VLM field stays hidden).
            InterfaceType.VLM: None,
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "qwen": ProviderProfile(
        key="qwen",
        session_accumulation=True,
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        # International (Singapore) endpoint; keys are region-scoped.
        # Alibaba is migrating to workspace-scoped maas.aliyuncs.com
        # domains, but this legacy intl domain needs no WorkspaceId.
        default_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        display_name="Qwen (Alibaba)",
        settings_key="qwen",
        connection_test_model="qwen-flash",
        supports_model_discovery=True,
        # DashScope documents temperature range [0, 2) and "do not set to 0"
        # — send a small positive value instead of the caller's 0.0.
        # (json_object works because our prompts contain the word "json".)
        fixed_temperature=0.01,
        # Qwen output caps are well under our default; 8k is a safe ceiling.
        max_output_tokens=8192,
        default_models={
            InterfaceType.LLM: "qwen-max",
            InterfaceType.VLM: "qwen-vl-max",
            InterfaceType.EMBEDDING: "text-embedding-v4",
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "huggingface": ProviderProfile(
        key="huggingface",
        session_accumulation=True,
        api_key_env="HF_TOKEN",
        base_url_env="HF_ROUTER_BASE_URL",
        default_base_url="https://router.huggingface.co/v1",
        display_name="Hugging Face",
        settings_key="huggingface",
        # Hub ids, optionally suffixed with a provider (":groq") or policy
        # (":fastest" default, ":cheapest").
        connection_test_model="meta-llama/Llama-3.1-8B-Instruct",
        supports_model_discovery=True,
        default_models={
            InterfaceType.LLM: "deepseek-ai/DeepSeek-V3-0324",
            InterfaceType.VLM: "Qwen/Qwen2.5-VL-7B-Instruct",
            # The router's OpenAI-compatible /v1 surface is chat-only; no
            # /v1/embeddings, so no embedding default here.
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "nvidia": ProviderProfile(
        key="nvidia",
        session_accumulation=True,
        api_key_env="NVIDIA_API_KEY",
        base_url_env="NVIDIA_BASE_URL",
        default_base_url="https://integrate.api.nvidia.com/v1",
        display_name="NVIDIA NIM",
        settings_key="nvidia",
        connection_test_model="meta/llama-3.1-8b-instruct",
        supports_model_discovery=True,
        # NIM caps output low; Hermes ships 16384 as its battle-tested value.
        max_output_tokens=16384,
        default_models={
            InterfaceType.LLM: "meta/llama-3.3-70b-instruct",
            InterfaceType.VLM: "meta/llama-3.2-90b-vision-instruct",
            InterfaceType.EMBEDDING: "nvidia/nv-embedqa-e5-v5",
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "perplexity": ProviderProfile(
        key="perplexity",
        session_accumulation=True,
        api_key_env="PERPLEXITY_API_KEY",
        base_url_env="PERPLEXITY_BASE_URL",
        # Legacy Sonar chat-completions surface. NOTE: Perplexity retires the
        # Sonar tiers on 2026-09-27; the successor is the Agent API
        # (https://api.perplexity.ai/docs/agent-api). Migrate before then.
        default_base_url="https://api.perplexity.ai",
        display_name="Perplexity",
        settings_key="perplexity",
        connection_test_model="sonar",
        # Perplexity's chat API hard-400s on response_format json_object (it
        # only accepts text/json_schema); fall back to prompt-instructed JSON.
        supports_json_object=False,
        # Perplexity does NOT expose GET /v1/models and we don't ship a
        # hardcoded model list (it would go stale), so the settings UI renders
        # a free-text model box. sonar-pro is the pre-filled default below.
        default_models={
            InterfaceType.LLM: "sonar-pro",
            # Sonar accepts image input but is search-grounded, not a general
            # describe-image VLM — intentionally no VLM default.
            InterfaceType.VLM: None,
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    # GitHub Copilot is temporarily disabled (commented out, not removed).
    # The OAuth backend (craftos_integrations/.../llm_oauth/copilot.py) and its
    # tests remain intact; re-enable by uncommenting this profile.
    # "copilot": ProviderProfile(
    #     key="copilot",
    #     session_accumulation=True,
    #     # Subscription-only provider: no API-key mode exists. Without a
    #     # connected GitHub Copilot seat, calls fail with a classified auth
    #     # error pointing at Settings.
    #     default_base_url="https://api.githubcopilot.com",
    #     display_name="GitHub Copilot",
    #     requires_api_key=False,
    #     oauth_backend="copilot",
    #     subscription_label="Sign in with GitHub",
    #     subscription_models=("gpt-4o", "gpt-5.2"),
    #     subscription_default_model="gpt-4o",
    #     connection_test_model="gpt-4o",
    #     default_models={
    #         InterfaceType.LLM: "gpt-4o",
    #         InterfaceType.VLM: None,
    #         InterfaceType.EMBEDDING: None,
    #         InterfaceType.IMAGE_GEN: None,
    #         InterfaceType.VIDEO_GEN: None,
    #     },
    # ),
    "lmstudio": ProviderProfile(
        key="lmstudio",
        session_accumulation=True,
        base_url_env="LMSTUDIO_BASE_URL",
        default_base_url="http://localhost:1234/v1",
        display_name="LM Studio (Local)",
        requires_api_key=False,
        # LM Studio's OpenAI-compat endpoint supports json_schema, not
        # json_object — omit response_format and rely on prompt-instructed
        # JSON (vLLM and llama.cpp DO accept json_object, so they keep it).
        supports_json_object=False,
        # /v1/models discovery stays available for tooling, but the settings
        # UI keeps the model id free-text for local servers (local_kind set):
        # the user types whatever they loaded. The default below is a common
        # LM Studio download so the field is never blank.
        supports_model_discovery=True,
        local_kind="lmstudio",
        connection_test_model="openai/gpt-oss-20b",
        default_models={
            InterfaceType.LLM: "openai/gpt-oss-20b",
            # Vision runs if the user has a VLM loaded; Qwen2.5-VL is a common
            # LM Studio vision download.
            InterfaceType.VLM: "qwen2.5-vl-7b-instruct",
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "vllm": ProviderProfile(
        key="vllm",
        session_accumulation=True,
        base_url_env="VLLM_BASE_URL",
        default_base_url="http://localhost:8000/v1",
        display_name="vLLM (Local)",
        requires_api_key=False,
        # vLLM serves exactly one model. Discovery stays available for
        # tooling; the settings UI model field is free-text (local_kind).
        supports_model_discovery=True,
        local_kind="vllm",
        connection_test_model="meta-llama/Llama-3.1-8B-Instruct",
        default_models={
            InterfaceType.LLM: "meta-llama/Llama-3.1-8B-Instruct",
            InterfaceType.VLM: "Qwen/Qwen2.5-VL-7B-Instruct",
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
    "llamacpp": ProviderProfile(
        key="llamacpp",
        session_accumulation=True,
        base_url_env="LLAMACPP_BASE_URL",
        default_base_url="http://localhost:8080/v1",
        display_name="llama.cpp (Local)",
        requires_api_key=False,
        # llama-server serves one loaded model. Discovery stays available for
        # tooling; the settings UI model field is free-text (local_kind).
        supports_model_discovery=True,
        local_kind="llamacpp",
        connection_test_model="llama-3.1-8b-instruct",
        default_models={
            InterfaceType.LLM: "llama-3.1-8b-instruct",
            InterfaceType.VLM: None,
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    ),
}


def get_profile(provider: str) -> ProviderProfile:
    """Return the profile for ``provider``.

    Raises the same ``ValueError`` the factory has always raised for unknown
    providers, so the error contract is unchanged.
    """
    try:
        return PROVIDER_CONFIG[provider]
    except KeyError:
        raise ValueError(f"Unsupported provider: {provider}") from None


def _sanity_check_profiles() -> None:
    """Registry invariants (Phase 0/1 gate; cheap, import-time)."""
    seen_settings_keys: Dict[str, str] = {}
    for key, profile in PROVIDER_CONFIG.items():
        assert profile.key == key, f"profile.key mismatch for {key!r}"
        assert profile.display_name, f"missing display_name for {key!r}"
        if profile.requires_api_key:
            assert profile.api_key_env, f"missing api_key_env for {key!r}"
            assert profile.settings_key, f"missing settings_key for {key!r}"
        if profile.settings_key:
            prior = seen_settings_keys.setdefault(profile.settings_key, key)
            assert prior == key, (
                f"settings_key {profile.settings_key!r} shared by "
                f"{prior!r} and {key!r}"
            )


_sanity_check_profiles()
