# -*- coding: utf-8 -*-
"""Chat Completions → Codex Responses API translator for ChatGPT subscription.

The ChatGPT subscription backend at ``chatgpt.com/backend-api/codex`` is
*not* a normal Responses API endpoint — it's the Codex CLI's transport,
and it's significantly stricter about what it'll accept. CraftBot's LLM
interface is written against Chat Completions. Rather than fork the
interface for one auth mode, this thin wrapper exposes a
``.chat.completions.create(**kwargs)`` surface that translates each call
to ``client.responses.create(**translated)`` and re-shapes the response
back into a ChatCompletion-compatible dataclass.

The constraint set was extracted from numman-ali/opencode-openai-codex-auth
(the canonical reference implementation). Required (force-set every call):

- ``store: false``      ("Store must be set to false")
- ``stream: true``      ("Stream must be set to true"); aggregated below
- ``reasoning.effort: <model-appropriate>`` ("none" for non-codex 5.1/5.2,
  "low" for codex variants — "minimal" is rejected by the backend)
- ``reasoning.summary: "auto"``
- ``include: ["reasoning.encrypted_content"]``
  (mandatory under ``store=false`` so the model can keep its own
  reasoning context across turns)
- ``instructions: <system-prompt text>``  (extracted from messages[role=system])

Silently DROPPED on the way out (Codex rejects with 400 ``Unsupported
parameter`` or just ignores):

- ``temperature``, ``top_p``, ``seed``, ``metadata``, ``user``
- ``max_tokens`` / ``max_completion_tokens`` / ``max_output_tokens``
- ``response_format`` / ``text.format`` — JSON-mode is enforced by the
  system prompt instead (CraftBot's system prompts already require JSON)
- ``previous_response_id`` — incompatible with ``store=false``

FORWARDED for cache routing (Codex-specific — the whole reason prefix
caching works under ``store=false``):

- ``prompt_cache_key`` — sourced from the caller's ``extra_body`` when
  present, or a stable per-client UUID as fallback. Codex-rs uses
  ``thread_id`` here; CraftBot's LLM interface uses
  ``<call_type>_<sha256(system_prompt)>``. Any stable string works;
  rotating it per turn breaks caching (known anti-pattern).

Response shape: the SDK ``Response`` object's ``output_text`` is exposed
as ``choices[0].message.content``; usage fields are re-mapped onto the
Chat-Completions field names. Both ``response.completed`` and
``response.done`` events are watched for the terminal payload — some
streams emit only one or the other.

What is NOT bridged yet:
- Caller-side streaming (``stream=True`` from the caller) — we stream
  internally, but returning chunks to the caller would need a streaming
  shim of the Chat-Completions chunk shape.
- Tool calls (``tools=[...]``) — the Responses API exposes them inside
  ``output`` items, not on ``choices[0].message.tool_calls``.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Tuple


logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
# ChatCompletion-shaped response dataclasses
#
# Built with plain attributes (not pydantic) because the interface code
# only reads a small fixed set of attributes via dot-access — and matching
# the SDK's BaseModel surface for a translator-only path adds dependency
# pain without paying for itself.
# ════════════════════════════════════════════════════════════════════════


class _PromptTokensDetails:
    __slots__ = ("cached_tokens",)

    def __init__(self, cached_tokens: int = 0):
        self.cached_tokens = cached_tokens


class _Usage:
    __slots__ = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_tokens_details",
    )

    def __init__(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.prompt_tokens_details = _PromptTokensDetails(cached_tokens=cached_tokens)


class _Message:
    __slots__ = ("role", "content", "tool_calls")

    def __init__(self, role: str = "assistant", content: str = "", tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    __slots__ = ("index", "message", "finish_reason")

    def __init__(self, message: _Message, finish_reason: str = "stop"):
        self.index = 0
        self.message = message
        self.finish_reason = finish_reason


class _ChatCompletionShim:
    __slots__ = ("id", "choices", "usage", "model")

    def __init__(
        self,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int,
        model: str,
        response_id: str,
        finish_reason: str = "stop",
    ):
        self.id = response_id
        self.model = model
        self.choices = [_Choice(_Message(content=content), finish_reason=finish_reason)]
        self.usage = _Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )


# ════════════════════════════════════════════════════════════════════════
# Translator
# ════════════════════════════════════════════════════════════════════════


# Fields the Codex backend is confirmed to accept. Codex is significantly
# more restrictive than ``api.openai.com``'s Responses API: any field not
# on this list tends to come back as
# ``400 {"detail": "Unsupported parameter: <name>"}``. Start narrow; widen
# only when a field is verified to work in production.
#
# Anything passed by the caller and NOT on this list is dropped on the
# floor by the translator — we don't surface it as an error because the
# Chat-Completions surface is what CraftBot's interface code knows, and
# silently honoring "best-effort" semantics is fine for fields that just
# don't apply at this backend (e.g. ``max_tokens`` becomes "let the
# server decide" rather than a hard failure).
def _codex_reasoning_config(_model: str) -> Dict[str, str]:
    """Build the ``reasoning`` block Codex requires on every request.

    "medium" effort matches the Codex CLI default — fast enough for
    JSON action-decision loops, deliberate enough that the model
    follows instruction-following. ``"auto"`` summary matches the CLI.
    """
    return {"effort": "medium", "summary": "auto"}


def _extract_instructions(
    messages: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Pull system-role text out of messages, return (instructions, rest).

    Codex's Responses API doesn't accept a system-role item inside
    ``input``; system prompts go in the top-level ``instructions`` field.
    Multiple system messages are joined with blank lines.
    """
    parts: List[str] = []
    rest: List[Dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system":
            c = m.get("content", "")
            if isinstance(c, str) and c:
                parts.append(c)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict):
                        t = part.get("text") or ""
                        if t:
                            parts.append(t)
        else:
            rest.append(m)
    return "\n\n".join(parts).strip(), rest


