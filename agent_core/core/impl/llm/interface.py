# -*- coding: utf-8 -*-
"""
Shared LLM (Large Language Model) interface for agent_core.

This module provides the LLMInterface class that handles LLM
calls across different providers (OpenAI, Gemini, Anthropic, BytePlus, Ollama).

Hooks allow runtime-specific behavior:
- Token counting via get_token_count/set_token_count hooks
- Usage reporting via report_usage hook (CraftBot only)
- Database logging via log_to_db hook
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import re
import time
import requests
from typing import Any, Dict, List, Optional


from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import (
    BytePlusCacheManager,
    BytePlusContextOverflowError,
    GeminiCacheManager,
    get_cache_config,
    get_cache_metrics,
)
from agent_core.core.impl.llm.errors import (
    LLMConsecutiveFailureError,
    classify_llm_error,
)
from agent_core.core.hooks import (
    GetTokenCountHook,
    SetTokenCountHook,
    ReportUsageHook,
    LogToDbHook,
    UsageEventData,
    LLMCallRecord,
    RecordLLMCallHook,
)

# Logging setup - use shared agent_core logger for consistency
from agent_core.utils.logger import logger
from agent_core.utils.token import billable_tokens

# Per-call metadata (prompt identity + start time) propagated from the public
# entry methods down to the capture chokepoint (_call_log_to_db) without
# threading it through every provider method. asyncio.to_thread copies the
# context into the worker thread, so this survives the sync offload, and each
# asyncio Task / thread gets its own copy so concurrent calls don't clobber.
_llm_call_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_llm_call_ctx", default={}
)

# Per-call metadata (prompt identity + start time) propagated from the public
# entry methods down to the capture chokepoint (_call_log_to_db) without
# threading it through every provider method. asyncio.to_thread copies the
# context into the worker thread, so this survives the sync offload, and each
# asyncio Task / thread gets its own copy so concurrent calls don't clobber.
_llm_call_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_llm_call_ctx", default={}
)


class _EmptyResponse(Exception):
    """Raised when a provider returns empty/error content and the failure has already been counted.

    Using a distinct class prevents the outer except-Exception block in
    _generate_response_sync from double-incrementing the consecutive-failure
    counter for the same call.
    """


# Models that do NOT support assistant message prefill
# These require output_config.format for structured JSON output
_ANTHROPIC_NO_PREFILL_PATTERNS = (
    "claude-opus-4",  # Claude Opus 4.x (4.5, 4.6, etc.)
    "claude-sonnet-4",  # Claude Sonnet 4.x (4.5, 4.6, etc.)
    "claude-3-7",  # Claude 3.7 Sonnet
    "claude-3.7",  # Alternative naming
)


def _model_supports_prefill(model: str) -> bool:
    """Check if an Anthropic model supports assistant message prefill.

    Newer Claude models (4.x, 3.7) do not support prefilling.
    Older models (3.5 Sonnet, 3 Opus) still support it.

    Args:
        model: The model identifier string.

    Returns:
        True if the model supports prefill, False otherwise.
    """
    if not model:
        return True  # Default to supporting prefill for safety

    model_lower = model.lower()
    for pattern in _ANTHROPIC_NO_PREFILL_PATTERNS:
        if pattern in model_lower:
            return False
    return True


class LLMInterface:
    """LLM interface with multi-provider support and hook-based customization.

    Supports OpenAI, Gemini, Anthropic, BytePlus, and remote Ollama.
    Uses hooks for state access and usage reporting to decouple from
    runtime-specific state management.

    Args:
        provider: LLM provider name ("openai", "gemini", "anthropic", "byteplus", "remote").
        model: Model name override.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in response.
        deferred: Whether to defer initialization.
        get_token_count: Hook to get current token count from state.
        set_token_count: Hook to set token count in state.
        report_usage: Optional hook to report usage for cost tracking.
        log_to_db: Optional hook to log prompts to database.
    """

    _CODE_BLOCK_RE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.MULTILINE)

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 50000,
        deferred: bool = False,
        get_token_count: Optional[GetTokenCountHook] = None,
        set_token_count: Optional[SetTokenCountHook] = None,
        report_usage: Optional[ReportUsageHook] = None,
        log_to_db: Optional[LogToDbHook] = None,
        record_llm_call: Optional[RecordLLMCallHook] = None,
    ) -> None:
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._gemini_client = None
        self._anthropic_client = None
        self._initialized = False
        self._deferred = deferred

        # Store for reinitialization
        self._init_api_key = api_key
        self._init_base_url = base_url

        # Hooks for runtime-specific behavior
        self._get_token_count = get_token_count or (lambda: 0)
        self._set_token_count = set_token_count or (lambda x: None)
        self._report_usage = report_usage
        self._log_to_db = log_to_db
        self._record_llm_call = record_llm_call

        # Consecutive failure tracking to prevent infinite retry loops
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5

        # Defer imports to avoid circular dependency
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType

        ctx = ModelFactory.create(
            provider=provider,
            interface=InterfaceType.LLM,
            model_override=model,
            api_key=api_key,
            base_url=base_url,
            deferred=deferred,
        )

        logger.info(f"[LLM FACTORY] {ctx}")

        self.provider = ctx["provider"]
        self.model = ctx["model"]
        self.client = ctx["client"]
        self._gemini_client = ctx["gemini_client"]
        self.remote_url = ctx["remote_url"]
        self._anthropic_client = ctx["anthropic_client"]
        self._bedrock_client = ctx.get("bedrock_client")
        self._initialized = ctx.get("initialized", False)
        # auth_mode is "subscription" when an OAuth bearer is in use, else
        # unset (treat as "api_key"). The factory wraps the ``client`` in a
        # ChatGPTSubscriptionClient when auth_mode=="subscription" for
        # OpenAI, which translates chat.completions calls to the Responses
        # API on the fly — no behavioral difference at the call sites.
        self._auth_mode: str = ctx.get("auth_mode", "api_key")
        if self.provider == "openai" and self._auth_mode == "subscription":
            logger.info(
                "[LLM] OpenAI ChatGPT subscription mode active — routing via"
                " chatgpt.com/backend-api/codex Responses API."
            )

        # Initialize BytePlus-specific attributes
        self._byteplus_cache_manager: Optional[BytePlusCacheManager] = None
        self.byteplus_base_url: Optional[str] = None
        # Store system prompts for lazy session creation (instance variable)
        self._session_system_prompts: Dict[str, str] = {}
        # Multi-turn session message history for KV cache accumulation.
        # All four providers below benefit from a growing prefix because their
        # caching is opt-in (cache_control / cachePoint marker on the last
        # assistant message). The cache eventually self-activates once the
        # accumulated prefix crosses the provider's minimum-token threshold.
        # - anthropic: cache_control on last assistant content block
        # - bedrock:   cachePoint after last assistant content block
        # - openrouter routing to Claude: extra_body.cache_control applied
        #   by OR to the last cacheable block (i.e. last assistant message)
        # - gemini:    growing `contents` array; implicit caching matches
        #   the longest stable prefix automatically (no marker required)
        self._anthropic_session_messages: Dict[str, List[dict]] = {}
        self._bedrock_session_messages: Dict[str, List[dict]] = {}
        self._openrouter_anthropic_session_messages: Dict[str, List[dict]] = {}
        self._gemini_session_messages: Dict[str, List[dict]] = {}
        # openai / deepseek / grok / non-Claude openrouter: stateless
        # chat-completions APIs with no server-side session. We accumulate a
        # growing [user, assistant, ...] history here and resend it each turn
        # so the model retains earlier context (the delta-only approach dropped
        # everything but the newest turn); the stable growing prefix also feeds
        # prompt_cache_key prefix caching.
        self._openai_compat_session_messages: Dict[str, List[dict]] = {}

        if ctx["byteplus"]:
            self.api_key = ctx["byteplus"]["api_key"]
            self.byteplus_base_url = ctx["byteplus"]["base_url"]
            # Initialize cache manager for BytePlus (caching always enabled)
            self._byteplus_cache_manager = BytePlusCacheManager(
                api_key=self.api_key,
                base_url=self.byteplus_base_url,
                model=self.model,
            )

        # Initialize Gemini-specific attributes
        self._gemini_cache_manager: Optional[GeminiCacheManager] = None
        if self._gemini_client:
            self._gemini_cache_manager = GeminiCacheManager(
                gemini_client=self._gemini_client,
                model=self.model,
            )

    @property
    def is_initialized(self) -> bool:
        """Check if the LLM client is properly initialized."""
        return self._initialized

    def reinitialize(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> bool:
        """Reinitialize the LLM client with new settings.

        Args:
            provider: Optional provider override. If None, uses current provider.
            api_key: Optional API key. If None, reads from settings.json.
            base_url: Optional base URL. If None, reads from settings.json.

        Returns:
            True if initialization was successful, False otherwise.
        """
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType

        target_provider = provider or self.provider

        # Read API key and base URL from settings.json if not provided
        if api_key is None or base_url is None:
            from app.config import get_api_key, get_base_url

            target_api_key = (
                api_key if api_key is not None else get_api_key(target_provider)
            )
            target_base_url = (
                base_url if base_url is not None else get_base_url(target_provider)
            )
        else:
            target_api_key = api_key
            target_base_url = base_url

        try:
            from app.config import get_llm_model as _get_llm_model  # type: ignore[import]

            target_model = _get_llm_model()
        except Exception:
            target_model = (
                None  # app context not available (e.g. agent_core standalone)
            )

        try:
            logger.info(
                f"[LLM] Reinitializing with provider: {target_provider}, model: {target_model or 'registry default'}"
            )
            ctx = ModelFactory.create(
                provider=target_provider,
                interface=InterfaceType.LLM,
                model_override=target_model,
                api_key=target_api_key,
                base_url=target_base_url,
                deferred=False,
            )

            self.provider = ctx["provider"]
            self.model = ctx["model"]
            self.client = ctx["client"]
            self._gemini_client = ctx["gemini_client"]
            self.remote_url = ctx["remote_url"]
            self._anthropic_client = ctx["anthropic_client"]
            self._bedrock_client = ctx.get("bedrock_client")
            self._initialized = ctx.get("initialized", False)
            self._auth_mode = ctx.get("auth_mode", "api_key")

            if ctx["byteplus"]:
                self.api_key = ctx["byteplus"]["api_key"]
                self.byteplus_base_url = ctx["byteplus"]["base_url"]
                # Reinitialize cache manager for BytePlus
                self._byteplus_cache_manager = BytePlusCacheManager(
                    api_key=self.api_key,
                    base_url=self.byteplus_base_url,
                    model=self.model,
                )
                # Reset session system prompts and multi-turn message histories
                self._session_system_prompts = {}
                self._anthropic_session_messages = {}
                self._bedrock_session_messages = {}
                self._openrouter_anthropic_session_messages = {}
                self._gemini_session_messages = {}
                self._openai_compat_session_messages = {}
            else:
                self._byteplus_cache_manager = None
                self._session_system_prompts = {}
                self._anthropic_session_messages = {}
                self._bedrock_session_messages = {}
                self._openrouter_anthropic_session_messages = {}
                self._gemini_session_messages = {}
                self._openai_compat_session_messages = {}

            # Reinitialize Gemini cache manager
            if self._gemini_client:
                self._gemini_cache_manager = GeminiCacheManager(
                    gemini_client=self._gemini_client,
                    model=self.model,
                )
            else:
                self._gemini_cache_manager = None

            # Reset consecutive failure counter — a config change is an explicit
            # user-initiated retry signal. Without this, a prior run that hit the
            # failure threshold would continue to abort even with the new config.
            if self._consecutive_failures > 0:
                logger.info(
                    f"[LLM] Resetting consecutive failure counter on reinitialize "
                    f"(was {self._consecutive_failures})"
                )
                self._consecutive_failures = 0

            logger.info(
                f"[LLM] Reinitialized successfully with provider: {self.provider}, model: {self.model}"
            )
            return self._initialized
        except EnvironmentError as e:
            logger.warning(f"[LLM] Failed to reinitialize - missing API key: {e}")
            return False
        except Exception as e:
            logger.error(
                f"[LLM] Failed to reinitialize - unexpected error: {e}", exc_info=True
            )
            return False

    # ───────────────────────  Usage Reporting  ────────────────────────────

    def _report_usage_async(
        self,
        service_type: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        """Report usage asynchronously if hook is set."""
        if not self._report_usage:
            return

        try:
            event = UsageEventData(
                service_type=service_type,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
            )
            # Schedule the async hook on the event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._report_usage(event))
            except RuntimeError:
                # No running event loop - create one for this call
                asyncio.run(self._report_usage(event))
        except Exception as e:
            logger.warning(f"[LLM] Failed to report usage: {e}")

    def _call_log_to_db(
        self,
        system_prompt: str | None,
        user_prompt: str,
        output: str,
        status: str,
        token_count_input: int,
        token_count_output: int,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        """Call the log_to_db hook if set, and capture the full call for the
        prompt profiler / eval harvesting.

        This method is invoked from every provider path right after the
        response is parsed, so it is the single chokepoint where the full
        prompt, response, and token counts coexist. Prompt identity + latency
        are read from the per-call context (`_llm_call_ctx`) set at the public
        entry point.
        """
        if self._log_to_db:
            try:
                self._log_to_db(
                    system_prompt,
                    user_prompt,
                    output,
                    status,
                    token_count_input,
                    token_count_output,
                )
            except Exception as e:
                logger.warning(f"[LLM] Failed to log to database: {e}")

        if self._record_llm_call:
            try:
                ctx = _llm_call_ctx.get() or {}
                start = ctx.get("start")
                latency_ms = int((time.perf_counter() - start) * 1000) if start else 0
                self._record_llm_call(
                    LLMCallRecord(
                        provider=self.provider or "",
                        model=self.model or "",
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response=output,
                        status=status,
                        input_tokens=token_count_input,
                        output_tokens=token_count_output,
                        cached_tokens=cached_tokens,
                        cache_creation_tokens=cache_creation_tokens,
                        latency_ms=latency_ms,
                        prompt_name=ctx.get("prompt_name"),
                        call_type=ctx.get("call_type"),
                        task_id=ctx.get("task_id"),
                    )
                )
            except Exception as e:
                logger.warning(f"[LLM] Failed to capture LLM call: {e}")

    def _begin_call(
        self,
        prompt_name: Optional[str] = None,
        call_type: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> None:
        """Stamp per-call identity + start time into the context for capture.

        Called at the public entry points; read back at the capture chokepoint
        (`_call_log_to_db`). The explicit `prompt_name` (passed by the call
        site) is what lets the profiler tell apart prompts that share a
        call_type (e.g. the three action-selection prompts).
        """
        _llm_call_ctx.set(
            {
                "prompt_name": prompt_name,
                "call_type": call_type,
                "task_id": task_id,
                "start": time.perf_counter(),
            }
        )

    # ───────────────────────────  Public helpers  ────────────────────────────
    def _generate_response_sync(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Synchronous implementation shared by sync/async entry points."""
        if user_prompt is None:
            raise ValueError("`user_prompt` cannot be None.")

        # Check if we've hit the consecutive failure threshold
        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.critical(
                f"[LLM ABORT] Consecutive failure threshold reached "
                f"({self._consecutive_failures}/{self._max_consecutive_failures}). "
                f"Aborting to prevent infinite retries."
            )
            raise LLMConsecutiveFailureError(self._consecutive_failures)

        if log_response:
            logger.info(f"[LLM SEND] system={system_prompt} | user={user_prompt}")

        try:
            if self.provider in (
                "openai",
                "minimax",
                "deepseek",
                "moonshot",
                "grok",
                "openrouter",
                "glm",
                "fugu",
            ):
                response = self._generate_openai(system_prompt, user_prompt)
            elif self.provider == "remote":
                response = self._generate_ollama(system_prompt, user_prompt)
            elif self.provider == "gemini":
                response = self._generate_gemini(system_prompt, user_prompt)
            elif self.provider == "byteplus":
                response = self._generate_byteplus(system_prompt, user_prompt)
            elif self.provider == "anthropic":
                response = self._generate_anthropic(system_prompt, user_prompt)
            elif self.provider == "bedrock":
                response = self._generate_bedrock(system_prompt, user_prompt)
            else:  # pragma: no cover
                raise RuntimeError(f"Unknown provider {self.provider!r}")

            content = response.get("content", "").strip()

            # Check if response is empty and provide diagnostics
            if not content:
                # Prefer the classified rich message (provider + upstream +
                # raw + action hint inline) over the bare exception string.
                # This is what the user actually sees in the chat bubble.
                error_info = response.get("error_info_obj")
                error_msg = response.get("error", "")
                if error_info is not None:
                    error_detail = error_info.message
                elif error_msg:
                    error_detail = f"LLM provider returned error: {error_msg}"
                else:
                    error_detail = (
                        f"LLM returned empty response. "
                        f"Provider: {self.provider}, Model: {self.model}. "
                        f"This may indicate: API authentication failure, invalid API key, rate limiting, "
                        f"connection timeout, or LLM service unavailability. "
                        f"Check your credentials and API status."
                    )
                logger.error(f"[LLM ERROR] {error_detail}")
                # Track consecutive failure
                self._consecutive_failures += 1
                logger.warning(
                    f"[LLM CONSECUTIVE FAILURE] Count: {self._consecutive_failures}/{self._max_consecutive_failures}"
                )
                if self._consecutive_failures >= self._max_consecutive_failures:
                    # Attach the underlying classified info so the agent_base
                    # error handler can show the *cause* of the 5 failures
                    # (e.g. "rate-limited on Google AI Studio") instead of a
                    # meta-message about retry counts.
                    raise LLMConsecutiveFailureError(
                        self._consecutive_failures,
                        last_error_info=error_info,
                    )
                # Use _EmptyResponse so the outer except-Exception block does NOT
                # re-increment the counter for this same call (double-counting bug).
                raise _EmptyResponse(error_detail)

            # Success - reset consecutive failure counter
            self._consecutive_failures = 0

            cleaned = re.sub(self._CODE_BLOCK_RE, "", content)

            # Update token count via hook
            current_count = self._get_token_count()
            self._set_token_count(current_count + billable_tokens(response))

            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned

        except LLMConsecutiveFailureError:
            # Re-raise consecutive failure errors without incrementing counter
            raise
        except _EmptyResponse as e:
            # Failure already counted above; convert back to RuntimeError for callers.
            raise RuntimeError(str(e)) from None
        except Exception as e:
            # Track consecutive failure for any other exception
            self._consecutive_failures += 1
            logger.warning(
                f"[LLM CONSECUTIVE FAILURE] Count: {self._consecutive_failures}/{self._max_consecutive_failures} | Error: {e}"
            )
            if self._consecutive_failures >= self._max_consecutive_failures:
                # Classify on the way out so the fatal-failure handler can
                # surface the cause, not just the count.
                try:
                    info = classify_llm_error(
                        e, provider=self.provider, model=self.model
                    )
                except Exception:
                    info = None
                raise LLMConsecutiveFailureError(
                    self._consecutive_failures,
                    last_error=e,
                    last_error_info=info,
                ) from e
            raise

    @profile("llm_generate_response", OperationCategory.LLM)
    def generate_response(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
        prompt_name: Optional[str] = None,
    ) -> str:
        """Generate a single response from the configured provider."""
        self._begin_call(prompt_name=prompt_name)
        return self._generate_response_sync(system_prompt, user_prompt, log_response)

    @profile("llm_generate_response_async", OperationCategory.LLM)
    async def generate_response_async(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
        prompt_name: Optional[str] = None,
    ) -> str:
        """Async wrapper that defers the blocking call to a worker thread."""
        # Stamp the context here, in the caller's context, so asyncio.to_thread
        # copies it into the worker thread where the capture runs.
        self._begin_call(prompt_name=prompt_name)
        return await asyncio.to_thread(
            self._generate_response_sync,
            system_prompt,
            user_prompt,
            log_response,
        )

    def reset_failure_counter(self) -> None:
        """Reset the consecutive failure counter.

        Call this when starting a new task or when the user manually
        chooses to retry after fixing configuration issues.
        """
        if self._consecutive_failures > 0:
            logger.info(
                f"[LLM] Resetting consecutive failure counter "
                f"(was {self._consecutive_failures})"
            )
        self._consecutive_failures = 0

    @property
    def consecutive_failures(self) -> int:
        """Get the current consecutive failure count."""
        return self._consecutive_failures

    # ─────────────────── Session/Explicit Cache Methods ───────────────────

    def create_session_cache(
        self, task_id: str, call_type: str, system_prompt: str
    ) -> Optional[str]:
        """Register a session/cache for a specific call type within a task.

        Supports multiple providers:
        - BytePlus: Uses session caching with Responses API
        - Gemini: Uses explicit caching with per-call-type caches

        The actual cache is created lazily on the first LLM call.
        This method stores the system prompt for later use.

        Should be called at task start. Each call type gets its own cache.

        Args:
            task_id: Unique identifier for the task.
            call_type: Type of LLM call (use LLMCallType enum values).
            system_prompt: Initial system prompt for the session.

        Returns:
            A placeholder ID if successful, None if caching not available.
        """
        # Check if caching is supported for this provider
        supports_caching = (
            (self.provider == "byteplus" and self._byteplus_cache_manager)
            or (self.provider == "gemini" and self._gemini_cache_manager)
            or (
                self.provider
                in ("openai", "deepseek", "grok", "openrouter", "glm", "fugu")
                and self.client
            )  # OpenAI/DeepSeek/Grok/OpenRouter use automatic caching with prompt_cache_key (and cache_control for Anthropic-routed OpenRouter models)
            or (
                self.provider == "anthropic" and self._anthropic_client
            )  # Anthropic uses ephemeral caching with extended TTL
            or (
                self.provider == "bedrock" and self._bedrock_client
            )  # Bedrock uses cachePoint (only Anthropic Claude models on Bedrock support it)
        )

        if not supports_caching:
            logger.debug(
                f"[SESSION] Session cache not available for provider: {self.provider}"
            )
            return None

        # Store system prompt for lazy session/cache creation
        session_key = f"{task_id}:{call_type}"
        self._session_system_prompts[session_key] = system_prompt
        logger.info(
            f"[SESSION] Registered session for {session_key} (provider: {self.provider})"
        )
        return session_key  # Return placeholder ID

    def get_session_system_prompt(self, task_id: str, call_type: str) -> Optional[str]:
        """Get the stored system prompt for a session.

        Args:
            task_id: The task ID.
            call_type: Type of LLM call.

        Returns:
            The system prompt if registered, None otherwise.
        """
        session_key = f"{task_id}:{call_type}"
        return self._session_system_prompts.get(session_key)

    def end_session_cache(self, task_id: str, call_type: str) -> None:
        """End a session/explicit cache for a specific call type.

        Should be called at task end to clean up resources.

        Args:
            task_id: The task ID.
            call_type: Type of LLM call (use LLMCallType enum values).
        """
        # Clean up stored system prompt and multi-turn message histories
        session_key = f"{task_id}:{call_type}"
        system_prompt = self._session_system_prompts.pop(session_key, None)
        self._anthropic_session_messages.pop(session_key, None)
        self._bedrock_session_messages.pop(session_key, None)
        self._openrouter_anthropic_session_messages.pop(session_key, None)
        self._gemini_session_messages.pop(session_key, None)
        self._openai_compat_session_messages.pop(session_key, None)

        # Clean up provider-specific caches
        if self.provider == "byteplus" and self._byteplus_cache_manager:
            self._byteplus_cache_manager.end_session(task_id, call_type)
        elif self.provider == "gemini" and self._gemini_cache_manager and system_prompt:
            # Invalidate the explicit cache for this system prompt + call_type
            self._gemini_cache_manager.invalidate_cache(system_prompt, call_type)

    def end_all_session_caches(self, task_id: str) -> None:
        """End ALL session/explicit caches for a task (all call types).

        Convenience method to clean up all caches when a task ends.

        Args:
            task_id: The task whose sessions should be ended.
        """
        # Get all system prompts for this task before removing
        keys_to_remove = [
            k for k in self._session_system_prompts if k.startswith(f"{task_id}:")
        ]
        prompts_and_types = []
        for key in keys_to_remove:
            system_prompt = self._session_system_prompts.pop(key, None)
            if system_prompt:
                # Extract call_type from key (format: "task_id:call_type")
                call_type = key.split(":", 1)[1] if ":" in key else None
                if call_type:
                    prompts_and_types.append((system_prompt, call_type))

        # Clean up multi-turn message histories across all providers that
        # accumulate (anthropic, bedrock, openrouter-via-claude, gemini,
        # openai-subscription).
        for buffer in (
            self._anthropic_session_messages,
            self._bedrock_session_messages,
            self._openrouter_anthropic_session_messages,
            self._gemini_session_messages,
            self._openai_compat_session_messages,
        ):
            stale = [k for k in buffer if k.startswith(f"{task_id}:")]
            for key in stale:
                buffer.pop(key, None)

        # Clean up provider-specific caches
        if self.provider == "byteplus" and self._byteplus_cache_manager:
            self._byteplus_cache_manager.end_all_sessions_for_task(task_id)
        elif self.provider == "gemini" and self._gemini_cache_manager:
            # Invalidate all explicit caches for this task's prompts
            for system_prompt, call_type in prompts_and_types:
                self._gemini_cache_manager.invalidate_cache(system_prompt, call_type)

    def _trim_openai_compat_history(self, history: List[dict]) -> None:
        """Bound an accumulated openai-compat session history IN PLACE.

        Stateless resends grow every turn, so cap the history to keep
        ``[system + history + new turn + response]`` inside the model's context
        window. This is a safety backstop — the agent's summarization-driven
        session reset (which clears the whole buffer via ``end_session_cache``)
        normally fires first.

        Trimming preserves the FIRST user/assistant pair — the grounding turn
        carrying the original query / Definition of Done — and drops the oldest
        MIDDLE pairs, so we never re-introduce the amnesia this fix exists to
        prevent. Uses a chars≈4*tokens heuristic.
        """
        # ~240k chars ≈ ~60k tokens: comfortably inside grok-3's 131k window
        # after the system prompt, the newest turn, and the response.
        max_history_chars = 240_000

        def _size() -> int:
            return sum(len(m.get("content", "") or "") for m in history)

        # Keep index 0/1 (grounding) and the most recent pair; trim from the
        # oldest middle pair inward.
        while len(history) > 4 and _size() > max_history_chars:
            del history[2:4]

    def has_session_cache(self, task_id: str, call_type: str) -> bool:
        """Check if a session/explicit cache is available for the given task and call type.

        Returns True if:
        - An actual session cache exists (created on previous calls), OR
        - A session has been registered (system prompt stored for lazy creation)

        Supports:
        - BytePlus: Session caching with previous_response_id
        - Gemini: Explicit caching with per-call-type caches

        This allows callers to use session-based generation even on the first call,
        as the session will be created lazily when needed.
        """
        session_key = f"{task_id}:{call_type}"

        # Check if system prompt is registered (works for all providers)
        if session_key in self._session_system_prompts:
            # Also verify the provider supports caching
            if self.provider == "byteplus" and self._byteplus_cache_manager:
                return True
            if self.provider == "gemini" and self._gemini_cache_manager:
                return True
            if (
                self.provider
                in ("openai", "deepseek", "grok", "openrouter", "glm", "fugu")
                and self.client
            ):
                return True
            if self.provider == "anthropic" and self._anthropic_client:
                return True
            if self.provider == "bedrock" and self._bedrock_client:
                return True

        # Check provider-specific actual session existence
        if self.provider == "byteplus" and self._byteplus_cache_manager:
            return self._byteplus_cache_manager.has_session(task_id, call_type)

        return False

    def get_cache_stats(self) -> str:
        """Get a summary of cache metrics for all providers.

        Returns a formatted string with cache hit rates, token savings, etc.
        Useful for validating cache effectiveness.
        """
        return get_cache_metrics().get_summary()

    def reset_cache_stats(self) -> None:
        """Reset all cache metrics to zero.

        Useful for starting a new measurement period.
        """
        get_cache_metrics().reset()
        logger.info("[CACHE] Cache metrics reset")

    def _finalize_session_response(
        self, response: Dict[str, Any], log_response: bool
    ) -> str:
        """Shared tail for the session-cache provider branches.

        Mirrors the failure handling in `_generate_response_sync`: an empty
        response is treated as a failure, the consecutive-failure counter is
        tracked, and the classified cause is surfaced (raising
        `LLMConsecutiveFailureError` once the threshold is hit so the agent
        aborts instead of retrying forever). On success the counter resets and
        the cleaned content is returned.
        """
        content = (response.get("content") or "").strip()
        if not content:
            error_info = response.get("error_info_obj")
            error_msg = response.get("error", "")
            if error_info is not None:
                error_detail = error_info.message
            elif error_msg:
                error_detail = f"LLM provider returned error: {error_msg}"
            else:
                error_detail = (
                    f"LLM returned empty response. "
                    f"Provider: {self.provider}, Model: {self.model}. "
                    f"This may indicate an API error or service unavailability."
                )
            logger.error(f"[LLM ERROR] {error_detail}")
            self._consecutive_failures += 1
            logger.warning(
                f"[LLM CONSECUTIVE FAILURE] Count: "
                f"{self._consecutive_failures}/{self._max_consecutive_failures}"
            )
            if self._consecutive_failures >= self._max_consecutive_failures:
                raise LLMConsecutiveFailureError(
                    self._consecutive_failures, last_error_info=error_info
                )
            raise RuntimeError(error_detail)

        # Success - reset consecutive failure counter
        self._consecutive_failures = 0
        cleaned = re.sub(self._CODE_BLOCK_RE, "", content)
        current_count = self._get_token_count()
        self._set_token_count(current_count + billable_tokens(response))
        if log_response:
            logger.info(f"[LLM RECV] {cleaned}")
        return cleaned

    def _generate_response_with_session_sync(
        self,
        task_id: str,
        call_type: str,
        user_prompt: str,
        system_prompt_for_new_session: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Generate response using session/explicit cache for the given task and call type.

        Supports multiple providers:
        - BytePlus: Uses session caching with previous_response_id chaining
        - Gemini: Uses explicit caching with separate caches per call_type
        - Others: Falls back to standard generation

        If no session exists and system_prompt_for_new_session is provided,
        creates a new session cache first. Each call type gets its own session.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.

        Returns:
            The cleaned response content.
        """
        if user_prompt is None:
            raise ValueError("`user_prompt` cannot be None.")

        # Same consecutive-failure backstop as `_generate_response_sync`. The
        # session path previously had none, so a persistent provider error
        # (e.g. out-of-credits) retried forever instead of aborting.
        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.critical(
                f"[LLM ABORT] Consecutive failure threshold reached "
                f"({self._consecutive_failures}/{self._max_consecutive_failures}). "
                f"Aborting to prevent infinite retries."
            )
            raise LLMConsecutiveFailureError(self._consecutive_failures)

        if log_response:
            logger.info(
                f"[LLM SESSION] task={task_id} call_type={call_type} | user={user_prompt}"
            )

        # Handle Gemini with multi-turn implicit-cache accumulation.
        # Gemini's implicit caching (always on for 2.5 models) automatically
        # matches the longest stable prefix across requests, so by sending a
        # growing user/model history each call we let the cache cover more of
        # the input every turn — including content too short to qualify for
        # the explicit-cache code path (≥1024 tokens). The accumulated buffer
        # uses Gemini's role names ("user" / "model") and parts schema.
        if self.provider == "gemini" and self._gemini_cache_manager:
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = (
                system_prompt_for_new_session or stored_system_prompt
            )

            if not effective_system_prompt:
                raise ValueError(f"No system prompt for task {task_id}:{call_type}")

            if session_key not in self._gemini_session_messages:
                self._gemini_session_messages[session_key] = []
            history = self._gemini_session_messages[session_key]

            # Build contents = history + new user turn.
            contents: List[Dict[str, Any]] = []
            for msg in history:
                contents.append({"role": msg["role"], "parts": msg["parts"]})
            contents.append({"role": "user", "parts": [{"text": user_prompt}]})

            logger.debug(
                f"[GEMINI SESSION] {session_key}: {len(history)} history msgs, "
                f"sending {len(contents)} total contents"
            )

            response = self._generate_gemini(
                effective_system_prompt,
                user_prompt,
                call_type=call_type,
                contents_override=contents,
            )

            assistant_content = response.get("content", "")
            if assistant_content and not response.get("error"):
                history.append({"role": "user", "parts": [{"text": user_prompt}]})
                history.append(
                    {"role": "model", "parts": [{"text": assistant_content}]}
                )

            return self._finalize_session_response(response, log_response)

        # Handle OpenAI/DeepSeek/Grok/OpenRouter with call_type-based cache routing
        if self.provider in ("openai", "deepseek", "grok", "openrouter", "glm", "fugu"):
            # Get stored system prompt or use provided one
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = (
                system_prompt_for_new_session or stored_system_prompt
            )

            if not effective_system_prompt:
                raise ValueError(f"No system prompt for task {task_id}:{call_type}")

            # OpenRouter routing to Claude needs multi-turn accumulation because
            # Anthropic's prompt caching is opt-in and OR's `cache_control` field
            # gets applied to the LAST cacheable block in the request — which is
            # the last assistant message when we send full history. Without
            # accumulation, only the system block can be cached, and short
            # system prompts silently no-op below the Anthropic 1024-token
            # minimum. Mirrors the Anthropic-direct path.
            model_lower_router = (self.model or "").lower()
            is_openrouter_claude = self.provider == "openrouter" and (
                model_lower_router.startswith("anthropic/")
                or "claude" in model_lower_router
            )

            if is_openrouter_claude:
                if session_key not in self._openrouter_anthropic_session_messages:
                    self._openrouter_anthropic_session_messages[session_key] = []
                history = self._openrouter_anthropic_session_messages[session_key]

                # Build OpenAI-shaped messages: [system, user1, assistant1,
                # ..., new_user]. OpenRouter applies extra_body.cache_control
                # to the last cacheable block automatically.
                or_messages: List[Dict[str, Any]] = [
                    {"role": "system", "content": effective_system_prompt}
                ]
                for msg in history:
                    or_messages.append({"role": msg["role"], "content": msg["content"]})
                or_messages.append({"role": "user", "content": user_prompt})

                logger.debug(
                    f"[OPENROUTER-CLAUDE SESSION] {session_key}: "
                    f"{len(history)} history msgs, sending {len(or_messages)} total"
                )

                response = self._generate_openai(
                    effective_system_prompt,
                    user_prompt,
                    call_type=call_type,
                    messages_override=or_messages,
                )

                assistant_content = response.get("content", "")
                if assistant_content and not response.get("error"):
                    history.append({"role": "user", "content": user_prompt})
                    history.append({"role": "assistant", "content": assistant_content})
            else:
                # openai / deepseek / grok / non-Claude openrouter.
                #
                # These are STATELESS chat-completions APIs — there is no
                # server-side session. The old path sent only [system, delta]
                # each turn and relied on "automatic prefix caching" to carry
                # context, but prefix caching is a COST optimization, not
                # memory: it never re-supplies tokens you don't send. So after
                # the first turn the model saw only the newest delta and lost
                # the original query and all earlier events (this is what made
                # validation sub-agents fail with "No Definition of Done").
                #
                # Fix: accumulate a growing [user, assistant, ...] history and
                # resend [system, u1, a1, ..., new_user] every turn. Correctness
                # aside, the stable growing prefix is exactly what prompt_cache_key
                # rewards, so most of the resend is served from cache once warm.
                if session_key not in self._openai_compat_session_messages:
                    self._openai_compat_session_messages[session_key] = []
                history = self._openai_compat_session_messages[session_key]
                self._trim_openai_compat_history(history)

                oa_messages: List[Dict[str, Any]] = [
                    {"role": "system", "content": effective_system_prompt}
                ]
                for msg in history:
                    oa_messages.append({"role": msg["role"], "content": msg["content"]})
                oa_messages.append({"role": "user", "content": user_prompt})

                logger.debug(
                    f"[OPENAI-COMPAT SESSION] {session_key} ({self.provider}): "
                    f"{len(history)} history msgs, sending {len(oa_messages)} total"
                )

                response = self._generate_openai(
                    effective_system_prompt,
                    user_prompt,
                    call_type=call_type,
                    messages_override=oa_messages,
                )

                assistant_content = response.get("content", "")
                if assistant_content and not response.get("error"):
                    history.append({"role": "user", "content": user_prompt})
                    history.append({"role": "assistant", "content": assistant_content})

            return self._finalize_session_response(response, log_response)

        # Handle Anthropic with multi-turn KV caching
        if self.provider == "anthropic" and self._anthropic_client:
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = (
                system_prompt_for_new_session or stored_system_prompt
            )

            if not effective_system_prompt:
                raise ValueError(f"No system prompt for task {task_id}:{call_type}")

            # Get or initialize multi-turn message history
            if session_key not in self._anthropic_session_messages:
                self._anthropic_session_messages[session_key] = []

            history = self._anthropic_session_messages[session_key]

            # Build messages: history (with cache_control on last assistant) + new user msg
            messages: List[dict] = []

            # Copy history messages (strip old cache_control, we'll re-place it)
            for msg in history:
                msg_copy = {"role": msg["role"]}
                content = msg["content"]
                if isinstance(content, list):
                    # Strip cache_control from content blocks
                    msg_copy["content"] = [
                        {k: v for k, v in block.items() if k != "cache_control"}
                        for block in content
                    ]
                else:
                    msg_copy["content"] = content
                messages.append(msg_copy)

            # Place cache_control on the LAST assistant message for prefix caching
            if messages:
                cache_control = {"type": "ephemeral"}
                if call_type:
                    cache_control["ttl"] = "1h"
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i]["role"] == "assistant":
                        content = messages[i]["content"]
                        if isinstance(content, str):
                            messages[i]["content"] = [
                                {
                                    "type": "text",
                                    "text": content,
                                    "cache_control": cache_control,
                                }
                            ]
                        elif isinstance(content, list):
                            # Add cache_control to the last text block
                            for j in range(len(content) - 1, -1, -1):
                                if content[j].get("type") == "text":
                                    content[j]["cache_control"] = cache_control
                                    break
                        break

            # Append the new user message
            messages.append({"role": "user", "content": user_prompt})

            logger.debug(
                f"[ANTHROPIC SESSION] {session_key}: {len(history)} history msgs, "
                f"sending {len(messages)} total msgs"
            )

            # Call Anthropic with the full multi-turn messages
            response = self._generate_anthropic(
                effective_system_prompt,
                user_prompt,
                call_type=call_type,
                messages=messages,
            )

            # On success, accumulate the user message + assistant response in history
            assistant_content = response.get("content", "")
            if assistant_content and not response.get("error"):
                history.append({"role": "user", "content": user_prompt})
                history.append({"role": "assistant", "content": assistant_content})

            return self._finalize_session_response(response, log_response)

        # Handle Bedrock with multi-turn cachePoint caching.
        # Mirrors the Anthropic-direct pattern: accumulate the user/assistant
        # exchange across calls so the cachePoint sits at the end of a growing
        # prefix. AWS Bedrock measures the minimum-token threshold against the
        # tokens BEFORE the cachePoint marker — for models with 4096-token
        # minimums (Haiku 4.5 / Sonnet 4.5 / Opus 4.5/4.6) a single-turn call
        # with the cachePoint in the system block is almost always below the
        # threshold and silently no-ops. Accumulating turns lets the prefix
        # grow until it crosses the threshold, after which caching activates
        # and serves all subsequent calls.
        if self.provider == "bedrock" and self._bedrock_client:
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = (
                system_prompt_for_new_session or stored_system_prompt
            )

            if not effective_system_prompt:
                raise ValueError(f"No system prompt for task {task_id}:{call_type}")

            # Get or initialize multi-turn message history (Bedrock Converse
            # content-block format: {"role": ..., "content": [{"text": ...}]}).
            if session_key not in self._bedrock_session_messages:
                self._bedrock_session_messages[session_key] = []
            history = self._bedrock_session_messages[session_key]

            # Build messages: history (strip any prior cachePoint blocks, we
            # re-place exactly one) + new user message.
            messages: List[dict] = []
            for msg in history:
                content_blocks = [
                    block for block in msg["content"] if "cachePoint" not in block
                ]
                messages.append({"role": msg["role"], "content": content_blocks})

            # Place cachePoint at the end of the LAST assistant content block —
            # this caches the entire prefix up to (and including) the last
            # model response. On the first turn there's no history yet, so no
            # cachePoint is placed in messages and the call falls through to
            # the system-block cachePoint (which is itself useful when the
            # system prompt alone already exceeds the threshold).
            if messages:
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i]["role"] == "assistant":
                        messages[i]["content"].append(
                            {"cachePoint": {"type": "default"}}
                        )
                        break

            messages.append({"role": "user", "content": [{"text": user_prompt}]})

            # INFO-level diagnostic so we can see what's actually being sent
            # without enabling debug logging. Remove once cache is confirmed
            # working.
            logger.info(
                f"[BEDROCK SESSION] {session_key}: history={len(history)} msgs, "
                f"sending {len(messages)} msgs to Converse"
            )

            response = self._generate_bedrock(
                effective_system_prompt,
                user_prompt,
                call_type=call_type,
                messages=messages,
            )

            # On success, accumulate the user message + assistant response in
            # history (without cachePoint — it's re-placed each call).
            assistant_content = response.get("content", "")
            response_has_error = bool(response.get("error"))
            if assistant_content and not response_has_error:
                history.append({"role": "user", "content": [{"text": user_prompt}]})
                history.append(
                    {"role": "assistant", "content": [{"text": assistant_content}]}
                )
                logger.info(
                    f"[BEDROCK SESSION] {session_key}: appended turn → "
                    f"history={len(history)} msgs"
                )
            else:
                logger.warning(
                    f"[BEDROCK SESSION] {session_key}: SKIPPED history append "
                    f"(content_empty={not assistant_content}, "
                    f"has_error={response_has_error})"
                )

            return self._finalize_session_response(response, log_response)

        # If not BytePlus (and not Gemini/OpenAI/Anthropic/Bedrock which are handled above), fall back to standard
        if self.provider != "byteplus" or not self._byteplus_cache_manager:
            return self._generate_response_sync(
                system_prompt_for_new_session, user_prompt, log_response=False
            )

        # Use SESSION cache for BytePlus - context grows with each call via previous_response_id
        # The session accumulates: system_prompt + user_prompt_1 + response_1 + user_prompt_2 + ...
        # Only delta events should be sent after the first call to avoid duplication
        session_key = f"{task_id}:{call_type}"

        try:
            # Check if session exists in BytePlus cache manager
            if self._byteplus_cache_manager.has_session(task_id, call_type):
                # Session exists - use it
                response = self._generate_byteplus_with_session(
                    task_id, call_type, user_prompt
                )
            else:
                # No session exists - create one and get first response
                stored_system_prompt = self._session_system_prompts.get(session_key)
                effective_system_prompt = (
                    system_prompt_for_new_session or stored_system_prompt
                )

                if not effective_system_prompt:
                    raise ValueError(f"No system prompt for task {task_id}:{call_type}")

                logger.info(f"[SESSION CACHE] Creating new session for {session_key}")
                result = self._byteplus_cache_manager.create_session_cache(
                    task_id=task_id,
                    call_type=call_type,
                    system_prompt=effective_system_prompt,
                    user_prompt=user_prompt,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                # Process the response from session creation
                response = self._process_session_response(
                    result, task_id, call_type, is_first_call=True
                )

        except Exception as e:
            logger.warning(f"[SESSION CACHE] Failed: {e}, falling back to standard")
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = (
                system_prompt_for_new_session or stored_system_prompt
            )
            return self._generate_response_sync(
                effective_system_prompt, user_prompt, log_response=False
            )

        return self._finalize_session_response(response, log_response)

    def _process_session_response(
        self,
        result: Dict[str, Any],
        task_id: str,
        call_type: str,
        is_first_call: bool = False,
    ) -> Dict[str, Any]:
        """Process response from session cache call and record metrics.

        Args:
            result: Raw response from Responses API.
            task_id: The task ID.
            call_type: Type of LLM call.
            is_first_call: Whether this is the first call (session creation).

        Returns:
            Processed response dict with 'tokens_used' and 'content'.
        """
        session_key = f"{task_id}:{call_type}"

        # Parse content (Responses API format)
        content = self._parse_responses_api_content(result)

        # Token usage from Responses API
        usage = result.get("usage") or {}
        token_count_input = int(usage.get("input_tokens", 0))
        token_count_output = int(usage.get("output_tokens", 0))
        total_tokens = int(usage.get("total_tokens", 0)) or (
            token_count_input + token_count_output
        )

        # Log cache info and record metrics
        cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(
                f"[CACHE] BytePlus session cache hit: {cached_tokens}/{token_count_input} tokens cached"
            )
            metrics.record_hit(
                "byteplus",
                "session",
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        else:
            # First call in session or cache miss
            metrics.record_miss("byteplus", "session", total_tokens=token_count_input)

        logger.info(f"BYTEPLUS SESSION RESPONSE for {session_key}: {result}")

        self._call_log_to_db(
            f"[SESSION:{session_key}]",
            "[session_call]",
            content,
            "success",
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens or 0,
        )

        # Report usage
        self._report_usage_async(
            "llm_byteplus",
            "byteplus",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens or 0,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens or 0,
        }

    def _process_prefix_response(
        self, result: Dict[str, Any], session_key: str
    ) -> Dict[str, Any]:
        """Process response from prefix cache call and record metrics.

        Args:
            result: Raw response from Responses API.
            session_key: The session key for logging.

        Returns:
            Processed response dict with 'tokens_used' and 'content'.
        """
        # Parse content (Responses API format)
        content = self._parse_responses_api_content(result)

        # Token usage from Responses API
        usage = result.get("usage") or {}
        token_count_input = int(usage.get("input_tokens", 0))
        token_count_output = int(usage.get("output_tokens", 0))
        total_tokens = int(usage.get("total_tokens", 0)) or (
            token_count_input + token_count_output
        )

        # Log cache info and record metrics
        cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(
                f"[CACHE] BytePlus prefix cache hit: {cached_tokens}/{token_count_input} tokens cached"
            )
            metrics.record_hit(
                "byteplus",
                "prefix",
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        else:
            # First call or cache miss
            metrics.record_miss("byteplus", "prefix", total_tokens=token_count_input)

        logger.info(
            f"BYTEPLUS PREFIX RESPONSE for {session_key}: input={token_count_input}, cached={cached_tokens}"
        )

        self._call_log_to_db(
            f"[PREFIX:{session_key}]",
            "[prefix_call]",
            content,
            "success",
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens or 0,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens or 0,
        }

    def generate_response_with_session(
        self,
        task_id: str,
        call_type: str,
        user_prompt: str,
        system_prompt_for_new_session: Optional[str] = None,
        log_response: bool = True,
        prompt_name: Optional[str] = None,
    ) -> str:
        """Synchronous session-based response generation.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.
            prompt_name: Identity of the named prompt, for capture/profiling.
        """
        self._begin_call(prompt_name=prompt_name, call_type=call_type, task_id=task_id)
        return self._generate_response_with_session_sync(
            task_id, call_type, user_prompt, system_prompt_for_new_session, log_response
        )

    @profile("llm_generate_response_with_session_async", OperationCategory.LLM)
    async def generate_response_with_session_async(
        self,
        task_id: str,
        call_type: str,
        user_prompt: str,
        system_prompt_for_new_session: Optional[str] = None,
        log_response: bool = True,
        prompt_name: Optional[str] = None,
    ) -> str:
        """Async wrapper for session-based response generation.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.
            prompt_name: Identity of the named prompt, for capture/profiling.
        """
        # Stamp here (caller's context) so asyncio.to_thread copies it into the
        # worker thread where capture runs.
        self._begin_call(prompt_name=prompt_name, call_type=call_type, task_id=task_id)
        return await asyncio.to_thread(
            self._generate_response_with_session_sync,
            task_id,
            call_type,
            user_prompt,
            system_prompt_for_new_session,
            log_response,
        )

    def _generate_byteplus_with_session(
        self, task_id: str, call_type: str, user_prompt: str
    ) -> Dict[str, Any]:
        """Use Responses API with session caching for task/GUI calls.

        The context grows with each call as we chain responses via previous_response_id.
        Each call type has its own session to avoid polluting different prompt structures.

        If context overflow is detected, the session is automatically reset and retried
        with a fresh session containing only the system prompt and current user prompt.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        cached_tokens = 0
        session_key = f"{task_id}:{call_type}"

        try:
            if not self._byteplus_cache_manager.has_session(task_id, call_type):
                raise ValueError(f"No session cache found for {session_key}")

            result = self._byteplus_cache_manager.chat_with_session(
                task_id=task_id,
                call_type=call_type,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            logger.info(f"BYTEPLUS SESSION RESPONSE: {result}")

            # Parse response (Responses API format)
            content = self._parse_responses_api_content(result)

            # Token usage from Responses API
            usage = result.get("usage") or {}
            token_count_input = int(usage.get("input_tokens", 0))
            token_count_output = int(usage.get("output_tokens", 0))
            total_tokens = int(usage.get("total_tokens", 0)) or (
                token_count_input + token_count_output
            )

            # Log cache info and record metrics
            # Responses API uses input_tokens_details instead of prompt_tokens_details
            cached_tokens = usage.get("input_tokens_details", {}).get(
                "cached_tokens", 0
            )
            metrics = get_cache_metrics()
            if cached_tokens and cached_tokens > 0:
                logger.info(
                    f"[CACHE] BytePlus session cache hit: {cached_tokens}/{token_count_input} tokens cached"
                )
                metrics.record_hit(
                    "byteplus",
                    "session",
                    cached_tokens=cached_tokens,
                    total_tokens=token_count_input,
                )
            else:
                # First call in session or growing context
                metrics.record_miss(
                    "byteplus", "session", total_tokens=token_count_input
                )

            status = "success"

        except BytePlusContextOverflowError:
            # Context exceeded maximum length - reset session and retry with fresh context
            logger.warning(
                f"[BYTEPLUS] Context overflow for {session_key}, resetting session and retrying..."
            )

            # End the overflowed session
            self._byteplus_cache_manager.end_session(task_id, call_type)

            # Get the stored system prompt for this session
            system_prompt = self._session_system_prompts.get(session_key)
            if not system_prompt:
                exc_obj = ValueError(
                    f"Cannot reset session {session_key}: no system prompt stored"
                )
                logger.error(str(exc_obj))
            else:
                try:
                    # Create a fresh session with system prompt and current user prompt
                    logger.info(
                        f"[BYTEPLUS] Creating fresh session for {session_key} after overflow"
                    )
                    result = self._byteplus_cache_manager.create_session_cache(
                        task_id=task_id,
                        call_type=call_type,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )

                    logger.info(f"BYTEPLUS SESSION RESPONSE (after reset): {result}")

                    # Parse response
                    content = self._parse_responses_api_content(result)

                    # Token usage
                    usage = result.get("usage") or {}
                    token_count_input = int(usage.get("input_tokens", 0))
                    token_count_output = int(usage.get("output_tokens", 0))
                    total_tokens = int(usage.get("total_tokens", 0)) or (
                        token_count_input + token_count_output
                    )

                    # Record as cache miss (fresh session)
                    metrics = get_cache_metrics()
                    metrics.record_miss(
                        "byteplus", "session_reset", total_tokens=token_count_input
                    )

                    status = "success"
                    logger.info(
                        f"[BYTEPLUS] Successfully recovered from context overflow for {session_key}"
                    )

                except Exception as retry_exc:
                    exc_obj = retry_exc
                    logger.error(
                        f"Error retrying BytePlus Session API for {session_key} after reset: {retry_exc}"
                    )

        except Exception as exc:
            exc_obj = exc
            logger.error(f"Error calling BytePlus Session API for {session_key}: {exc}")

        self._call_log_to_db(
            f"[SESSION:{session_key}]",  # Mark as session call in logs with call_type
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens or 0,
        )

        # Report usage
        cached_tokens = 0
        if status == "success":
            usage = result.get("usage") or {} if "result" in dir() else {}
            cached_tokens = (
                usage.get("input_tokens_details", {}).get("cached_tokens", 0)
                if usage
                else 0
            )
        self._report_usage_async(
            "llm_byteplus",
            "byteplus",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens or 0,
        }

    # ───────────────────── Provider‑specific private helpers ─────────────────────
    @profile("llm_openai_call", OperationCategory.LLM)
    def _generate_openai(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        messages_override: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate response using OpenAI with automatic prompt caching.

        OpenAI's prompt caching is automatic for prompts ≥1024 tokens:
        - No code changes required to enable caching
        - Cached tokens are returned in usage.prompt_tokens_details.cached_tokens
        - 50% discount on cached input tokens
        - Cache retention: 5-10 minutes (up to 1 hour during off-peak)
        - Using prompt_cache_key influences routing for better cache hit rates

        Args:
            system_prompt: The system prompt.
            user_prompt: The user prompt for this request.
            call_type: Optional call type for cache routing (e.g., "reasoning", "action_selection").
                       When provided, generates a prompt_cache_key to improve cache hit rates
                       when alternating between different call types.
            messages_override: Optional pre-built multi-turn messages list. Used
                by the OpenRouter-via-Claude session path to send a growing
                conversation history so the upstream Anthropic model can cache
                the accumulating prefix via OR's cache_control field. When set,
                it's sent verbatim — system_prompt is still passed in for cache-
                key derivation but the request body uses messages_override.

        Cache hits are logged when cached_tokens > 0 in the response.
        """
        token_count_input = token_count_output = 0
        cached_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = f"automatic_{call_type}" if call_type else "automatic"

        try:
            if messages_override is not None:
                messages: List[Dict[str, Any]] = messages_override
            else:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": user_prompt})

            # Build request kwargs
            request_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            }

            # Newer OpenAI models (o1, o3, o4, gpt-5, etc.) require
            # 'max_completion_tokens' instead of the legacy 'max_tokens' parameter.
            model_lower = (self.model or "").lower()
            uses_max_completion_tokens = (
                model_lower.startswith("o1")
                or model_lower.startswith("o3")
                or model_lower.startswith("o4")
                or model_lower.startswith("gpt-5")
            )
            if uses_max_completion_tokens:
                request_kwargs["max_completion_tokens"] = self.max_tokens
            else:
                request_kwargs["max_tokens"] = self.max_tokens

            # Always enforce JSON output format
            request_kwargs["response_format"] = {"type": "json_object"}

            # Build provider-specific cache hints in extra_body.
            # - prompt_cache_key (OpenAI/DeepSeek/OpenRouter/Grok): improves
            #   prefix-cache routing stickiness across alternating call types.
            #   Grok DOES honor it — verified empirically: without a key a
            #   repeated identical prefix intermittently missed (routing bounced
            #   to a cold node); with prompt_cache_key the same prefix stayed a
            #   consistent hit. The old code skipped grok on a stale assumption.
            # - cache_control (OpenRouter routing to Anthropic Claude only): Anthropic
            #   prompt caching is opt-in. OpenRouter accepts a top-level cache_control
            #   field and applies it to the last cacheable block automatically. For
            #   OpenAI/DeepSeek/Gemini upstreams via OpenRouter, caching is automatic
            #   on the upstream side, so cache_control would be ignored — we only set
            #   it when the slug is Anthropic-routed.
            extra_body: Dict[str, Any] = {}

            long_enough = (
                system_prompt and len(system_prompt) >= config.min_cache_tokens
            )

            if call_type and long_enough:
                prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
                cache_key = f"{call_type}_{prompt_hash}"
                extra_body["prompt_cache_key"] = cache_key
                logger.debug(f"[OPENAI] Using prompt_cache_key: {cache_key}")

            if self.provider == "openrouter" and long_enough:
                model_lower_for_cache = (self.model or "").lower()
                # OpenRouter slugs are "<provider>/<model>". Anthropic Claude routes
                # are the only ones requiring opt-in cache_control. Detect by either
                # the slug prefix or the "claude" substring (some aliases like
                # "anthropic/claude-3.5-sonnet:beta" still match).
                if (
                    model_lower_for_cache.startswith("anthropic/")
                    or "claude" in model_lower_for_cache
                ):
                    cache_control: Dict[str, Any] = {"type": "ephemeral"}
                    if call_type:
                        # 1-hour TTL keeps caches alive across alternating call types
                        # (mirrors the Anthropic-direct path).
                        cache_control["ttl"] = "1h"
                    extra_body["cache_control"] = cache_control
                    logger.debug(
                        f"[OPENROUTER] Anthropic cache_control: {cache_control} (model={self.model})"
                    )

            if extra_body:
                request_kwargs["extra_body"] = extra_body

            # In ChatGPT subscription mode the ``self.client`` is a
            # ChatGPTSubscriptionClient that re-routes chat.completions
            # calls through the Responses API (the only surface the
            # chatgpt.com/backend-api/codex backend exposes). Call-site
            # stays unchanged.
            response = self.client.chat.completions.create(**request_kwargs)
            if not response.choices:
                raise ValueError(f"Provider returned no choices (model={self.model!r})")
            content = (response.choices[0].message.content or "").strip()
            token_count_input = response.usage.prompt_tokens
            token_count_output = response.usage.completion_tokens

            # Extract cached tokens. Empirically ALL the OpenAI-compatible
            # upstreams we use — including grok (xAI) — report cached tokens
            # under usage.prompt_tokens_details.cached_tokens. Grok does NOT
            # return the top-level prompt_cache_hit_tokens field (verified: it
            # is always absent), so the old grok-specific read reported 0 even
            # on real cache hits. Read the nested field first, then fall back
            # to the legacy top-level field for any provider that still uses it.
            prompt_tokens_details = getattr(
                response.usage, "prompt_tokens_details", None
            )
            if prompt_tokens_details:
                cached_tokens = getattr(prompt_tokens_details, "cached_tokens", 0) or 0
            if not cached_tokens:
                cached_tokens = (
                    getattr(response.usage, "prompt_cache_hit_tokens", 0) or 0
                )

            # Record cache metrics
            provider_label = self.provider  # "openai", "grok", "deepseek", etc.
            metrics = get_cache_metrics()
            if cached_tokens > 0:
                logger.info(
                    f"[CACHE] {provider_label} {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache"
                )
                metrics.record_hit(
                    provider_label,
                    cache_type,
                    cached_tokens=cached_tokens,
                    total_tokens=token_count_input,
                )
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching should have been attempted (prompt long enough)
                # This is a miss - either first call or cache expired
                metrics.record_miss(
                    provider_label, cache_type, total_tokens=token_count_input
                )

            status = "success"
        except Exception as exc:
            exc_obj = exc
            logger.error(f"Error calling OpenAI API: {exc}")

        total_tokens = token_count_input + token_count_output

        self._call_log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens or 0,
        )

        # Report usage. service_type stays "llm_openai" (the request shape) but
        # provider attributes to the actual upstream so dashboards split out
        # OpenRouter / DeepSeek / Grok separately.
        self._report_usage_async(
            "llm_openai",
            self.provider,
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        result = {
            "tokens_used": total_tokens or 0,
            "cached_tokens": cached_tokens,
        }

        if exc_obj:
            # Include error details for better diagnostics
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            # Classify once and stash the LLMErrorInfo object so the outer
            # `_generate_response_sync` can attach it to the consecutive-
            # failure exception. Without this, providers that go through
            # this path (OpenAI, OpenRouter, Grok, DeepSeek, MiniMax,
            # Moonshot) would surface a bare "Aborted after N consecutive
            # failures." with no cause when they fail. The classifier is
            # wrapped in try/except so it can never break the error path.
            try:
                result["error_info_obj"] = classify_llm_error(
                    exc_obj, provider=self.provider, model=self.model
                )
            except Exception:
                pass
            result["content"] = ""
            logger.error(f"[OPENAI_ERROR] {error_str}")
        else:
            result["content"] = content or ""

        return result

    @profile("llm_ollama_call", OperationCategory.LLM)
    def _generate_ollama(
        self, system_prompt: str | None, user_prompt: str
    ) -> Dict[str, Any]:
        token_count_input = token_count_output = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None

        try:
            payload = {
                "model": self.model,
                "prompt": user_prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": self.temperature,
                },
            }
            if system_prompt:
                payload["system"] = system_prompt
            url: str = f"{self.remote_url.rstrip('/')}/api/generate"
            response = requests.post(url, json=payload, timeout=600)
            response.raise_for_status()
            result = response.json()

            content = result.get("response", "").strip()
            token_count_input = result.get("prompt_eval_count", 0)
            token_count_output = result.get("eval_count", 0)
            total_tokens = token_count_input + token_count_output
            status = "success"
        except Exception as exc:
            exc_obj = exc
            logger.error(f"Error calling Ollama API: {exc}")

        self._call_log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )

        # Report usage (no caching for Ollama)
        self._report_usage_async(
            "llm_ollama", "remote", self.model, token_count_input, token_count_output, 0
        )

        result = {"tokens_used": total_tokens or 0}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            # Classify once and stash the LLMErrorInfo object so the
            # outer `_generate_response_sync` can put `info.message`
            # (the rich detailed string) into the RuntimeError it raises,
            # and attach the info to LLMConsecutiveFailureError at the
            # 5-failure threshold. The classifier is wrapped in try/except
            # so it can never break the error path itself.
            try:
                result["error_info_obj"] = classify_llm_error(
                    exc_obj, provider=self.provider, model=self.model
                )
            except Exception:
                pass
            result["content"] = ""
            logger.error(f"[OLLAMA_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    @profile("llm_gemini_call", OperationCategory.LLM)
    def _generate_gemini(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        contents_override: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate response using Gemini with explicit or implicit caching.

        When call_type is provided and system_prompt is long enough, uses explicit
        caching via GeminiCacheManager. This ensures different call types (reasoning,
        action_selection, etc.) get separate caches for optimal cache hit rates.

        Without call_type, falls back to Gemini's implicit caching which may have
        lower hit rates when alternating between different prompt structures.

        Args:
            system_prompt: The system prompt (cached when using explicit caching).
            user_prompt: The user prompt for this request.
            call_type: Optional call type for cache keying (e.g., "reasoning", "action_selection").
                       When provided, enables explicit caching per call type.
            contents_override: Optional pre-built multi-turn `contents` array
                from the session-cache path. When provided, skips the
                explicit-cache code path and sends the full conversation
                history so Gemini's implicit caching catches the growing
                stable prefix automatically (caching covers more tokens with
                every turn without us needing to manage a named cache object).

        Returns:
            Dict with tokens_used, content, cached_tokens.
        """
        from app.google_gemini_client import GeminiAPIError

        token_count_input = token_count_output = 0
        cached_tokens = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = "implicit"  # Default cache type for metrics

        try:
            if not self._gemini_client:
                raise RuntimeError("Gemini client was not initialised.")

            # Multi-turn implicit-cache path takes precedence when provided —
            # the session-cache dispatcher accumulates history and we want
            # Gemini's automatic prefix matching to do the work.
            if contents_override is not None:
                cache_type = f"implicit_{call_type}" if call_type else "implicit"
                logger.debug(
                    f"[GEMINI] Using multi-turn implicit caching "
                    f"(call_type={call_type}, turns={len(contents_override)})"
                )
                result = self._gemini_client.generate_text_multiturn(
                    self.model,
                    contents=contents_override,
                    system_prompt=system_prompt,
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                    json_mode=True,
                )
            else:
                # Use explicit caching when:
                # 1. call_type is provided
                # 2. system_prompt is long enough
                # 3. cache manager is available
                # Note: GeminiCacheManager will automatically fall back to implicit
                # caching if the system prompt is below Gemini's 1024 token minimum
                use_explicit_cache = (
                    call_type
                    and system_prompt
                    and len(system_prompt) >= config.min_cache_tokens
                    and self._gemini_cache_manager
                )

                if use_explicit_cache:
                    cache_type = f"explicit_{call_type}"
                    logger.debug(
                        f"[GEMINI] Using explicit caching for call_type: {call_type}"
                    )
                    result = self._gemini_cache_manager.get_or_create_cache(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        call_type=call_type,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                else:
                    # Fall back to implicit caching (or no caching for short prompts)
                    result = self._gemini_client.generate_text(
                        self.model,
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        temperature=self.temperature,
                        max_output_tokens=self.max_tokens,
                        json_mode=True,
                    )

            # Extract response data
            content = result.get("content", "")
            total_tokens = result.get("tokens_used", 0)
            token_count_input = result.get("prompt_tokens", 0)
            token_count_output = result.get("completion_tokens", 0)
            cached_tokens = result.get("cached_tokens", 0)

            # Record cache metrics
            metrics = get_cache_metrics()
            if cached_tokens > 0:
                logger.info(
                    f"[CACHE] Gemini {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache"
                )
                metrics.record_hit(
                    "gemini",
                    cache_type,
                    cached_tokens=cached_tokens,
                    total_tokens=token_count_input,
                )
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching should have been attempted (prompt long enough)
                # This is a miss - either first call or cache expired
                metrics.record_miss(
                    "gemini", cache_type, total_tokens=token_count_input
                )

            status = "success"
        except GeminiAPIError as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Gemini API rejected the prompt: {exc}")
        except Exception as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Error calling Gemini API: {exc}")

        self._call_log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens,
        )

        # Report usage
        self._report_usage_async(
            "llm_gemini",
            "gemini",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        result = {"tokens_used": total_tokens or 0, "cached_tokens": cached_tokens}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            # Classify once and stash the LLMErrorInfo object so the
            # outer `_generate_response_sync` can put `info.message`
            # (the rich detailed string) into the RuntimeError it raises,
            # and attach the info to LLMConsecutiveFailureError at the
            # 5-failure threshold. The classifier is wrapped in try/except
            # so it can never break the error path itself.
            try:
                result["error_info_obj"] = classify_llm_error(
                    exc_obj, provider=self.provider, model=self.model
                )
            except Exception:
                pass
            result["content"] = ""
            logger.error(f"[GEMINI_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    @profile("llm_byteplus_call", OperationCategory.LLM)
    def _generate_byteplus(
        self, system_prompt: str | None, user_prompt: str
    ) -> Dict[str, Any]:
        """Generate response using BytePlus with automatic prefix caching.

        Routes to prefix cache or standard API based on context.
        """
        config = get_cache_config()
        # Use prefix caching if:
        # - System prompt is provided
        # - System prompt is long enough (uses shared config)
        # - Cache manager is available
        if (
            system_prompt
            and len(system_prompt) >= config.min_cache_tokens
            and self._byteplus_cache_manager
        ):
            return self._generate_byteplus_with_prefix_cache(system_prompt, user_prompt)

        # Standard path (no caching)
        return self._generate_byteplus_standard(system_prompt, user_prompt)

    def _generate_byteplus_with_prefix_cache(
        self, system_prompt: str, user_prompt: str
    ) -> Dict[str, Any]:
        """Use Responses API with prefix caching.

        The system prompt is cached and reused across calls with the same content.
        Only the user prompt is processed fresh each time.
        Uses previous_response_id chaining for cache hits.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        cached_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None

        try:
            # Get response using prefix cache (creates cache on first call)
            result = self._byteplus_cache_manager.get_or_create_prefix_cache(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            logger.info(f"BYTEPLUS CACHED RESPONSE: {result}")

            # Parse response (Responses API format)
            content = self._parse_responses_api_content(result)

            # Token usage from Responses API
            usage = result.get("usage") or {}
            token_count_input = int(usage.get("input_tokens", 0))
            token_count_output = int(usage.get("output_tokens", 0))
            total_tokens = int(usage.get("total_tokens", 0)) or (
                token_count_input + token_count_output
            )

            # Log cache hit info if available and record metrics
            # Responses API uses input_tokens_details instead of prompt_tokens_details
            cached_tokens = usage.get("input_tokens_details", {}).get(
                "cached_tokens", 0
            )
            metrics = get_cache_metrics()
            if cached_tokens and cached_tokens > 0:
                logger.info(
                    f"[CACHE] BytePlus prefix cache hit: {cached_tokens}/{token_count_input} tokens cached"
                )
                metrics.record_hit(
                    "byteplus",
                    "prefix",
                    cached_tokens=cached_tokens,
                    total_tokens=token_count_input,
                )
            else:
                # First call or cache miss
                metrics.record_miss(
                    "byteplus", "prefix", total_tokens=token_count_input
                )

            status = "success"

        except requests.HTTPError as e:
            # Check if this is a cache-related error (expired, not found)
            if e.response is not None and e.response.status_code in (404, 410):
                logger.warning(f"[CACHE] Cache expired or not found, recreating: {e}")
                # Invalidate and retry once
                self._byteplus_cache_manager.invalidate_prefix_cache(system_prompt)
                try:
                    result = self._byteplus_cache_manager.get_or_create_prefix_cache(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    content = self._parse_responses_api_content(result)
                    usage = result.get("usage") or {}
                    token_count_input = int(usage.get("input_tokens", 0))
                    token_count_output = int(usage.get("output_tokens", 0))
                    total_tokens = int(usage.get("total_tokens", 0)) or (
                        token_count_input + token_count_output
                    )
                    status = "success"
                except Exception as retry_exc:
                    exc_obj = retry_exc
                    logger.error(f"[CACHE] Retry failed, falling back: {retry_exc}")
                    return self._generate_byteplus_standard(system_prompt, user_prompt)
            else:
                exc_obj = e
                logger.error(f"Error calling BytePlus Responses API: {e}")
        except Exception as exc:
            exc_obj = exc
            logger.error(f"Error calling BytePlus Responses API: {exc}")

        self._call_log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens or 0,
        )

        # Report usage
        self._report_usage_async(
            "llm_byteplus",
            "byteplus",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens or 0,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens or 0,
        }

    def _parse_responses_api_content(self, result: Dict[str, Any]) -> str:
        """Parse content from BytePlus Responses API response.

        The Responses API uses a different format than chat/completions:
        {
            "output": [
                {"type": "message", "role": "assistant", "content": [
                    {"type": "text", "text": "..."}
                ]}
            ]
        }
        """
        content = ""
        output = result.get("output", [])
        for item in output:
            if item.get("type") == "message" and item.get("role") == "assistant":
                content_blocks = item.get("content", [])
                for block in content_blocks:
                    # Handle both "text" and "output_text" types (BytePlus uses "output_text")
                    if block.get("type") in ("text", "output_text"):
                        content += block.get("text", "")
        return content.strip()

    def _generate_byteplus_standard(
        self, system_prompt: str | None, user_prompt: str
    ) -> Dict[str, Any]:
        """Standard BytePlus API call without caching (uses /chat/completions)."""
        token_count_input = token_count_output = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None

        try:
            # Build OpenAI-compatible messages array
            messages: List[Dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            url = f"{self.byteplus_base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": self.model,
                "messages": messages,
                # Wire through sampling + output control
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                # Note: response_format not supported by all BytePlus models (e.g., kimi)
                # "stream": False,  # default is non-streaming
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }

            # Log the request
            logger.info(f"[BYTEPLUS STANDARD REQUEST] URL: {url}")
            logger.info(
                f"[BYTEPLUS STANDARD REQUEST] Model: {self.model}, Temp: {self.temperature}, MaxTokens: {self.max_tokens}"
            )
            logger.info(f"[BYTEPLUS STANDARD REQUEST] Messages count: {len(messages)}")

            response = requests.post(url, json=payload, headers=headers, timeout=600)

            # Log response status
            logger.info(f"[BYTEPLUS STANDARD RESPONSE] Status: {response.status_code}")

            response.raise_for_status()
            result = response.json()

            logger.info(f"[BYTEPLUS STANDARD RESPONSE] Body: {result}")

            # Non-streaming content location (OpenAI-compatible)
            choices = result.get("choices", [])
            if choices:
                # choices[0].message.content is the OpenAI-compatible field
                content = (
                    choices[0].get("message", {}).get("content")
                    or choices[0].get("delta", {}).get("content", "")
                    or ""
                ).strip()

            total_tokens = int(result.get("usage", {}).get("total_tokens", 0))

            # Token usage (prompt/completion/total)
            usage = result.get("usage") or {}
            token_count_input = int(usage.get("prompt_tokens", 0))
            token_count_output = int(usage.get("completion_tokens", 0))
            status = "success"

        except Exception as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Error calling BytePlus API: {exc}")

        self._call_log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )

        # Report usage (no caching for standard path)
        self._report_usage_async(
            "llm_byteplus",
            "byteplus",
            self.model,
            token_count_input,
            token_count_output,
            0,
        )

        result = {"tokens_used": total_tokens or 0}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            # Classify once and stash the LLMErrorInfo object so the
            # outer `_generate_response_sync` can put `info.message`
            # (the rich detailed string) into the RuntimeError it raises,
            # and attach the info to LLMConsecutiveFailureError at the
            # 5-failure threshold. The classifier is wrapped in try/except
            # so it can never break the error path itself.
            try:
                result["error_info_obj"] = classify_llm_error(
                    exc_obj, provider=self.provider, model=self.model
                )
            except Exception:
                pass
            result["content"] = ""
            logger.error(f"[BYTEPLUS_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    @profile("llm_anthropic_call", OperationCategory.LLM)
    def _generate_anthropic(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        messages: Optional[List[dict]] = None,
    ) -> Dict[str, Any]:
        """Generate response using Anthropic with prompt caching.

        Anthropic's prompt caching uses `cache_control` markers on content blocks.
        When the system prompt is long enough (≥1024 tokens), we enable caching.

        For multi-turn sessions, pass pre-built `messages` with cache_control on the
        last assistant message. This enables prefix caching of the entire conversation
        history, not just the system prompt.

        TTL Options:
        - Default (5 minutes): Free, uses "ephemeral" type
        - Extended (1 hour): When call_type is provided, uses extended TTL for better
          cache hit rates when alternating between different call types.
          Note: Extended TTL cache writes cost 100% more, but reads are 90% cheaper.

        Args:
            system_prompt: The system prompt (cached when long enough).
            user_prompt: The user prompt for this request.
            call_type: Optional call type (e.g., "reasoning", "action_selection").
                       When provided, uses extended 1-hour TTL for better cache hit rates.
            messages: Optional pre-built messages list for multi-turn sessions.
                      When provided, used instead of building a single-turn message.

        Cache hits are logged when `cache_read_input_tokens` > 0 in the response.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        cached_tokens = 0
        # Initialized here (not just inside the try) so the post-`except`
        # _call_log_to_db below can reference them even when the API call
        # throws before they're assigned (e.g. out-of-credits). Otherwise the
        # real provider error is masked by an UnboundLocalError.
        cache_creation = 0
        cache_read = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = f"ephemeral_{call_type}" if call_type else "ephemeral"

        try:
            if not self._anthropic_client:
                raise RuntimeError("Anthropic client was not initialised.")

            # Build the message - use pre-built messages for multi-turn, or single-turn
            # Anthropic requires max_tokens; use 16384 (Claude 4 default) to avoid truncation
            message_kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": 16384,
                "messages": messages
                if messages is not None
                else [
                    {"role": "user", "content": user_prompt},
                ],
            }

            if system_prompt:
                # Use caching if system prompt is long enough
                if len(system_prompt) >= config.min_cache_tokens:
                    # Format system as list of content blocks with cache_control
                    # Use extended 1-hour TTL when call_type is provided for better
                    # cache hit rates when alternating between different call types
                    cache_control: Dict[str, str] = {"type": "ephemeral"}
                    if call_type:
                        # Extended TTL: cache writes cost 100% more, reads 90% cheaper
                        # Better for alternating call types where 5-minute TTL might expire
                        cache_control["ttl"] = "1h"
                        logger.debug(
                            f"[ANTHROPIC] Using 1-hour TTL for call_type: {call_type}"
                        )

                    message_kwargs["system"] = [
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": cache_control,
                        }
                    ]
                else:
                    # Short prompt - use simple string format (no caching)
                    message_kwargs["system"] = system_prompt

            # Always pass temperature for Anthropic (their default is 1.0, not 0.0)
            message_kwargs["temperature"] = self.temperature

            response = self._anthropic_client.messages.create(**message_kwargs)

            # Extract content from the response
            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text
            content = content.strip()

            # Token usage from Anthropic response
            # Anthropic reports input_tokens as non-cached input only.
            # cache_creation_input_tokens: tokens written to cache (first call)
            # cache_read_input_tokens: tokens read from cache (subsequent calls)
            # Total input = input_tokens + cache_creation + cache_read
            base_input = response.usage.input_tokens
            token_count_output = response.usage.output_tokens
            cache_creation = (
                getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            )
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            token_count_input = base_input + cache_creation + cache_read
            total_tokens = token_count_input + token_count_output
            cached_tokens = cache_read

            # Record metrics
            metrics = get_cache_metrics()
            if cache_read > 0:
                logger.info(
                    f"[CACHE] Anthropic {cache_type} cache hit: {cache_read}/{token_count_input} tokens from cache"
                )
                metrics.record_hit(
                    "anthropic",
                    cache_type,
                    cached_tokens=cache_read,
                    total_tokens=token_count_input,
                )
            elif cache_creation > 0:
                logger.info(
                    f"[CACHE] Anthropic {cache_type} cache created: {cache_creation} tokens cached"
                )
                # Cache creation is a "miss" for the current call but sets up future hits
                metrics.record_miss(
                    "anthropic", cache_type, total_tokens=token_count_input
                )
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching was attempted but no cache info returned - unexpected
                metrics.record_miss(
                    "anthropic", cache_type, total_tokens=token_count_input
                )

            status = "success"

        except Exception as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Error calling Anthropic API: {exc}")

        self._call_log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens,  # cache_read — was MISSING (always 0)
            cache_creation_tokens=cache_creation,  # cache_write — to settle write-vs-expiry
        )

        # Report usage
        self._report_usage_async(
            "llm_anthropic",
            "anthropic",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        result = {"tokens_used": total_tokens or 0, "cached_tokens": cached_tokens}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            # Classify once and stash the LLMErrorInfo object so the
            # outer `_generate_response_sync` can put `info.message`
            # (the rich detailed string) into the RuntimeError it raises,
            # and attach the info to LLMConsecutiveFailureError at the
            # 5-failure threshold. The classifier is wrapped in try/except
            # so it can never break the error path itself.
            try:
                result["error_info_obj"] = classify_llm_error(
                    exc_obj, provider=self.provider, model=self.model
                )
            except Exception:
                pass
            result["content"] = ""
            logger.error(f"[ANTHROPIC_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    # ─────────── Bedrock model capability detection ───────────────────

    # Bedrock model ID prefixes that support cachePoint prompt caching.
    # Only Anthropic Claude models on Bedrock currently support this feature —
    # sending cachePoint to Llama / Titan / Mistral raises ValidationException.
    _BEDROCK_CACHE_PREFIXES = (
        "anthropic.",
        "us.anthropic.",
        "eu.anthropic.",
        "ap.anthropic.",
    )

    def _bedrock_model_supports_caching(self, model: Optional[str] = None) -> bool:
        """Check if the current Bedrock model supports cachePoint prompt caching."""
        model_id = model or self.model or ""
        return any(model_id.startswith(p) for p in self._BEDROCK_CACHE_PREFIXES)

    @profile("llm_bedrock_call", OperationCategory.LLM)
    def _generate_bedrock(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        messages: Optional[List[dict]] = None,
    ) -> Dict[str, Any]:
        """Generate response via AWS Bedrock Converse API with prompt caching.

        Converse is the unified Bedrock API across Claude / Llama / Titan /
        Mistral. cachePoint markers are inserted only for models that support
        it (Anthropic Claude family) — other models would reject the request.

        Args:
            system_prompt: The system prompt.
            user_prompt: The user prompt for this request.
            call_type: Optional call type for cache labelling.
            messages: Optional pre-built multi-turn messages list. When provided
                (from the session-cache path), the caller has already placed a
                `cachePoint` block at the end of the last assistant content —
                that captures the entire growing prefix. In that mode we do
                NOT also put a cachePoint in the system block (only one is
                needed and placing it in messages lets the cache grow with the
                conversation). When messages is None, falls back to a fresh
                single-turn call with cachePoint on the system block.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        cached_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = f"cachepoint_{call_type}" if call_type else "cachepoint"

        try:
            if not self._bedrock_client:
                raise RuntimeError("Bedrock client was not initialised.")

            # Multi-turn path: caller provided pre-built messages with cachePoint
            # already placed on the last assistant message (if any). Single-turn
            # path: build a fresh user-only message list.
            multi_turn = messages is not None
            converse_messages = (
                messages
                if multi_turn
                else [{"role": "user", "content": [{"text": user_prompt}]}]
            )

            converse_kwargs: Dict[str, Any] = {
                "modelId": self.model,
                "messages": converse_messages,
                "inferenceConfig": {
                    "temperature": self.temperature,
                    "maxTokens": self.max_tokens,
                },
            }

            if system_prompt:
                # When messages already carry a cachePoint (multi-turn first
                # call having a history assistant), don't double up by adding
                # another in the system block — Bedrock would still accept it
                # but a redundant checkpoint wastes a slot (max 4 per request).
                msgs_have_cachepoint = multi_turn and any(
                    any("cachePoint" in block for block in msg.get("content", []))
                    for msg in converse_messages
                )
                use_system_cache = bool(
                    call_type
                    and len(system_prompt) >= config.min_cache_tokens
                    and self._bedrock_model_supports_caching()
                    and not msgs_have_cachepoint
                )
                if use_system_cache:
                    converse_kwargs["system"] = [
                        {"text": system_prompt},
                        {"cachePoint": {"type": "default"}},
                    ]
                else:
                    converse_kwargs["system"] = [{"text": system_prompt}]

            response = self._bedrock_client.converse(**converse_kwargs)

            output_message = response.get("output", {}).get("message", {})
            content_blocks = output_message.get("content", []) or []
            content = "".join(
                block.get("text", "") for block in content_blocks if "text" in block
            ).strip()

            usage = response.get("usage", {}) or {}
            token_count_input = int(usage.get("inputTokens", 0) or 0)
            token_count_output = int(usage.get("outputTokens", 0) or 0)
            total_tokens = token_count_input + token_count_output

            if self._bedrock_model_supports_caching():
                # Official Converse response uses `cacheReadInputTokens` /
                # `cacheWriteInputTokens` (no "Count" suffix) per the API
                # reference. The "...TokenCount" variants are tolerated as a
                # defensive fallback in case older SDK builds expose them.
                cache_read = int(
                    usage.get("cacheReadInputTokens")
                    or usage.get("cacheReadInputTokenCount")
                    or 0
                )
                cache_write = int(
                    usage.get("cacheWriteInputTokens")
                    or usage.get("cacheWriteInputTokenCount")
                    or 0
                )
                cached_tokens = cache_read + cache_write

                metrics = get_cache_metrics()
                if cache_read > 0:
                    logger.info(
                        f"[CACHE] Bedrock {cache_type} cache hit: "
                        f"{cache_read}/{token_count_input} tokens from cache"
                    )
                    metrics.record_hit(
                        "bedrock",
                        cache_type,
                        cached_tokens=cache_read,
                        total_tokens=token_count_input,
                    )
                elif cache_write > 0:
                    logger.info(
                        f"[CACHE] Bedrock {cache_type} cache created: "
                        f"{cache_write} tokens cached"
                    )
                    metrics.record_miss(
                        "bedrock", cache_type, total_tokens=token_count_input
                    )
                elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                    metrics.record_miss(
                        "bedrock", cache_type, total_tokens=token_count_input
                    )

            status = "success"

        except Exception as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Error calling Bedrock Converse API: {exc}")

        self._call_log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
            cached_tokens=cached_tokens or 0,
        )

        self._report_usage_async(
            "llm_bedrock",
            "bedrock",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        result = {
            "tokens_used": total_tokens or 0,
            "cached_tokens": cached_tokens,
        }
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            try:
                result["error_info_obj"] = classify_llm_error(
                    exc_obj, provider=self.provider, model=self.model
                )
            except Exception:
                pass
            result["content"] = ""
            logger.error(f"[BEDROCK_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    # ─────────────────── CLI helper for ad‑hoc testing ───────────────────
    def _cli(self) -> None:  # pragma: no cover
        """Run a quick interactive shell for manual testing."""
        logger.debug(
            "Provider: {provider!r}, model: {model!r}",
            provider=self.provider,
            model=self.model,
        )
        while True:
            user_prompt = input("\nEnter prompt (or 'exit'): ").strip()
            if user_prompt.lower() in {"exit", "quit"}:
                break
            response = self.generate_response(user_prompt=user_prompt)
            logger.debug(f"AI Response:\n{response}\n")
