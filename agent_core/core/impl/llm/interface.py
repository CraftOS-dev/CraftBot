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
import hashlib
import re
import requests
from typing import Any, Dict, List, Optional

from openai import OpenAI

from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import (
    BytePlusCacheManager,
    BytePlusContextOverflowError,
    GeminiCacheManager,
    get_cache_config,
    get_cache_metrics,
)
from agent_core.core.hooks import (
    GetTokenCountHook,
    SetTokenCountHook,
    ReportUsageHook,
    LogToDbHook,
    UsageEventData,
)

# Logging setup - use shared agent_core logger for consistency
from agent_core.utils.logger import logger


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
        max_tokens: int = 8000,
        deferred: bool = False,
        get_token_count: Optional[GetTokenCountHook] = None,
        set_token_count: Optional[SetTokenCountHook] = None,
        report_usage: Optional[ReportUsageHook] = None,
        log_to_db: Optional[LogToDbHook] = None,
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

        # Defer imports to avoid circular dependency
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType
        from app.google_gemini_client import GeminiClient

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
        self._initialized = ctx.get("initialized", False)

        # Initialize BytePlus-specific attributes
        self._byteplus_cache_manager: Optional[BytePlusCacheManager] = None
        # Store system prompts for lazy session creation (instance variable)
        self._session_system_prompts: Dict[str, str] = {}

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
            target_api_key = api_key if api_key is not None else get_api_key(target_provider)
            target_base_url = base_url if base_url is not None else get_base_url(target_provider)
        else:
            target_api_key = api_key
            target_base_url = base_url

        try:
            logger.info(f"[LLM] Reinitializing with provider: {target_provider}")
            ctx = ModelFactory.create(
                provider=target_provider,
                interface=InterfaceType.LLM,
                model_override=None,
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
            self._initialized = ctx.get("initialized", False)

            if ctx["byteplus"]:
                self.api_key = ctx["byteplus"]["api_key"]
                self.byteplus_base_url = ctx["byteplus"]["base_url"]
                # Reinitialize cache manager for BytePlus
                self._byteplus_cache_manager = BytePlusCacheManager(
                    api_key=self.api_key,
                    base_url=self.byteplus_base_url,
                    model=self.model,
                )
                # Reset session system prompts
                self._session_system_prompts = {}
            else:
                self._byteplus_cache_manager = None
                self._session_system_prompts = {}

            # Reinitialize Gemini cache manager
            if self._gemini_client:
                self._gemini_cache_manager = GeminiCacheManager(
                    gemini_client=self._gemini_client,
                    model=self.model,
                )
            else:
                self._gemini_cache_manager = None

            logger.info(f"[LLM] Reinitialized successfully with provider: {self.provider}, model: {self.model}")
            return self._initialized
        except EnvironmentError as e:
            logger.warning(f"[LLM] Failed to reinitialize - missing API key: {e}")
            return False
        except Exception as e:
            logger.error(f"[LLM] Failed to reinitialize - unexpected error: {e}", exc_info=True)
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
    ) -> None:
        """Call the log_to_db hook if set."""
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

        if log_response:
            logger.info(f"[LLM SEND] system={system_prompt} | user={user_prompt}")

        if self.provider == "openai":
            response = self._generate_openai(system_prompt, user_prompt)
        elif self.provider == "remote":
            response = self._generate_ollama(system_prompt, user_prompt)
        elif self.provider == "gemini":
            response = self._generate_gemini(system_prompt, user_prompt)
        elif self.provider == "byteplus":
            response = self._generate_byteplus(system_prompt, user_prompt)
        elif self.provider == "anthropic":
            response = self._generate_anthropic(system_prompt, user_prompt)
        else:  # pragma: no cover
            raise RuntimeError(f"Unknown provider {self.provider!r}")

        content = response.get("content", "").strip()
        
        # Check if response is empty and provide diagnostics
        if not content:
            error_msg = response.get("error", "")
            if error_msg:
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
            raise RuntimeError(error_detail)
        
        cleaned = re.sub(self._CODE_BLOCK_RE, "", content)

        # Update token count via hook
        current_count = self._get_token_count()
        self._set_token_count(current_count + response.get("tokens_used", 0))

        if log_response:
            logger.info(f"[LLM RECV] {cleaned}")
        return cleaned

    @profile("llm_generate_response", OperationCategory.LLM)
    def generate_response(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Generate a single response from the configured provider."""
        return self._generate_response_sync(system_prompt, user_prompt, log_response)

    @profile("llm_generate_response_async", OperationCategory.LLM)
    async def generate_response_async(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Async wrapper that defers the blocking call to a worker thread."""
        return await asyncio.to_thread(
            self._generate_response_sync,
            system_prompt,
            user_prompt,
            log_response,
        )

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
            (self.provider == "byteplus" and self._byteplus_cache_manager) or
            (self.provider == "gemini" and self._gemini_cache_manager) or
            (self.provider == "openai" and self.client) or  # OpenAI uses automatic caching with prompt_cache_key
            (self.provider == "anthropic" and self._anthropic_client)  # Anthropic uses ephemeral caching with extended TTL
        )

        if not supports_caching:
            logger.debug(f"[SESSION] Session cache not available for provider: {self.provider}")
            return None

        # Store system prompt for lazy session/cache creation
        session_key = f"{task_id}:{call_type}"
        self._session_system_prompts[session_key] = system_prompt
        logger.info(f"[SESSION] Registered session for {session_key} (provider: {self.provider})")
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
        # Clean up stored system prompt
        session_key = f"{task_id}:{call_type}"
        system_prompt = self._session_system_prompts.pop(session_key, None)

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
        keys_to_remove = [k for k in self._session_system_prompts if k.startswith(f"{task_id}:")]
        prompts_and_types = []
        for key in keys_to_remove:
            system_prompt = self._session_system_prompts.pop(key, None)
            if system_prompt:
                # Extract call_type from key (format: "task_id:call_type")
                call_type = key.split(":", 1)[1] if ":" in key else None
                if call_type:
                    prompts_and_types.append((system_prompt, call_type))

        # Clean up provider-specific caches
        if self.provider == "byteplus" and self._byteplus_cache_manager:
            self._byteplus_cache_manager.end_all_sessions_for_task(task_id)
        elif self.provider == "gemini" and self._gemini_cache_manager:
            # Invalidate all explicit caches for this task's prompts
            for system_prompt, call_type in prompts_and_types:
                self._gemini_cache_manager.invalidate_cache(system_prompt, call_type)

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
            if self.provider == "openai" and self.client:
                return True
            if self.provider == "anthropic" and self._anthropic_client:
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

        if log_response:
            logger.info(f"[LLM SESSION] task={task_id} call_type={call_type} | user={user_prompt}")

        # Handle Gemini with explicit caching (per call_type)
        if self.provider == "gemini" and self._gemini_cache_manager:
            # Get stored system prompt or use provided one
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

            if not effective_system_prompt:
                raise ValueError(
                    f"No system prompt for task {task_id}:{call_type}"
                )

            # Use Gemini with explicit caching (call_type passed for cache keying)
            response = self._generate_gemini(effective_system_prompt, user_prompt, call_type=call_type)
            cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())
            current_count = self._get_token_count()
            self._set_token_count(current_count + response.get("tokens_used", 0))
            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned

        # Handle OpenAI with call_type-based cache routing
        if self.provider == "openai":
            # Get stored system prompt or use provided one
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

            if not effective_system_prompt:
                raise ValueError(
                    f"No system prompt for task {task_id}:{call_type}"
                )

            # Use OpenAI with call_type for better cache routing via prompt_cache_key
            response = self._generate_openai(effective_system_prompt, user_prompt, call_type=call_type)
            cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())
            current_count = self._get_token_count()
            self._set_token_count(current_count + response.get("tokens_used", 0))
            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned

        # Handle Anthropic with call_type-based extended TTL caching
        if self.provider == "anthropic" and self._anthropic_client:
            # Get stored system prompt or use provided one
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

            if not effective_system_prompt:
                raise ValueError(
                    f"No system prompt for task {task_id}:{call_type}"
                )

            # Use Anthropic with call_type for extended 1-hour TTL caching
            response = self._generate_anthropic(effective_system_prompt, user_prompt, call_type=call_type)
            cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())
            current_count = self._get_token_count()
            self._set_token_count(current_count + response.get("tokens_used", 0))
            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned

        # If not BytePlus (and not Gemini/OpenAI/Anthropic which are handled above), fall back to standard
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
                response = self._generate_byteplus_with_session(task_id, call_type, user_prompt)
            else:
                # No session exists - create one and get first response
                stored_system_prompt = self._session_system_prompts.get(session_key)
                effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

                if not effective_system_prompt:
                    raise ValueError(
                        f"No system prompt for task {task_id}:{call_type}"
                    )

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
                response = self._process_session_response(result, task_id, call_type, is_first_call=True)

        except Exception as e:
            logger.warning(f"[SESSION CACHE] Failed: {e}, falling back to standard")
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = system_prompt_for_new_session or stored_system_prompt
            return self._generate_response_sync(
                effective_system_prompt, user_prompt, log_response=False
            )

        cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())

        current_count = self._get_token_count()
        self._set_token_count(current_count + response.get("tokens_used", 0))
        if log_response:
            logger.info(f"[LLM RECV] {cleaned}")
        return cleaned

    def _process_session_response(
        self, result: Dict[str, Any], task_id: str, call_type: str, is_first_call: bool = False
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
        total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

        # Log cache info and record metrics
        cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(f"[CACHE] BytePlus session cache hit: {cached_tokens}/{token_count_input} tokens cached")
            metrics.record_hit("byteplus", "session", cached_tokens=cached_tokens, total_tokens=token_count_input)
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
        )

        # Report usage
        self._report_usage_async(
            "llm_byteplus", "byteplus", self.model,
            token_count_input, token_count_output, cached_tokens or 0
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
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
        total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

        # Log cache info and record metrics
        cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(f"[CACHE] BytePlus prefix cache hit: {cached_tokens}/{token_count_input} tokens cached")
            metrics.record_hit("byteplus", "prefix", cached_tokens=cached_tokens, total_tokens=token_count_input)
        else:
            # First call or cache miss
            metrics.record_miss("byteplus", "prefix", total_tokens=token_count_input)

        logger.info(f"BYTEPLUS PREFIX RESPONSE for {session_key}: input={token_count_input}, cached={cached_tokens}")

        self._call_log_to_db(
            f"[PREFIX:{session_key}]",
            "[prefix_call]",
            content,
            "success",
            token_count_input,
            token_count_output,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    def generate_response_with_session(
        self,
        task_id: str,
        call_type: str,
        user_prompt: str,
        system_prompt_for_new_session: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Synchronous session-based response generation.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.
        """
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
    ) -> str:
        """Async wrapper for session-based response generation.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.
        """
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
            total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

            # Log cache info and record metrics
            # Responses API uses input_tokens_details instead of prompt_tokens_details
            cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
            metrics = get_cache_metrics()
            if cached_tokens and cached_tokens > 0:
                logger.info(f"[CACHE] BytePlus session cache hit: {cached_tokens}/{token_count_input} tokens cached")
                metrics.record_hit("byteplus", "session", cached_tokens=cached_tokens, total_tokens=token_count_input)
            else:
                # First call in session or growing context
                metrics.record_miss("byteplus", "session", total_tokens=token_count_input)

            status = "success"

        except BytePlusContextOverflowError as overflow_exc:
            # Context exceeded maximum length - reset session and retry with fresh context
            logger.warning(f"[BYTEPLUS] Context overflow for {session_key}, resetting session and retrying...")

            # End the overflowed session
            self._byteplus_cache_manager.end_session(task_id, call_type)

            # Get the stored system prompt for this session
            system_prompt = self._session_system_prompts.get(session_key)
            if not system_prompt:
                exc_obj = ValueError(f"Cannot reset session {session_key}: no system prompt stored")
                logger.error(str(exc_obj))
            else:
                try:
                    # Create a fresh session with system prompt and current user prompt
                    logger.info(f"[BYTEPLUS] Creating fresh session for {session_key} after overflow")
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
                    total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

                    # Record as cache miss (fresh session)
                    metrics = get_cache_metrics()
                    metrics.record_miss("byteplus", "session_reset", total_tokens=token_count_input)

                    status = "success"
                    logger.info(f"[BYTEPLUS] Successfully recovered from context overflow for {session_key}")

                except Exception as retry_exc:
                    exc_obj = retry_exc
                    logger.error(f"Error retrying BytePlus Session API for {session_key} after reset: {retry_exc}")

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
        )

        # Report usage
        cached_tokens = 0
        if status == "success":
            usage = result.get("usage") or {} if 'result' in dir() else {}
            cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0) if usage else 0
        self._report_usage_async(
            "llm_byteplus", "byteplus", self.model,
            token_count_input, token_count_output, cached_tokens
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    # ───────────────────── Provider‑specific private helpers ─────────────────────
    @profile("llm_openai_call", OperationCategory.LLM)
    def _generate_openai(
        self, system_prompt: str | None, user_prompt: str, call_type: Optional[str] = None
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
            messages: List[Dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            # Build request kwargs
            request_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }

            # Always enforce JSON output format
            request_kwargs["response_format"] = {"type": "json_object"}

            # Add prompt_cache_key when call_type is provided for better cache routing
            # This helps when alternating between different call types (reasoning, action_selection)
            if call_type and system_prompt and len(system_prompt) >= config.min_cache_tokens:
                prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
                cache_key = f"{call_type}_{prompt_hash}"
                request_kwargs["extra_body"] = {"prompt_cache_key": cache_key}
                logger.debug(f"[OPENAI] Using prompt_cache_key: {cache_key}")

            response = self.client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content.strip()
            token_count_input = response.usage.prompt_tokens
            token_count_output = response.usage.completion_tokens

            # Extract cached tokens from prompt_tokens_details (OpenAI automatic caching)
            # Available for prompts ≥1024 tokens
            prompt_tokens_details = getattr(response.usage, "prompt_tokens_details", None)
            if prompt_tokens_details:
                cached_tokens = getattr(prompt_tokens_details, "cached_tokens", 0) or 0

            # Record cache metrics
            metrics = get_cache_metrics()
            if cached_tokens > 0:
                logger.info(f"[CACHE] OpenAI {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache")
                metrics.record_hit("openai", cache_type, cached_tokens=cached_tokens, total_tokens=token_count_input)
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching should have been attempted (prompt long enough)
                # This is a miss - either first call or cache expired
                metrics.record_miss("openai", cache_type, total_tokens=token_count_input)

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
        )

        # Report usage
        self._report_usage_async(
            "llm_openai", "openai", self.model,
            token_count_input, token_count_output, cached_tokens
        )

        result = {
            "tokens_used": total_tokens or 0,
            "cached_tokens": cached_tokens,
        }
        
        if exc_obj:
            # Include error details for better diagnostics
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            result["content"] = ""
            logger.error(f"[OPENAI_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        
        return result

    @profile("llm_ollama_call", OperationCategory.LLM)
    def _generate_ollama(self, system_prompt: str | None, user_prompt: str) -> Dict[str, Any]:
        token_count_input = token_count_output = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None

        try:
            payload = {
                "model": self.model,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                }
            }
            url: str = f"{self.remote_url.rstrip('/')}/generate"
            response = requests.post(url, json=payload, timeout=600)
            response.raise_for_status()
            result = response.json()

            content = result.get("response", "").strip()
            total_tokens = result.get("usage", {}).get("total_tokens", 0)
            token_count_input = result.get("prompt_eval_count", 0)
            token_count_output = result.get("eval_count", 0)
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
            "llm_ollama", "remote", self.model,
            token_count_input, token_count_output, 0
        )
        
        result = {"tokens_used": total_tokens or 0}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            result["content"] = ""
            logger.error(f"[OLLAMA_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    @profile("llm_gemini_call", OperationCategory.LLM)
    def _generate_gemini(
        self, system_prompt: str | None, user_prompt: str, call_type: Optional[str] = None
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

            # Use explicit caching when:
            # 1. call_type is provided
            # 2. system_prompt is long enough
            # 3. cache manager is available
            # Note: GeminiCacheManager will automatically fall back to implicit caching
            # if the system prompt is below Gemini's 1024 token minimum
            use_explicit_cache = (
                call_type
                and system_prompt
                and len(system_prompt) >= config.min_cache_tokens
                and self._gemini_cache_manager
            )

            if use_explicit_cache:
                cache_type = f"explicit_{call_type}"
                logger.debug(f"[GEMINI] Using explicit caching for call_type: {call_type}")
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
                logger.info(f"[CACHE] Gemini {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache")
                metrics.record_hit("gemini", cache_type, cached_tokens=cached_tokens, total_tokens=token_count_input)
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching should have been attempted (prompt long enough)
                # This is a miss - either first call or cache expired
                metrics.record_miss("gemini", cache_type, total_tokens=token_count_input)

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
        )

        # Report usage
        self._report_usage_async(
            "llm_gemini", "gemini", self.model,
            token_count_input, token_count_output, cached_tokens
        )
        
        result = {"tokens_used": total_tokens or 0, "cached_tokens": cached_tokens}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            result["content"] = ""
            logger.error(f"[GEMINI_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    @profile("llm_byteplus_call", OperationCategory.LLM)
    def _generate_byteplus(self, system_prompt: str | None, user_prompt: str) -> Dict[str, Any]:
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
            total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

            # Log cache hit info if available and record metrics
            # Responses API uses input_tokens_details instead of prompt_tokens_details
            cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
            metrics = get_cache_metrics()
            if cached_tokens and cached_tokens > 0:
                logger.info(f"[CACHE] BytePlus prefix cache hit: {cached_tokens}/{token_count_input} tokens cached")
                metrics.record_hit("byteplus", "prefix", cached_tokens=cached_tokens, total_tokens=token_count_input)
            else:
                # First call or cache miss
                metrics.record_miss("byteplus", "prefix", total_tokens=token_count_input)

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
                    total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)
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
        )

        # Report usage
        self._report_usage_async(
            "llm_byteplus", "byteplus", self.model,
            token_count_input, token_count_output, cached_tokens or 0
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
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
            logger.info(f"[BYTEPLUS STANDARD REQUEST] Model: {self.model}, Temp: {self.temperature}, MaxTokens: {self.max_tokens}")
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
            "llm_byteplus", "byteplus", self.model,
            token_count_input, token_count_output, 0
        )
        
        result = {"tokens_used": total_tokens or 0}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            result["content"] = ""
            logger.error(f"[BYTEPLUS_ERROR] {error_str}")
        else:
            result["content"] = content or ""
        return result

    @profile("llm_anthropic_call", OperationCategory.LLM)
    def _generate_anthropic(
        self, system_prompt: str | None, user_prompt: str, call_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate response using Anthropic with prompt caching.

        Anthropic's prompt caching uses `cache_control` markers on content blocks.
        When the system prompt is long enough (≥1024 tokens), we enable caching.

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

        Cache hits are logged when `cache_read_input_tokens` > 0 in the response.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        cached_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = f"ephemeral_{call_type}" if call_type else "ephemeral"

        try:
            if not self._anthropic_client:
                raise RuntimeError("Anthropic client was not initialised.")

            # Build the message with optional system prompt
            # Use JSON prefilling to enforce JSON output
            message_kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": "{"},  # JSON prefilling
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
                        logger.debug(f"[ANTHROPIC] Using 1-hour TTL for call_type: {call_type}")

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

            # Prepend the prefilled '{' to complete JSON
            content = "{" + content.strip()

            # Token usage from Anthropic response
            token_count_input = response.usage.input_tokens
            token_count_output = response.usage.output_tokens
            total_tokens = token_count_input + token_count_output

            # Log cache stats if available (Anthropic returns cache info in usage)
            # cache_creation_input_tokens: tokens written to cache (first call)
            # cache_read_input_tokens: tokens read from cache (subsequent calls)
            cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cached_tokens = cache_creation + cache_read

            # Record metrics
            metrics = get_cache_metrics()
            if cache_read > 0:
                logger.info(f"[CACHE] Anthropic {cache_type} cache hit: {cache_read}/{token_count_input} tokens from cache")
                metrics.record_hit("anthropic", cache_type, cached_tokens=cache_read, total_tokens=token_count_input)
            elif cache_creation > 0:
                logger.info(f"[CACHE] Anthropic {cache_type} cache created: {cache_creation} tokens cached")
                # Cache creation is a "miss" for the current call but sets up future hits
                metrics.record_miss("anthropic", cache_type, total_tokens=token_count_input)
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching was attempted but no cache info returned - unexpected
                metrics.record_miss("anthropic", cache_type, total_tokens=token_count_input)

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
        )

        # Report usage
        self._report_usage_async(
            "llm_anthropic", "anthropic", self.model,
            token_count_input, token_count_output, cached_tokens
        )
        
        result = {"tokens_used": total_tokens or 0, "cached_tokens": cached_tokens}
        if exc_obj:
            error_str = f"{type(exc_obj).__name__}: {str(exc_obj)}"
            result["error"] = error_str
            result["content"] = ""
            logger.error(f"[ANTHROPIC_ERROR] {error_str}")
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