def _translate_request(
    kwargs: Dict[str, Any], fallback_cache_key: str
) -> Dict[str, Any]:
    """Re-shape a Chat Completions call into a Codex Responses API call.

    Codex's surface is stricter than the public Responses API. The
    translator sends only fields known to be accepted and drops the rest
    so SDK defaults can't quietly re-introduce a 400 we already fixed.

    ``fallback_cache_key`` is used for ``prompt_cache_key`` when the caller
    hasn't supplied one via ``extra_body`` — Codex routes cache lookups by
    this value, so keeping it stable across the conversation is what makes
    prefix caching actually work under ``store=false``.
    """
    model = kwargs["model"]
    out: Dict[str, Any] = {"model": model}

    # Codex hard requirements (override caller no matter what):
    #   store=false  — "Store must be set to false"
    #   stream=true  — "Stream must be set to true"; aggregated below.
    out["store"] = False
    out["stream"] = True

    # System message → ``instructions`` (Codex Responses API top-level
    # field). System-role items inside ``input`` are rejected. The
    # remaining user/assistant messages become the ``input`` array.
    raw_messages = kwargs.get("messages") or []
    instructions, rest = _extract_instructions(raw_messages)
    if instructions:
        out["instructions"] = instructions
    out["input"] = _normalize_messages(rest)

    # ``reasoning`` is REQUIRED for every gpt-5.x model on Codex.
    out["reasoning"] = _codex_reasoning_config(model)

    # ``text.verbosity`` is required by the Codex backend to know how
    # long a response to produce. The reference impl always sets it;
    # omitting it results in Codex completing the request with
    # ``output_len=0`` — no reasoning items, no message, nothing.
    # "medium" matches the reference impl's default and the Codex CLI.
    out["text"] = {"verbosity": "medium"}

    # ``include`` is REQUIRED under ``store=false`` — without
    # ``reasoning.encrypted_content`` the model loses its own reasoning
    # context turn-over-turn (backend keeps no state of its own).
    out["include"] = ["reasoning.encrypted_content"]

    # ``prompt_cache_key`` is what turns a cold shard into a warm one.
    # Codex-rs sets it to ``self.state.thread_id.to_string()`` (a UUID
    # stable for the entire conversation). Under ``store=false``, this is
    # the ONLY thing keeping requests landing on the same warm-cache shard;
    # rotating it per turn (e.g. hashing the growing messages array) is a
    # known anti-pattern that pegs cache hit at ~10%. We prefer the value
    # the caller supplied via ``extra_body.prompt_cache_key`` — CraftBot's
    # LLM interface generates a stable ``<call_type>_<system_prompt_hash>``
    # there — and fall back to a per-client UUID if the caller omitted it.
    extra_body = kwargs.get("extra_body") or {}
    if isinstance(extra_body, dict) and extra_body.get("prompt_cache_key"):
        out["prompt_cache_key"] = str(extra_body["prompt_cache_key"])
    elif fallback_cache_key:
        out["prompt_cache_key"] = fallback_cache_key

    # Everything else from the caller is DROPPED — Codex either rejects
    # or ignores these. JSON-mode is enforced via the system prompt
    # (CraftBot's agent already requires JSON in its prompts), since
    # ``response_format`` / ``text.format`` aren't part of the working
    # Codex client's request shape. See module docstring for the full list.

    # Caller-side streaming would mean "return chunks to the caller". The
    # adapter currently returns a fully-aggregated ChatCompletion shim, so
    # caller-side stream=True is not supported even though we stream
    # internally. The two are unrelated — internal stream is forced
    # because Codex requires it; caller-side stream would require us to
    # return an iterator, which would also need a streaming shim of the
    # Chat-Completions chunk shape. Out of scope for now.
    if kwargs.get("stream"):
        raise NotImplementedError(
            "ChatGPT subscription mode does not yet expose streaming to"
            " callers. The adapter streams from Codex internally and returns"
            " an aggregated response."
        )
    if kwargs.get("tools"):
        raise NotImplementedError(
            "ChatGPT subscription mode does not yet support tool calls;"
            " disconnect the subscription from Settings to fall back to"
            " your API key for tool-using flows."
        )

    return out


