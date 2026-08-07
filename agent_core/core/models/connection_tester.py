# -*- coding: utf-8 -*-
"""Connection tester for validating provider API keys and model ids.

When `model` is provided, each tester attempts a tiny chat-completion (or
equivalent) against that exact model — so a typo in the model id is caught
at test time, not at first real call. When `model` is omitted we fall back
to a known-good default model from connection_test_models.json.

On failure we run the underlying exception through `classify_llm_error` so
the test result message reads exactly like a real LLM error in the chat.
"""

from typing import Dict, Any, Optional
import httpx

from agent_core.core.models.provider_config import PROVIDER_CONFIG


def test_provider_connection(
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 15.0,
    model: Optional[str] = None,
    aws_credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Test if a provider's API key (and optionally model id) is valid.

    Args:
        provider: The LLM provider name.
        api_key: The API key to test.
        base_url: Optional base URL override.
        timeout: Request timeout in seconds.
        model: When provided, the tester verifies this exact model is
            reachable. Catches typos in the model id (e.g.
            "claude-sonnet-4-5-2025092945" vs the real
            "claude-sonnet-4-5-20250929") that would otherwise pass an
            auth-only test and only fail at first real call.

    Returns:
        Dictionary with success/message/provider/error.
    """
    if provider not in PROVIDER_CONFIG:
        return {
            "success": False,
            "message": f"Unknown provider: {provider}",
            "provider": provider,
            "error": f"Supported providers: {', '.join(PROVIDER_CONFIG.keys())}",
        }

    cfg = PROVIDER_CONFIG[provider]

    try:
        if provider == "openai":
            return _test_openai(api_key, timeout, model)
        elif provider == "anthropic":
            return _test_anthropic(api_key, timeout, model)
        elif provider == "gemini":
            return _test_gemini(api_key, timeout, model)
        elif provider == "byteplus":
            url = base_url or cfg.default_base_url
            return _test_byteplus(api_key, url, timeout, model)
        elif provider == "remote":
            url = base_url or cfg.default_base_url
            return _test_remote(url, timeout)
        elif provider == "grok":
            url = cfg.default_base_url
            return _test_grok(api_key, url, timeout, model)
        elif provider == "openrouter":
            url = base_url or cfg.default_base_url
            return _test_openrouter(api_key, url, timeout, model)
        elif provider == "deepseek":
            url = cfg.default_base_url
            return _test_openai_compat(provider, api_key, url, timeout, model)
        elif provider == "glm":
            url = cfg.default_base_url
            return _test_openai_compat(provider, api_key, url, timeout, model)
        elif provider == "fugu":
            url = cfg.default_base_url
            return _test_openai_compat(provider, api_key, url, timeout, model)
        elif provider in ("moonshot", "minimax"):
            return _test_moonshot_minimax(
                provider, api_key, cfg.default_base_url, timeout, model
            )
        elif provider == "bedrock":
            # `base_url` carries the AWS region through the existing factory
            # plumbing. `aws_credentials` (if provided) override what's in
            # settings.json — used when the user is testing new creds before
            # save. Otherwise the tester reads via app.config so the boto3
            # credential chain is respected on EC2/ECS hosts.
            return _test_bedrock(
                region=base_url,
                model=model,
                timeout=timeout,
                aws_credentials=aws_credentials,
            )
        else:
            return {
                "success": False,
                "message": f"Connection test not implemented for {provider}",
                "provider": provider,
                "error": "Not implemented",
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Connection test failed: {str(e)}",
            "provider": provider,
            "error": str(e),
        }


# ─── OpenRouter proxy helpers (Moonshot / MiniMax) ────────────────────

_OR_MODEL_MAP: dict = {
    "moonshot": {
        "kimi-k2.5": "moonshotai/kimi-k2.5",
        "moonshot-v1-8k": "moonshotai/moonshot-v1-8k",
        "moonshot-v1-32k": "moonshotai/moonshot-v1-32k",
        "moonshot-v1-128k": "moonshotai/moonshot-v1-128k",
        "moonshot-v1-8k-vision-preview": "moonshotai/moonshot-v1-8k-vision-preview",
    },
    "minimax": {
        "MiniMax-Text-01": "minimax/minimax-01",
        "MiniMax-VL-01": "minimax/minimax-01",
        "abab6.5s-chat": "minimax/abab6.5s-chat",
    },
}

_OR_NAMESPACE = {"moonshot": "moonshotai", "minimax": "minimax"}
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _to_openrouter_slug_for_test(provider: str, model: str) -> str:
    if "/" in model:
        return model
    explicit = _OR_MODEL_MAP.get(provider, {}).get(model)
    if explicit:
        return explicit
    return f"{_OR_NAMESPACE.get(provider, provider)}/{model}"


def _get_openrouter_fallback_for_test() -> tuple:
    """Return (or_api_key, or_base_url) if OpenRouter is configured, else (None, None)."""
    try:
        from app.config import get_api_key

        or_key = get_api_key("openrouter") or None
        return (or_key, _OPENROUTER_BASE_URL) if or_key else (None, None)
    except Exception:
        return (None, None)


def _test_moonshot_minimax(
    provider: str,
    api_key: Optional[str],
    direct_url: str,
    timeout: float,
    model: Optional[str],
) -> Dict[str, Any]:
    """Test Moonshot or MiniMax.

    Two distinct modes:
    - Direct key provided: test only the provider's own endpoint. No silent
      OR fallback — if it fails the caller gets the real error and can decide
      whether to switch to OpenRouter.
    - No key: try OpenRouter if configured (factory runtime-fallback path).
    """
    display = _DISPLAY.get(provider, provider)

    if api_key:
        # Test the direct endpoint only.  Returning OR-fallback success here
        # would be misleading because the factory uses the direct key at runtime.
        return _test_openai_compat(provider, api_key, direct_url, timeout, model)

    # No direct key — check whether OpenRouter is configured as a fallback.
    or_key, or_url = _get_openrouter_fallback_for_test()
    if or_key:
        or_model = _to_openrouter_slug_for_test(provider, model or "")
        or_result = _test_openrouter(or_key, or_url, timeout, or_model)
        if or_result.get("success"):
            or_result["message"] += f" (routing {display} via OpenRouter)"
        return or_result

    return {
        "success": False,
        "message": f"API key is required for {display}, or configure OpenRouter as a fallback.",
        "provider": provider,
        "error": "No API key and OpenRouter is not configured.",
    }


# ─── Helpers ──────────────────────────────────────────────────────────


def _classified_error_result(
    exc: Exception, provider: str, model: Optional[str]
) -> Dict[str, Any]:
    """Run an exception through the classifier and return a failure result
    with the rich message — same format the chat sees for real LLM errors."""
    try:
        from agent_core.core.impl.llm.errors import classify_llm_error

        info = classify_llm_error(exc, provider=provider, model=model)
        return {
            "success": False,
            "message": info.message,
            "provider": provider,
            "error": info.message,
        }
    except Exception:  # pragma: no cover — classifier must never break test
        return {
            "success": False,
            "message": str(exc),
            "provider": provider,
            "error": str(exc),
        }


def _resolve_test_model(provider: str, model: Optional[str], fallback: str) -> str:
    """Use the user's model when provided; otherwise pull the default test
    model from connection_test_models.json (auth-only validation)."""
    if model:
        return model
    try:
        from app.config import get_connection_test_model

        configured = get_connection_test_model(provider)
        if configured:
            return configured
    except Exception:
        pass
    return fallback


def _success(provider: str, model: Optional[str]) -> Dict[str, Any]:
    detail = f" with model {model}" if model else ""
    return {
        "success": True,
        "message": f"Successfully connected to {_DISPLAY.get(provider, provider)} API{detail}.",
        "provider": provider,
    }


_DISPLAY = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "byteplus": "BytePlus",
    "deepseek": "DeepSeek",
    "moonshot": "Moonshot",
    "minimax": "MiniMax",
    "grok": "Grok (xAI)",
    "glm": "Z.ai (GLM)",
    "fugu": "Sakana (Fugu)",
    "openrouter": "OpenRouter",
    "remote": "Ollama",
    "bedrock": "AWS Bedrock",
}


# ─── OpenAI / OpenAI-compat ───────────────────────────────────────────


def _openai_compat_chat_test(
    *,
    provider: str,
    api_key: Optional[str],
    base_url: Optional[str],
    model: str,
    timeout: float,
) -> Dict[str, Any]:
    """Hit /chat/completions with the user's model. The response tells us:
        200/400/422 → key + model OK
        401         → bad key
        404         → bad model
        402         → no credits (key valid)
        429         → rate limited (key valid)
    For all failure shapes, we surface the classifier's rich message.
    """
    if not api_key:
        return {
            "success": False,
            "message": f"API key is required for {_DISPLAY.get(provider, provider)}",
            "provider": provider,
            "error": "Missing API key",
        }
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout,
            max_retries=0,
        )
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        return _success(provider, model)
    except Exception as exc:
        # 422 BadRequest with a "messages" issue still means auth+model worked.
        # Classify, and if it's a BAD_REQUEST not about the model, treat as success.
        from agent_core.core.impl.llm.errors import classify_llm_error, ErrorCategory

        try:
            info = classify_llm_error(exc, provider=provider, model=model)
            if info.category in (
                ErrorCategory.AUTH,
                ErrorCategory.MODEL,
                ErrorCategory.CREDIT,
            ):
                return {
                    "success": False,
                    "message": info.message,
                    "provider": provider,
                    "error": info.message,
                }
            # RATE_LIMIT, SERVER, BAD_REQUEST, etc. — auth+model are likely fine.
            return _success(provider, model)
        except Exception:
            return _classified_error_result(exc, provider, model)


def _test_openai(
    api_key: Optional[str], timeout: float, model: Optional[str]
) -> Dict[str, Any]:
    if model:
        return _openai_compat_chat_test(
            provider="openai",
            api_key=api_key,
            base_url=None,
            model=model,
            timeout=timeout,
        )
    # No model specified → just verify the key with /models list (cheaper).
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for OpenAI",
            "provider": "openai",
            "error": "Missing API key",
        }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code == 200:
            return _success("openai", None)
        response.raise_for_status()
        return {
            "success": False,
            "message": f"API returned status {response.status_code}",
            "provider": "openai",
            "error": response.text[:300],
        }
    except Exception as exc:
        return _classified_error_result(exc, "openai", None)


def _test_openai_compat(
    provider: str,
    api_key: Optional[str],
    base_url: str,
    timeout: float,
    model: Optional[str],
) -> Dict[str, Any]:
    if model:
        return _openai_compat_chat_test(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
    # No model → /models list (auth-only).
    display = _DISPLAY.get(provider, provider)
    if not api_key:
        return {
            "success": False,
            "message": f"API key is required for {display}",
            "provider": provider,
            "error": "Missing API key",
        }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code == 200:
            return _success(provider, None)
        response.raise_for_status()
        return {
            "success": False,
            "message": f"API returned status {response.status_code}",
            "provider": provider,
            "error": response.text[:300],
        }
    except Exception as exc:
        return _classified_error_result(exc, provider, None)


# ─── Anthropic ────────────────────────────────────────────────────────


def _test_anthropic(
    api_key: Optional[str], timeout: float, model: Optional[str]
) -> Dict[str, Any]:
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for Anthropic",
            "provider": "anthropic",
            "error": "Missing API key",
        }

    test_model = _resolve_test_model(
        "anthropic", model, fallback="claude-haiku-4-5-20251001"
    )

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
        client.messages.create(
            model=test_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return _success("anthropic", model)
    except Exception as exc:
        from agent_core.core.impl.llm.errors import classify_llm_error, ErrorCategory

        try:
            info = classify_llm_error(exc, provider="anthropic", model=test_model)
            # Auth, missing model, or credit issues are real failures.
            # 400 BadRequest about the prompt itself is fine (auth+model OK).
            if info.category in (
                ErrorCategory.AUTH,
                ErrorCategory.MODEL,
                ErrorCategory.CREDIT,
            ):
                return {
                    "success": False,
                    "message": info.message,
                    "provider": "anthropic",
                    "error": info.message,
                }
            return _success("anthropic", model)
        except Exception:
            return _classified_error_result(exc, "anthropic", model)


# ─── Gemini ────────────────────────────────────────────────────────────


def _test_gemini(
    api_key: Optional[str], timeout: float, model: Optional[str]
) -> Dict[str, Any]:
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for Gemini",
            "provider": "gemini",
            "error": "Missing API key",
        }
    if model:
        # Verify the specific model via models/{name}.
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}?key={api_key}"
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(url)
            if response.status_code == 200:
                return _success("gemini", model)
            response.raise_for_status()
            return {
                "success": False,
                "message": f"API returned status {response.status_code}",
                "provider": "gemini",
                "error": response.text[:300],
            }
        except Exception as exc:
            return _classified_error_result(exc, "gemini", model)
    # No model → list endpoint (auth-only).
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
            )
        if response.status_code == 200:
            return _success("gemini", None)
        response.raise_for_status()
        return {
            "success": False,
            "message": f"API returned status {response.status_code}",
            "provider": "gemini",
            "error": response.text[:300],
        }
    except Exception as exc:
        return _classified_error_result(exc, "gemini", None)


# ─── BytePlus ─────────────────────────────────────────────────────────


def _test_byteplus(
    api_key: Optional[str],
    base_url: Optional[str],
    timeout: float,
    model: Optional[str],
) -> Dict[str, Any]:
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for BytePlus",
            "provider": "byteplus",
            "error": "Missing API key",
        }
    url = base_url or "https://ark.ap-southeast.bytepluses.com/api/v3"
    if model:
        # Verify via tiny chat completion.
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                )
            if response.status_code in (200, 400, 422):
                # 200 = both OK. 400/422 = auth+model OK, request quirk only.
                return _success("byteplus", model)
            response.raise_for_status()
            return {
                "success": False,
                "message": f"API returned status {response.status_code}",
                "provider": "byteplus",
                "error": response.text[:300],
            }
        except Exception as exc:
            return _classified_error_result(exc, "byteplus", model)
    # No model → /models list.
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                f"{url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code == 200:
            return _success("byteplus", None)
        response.raise_for_status()
        return {
            "success": False,
            "message": f"API returned status {response.status_code}",
            "provider": "byteplus",
            "error": response.text[:300],
        }
    except Exception as exc:
        return _classified_error_result(exc, "byteplus", None)


# ─── Remote (Ollama) ──────────────────────────────────────────────────


def _test_remote(base_url: Optional[str], timeout: float) -> Dict[str, Any]:
    """No API key required; the UI already validates Ollama models via
    the /api/tags dropdown, so this stays auth-equivalent."""
    url = base_url or "http://localhost:11434"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{url.rstrip('/')}/api/tags")
        if response.status_code == 200:
            models = [m["name"] for m in response.json().get("models", [])]
            if models:
                message = (
                    f"Connected! {len(models)} model(s) available: {', '.join(models)}"
                )
            else:
                message = "Connected to Ollama, but no models downloaded yet. Use '+ Download New Model' to get one."
            return {
                "success": True,
                "message": message,
                "provider": "remote",
                "models": models,
            }
        return {
            "success": False,
            "message": f"Ollama returned status {response.status_code}",
            "provider": "remote",
            "error": response.text[:200] if response.text else "Unknown error",
        }
    except Exception as exc:
        return _classified_error_result(exc, "remote", None)


# ─── OpenRouter ───────────────────────────────────────────────────────


def _test_openrouter(
    api_key: Optional[str],
    base_url: str,
    timeout: float,
    model: Optional[str],
) -> Dict[str, Any]:
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for OpenRouter",
            "provider": "openrouter",
            "error": "Missing API key",
        }
    if model:
        # Verify auth + model + credits via tiny chat completion. OR returns
        # 401 (bad key), 402 (no credits), 404 (bad model slug), or 200/4xx
        # depending on upstream. Classifier handles them all.
        return _openai_compat_chat_test(
            provider="openrouter",
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
        )
    # No model → /auth/key (auth + balance only).
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                f"{base_url.rstrip('/')}/auth/key",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code == 200:
            data = response.json().get("data", {}) or {}
            limit = data.get("limit")
            usage = data.get("usage")
            label = data.get("label") or "OpenRouter key"
            if limit is None:
                msg = f"Connected to OpenRouter ({label}) — unlimited credits"
            else:
                remaining = max(0.0, float(limit) - float(usage or 0.0))
                msg = (
                    f"Connected to OpenRouter ({label}) — "
                    f"${remaining:.2f} of ${float(limit):.2f} remaining"
                )
            return {"success": True, "message": msg, "provider": "openrouter"}
        if response.status_code in (401, 403):
            return {
                "success": False,
                "message": "Invalid API key",
                "provider": "openrouter",
                "error": "Authentication failed - check your OpenRouter API key",
            }
        return {
            "success": False,
            "message": f"API returned status {response.status_code}",
            "provider": "openrouter",
            "error": response.text[:300],
        }
    except Exception as exc:
        return _classified_error_result(exc, "openrouter", None)


# ─── Grok ─────────────────────────────────────────────────────────────


def _test_grok(
    api_key: Optional[str],
    base_url: str,
    timeout: float,
    model: Optional[str],
) -> Dict[str, Any]:
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for Grok (xAI)",
            "provider": "grok",
            "error": "Missing API key",
        }
    test_model = _resolve_test_model("grok", model, fallback="grok-3")
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": test_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        if response.status_code == 200:
            return _success("grok", model)
        if response.status_code in (400, 422) and model is None:
            # Hardcoded test model probably hit a tier restriction; auth still
            # OK — but xAI returns 400 (not 401) for rejected bearers too
            # ({"code":"invalid-argument","error":"Incorrect API key
            # provided..."}), so only call it a success when the body isn't
            # complaining about credentials.
            lower = response.text.lower()
            if not (
                "api key" in lower or "api_key" in lower or "access token" in lower
            ):
                return _success("grok", None)
        response.raise_for_status()
        return {
            "success": False,
            "message": f"API returned status {response.status_code}",
            "provider": "grok",
            "error": response.text[:300],
        }
    except Exception as exc:
        return _classified_error_result(exc, "grok", model)


# ─── Bedrock ──────────────────────────────────────────────────────────


def _test_bedrock(
    region: Optional[str],
    model: Optional[str],
    timeout: float,
    aws_credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Verify the Bedrock credential chain and (optionally) a specific model.

    Bedrock has no shared "API key"; we exercise the boto3 credential chain
    (settings.json → env → IAM role / SSO profile) by calling the public
    `list_foundation_models` endpoint. When `model` is supplied we also do a
    1-token `converse` call against the model so a typo in the model ID is
    caught at test time rather than at first real call.
    """
    try:
        import boto3  # type: ignore
        from botocore.config import Config  # type: ignore
    except ImportError:
        return {
            "success": False,
            "message": "boto3 is not installed. Run `pip install boto3`.",
            "provider": "bedrock",
            "error": "boto3 missing",
        }

    test_model = _resolve_test_model(
        "bedrock", model, fallback="us.anthropic.claude-haiku-4-5-20251001-v1:0"
    )

    # Caller-supplied creds (from the settings form, pre-save) win over what's
    # in settings.json. Otherwise fall through app.config which reads settings →
    # env → IAM role / SSO via the default boto3 chain.
    aws_region = region
    access_key = secret_key = session_token = None
    if aws_credentials:
        access_key = aws_credentials.get("access_key_id") or None
        secret_key = aws_credentials.get("secret_access_key") or None
        session_token = aws_credentials.get("session_token") or None
        aws_region = aws_credentials.get("region") or aws_region
    if not (access_key and secret_key):
        try:
            from app.config import get_aws_credentials

            creds = get_aws_credentials()
            access_key = access_key or (creds.get("access_key_id") or None)
            secret_key = secret_key or (creds.get("secret_access_key") or None)
            session_token = session_token or (creds.get("session_token") or None)
            aws_region = aws_region or creds.get("region") or "us-east-1"
        except Exception:
            aws_region = aws_region or "us-east-1"
    else:
        aws_region = aws_region or "us-east-1"

    try:
        cfg = Config(
            retries={"max_attempts": 1, "mode": "standard"},
            connect_timeout=timeout,
            read_timeout=timeout,
        )
        client_kwargs = {"region_name": aws_region, "config": cfg}
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
            if session_token:
                client_kwargs["aws_session_token"] = session_token

        if model:
            # Use bedrock-runtime + Converse for a real round-trip against the
            # model. If it returns OK we know auth + model + region all work.
            rt = boto3.client("bedrock-runtime", **client_kwargs)
            rt.converse(
                modelId=test_model,
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                inferenceConfig={"maxTokens": 1, "temperature": 0.0},
            )
            return _success("bedrock", model)

        # No model → just verify creds via `list_foundation_models` on the
        # bedrock control-plane client.
        cp = boto3.client("bedrock", **client_kwargs)
        cp.list_foundation_models()
        return _success("bedrock", None)
    except Exception as exc:
        # Use the classifier so the chat sees the same rich error as a real
        # call. Bedrock errors surface as botocore ClientError; the classifier
        # falls back to UNKNOWN with the raw message preserved, which is still
        # informative.
        return _classified_error_result(exc, "bedrock", model)
