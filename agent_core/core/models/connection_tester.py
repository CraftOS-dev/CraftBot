# -*- coding: utf-8 -*-
"""Connection tester for validating provider API keys."""

from typing import Dict, Any, Optional
import httpx

from agent_core.core.models.provider_config import PROVIDER_CONFIG


def test_provider_connection(
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Test if a provider's API key is valid by making a minimal API call.

    Args:
        provider: The LLM provider name (openai, gemini, anthropic, byteplus, remote)
        api_key: The API key to test. If None, will check if connection is possible.
        base_url: Optional base URL override (for byteplus/remote providers)
        timeout: Request timeout in seconds

    Returns:
        Dictionary with:
        - success: bool indicating if connection succeeded
        - message: str with success/failure message
        - provider: str provider name
        - error: Optional[str] error details if failed
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
            return _test_openai(api_key, timeout)
        elif provider == "anthropic":
            return _test_anthropic(api_key, timeout)
        elif provider == "gemini":
            return _test_gemini(api_key, timeout)
        elif provider == "byteplus":
            url = base_url or cfg.default_base_url
            return _test_byteplus(api_key, url, timeout)
        elif provider == "remote":
            url = base_url or cfg.default_base_url
            return _test_remote(url, timeout)
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


def _test_openai(api_key: Optional[str], timeout: float) -> Dict[str, Any]:
    """Test OpenAI API connection."""
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for OpenAI",
            "provider": "openai",
            "error": "Missing API key",
        }

    try:
        # Use models endpoint - lightweight call to verify API key
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )

        if response.status_code == 200:
            return {
                "success": True,
                "message": "Successfully connected to OpenAI API",
                "provider": "openai",
            }
        elif response.status_code == 401:
            return {
                "success": False,
                "message": "Invalid API key",
                "provider": "openai",
                "error": "Authentication failed - check your API key",
            }
        else:
            return {
                "success": False,
                "message": f"API returned status {response.status_code}",
                "provider": "openai",
                "error": response.text[:200] if response.text else "Unknown error",
            }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Connection timed out",
            "provider": "openai",
            "error": "Request timed out - check your network connection",
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "message": "Network error",
            "provider": "openai",
            "error": str(e),
        }


def _test_anthropic(api_key: Optional[str], timeout: float) -> Dict[str, Any]:
    """Test Anthropic API connection."""
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for Anthropic",
            "provider": "anthropic",
            "error": "Missing API key",
        }

    try:
        # Use a minimal messages request to verify API key
        # We send an invalid request that will fail fast but verify auth
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )

        # 200 means success (actual completion - shouldn't happen with max_tokens=1 but possible)
        # 400 with specific error also indicates valid auth
        if response.status_code == 200:
            return {
                "success": True,
                "message": "Successfully connected to Anthropic API",
                "provider": "anthropic",
            }
        elif response.status_code == 401:
            return {
                "success": False,
                "message": "Invalid API key",
                "provider": "anthropic",
                "error": "Authentication failed - check your API key",
            }
        elif response.status_code == 400:
            # Bad request but auth succeeded
            return {
                "success": True,
                "message": "Successfully connected to Anthropic API",
                "provider": "anthropic",
            }
        elif response.status_code == 529:
            # Overloaded but auth succeeded
            return {
                "success": True,
                "message": "Connected to Anthropic API (service currently overloaded)",
                "provider": "anthropic",
            }
        else:
            return {
                "success": False,
                "message": f"API returned status {response.status_code}",
                "provider": "anthropic",
                "error": response.text[:200] if response.text else "Unknown error",
            }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Connection timed out",
            "provider": "anthropic",
            "error": "Request timed out - check your network connection",
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "message": "Network error",
            "provider": "anthropic",
            "error": str(e),
        }


def _test_gemini(api_key: Optional[str], timeout: float) -> Dict[str, Any]:
    """Test Google Gemini API connection."""
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for Gemini",
            "provider": "gemini",
            "error": "Missing API key",
        }

    try:
        # Use models list endpoint to verify API key
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
            )

        if response.status_code == 200:
            return {
                "success": True,
                "message": "Successfully connected to Google Gemini API",
                "provider": "gemini",
            }
        elif response.status_code == 400 or response.status_code == 403:
            return {
                "success": False,
                "message": "Invalid API key",
                "provider": "gemini",
                "error": "Authentication failed - check your API key",
            }
        else:
            return {
                "success": False,
                "message": f"API returned status {response.status_code}",
                "provider": "gemini",
                "error": response.text[:200] if response.text else "Unknown error",
            }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Connection timed out",
            "provider": "gemini",
            "error": "Request timed out - check your network connection",
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "message": "Network error",
            "provider": "gemini",
            "error": str(e),
        }


def _test_byteplus(
    api_key: Optional[str], base_url: Optional[str], timeout: float
) -> Dict[str, Any]:
    """Test BytePlus API connection."""
    if not api_key:
        return {
            "success": False,
            "message": "API key is required for BytePlus",
            "provider": "byteplus",
            "error": "Missing API key",
        }

    url = base_url or "https://ark.ap-southeast.bytepluses.com/api/v3"

    try:
        # BytePlus uses OpenAI-compatible API, test with models endpoint
        with httpx.Client(timeout=timeout) as client:
            response = client.get(
                f"{url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )

        if response.status_code == 200:
            return {
                "success": True,
                "message": "Successfully connected to BytePlus API",
                "provider": "byteplus",
            }
        elif response.status_code == 401:
            return {
                "success": False,
                "message": "Invalid API key",
                "provider": "byteplus",
                "error": "Authentication failed - check your API key",
            }
        else:
            return {
                "success": False,
                "message": f"API returned status {response.status_code}",
                "provider": "byteplus",
                "error": response.text[:200] if response.text else "Unknown error",
            }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Connection timed out",
            "provider": "byteplus",
            "error": "Request timed out - check your network connection",
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "message": "Network error",
            "provider": "byteplus",
            "error": str(e),
        }


def _test_remote(base_url: Optional[str], timeout: float) -> Dict[str, Any]:
    """Test remote/Ollama connection (no API key required)."""
    url = base_url or "http://localhost:11434"

    try:
        # Ollama uses /api/tags to list models
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{url.rstrip('/')}/api/tags")

        if response.status_code == 200:
            return {
                "success": True,
                "message": "Successfully connected to Ollama",
                "provider": "remote",
            }
        else:
            return {
                "success": False,
                "message": f"Ollama returned status {response.status_code}",
                "provider": "remote",
                "error": response.text[:200] if response.text else "Unknown error",
            }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Connection timed out",
            "provider": "remote",
            "error": f"Could not connect to Ollama at {url}. Is it running?",
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "message": "Network error",
            "provider": "remote",
            "error": f"Could not connect to {url}: {str(e)}",
        }