def _consume_stream(stream: Any) -> Dict[str, Any]:
    """Drain a Responses-API event stream and return a normalized bundle.

    Under ``store=false`` (which Codex requires) the terminal
    ``response.completed`` event's ``response.output`` is empty — the
    backend strips output items from the persistence-off snapshot and
    expects the client to consume the streamed deltas directly as the
    actual model output. So we don't trust ``response.output_text`` from
    the terminal event; we take the accumulated
    ``response.output_text.delta`` chunks as the source of truth.

    Returned bundle keys:
      - ``response``       — terminal Response object (may have empty output)
      - ``text``           — content string from accumulated deltas
      - ``seen_types``     — every event type observed during the stream
    """
    final = None
    failure_payload = None
    seen_types: List[str] = []
    text_parts: List[str] = []
    for event in stream:
        etype = getattr(event, "type", "") or ""
        seen_types.append(etype)
        if etype in ("response.completed", "response.done"):
            final = getattr(event, "response", None) or final
        elif etype == "response.failed":
            err_resp = getattr(event, "response", None)
            err = getattr(err_resp, "error", None) if err_resp else None
            failure_payload = (
                err or f"response.failed (no error attached, event={event!r})"
            )
        elif etype == "error":
            failure_payload = getattr(event, "error", None) or repr(event)
        elif etype == "response.output_text.delta":
            delta = getattr(event, "delta", "") or ""
            if delta:
                text_parts.append(delta)
    if failure_payload is not None and final is None:
        raise RuntimeError(f"Codex stream failed: {failure_payload}")
    if final is None:
        # No terminal event at all — dump what we saw so the actual
        # Codex behavior is visible instead of being silently swallowed.
        raise RuntimeError(
            "Codex stream ended without response.completed/done. "
            f"Events seen: {seen_types[:20]}"
            f"{' …(truncated)' if len(seen_types) > 20 else ''}."
            " Backend may have closed mid-stream."
        )
    return {
        "response": final,
        "text": "".join(text_parts),
        "seen_types": seen_types,
    }


