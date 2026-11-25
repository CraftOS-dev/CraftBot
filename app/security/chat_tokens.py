"""Remove chat-template control tokens from outside content.

Settings > Security > "Strip chat tokens" (``strip_chat_tokens``).

A local model (Ollama, LM Studio) reads its conversation as one string in
its chat template. A web page, email or message carrying ``<|im_start|>
system`` or ``[INST]`` can then open what the model reads as a new system or
user turn, outside the envelope CraftBot puts around outside content.

Ported from OpenClaw's ``sanitizeModelSpecialTokens``
(src/security/external-content.ts, MIT, OpenClaw Foundation): every known
special token is replaced with ``[REMOVED_SPECIAL_TOKEN]`` (replaced, not
deleted, so the reader can see something was there), in the content and in
the metadata OpenClaw prints with it (sender, subject), where line breaks
are also flattened to spaces. OpenClaw applies it to everything it wraps as
external: email, webhooks, browser pages, web search and fetch results, and
channel metadata. The token spellings do not overlap, and the replacement
cannot form another token, so one pass is enough.
"""

from __future__ import annotations

import re

REPLACEMENT = "[REMOVED_SPECIAL_TOKEN]"

_TOKEN_LITERALS = (
    # ChatML / Qwen
    "<|im_start|>",
    "<|im_end|>",
    "<|endoftext|>",
    # Llama 3.x / 4.x
    "<|begin_of_text|>",
    "<|end_of_text|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<|eot_id|>",
    "<|python_tag|>",
    "<|eom_id|>",
    # Mistral / Mixtral
    "[INST]",
    "[/INST]",
    "<<SYS>>",
    "<</SYS>>",
    # Phi and other sentencepiece-style templates
    "<s>",
    "</s>",
    # GPT-OSS / harmony
    "<|channel|>",
    "<|message|>",
    "<|return|>",
    "<|call|>",
    # Gemma
    "<start_of_turn>",
    "<end_of_turn>",
)

_TOKEN_RE = re.compile(
    "|".join([*(re.escape(t) for t in _TOKEN_LITERALS), r"<\|reserved_special_token_\d+\|>"])
)
_LINE_BREAKS_RE = re.compile(r"[\r\n]+")


def strip_chat_tokens(text: str) -> str:
    """``text`` with every chat-template special token replaced."""
    if not text or ("<" not in text and "[" not in text):
        return text
    return _TOKEN_RE.sub(REPLACEMENT, text)


def strip_chat_tokens_inline(value: str) -> str:
    """For a one-line label shown with outside content (a sender, subject or
    source name): tokens replaced and line breaks flattened to spaces, so the
    label cannot start a line of its own."""
    if not value:
        return value
    return _LINE_BREAKS_RE.sub(" ", strip_chat_tokens(value))


__all__ = ["REPLACEMENT", "strip_chat_tokens", "strip_chat_tokens_inline"]
