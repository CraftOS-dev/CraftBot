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
import re
import time
from typing import Any, Dict, List, Optional


from agent_core.decorators import profile, OperationCategory
from agent_core.core.impl.llm.cache import (
    BytePlusCacheManager,
    GeminiCacheManager,
    get_cache_metrics,
)
from agent_core.core.errors import ErrorCategory, FAIL_FAST_CATEGORIES
from agent_core.core.impl.llm.errors import (
    LLMConsecutiveFailureError,
    LLMErrorInfo,
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
from agent_core.core.impl.llm import transports as _transports
from agent_core.core.models.registry import (
    get_registry as _get_registry,
    session_cc_providers as _session_cc_providers,
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


def _generic_empty_response_detail(provider: str, model: str) -> str:
    """Fallback detail text for an empty LLM response that carries neither a
    classified `error_info_obj` nor a raw `error` string. Shared by
    `_generate_response_sync` and `_finalize_session_response` — previously
    each had its own near-identical text that had drifted apart in wording.
    """
    return (
        f"LLM returned empty response. "
        f"Provider: {provider}, Model: {model}. "
        f"This may indicate: API authentication failure, invalid API key, rate limiting, "
        f"connection timeout, or LLM service unavailability. "
        f"Check your credentials and API status."
    )


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
        on_fallback: Optional[Any] = None,
    ) -> None:
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._gemini_client = None
        self._anthropic_client = None
        self._initialized = False
        self._deferred = deferred

        # Last-applied api_key/base_url, used by reinitialize() to detect
        # whether a Settings save actually changed anything.
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

        # Cross-provider fallback (Phase 5, FR-9). Turn-scoped: a fallback
        # serves the current turn only; the next turn retries the primary.
        # Fallback interfaces are lazily-built secondary LLMInterface
        # instances with their OWN session buffers, so the primary's
        # accumulated cache state is never disturbed (NFR-3).
        self._fallback_interfaces: Dict[str, "LLMInterface"] = {}
        # Set by reinitialize(): the first turn after an explicit provider
        # selection runs strict (no fallback) so misconfiguration surfaces
        # instead of being silently masked (OpenClaw's rule).
        self._suppress_fallback_once = False
        # (task_id, call_type) of the in-flight session call, stashed by the
        # session dispatcher so _finalize_session_response can retry the
        # same session turn on a fallback provider.
        self._current_session_call: Optional[tuple] = None
        self._on_fallback = on_fallback
        # True on secondary interfaces built BY the fallback machinery.
        # Enforces "at most one chain walk per turn" structurally: a
        # fallback instance never consults the chain itself, so a
        # multi-provider outage terminates instead of nesting
        # primary -> fb -> fb-of-fb recursion.
        self._is_fallback_instance = False

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

        _safe_ctx = {k: v for k, v in ctx.items() if k != "byteplus"}
        if ctx.get("byteplus"):
            _safe_ctx["byteplus"] = {
                "api_key": "<redacted>",
                "base_url": ctx["byteplus"].get("base_url"),
            }
        logger.info(f"[LLM FACTORY] {_safe_ctx}")

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

        # Explicit selection is strict for one turn (Phase 5): the next
        # generate call runs without fallback so a bad key/model surfaces.
        # Also drop cached fallback interfaces — the chain may have changed.
        self._suppress_fallback_once = True
        self._fallback_interfaces = {}

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

        # Diff against the currently-live config so a Settings save that
        # didn't actually change anything (or only changed the model within
        # the same provider) doesn't have to nuke every active task's
        # accumulated session state. `target_model is not None` guards the
        # no-op fast path off in the app-context-unavailable edge case above,
        # where we can't tell what "unchanged" means — fall through to the
        # full-reset path there, matching prior behavior.
        old_provider = self.provider
        old_model = self.model
        old_api_key = self._init_api_key
        old_base_url = self._init_base_url
        provider_unchanged = target_provider == old_provider
        nothing_changed = (
            provider_unchanged
            and target_model is not None
            and target_model == old_model
            and target_api_key == old_api_key
            and target_base_url == old_base_url
        )

        if nothing_changed:
            logger.info(
                "[LLM] Reinitialize no-op — provider/model/credentials "
                "unchanged, skipping reset"
            )
            return self._initialized

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
            else:
                self._byteplus_cache_manager = None

            if provider_unchanged:
                # Model/credentials-only change: the message-history buffers
                # are provider-agnostic message lists the new model can
                # consume as-is, so keep them — the prefix cache takes one
                # miss and re-warms instead of rebuilding from scratch.
                logger.info(
                    f"[LLM] Model-only reinit within provider {self.provider}: "
                    f"preserving session histories"
                )
            else:
                # Real provider change: message formats differ across
                # providers, so the accumulated histories aren't reusable.
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

            # Track last-applied credentials so the next reinitialize() call
            # can tell whether anything actually changed.
            self._init_api_key = target_api_key
            self._init_base_url = target_base_url

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
        thinking_budget: Optional[int] = None,
    ) -> None:
        """Stamp per-call identity + start time into the context for capture.

        Called at the public entry points; read back at the capture chokepoint
        (`_call_log_to_db`). The explicit `prompt_name` (passed by the call
        site) is what lets the profiler tell apart prompts that share a
        call_type (e.g. the three action-selection prompts).

        ``thinking_budget`` (when set) is read by the Gemini transport to cap
        reasoning tokens; other transports never look at it.
        """
        _llm_call_ctx.set(
            {
                "prompt_name": prompt_name,
                "call_type": call_type,
                "task_id": task_id,
                "thinking_budget": thinking_budget,
                "start": time.perf_counter(),
            }
        )

    # ───────────────────────────  Public helpers  ────────────────────────────

    def _register_failure(
        self,
        *,
        error_info: Optional[LLMErrorInfo],
        raw_error: Optional[Exception] = None,
    ) -> None:
        """Single chokepoint for consecutive-failure bookkeeping.

        Non-transient categories (bad key, out of credits, invalid model,
        blocked content, malformed request — see FAIL_FAST_CATEGORIES) abort
        immediately: retrying the same request with the same error can't
        succeed. Transient categories (rate-limit, server, connection,
        unclassified) keep the existing 5-attempt budget.

        Always raises `LLMConsecutiveFailureError` when the run should abort;
        otherwise returns normally so the caller can continue its own retry
        path.
        """
        category = error_info.category if error_info else ErrorCategory.UNKNOWN
        # Credential-pool bookkeeping (Phase 5, FR-7): rate-limit/billing/
        # auth failures cool the credential that served this call so the
        # next request rotates. No-op for single-key providers.
        try:
            from agent_core.core.models import credentials as _credentials

            _credentials.note_failure(self.provider, category.value)
        except Exception:  # pragma: no cover — pools must never break errors
            pass
        if category in FAIL_FAST_CATEGORIES:
            logger.critical(
                f"[LLM ABORT] Non-transient category={category.value} — failing fast "
                f"instead of retrying."
            )
            raise LLMConsecutiveFailureError(
                1, last_error=raw_error, last_error_info=error_info, is_immediate=True
            )

        self._consecutive_failures += 1
        logger.warning(
            f"[LLM CONSECUTIVE FAILURE] Count: "
            f"{self._consecutive_failures}/{self._max_consecutive_failures} "
            f"(category={category.value})"
        )
        if self._consecutive_failures >= self._max_consecutive_failures:
            raise LLMConsecutiveFailureError(
                self._consecutive_failures,
                last_error=raw_error,
                last_error_info=error_info,
            )

    # ─────────────── Cross-provider fallback (Phase 5, FR-9) ───────────────

    def _fallback_chain(self) -> List[str]:
        """Configured fallback providers, minus the active one, that have a
        usable credential or need none. Empty when unconfigured (default).

        Always empty on fallback instances themselves — only the PRIMARY
        interface walks the chain (one walk per turn, no nesting)."""
        if self._is_fallback_instance:
            return []
        try:
            from app.config import get_api_key, get_fallback_providers

            chain = []
            registry = _get_registry()
            for candidate in get_fallback_providers():
                if candidate == self.provider or candidate in chain:
                    continue
                prof = registry.get(candidate)
                if prof is None:
                    continue
                if prof.requires_api_key and not get_api_key(candidate):
                    logger.debug(
                        f"[FALLBACK] skipping {candidate}: no credential configured"
                    )
                    continue
                chain.append(candidate)
            return chain
        except Exception:
            return []

    def _get_fallback_interface(self, provider: str) -> Optional["LLMInterface"]:
        cached = self._fallback_interfaces.get(provider)
        if cached is not None:
            return cached
        try:
            from app.config import get_api_key, get_base_url

            iface = LLMInterface(
                provider=provider,
                api_key=get_api_key(provider) or None,
                base_url=get_base_url(provider),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                get_token_count=self._get_token_count,
                set_token_count=self._set_token_count,
                report_usage=self._report_usage,
                log_to_db=self._log_to_db,
                record_llm_call=self._record_llm_call,
            )
        except Exception as e:
            logger.warning(f"[FALLBACK] could not build {provider} interface: {e}")
            return None
        iface._is_fallback_instance = True
        self._fallback_interfaces[provider] = iface
        return iface

    def _notify_fallback(self, to_provider: str, reason: str) -> None:
        message = (
            f"Model fallback: {self.provider} -> {to_provider} ({reason}); "
            f"will retry {self.provider} next turn."
        )
        logger.warning(f"[FALLBACK] {message}")
        if self._on_fallback is not None:
            try:
                self._on_fallback(self.provider, to_provider, reason)
            except Exception:  # pragma: no cover — the hook must never break inference
                pass

    def _try_fallback(self, response: Dict[str, Any], attempt) -> Optional[str]:
        """Walk the fallback chain for this turn. ``attempt`` is a callable
        (fallback_iface) -> content-or-raises. Returns served content, or
        None when fallback is off / suppressed / exhausted / blocked.

        Never touches the primary's failure bookkeeping: on success the turn
        is served (caller resets the counter); on None the caller proceeds
        with today's exact failure path (NFR-1).
        """
        if self._suppress_fallback_once:
            self._suppress_fallback_once = False
            return None
        error_info = response.get("error_info_obj")
        category = error_info.category if error_info is not None else None
        if category is ErrorCategory.BLOCKED:
            # The same content would be blocked on any provider.
            return None
        reason = category.value if category is not None else "error"
        for candidate in self._fallback_chain():
            fb = self._get_fallback_interface(candidate)
            if fb is None:
                continue
            # One attempt per candidate per turn: a broken fallback must not
            # burn its own consecutive budget across turns.
            fb.reset_failure_counter()
            try:
                content = attempt(fb)
            except Exception as e:
                logger.warning(f"[FALLBACK] {candidate} also failed: {e}")
                continue
            if content:
                self._notify_fallback(candidate, reason)
                return content
        return None

    def _generate_response_sync(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
        json_mode: bool = True,
    ) -> str:
        """Synchronous implementation shared by sync/async entry points.

        ``json_mode`` declares the caller's expected output format. Callers
        whose prompts instruct JSON keep the default; prose callers
        (summarization, title generation, ...) MUST pass False — forcing a
        provider's JSON mode onto a prompt that never asks for JSON is
        out-of-contract and degenerates on several providers (DeepSeek
        emits whitespace-only output, OpenAI rejects the request).
        """
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
            # Dispatch on the provider profile's wire protocol (Phase 2,
            # docs/PROVIDER_LAYER_CATCHUP.md FR-2). Transports carry the
            # request/response encoding; all session state stays here. The
            # dynamic registry (not the static PROVIDER_CONFIG) is consulted
            # so settings.json custom providers dispatch too (Phase 3).
            _profile_cfg = _get_registry().get(self.provider)
            _transport = (
                _transports.TRANSPORTS.get(_profile_cfg.wire)
                if _profile_cfg is not None
                else None
            )
            if _transport is None:  # pragma: no cover
                raise RuntimeError(f"Unknown provider {self.provider!r}")
            response = _transport(
                self, system_prompt, user_prompt, json_mode=json_mode
            )
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
                    error_detail = _generic_empty_response_detail(
                        self.provider, self.model
                    )
                logger.error(f"[LLM ERROR] {error_detail}")
                # Turn-scoped cross-provider fallback (Phase 5, FR-9): try
                # the configured chain BEFORE any failure bookkeeping. A
                # served fallback turn is a success; an exhausted (or
                # unconfigured) chain falls through to the exact historical
                # failure path below.
                served = self._try_fallback(
                    response,
                    lambda fb: fb._generate_response_sync(
                        system_prompt, user_prompt, log_response=False
                    ),
                )
                if served is not None:
                    self._consecutive_failures = 0
                    return served
                # Registers/raises based on category (fail-fast vs retry
                # budget) — see _register_failure. Attaches the classified
                # info so the agent_base error handler can show the *cause*
                # of the failure(s), not just a retry count. raw_error is
                # passed even when error_info is None (e.g. BytePlus's
                # cache path returning empty content with no exception) so
                # a fatal LLMConsecutiveFailureError still carries *some*
                # detail instead of falling back to a bare, disconnected
                # "Aborted after consecutive failures." — see
                # app/agent_base.py:_classify_react_error.
                self._register_failure(
                    error_info=error_info, raw_error=RuntimeError(error_detail)
                )
                # Use _EmptyResponse so the outer except-Exception block does NOT
                # re-register this same call (double-counting bug).
                raise _EmptyResponse(error_detail)

            # Success - reset consecutive failure counter
            self._consecutive_failures = 0
            try:
                from agent_core.core.models import credentials as _credentials

                _credentials.note_success(self.provider)
            except Exception:
                pass

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
            # Classify on every failure now (not just once the retry budget
            # is exhausted) so non-transient categories can fail fast.
            try:
                info = classify_llm_error(e, provider=self.provider, model=self.model)
            except Exception:
                info = None
            logger.error(f"[LLM ERROR] {e}")
            self._register_failure(error_info=info, raw_error=e)
            raise

    @profile("llm_generate_response", OperationCategory.LLM)
    def generate_response(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
        prompt_name: Optional[str] = None,
        json_mode: bool = True,
    ) -> str:
        """Generate a single response from the configured provider.

        Pass ``json_mode=False`` when the prompt asks for prose — see
        ``_generate_response_sync``.
        """
        self._begin_call(prompt_name=prompt_name)
        return self._generate_response_sync(
            system_prompt, user_prompt, log_response, json_mode=json_mode
        )

    @profile("llm_generate_response_async", OperationCategory.LLM)
    async def generate_response_async(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
        prompt_name: Optional[str] = None,
        json_mode: bool = True,
        thinking_budget: Optional[int] = None,
    ) -> str:
        """Async wrapper that defers the blocking call to a worker thread.

        Pass ``json_mode=False`` when the prompt asks for prose — see
        ``_generate_response_sync``.

        ``thinking_budget`` caps reasoning tokens on providers that expose a
        thinking budget (Gemini). It rides the per-call context and is a no-op
        for every other provider; leave it None (the default) for normal calls.
        """
        # Stamp the context here, in the caller's context, so asyncio.to_thread
        # copies it into the worker thread where the capture runs.
        self._begin_call(prompt_name=prompt_name, thinking_budget=thinking_budget)
        return await asyncio.to_thread(
            self._generate_response_sync,
            system_prompt,
            user_prompt,
            log_response,
            json_mode,
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
                self.provider in _session_cc_providers()
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
        # Fixed history budget (~240k chars ≈ 60k tokens), leaving room for the
        # system prompt, newest turn, and response. Provider-independent by
        # design: we keep no per-model context-window table (no hardcoded model
        # list), so a single conservative constant governs trimming for every
        # provider. A power user can raise it via model.context_window_override.
        max_history_chars = 240_000
        try:
            from app.config import get_settings

            override = get_settings().get("model", {}).get("context_window_override")
            if override:
                max_history_chars = max(240_000, int(override) * 4)
        except Exception:
            pass

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
        response is treated as a failure and routed through
        `_register_failure` (fail-fast for non-transient categories, retry
        budget otherwise). On success the counter resets and the cleaned
        content is returned.
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
                error_detail = _generic_empty_response_detail(self.provider, self.model)
            logger.error(f"[LLM ERROR] {error_detail}")
            # Session-path fallback (Phase 5): retry the SAME session turn
            # on a fallback provider. The fallback interface keeps its own
            # session buffers, so its history accumulates independently and
            # the primary's buffers stay warm for the next-turn retry.
            if self._current_session_call is not None:
                task_id, call_type, fb_user_prompt = self._current_session_call
                stored_system = self._session_system_prompts.get(
                    f"{task_id}:{call_type}"
                )

                def _session_attempt(fb, _t=task_id, _c=call_type):
                    fb.create_session_cache(_t, _c, stored_system or "")
                    return fb._generate_response_with_session_sync(
                        _t, _c, fb_user_prompt, log_response=False
                    )

                served = self._try_fallback(response, _session_attempt)
                if served is not None:
                    self._consecutive_failures = 0
                    return served
            # See _generate_response_sync's equivalent call for why
            # raw_error is always passed, even when error_info is None.
            self._register_failure(
                error_info=error_info, raw_error=RuntimeError(error_detail)
            )
            raise RuntimeError(error_detail)

        # Success - reset consecutive failure counter
        self._consecutive_failures = 0
        try:
            from agent_core.core.models import credentials as _credentials

            _credentials.note_success(self.provider)
        except Exception:
            pass
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

        # Stash the in-flight session call so _finalize_session_response can
        # retry this same turn on a fallback provider (Phase 5, FR-9).
        self._current_session_call = (task_id, call_type, user_prompt)

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

        # Handle OpenAI/DeepSeek/Grok/OpenRouter with call_type-based cache routing.
        # Membership is derived from the profiles (wire == chat_completions AND
        # session_accumulation) — see registry.session_cc_providers().
        if self.provider in _session_cc_providers():
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
        """Delegate to the byteplus_responses transport (Phase 2)."""
        return _transports.byteplus_responses.generate_with_session(
            self, task_id, call_type, user_prompt
        )

    # ──────────── Provider-specific delegates (bodies live in transports/) ────────────
    def _generate_openai(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        messages_override: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = True,
    ) -> Dict[str, Any]:
        """Delegate to the chat_completions transport (Phase 2)."""
        return _transports.chat_completions.generate_openai(
            self,
            system_prompt,
            user_prompt,
            call_type=call_type,
            messages_override=messages_override,
            json_mode=json_mode,
        )

    @profile("llm_ollama_call", OperationCategory.LLM)
    def _generate_ollama(
        self, system_prompt: str | None, user_prompt: str, json_mode: bool = True
    ) -> Dict[str, Any]:
        """Delegate to the chat_completions transport's Ollama path (Phase 2)."""
        return _transports.chat_completions.generate_ollama(
            self, system_prompt, user_prompt, json_mode=json_mode
        )

    @profile("llm_gemini_call", OperationCategory.LLM)
    def _generate_gemini(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        contents_override: Optional[List[Dict[str, Any]]] = None,
        json_mode: bool = True,
    ) -> Dict[str, Any]:
        """Delegate to the gemini_native transport (Phase 2)."""
        return _transports.gemini_native.generate(
            self,
            system_prompt,
            user_prompt,
            call_type=call_type,
            contents_override=contents_override,
            json_mode=json_mode,
        )

    @profile("llm_byteplus_call", OperationCategory.LLM)
    def _generate_byteplus(
        self, system_prompt: str | None, user_prompt: str
    ) -> Dict[str, Any]:
        """Delegate to the byteplus_responses transport (Phase 2)."""
        return _transports.byteplus_responses.generate(
            self, system_prompt, user_prompt
        )

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

    def _generate_anthropic(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        messages: Optional[List[dict]] = None,
    ) -> Dict[str, Any]:
        """Delegate to the anthropic_messages transport (Phase 2)."""
        return _transports.anthropic_messages.generate(
            self,
            system_prompt,
            user_prompt,
            call_type=call_type,
            messages=messages,
        )

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

    def _generate_bedrock(
        self,
        system_prompt: str | None,
        user_prompt: str,
        call_type: Optional[str] = None,
        messages: Optional[List[dict]] = None,
    ) -> Dict[str, Any]:
        """Delegate to the bedrock_converse transport (Phase 2)."""
        return _transports.bedrock_converse.generate(
            self,
            system_prompt,
            user_prompt,
            call_type=call_type,
            messages=messages,
        )

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
            response = self.generate_response(user_prompt=user_prompt, json_mode=False)
            logger.debug(f"AI Response:\n{response}\n")