def _normalize_content_part(part: Any, role: str) -> Any:
    """Translate one Chat-Completions content part into the Responses dialect.

    - ``{"type": "text", ...}``      → ``input_text`` (``output_text`` for
      assistant role)
    - ``{"type": "image_url", ...}`` → ``input_image`` with ``image_url`` as
      a plain string (Chat Completions nests it as ``{"url": ...}``);
      ``detail`` is preserved when present.

    Parts already typed in the Responses dialect (``input_text``,
    ``input_image``, ``output_text``, ...) and anything unrecognized pass
    through unchanged.
    """
    if not isinstance(part, dict):
        return part
    part_type = part.get("type")
    if part_type == "text":
        text_type = "output_text" if role == "assistant" else "input_text"
        return {"type": text_type, "text": part.get("text", "")}
    if part_type == "image_url":
        image_url = part.get("image_url")
        detail = None
        if isinstance(image_url, dict):
            detail = image_url.get("detail")
            image_url = image_url.get("url", "")
        translated: Dict[str, Any] = {"type": "input_image", "image_url": image_url}
        if detail:
            translated["detail"] = detail
        return translated
    return part


def _normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Coerce Chat-Completions message items into Responses-API ``input`` items.

    For string content we wrap into the typed parts shape the Responses
    API expects (``{"type":"input_text"...}`` for non-assistant roles,
    ``{"type":"output_text"...}`` for assistant). List content has each
    part translated from the Chat-Completions dialect (``text``,
    ``image_url``) via ``_normalize_content_part``.

    Also strips any ``id`` field from each item. Under ``store=false``
    Codex tries to resolve item ids server-side and 404s when it can't
    find them — the Hermes and OpenCode transformers both drop ids
    unconditionally on the input path.
    """
    normalized: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, str):
            part_type = "output_text" if role == "assistant" else "input_text"
            item = {"role": role, "content": [{"type": part_type, "text": content}]}
        elif isinstance(content, list):
            item = {
                "role": role,
                "content": [_normalize_content_part(p, role) for p in content],
            }
        else:
            item = {"role": role, "content": content}
        # id is intentionally NOT copied even if present on m.
        normalized.append(item)
    return normalized


def _wants_json_mode(kwargs: Dict[str, Any]) -> bool:
    """True if the caller asked for JSON output via ``response_format``.

    The translator strips ``response_format`` from the outgoing Codex
    request (Codex doesn't accept it), but we still remember the caller's
    intent so we can guarantee JSON-shape on the way back — see
    ``_extract_first_json_object`` for why that matters for Codex.
    """
    rf = kwargs.get("response_format")
    if not isinstance(rf, dict):
        return False
    return rf.get("type") in ("json_object", "json_schema")


def _extract_first_json_object(text: str) -> Tuple[str, bool]:
    """Return the substring containing exactly the first JSON object in
    ``text``. Returns ``(text, False)`` unchanged if no truncation was
    needed or if we couldn't find a parseable JSON at the start.

    Codex's gpt-5.x reasoning models — unlike most non-reasoning models —
    will often chain multiple JSON action objects into one response when
    asked "reply with a JSON action":

        {"reasoning": "...", "action_name": "search", ...}{"reasoning":
        "...", "action_name": "fetch", ...}{"reasoning": "...",
        "action_name": "sub_task_end", ...}

    That trips CraftBot's per-call parser ("Extra data: line 1 column
    N"). Truncating to the first well-formed JSON object gives the
    sub-agent runner exactly what it expects — one action per call — and
    the model can re-plan the next action on the next call. The chained
    JSONs beyond the first are effectively speculative planning tokens
    that get discarded.

    Only applied when the caller explicitly asked for JSON via
    ``response_format`` (otherwise a caller wanting prose gets prose).
    """
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return text, False
    # Preserve leading whitespace offset so slice indices align.
    lead = len(text) - len(stripped)
    try:
        _obj, end = json.JSONDecoder().raw_decode(stripped)
    except (json.JSONDecodeError, ValueError):
        return text, False
    total_end = lead + end
    if total_end >= len(text):
        return text, False
    # There's trailing content beyond the first JSON — truncate.
    return text[:total_end], True


def _describe_response(resp: Any) -> Dict[str, Any]:
    """Snapshot the parts of a Responses-API response object that matter
    for diagnosing an empty-text failure. Used inside logs / exceptions
    so the actual backend behavior surfaces instead of a generic wrap."""
    shape: Dict[str, Any] = {
        "id": getattr(resp, "id", None),
        "model": getattr(resp, "model", None),
        "status": getattr(resp, "status", None),
        "error": getattr(resp, "error", None),
        "incomplete_details": getattr(resp, "incomplete_details", None),
    }
    output_items = getattr(resp, "output", None) or []
    shape["output_len"] = len(output_items)
    items: List[Dict[str, Any]] = []
    for i, item in enumerate(output_items):
        entry: Dict[str, Any] = {
            "type": getattr(item, "type", None),
            "status": getattr(item, "status", None),
        }
        # For message items, note whether text parts are present or empty
        # so the log distinguishes "no message at all" from "message with
        # empty content".
        content_parts = getattr(item, "content", None) or []
        if content_parts:
            part_types = []
            for part in content_parts:
                part_types.append(
                    {
                        "type": getattr(part, "type", None),
                        "text_len": len(getattr(part, "text", "") or ""),
                    }
                )
            entry["content_parts"] = part_types
        items.append(entry)
        if i >= 5:  # cap for log readability
            break
    if items:
        shape["output"] = items
    return shape


def _wrap_response(
    bundle: Dict[str, Any], model: str, json_mode: bool = False
) -> _ChatCompletionShim:
    """Wrap a normalized _consume_stream bundle in a ChatCompletion shim.

    Content comes from the accumulated deltas (``bundle["text"]``), NOT
    from ``response.output_text`` — the latter is empty under Codex's
    required ``store=false`` mode because the backend strips output
    items from the terminal snapshot. Usage still comes from the
    terminal response object.

    When ``json_mode`` is True (i.e. the caller passed
    ``response_format={"type": "json_object"}``), the content is
    truncated to the first well-formed JSON object. Codex's reasoning
    models chain multiple JSONs into one response when asked for a
    single-action decision; without this the caller's parser fails on
    the trailing "extra data."

    If content ended up empty even after taking the deltas as truth,
    that means Codex genuinely produced nothing (or streamed something
    other than text) — surface a specific error including the shape and
    the observed event types so the failure is diagnosable.
    """
    resp = bundle["response"]
    content = bundle.get("text") or ""
    seen = bundle.get("seen_types") or []

    if json_mode and content:
        truncated_content, was_truncated = _extract_first_json_object(content)
        if was_truncated:
            logger.info(
                f"[CHATGPT-SUB] JSON-mode: truncated response from "
                f"{len(content)} to {len(truncated_content)} chars "
                f"(dropped chained JSON tail)"
            )
            content = truncated_content

    usage = getattr(resp, "usage", None)
    prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cached_tokens = 0
    if usage is not None:
        details = getattr(usage, "input_tokens_details", None)
        if details is not None:
            cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)

    if not content:
        shape = _describe_response(resp)
        logger.error(
            f"[CHATGPT-SUB] Codex returned no text content. "
            f"Response shape: {shape}. Stream events seen: {seen[:40]}"
        )
        embedded_error = getattr(resp, "error", None)
        status = getattr(resp, "status", None)
        incomplete = getattr(resp, "incomplete_details", None)
        if embedded_error:
            raise RuntimeError(
                f"Codex returned an error in the response body: {embedded_error}"
            )
        if status and status != "completed":
            raise RuntimeError(
                f"Codex response ended with status={status!r}"
                + (f" (incomplete_details={incomplete})" if incomplete else "")
                + f". Response shape: {shape}. Events seen: {seen[:20]}"
            )
        raise RuntimeError(
            "Codex response had no text output. "
            f"Shape: {shape}. Events seen during stream: {seen[:20]}"
            f"{' …(truncated)' if len(seen) > 20 else ''}"
        )

    return _ChatCompletionShim(
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        model=getattr(resp, "model", model) or model,
        response_id=getattr(resp, "id", "") or "",
        finish_reason="stop",
    )


# ════════════════════════════════════════════════════════════════════════
# Public adapter — exposes the SDK-shaped surface the interface expects
# ════════════════════════════════════════════════════════════════════════


def _translate_backend_error(exc: Exception, model: str) -> Exception:
    """Rewrite Codex-backend errors into user-actionable messages.

    The chatgpt.com/backend-api/codex host returns 400 "model not
    supported when using Codex with a ChatGPT account" for Free-tier
    bearers — the API accepts the token but the account has no Codex
    entitlement. Surface that as a plan-explanation rather than a
    model-config error so the user knows to upgrade or switch auth.
    """
    text = str(exc)
    if "ChatGPT account" not in text and "not supported when using Codex" not in text:
        return exc
    plan = ""
    try:
        from craftos_integrations.integrations.llm_oauth.chatgpt import load as _load

        cred = _load()
        if cred is not None:
            plan = (getattr(cred, "plan", "") or "").lower()
    except Exception:
        pass
    if plan == "free" or not plan:
        return RuntimeError(
            "ChatGPT subscription is connected but this account has no Plus/Pro/Team "
            "plan — the Codex backend rejects all models for Free-tier accounts. "
            "Upgrade at chat.openai.com, disconnect the subscription in Settings, "
            "or switch back to API-key auth."
        )
    return RuntimeError(
        f"ChatGPT subscription rejected model {model!r}: {text}. "
        "Try a different model from the subscription list, or switch to API-key auth."
    )


class _CompletionsNamespace:
    def __init__(self, parent: "ChatGPTSubscriptionClient"):
        self._parent = parent

    def create(self, **kwargs: Any) -> _ChatCompletionShim:
        translated = _translate_request(
            kwargs, fallback_cache_key=self._parent._cache_key
        )
        logger.debug(
            "[CHATGPT-SUB] chat.completions.create → responses.create "
            f"(model={translated.get('model')!r}, "
            f"cache_key={translated.get('prompt_cache_key')!r}, "
            f"streaming=True)"
        )
        try:
            stream = self._parent._inner.responses.create(**translated)
        except Exception as exc:
            logger.error(
                f"[CHATGPT-SUB] responses.create failed: {type(exc).__name__}: {exc}"
            )
            raise _translate_backend_error(exc, translated.get("model", "")) from exc

        # The Codex backend requires stream=True, but the caller wants a
        # synchronous response. Consume the event stream into a normalized
        # bundle (terminal response object + accumulated text + seen event
        # types) and re-shape it into a ChatCompletion shim.
        try:
            bundle = _consume_stream(stream)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        return _wrap_response(
            bundle,
            model=translated.get("model", ""),
            json_mode=_wants_json_mode(kwargs),
        )


class _ChatNamespace:
    def __init__(self, parent: "ChatGPTSubscriptionClient"):
        self.completions = _CompletionsNamespace(parent)


class ChatGPTSubscriptionClient:
    """Wraps an ``openai.OpenAI`` client so the LLM interface's existing
    ``client.chat.completions.create(...)`` call routes through the
    Responses API end of the subscription backend.

    Construct it the same way you'd construct ``openai.OpenAI``, then use
    in place of the bare SDK client::

        sdk = OpenAI(api_key=token, base_url=SUB_URL, default_headers=hdrs)
        client = ChatGPTSubscriptionClient(sdk)
        ctx["client"] = client

    All non-``chat.completions`` attribute access is delegated to the
    wrapped SDK client, so the rare callers that touch ``client.responses``
    or ``client.files`` directly still work unchanged.
    """

    def __init__(self, openai_client: Any):
        self._inner = openai_client
        # Fallback prompt_cache_key. Codex's cache routing keys off this
        # value under ``store=false`` — a stable-per-conversation string
        # is required to land requests on the same warm shard. When the
        # caller supplies one via ``extra_body.prompt_cache_key`` (as
        # CraftBot's LLM interface does per call type) we forward it; if
        # not, this per-client UUID stands in and stays stable for the
        # lifetime of the LLM interface instance.
        self._cache_key = f"craftbot-{uuid.uuid4().hex}"
        self.chat = _ChatNamespace(self)

    # Anything we don't override forwards to the wrapped SDK client —
    # keeps direct-Responses callers working and gives the runtime
    # introspection tools the same shape as the real OpenAI client.
    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


__all__ = ["ChatGPTSubscriptionClient"]
